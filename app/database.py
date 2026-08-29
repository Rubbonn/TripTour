from app.constants import _APP_ORG_, _APP_NAME_
from pathlib import Path
from platformdirs import PlatformDirs
from sqlalchemy import create_engine, select
from sqlalchemy.orm import DeclarativeBase, Session, scoped_session, sessionmaker
from typing import Any

dirs = PlatformDirs(_APP_NAME_, _APP_ORG_)


class Base(DeclarativeBase):
	@classmethod
	def get(cls, primary_key: Any):
		return db.session().get(cls, primary_key)

	@classmethod
	def all(cls):
		return db.session().scalars(select(cls)).all()

	def save(self):
		session = db.session()
		session.add(self)
		session.commit()
		return self

	def delete(self):
		session = db.session()
		session.delete(self)
		session.commit()

class Database:
	def __init__(self):
		db_path = Path(dirs.user_data_dir) / 'database.sqlite3'
		db_path.parent.mkdir(parents=True, exist_ok=True)
		need_initialization = not db_path.exists()
		self._db_engine = create_engine(f'sqlite:///{db_path}')
		self._session_factory = scoped_session(
			sessionmaker(bind=self._db_engine, autoflush=False, expire_on_commit=False)
		)

		if need_initialization:
			import app.models
			Base.metadata.create_all(self._db_engine)

	def session(self) -> Session:
		return self._session_factory()

	def remove_session(self):
		self._session_factory.remove()


db = Database()

	