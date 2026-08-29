from datetime import datetime
from sqlalchemy import select, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, DeclarativeBase, relationship
from sqlalchemy.types import TypeDecorator
import torch
from typing import Any
	
class TensorJSON(TypeDecorator):
	impl = JSON
	cache_ok = True

	def process_bind_param(self, value: Any, dialect):
		if value is None:
			return None

		# Accept torch.Tensor and serialize while preserving original shape.
		if hasattr(value, 'detach') and hasattr(value, 'to'):
			return value.detach().to(device='cpu', dtype=torch.float32).tolist()

		if isinstance(value, (list, tuple)):
			return torch.as_tensor(value, dtype=torch.float32).tolist()

		raise TypeError(f'Unsupported embedding type: {type(value)!r}')

	def process_result_value(self, value: Any, dialect):
		if value is None:
			return None

		return torch.tensor(value, dtype=torch.float32)

class Base(DeclarativeBase):
	@classmethod
	def _get_session(cls):
		from app.database import db
		return db.session()

	@classmethod
	def get(cls, primary_key: Any):
		return cls._get_session().get(cls, primary_key)

	@classmethod
	def all(cls):
		return cls._get_session().scalars(select(cls)).all()

	def save(self):
		session = self._get_session()
		session.add(self)
		session.commit()
		return self

	def delete(self):
		session = self._get_session()
		session.delete(self)
		session.commit()

class TourModel(Base):
	__tablename__ = 'tours'

	id: Mapped[int] = mapped_column(primary_key=True)
	title: Mapped[str]
	language: Mapped[str]
	created_at: Mapped[datetime] = mapped_column(default=datetime.now)
	images: Mapped[list['ImageModel']] = relationship(back_populates='tour')

	def __repr__(self):
		return f'Tour(id={self.id}, title="{self.title}", language="{self.language}", created_at="{self.created_at}")'

class ImageModel(Base):
	__tablename__ = 'images'

	id: Mapped[int] = mapped_column(primary_key=True)
	id_tour: Mapped[int] = mapped_column(ForeignKey('tours.id'))
	tour: Mapped['TourModel'] = relationship(back_populates='images')
	path: Mapped[str]
	filename: Mapped[str]
	latitude: Mapped[float | None]
	longitude: Mapped[float | None]
	address: Mapped[str | None]
	date: Mapped[datetime | None]
	description: Mapped[str | None]
	laplacian_variance: Mapped[float]
	embedding: Mapped['torch.Tensor | None'] = mapped_column(TensorJSON)

	def __repr__(self):
		return f'Image(id={self.id}, id_tour={self.id_tour}, path="{self.path}", filename="{self.filename}", latitude={self.latitude}, longitude={self.longitude}, address="{self.address}", date="{self.date}", description="{self.description}", laplacian_variance={self.laplacian_variance}, embedding={self.embedding})'