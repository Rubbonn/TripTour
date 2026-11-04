'''
Copyright (C) 2026  Ruben Giuriato - Licensed under GNU GPLv3

Accesso al database tramite sessione ambientale (ContextVar).

La sessione vive nel contesto di esecuzione corrente (thread o task asyncio),
quindi ogni richiesta HTTP ha la sua, isolata dalle altre. Ci sono due modi per
ottenerla, e in un dato flusso se ne usa UNO SOLO: non mescolarli.

1. Scope automatico (consigliato nel web e negli script):

	with db.session_scope() as session:
		TourRepository().add(...)
	# commit se il blocco termina bene, rollback su eccezione, close sempre

	Gli scope possono essere annidati, ma ogni scope apre una sessione e una
	transazione indipendenti: il commit dello scope interno è definitivo e non
	viene annullato da un rollback dello scope esterno.

2. Sessione esplicita (controllo manuale di commit e chiusura):

	@app.teardown_appcontext
	def _close(exc):
		# Rete di sicurezza: la risposta è già costruita quando il teardown
		# gira, quindi qui si può solo annullare, non salvare.
		if exc is not None:
			db.rollback()
		db.close_session()

	# nell'endpoint: il commit va fatto QUI, prima di restituire la risposta,
	# altrimenti un errore di integrità non può più diventare un 500.
	TourRepository().add(...)
	db.commit()

In entrambi i casi il repository legge db.session senza riceverla come parametro.
'''

from app.settings import settings
from contextlib import contextmanager
from contextvars import ContextVar
from sqlalchemy import create_engine, Engine, URL
from sqlalchemy.orm import Session, sessionmaker
from threading import RLock
from typing import Any, Generator

# La sessione è globale per contesto di esecuzione (thread o task asyncio):
# è così che i repository la leggono senza riceverla come parametro.
_session_context: ContextVar[Session|None] = ContextVar('session_context', default=None)

# Opzioni di default pensate per MariaDB: evita di servire una connessione
# scaduta dopo un periodo di inattività (wait_timeout lato server).
_DEFAULT_ENGINE_KWARGS: dict[str, Any] = {
	'pool_pre_ping': True,
	'pool_recycle': 3600,
}

class Database:
	def __init__(self):
		# Nessuna configurazione viene letta qui: l'URL di default è costruito
		# in modo lazy da _get_engine(), così la classe è importabile e
		# configurabile (test, staging) anche senza variabili d'ambiente.
		self._db_path: str | URL | None = None
		self._engine_kwargs: dict[str, Any] = dict(_DEFAULT_ENGINE_KWARGS)
		self._db_engine: Engine | None = None
		self._session_factory: sessionmaker[Session] | None = None
		self._lock = RLock()

	@staticmethod
	def _default_url() -> URL:
		'''
		URL MariaDB costruito dai settings, letto solo al primo uso.

		URL.create evita che caratteri speciali nella password (@, :, /)
		rompano l'URL.
		'''
		return URL.create(
			'mariadb+pymysql',
			username=settings['MARIADB_USER'],
			password=settings['MARIADB_PASSWORD'],
			host=settings['MARIADB_HOST'],
			database=settings['MARIADB_DATABASE'],
		)

	def configure(self, db_url: str | URL, **engine_kwargs: Any):
		'''
		Cambia il database di destinazione (test, staging).

		Da chiamare prima di aprire uno scope o di usare db.session: se l'engine
		esiste già viene chiuso e ricreato al prossimo accesso. La sessione
		eventualmente già presente nel contesto corrente viene chiusa, così non
		resta legata al vecchio engine (vale solo per il thread/task chiamante).

		I kwargs extra sono passati a create_engine e sostituiscono i default
		(pool_pre_ping, pool_recycle).

		Esempio:
			db.configure('sqlite://', connect_args={'check_same_thread': False})
		'''
		self.close_session()

		with self._lock:
			if self._db_engine is not None:
				self._db_engine.dispose()
			self._db_path = db_url
			self._engine_kwargs = {**_DEFAULT_ENGINE_KWARGS, **engine_kwargs}
			self._db_engine = None
			self._session_factory = None

	def _get_engine(self) -> Engine:
		with self._lock:
			if self._db_engine is None:
				if self._db_path is None:
					self._db_path = self._default_url()
				self._db_engine = create_engine(self._db_path, echo=False, **self._engine_kwargs)
				self._session_factory = sessionmaker(bind=self._db_engine, autoflush=False, expire_on_commit=False)
			return self._db_engine

	def _get_factory(self) -> sessionmaker[Session]:
		self._get_engine()
		assert self._session_factory is not None
		return self._session_factory

	def create_all(self) -> None:
		'''
		Crea le tabelle mancanti a partire dai modelli.

		Solo per sviluppo: non migra tabelle esistenti. In produzione usa Alembic.
		'''
		from app.models import Base
		Base.metadata.create_all(self._get_engine())

	@property
	def session(self) -> Session:
		'''
		Sessione del contesto corrente, creata al primo accesso se non esiste.

		È il canale che i repository usano: non va passata come parametro.
		La sessione è legata al thread o al task asyncio corrente, quindi due
		richieste concorrenti non la condividono mai.

		Chi la crea è responsabile di committare (db.commit()) e di chiuderla
		(db.close_session()) a fine richiesta. Se invece usi db.session_scope(),
		commit, rollback e close sono gestiti automaticamente dallo scope.

		Il commit va fatto nell'endpoint, prima di restituire la risposta: nel
		teardown la risposta è già costruita e un errore di integrità non può
		più diventare un 500.

		Esempio:
			tour = db.session.get(TourModel, 1)
		'''
		session = _session_context.get()
		if session is None:
			session = self._get_factory()()
			_session_context.set(session)
		return session

	def commit(self) -> None:
		'''
		Committa la sessione del contesto corrente, se esiste.

		No-op se non c'è nessuna sessione: non ne crea una solo per committare.
		Da usare nella modalità esplicita (senza db.session_scope()).
		'''
		session = _session_context.get()
		if session is not None:
			session.commit()

	def rollback(self) -> None:
		'''
		Annulla la transazione della sessione corrente, se esiste.

		No-op se non c'è nessuna sessione. Da usare nella modalità esplicita,
		tipicamente nel teardown quando la richiesta è fallita.
		'''
		session = _session_context.get()
		if session is not None:
			session.rollback()

	def close_session(self) -> None:
		'''
		Chiude la sessione del contesto corrente e la rimuove dal contesto.

		Idempotente: se non c'è nessuna sessione non fa nulla. Va chiamata SEMPRE
		a fine richiesta nella modalità esplicita, altrimenti la connessione
		resta occupata e, con i thread riusati di Flask, viene trascinata nella
		richiesta successiva.

		Non committa: eventuali modifiche non committate vengono scartate da
		session.close(). Il commit va fatto prima, nell'endpoint.

		Da NON usare dentro db.session_scope(): lo scope possiede la sessione e
		la chiude da sé. Chiamarla lì dentro lascerebbe una sessione orfana
		aperta, perché lo scope chiuderebbe solo quella che ha creato.

		Esempio (Flask):
			@app.teardown_appcontext
			def _close(exc):
				# La risposta è già costruita: qui si può solo annullare.
				if exc is not None:
					db.rollback()
				db.close_session()
		'''
		session = _session_context.get()
		if session is None:
			return

		try:
			session.close()
		finally:
			# In modalità esplicita non esiste un token da resettare: il
			# contesto viene svuotato per non trascinare la sessione chiusa
			# nella richiesta successiva sullo stesso thread.
			_session_context.set(None)

	@contextmanager
	def session_scope(self) -> Generator[Session]:
		'''
		Confine transazionale: commit se il blocco termina bene, rollback altrimenti.

		La sessione viene creata all'ingresso e chiusa sempre in uscita, anche in
		caso di eccezione o di cancellazione della richiesta. Alla fine il
		contesto viene ripristinato al valore precedente, quindi gli scope
		possono essere annidati senza interferire.

		Attenzione: ogni scope apre una sessione e una transazione indipendenti.
		Il commit dello scope interno è definitivo e un rollback dello scope
		esterno non lo annulla. Per una transazione unica usa un solo scope.

		Esempio (Flask, view sincrona):
			@app.route('/tour', methods=['POST'])
			def create_tour():
				with db.session_scope() as session:
					session.add(TourModel(title='...', language='it'))
				return 'created'

		Esempio (script):
			with db.session_scope() as session:
				TourRepository().add(TourModel(title='...', language='it'))
		'''
		session = self._get_factory()()
		token = _session_context.set(session)
		try:
			yield session
			session.commit()
		except BaseException:  # include CancelledError
			session.rollback()
			raise
		finally:
			session.close()
			_session_context.reset(token)

db = Database()