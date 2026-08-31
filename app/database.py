'''
Copyright (C) 2026  Ruben Giuriato - Licensed under GNU GPLv3
'''

from app.constants import _APP_ORG_, _APP_NAME_
from pathlib import Path
from platformdirs import PlatformDirs
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, scoped_session, sessionmaker

dirs = PlatformDirs(_APP_NAME_, _APP_ORG_)

class Database:
	def __init__(self):
		db_path = Path(dirs.user_data_dir) / 'database.sqlite3'
		db_path.parent.mkdir(parents=True, exist_ok=True)
		self._db_engine = create_engine(f'sqlite:///{db_path}')
		self._session_factory = scoped_session(
			sessionmaker(bind=self._db_engine, autoflush=False, expire_on_commit=False)
		)

		from app.models import Base
		Base.metadata.create_all(self._db_engine)

	def session(self) -> Session:
		return self._session_factory()

	def remove_session(self):
		self._session_factory.remove()


db = Database()

	