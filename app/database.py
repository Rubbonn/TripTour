'''
Copyright (C) 2026  Ruben Giuriato - Licensed under GNU GPLv3

Accesso al database tramite sessione ambientale (ContextVar).

La sessione vive nel contesto di esecuzione corrente (thread o task asyncio),
quindi ogni richiesta HTTP ha la sua, isolata dalle altre. Ci sono due modi per
ottenerla, e in un dato flusso se ne usa UNO SOLO:

1. Scope automatico (consigliato nel web e negli script):

	with db.session_scope():
		TourRepository().add(...)
	# commit se il blocco termina bene, rollback su eccezione, close sempre

2. Sessione esplicita (controllo manuale di commit e chiusura):

	@app.teardown_appcontext
	def _close(exc):
		if exc is None:
			db.commit()
		else:
			db.rollback()
		db.close_session()

	# nell'endpoint
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
from typing import Generator

_session_context: ContextVar[Session|None] = ContextVar('session_context', default=None)

class Database:
	def __init__(self):
		# URL.create evita che caratteri speciali nella password (@, :, /) rompano l'URL
		self._db_path: str | URL = URL.create(
			'mariadb+pymysql',
			username=settings['MARIADB_USER'],
			password=settings['MARIADB_PASSWORD'],
			host=settings['MARIADB_HOST'],
			database=settings['MARIADB_DATABASE'],
		)
		self._db_engine = None
		self._session_factory = None
		self._lock = RLock()

	def configure(self, db_url: str | URL):
		'''
		Cambia il database di destinazione (test, staging).

		Da chiamare prima di aprire uno scope o di usare db.session: se l'engine
		esiste già viene chiuso e ricreato al prossimo accesso.

		Esempio:
			db.configure('sqlite://', connect_args={'check_same_thread': False})
		'''
		with self._lock:
			if self._db_engine is not None:
				self._db_engine.dispose()
			self._db_path = db_url
			self._db_engine = None
			self._session_factory = None

	def _get_engine(self) -> Engine:
		with self._lock:
			if self._db_engine is None:
				self._db_engine = create_engine(self._db_path, echo=False)
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

		Idempotente: se la sessione è già stata chiusa (per esempio da
		db.session_scope()) non fa nulla. Va chiamata SEMPRE a fine richiesta
		nella modalità esplicita, altrimenti la connessione resta occupata e,
		con i thread riusati di Flask, viene trascinata nella richiesta successiva.

		Esempio (Flask):
			@app.teardown_appcontext
			def _close(exc):
				if exc is None:
					db.commit()
				else:
					db.rollback()
				db.close_session()
		'''
		session = _session_context.get()
		if session is None:
			return

		try:
			session.close()
		finally:
			_session_context.set(None)

	@contextmanager
	def session_scope(self) -> Generator[None]:
		'''
		Confine transazionale: commit se il blocco termina bene, rollback altrimenti.

		La sessione viene creata all'ingresso e chiusa sempre in uscita, anche in
		caso di eccezione o di cancellazione della richiesta (FastAPI). Alla fine
		il contesto viene ripristinato al valore precedente, quindi gli scope
		possono essere annidati senza interferire.

		Esempio (middleware FastAPI):
			@app.middleware('http')
			async def _db_scope(request, call_next):
				with db.session_scope():
					return await call_next(request)

		Esempio (script):
			with db.session_scope():
				TourRepository().add(TourModel(title='...', language='it'))
		'''
		session = self._get_factory()()
		token = _session_context.set(session)
		try:
			yield
			session.commit()
		except BaseException:  # include CancelledError di FastAPI
			session.rollback()
			raise
		finally:
			session.close()
			_session_context.reset(token)

db = Database()