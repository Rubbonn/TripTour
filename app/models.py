'''
Copyright (C) 2026  Ruben Giuriato - Licensed under GNU GPLv3
'''

from datetime import datetime
from sqlalchemy import ForeignKey, JSON
from sqlalchemy.ext.orderinglist import ordering_list
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
	pass

class TourModel(Base):
	__tablename__ = 'tours'

	id: Mapped[int] = mapped_column(primary_key=True)
	title: Mapped[str]
	language: Mapped[str]
	created_at: Mapped[datetime] = mapped_column(default=datetime.now)
	images: Mapped[list['ImageModel']] = relationship(back_populates='tour', order_by='ImageModel.filename')
	scenes: Mapped[list['SceneModel']] = relationship(back_populates='tour', order_by='SceneModel.position', collection_class=ordering_list('position'), lazy='selectin')

	def __repr__(self):
		return f'Tour(id={self.id}, title="{self.title}", language="{self.language}", created_at="{self.created_at}")'

class ImageModel(Base):
	__tablename__ = 'images'

	id: Mapped[int] = mapped_column(primary_key=True)
	id_tour: Mapped[int] = mapped_column(ForeignKey('tours.id'))
	tour: Mapped['TourModel'] = relationship(back_populates='images')
	id_scene: Mapped[int | None] = mapped_column(ForeignKey('scenes.id'))
	scene: Mapped['SceneModel | None'] = relationship(back_populates='images')
	position: Mapped[int | None]
	path: Mapped[str]
	filename: Mapped[str]
	mime: Mapped[str]
	latitude: Mapped[float | None]
	longitude: Mapped[float | None]
	gps_confidence: Mapped[int]
	address: Mapped[str | None]
	address_confidence: Mapped[int]
	date: Mapped[datetime | None]
	date_confidence: Mapped[int]
	description: Mapped[str | None]
	laplacian_variance: Mapped[float]
	embedding: Mapped['torch.Tensor | None'] = mapped_column(TensorJSON)

	def __repr__(self):
		return f'Image(id={self.id}, id_tour={self.id_tour}, id_scene={self.id_scene}, position={self.position}, path="{self.path}", filename="{self.filename}", mime="{self.mime}", latitude={self.latitude}, longitude={self.longitude}, gps_confidence={self.gps_confidence}, address="{self.address}", address_confidence={self.address_confidence}, date="{self.date}", date_confidence={self.date_confidence}, description="{self.description}", laplacian_variance={self.laplacian_variance}, embedding={self.embedding})'

class SceneModel(Base):
	__tablename__ = 'scenes'

	id: Mapped[int] = mapped_column(primary_key=True)
	id_tour: Mapped[int] = mapped_column(ForeignKey('tours.id'))
	tour: Mapped['TourModel'] = relationship(back_populates='scenes')
	title: Mapped[str]
	position: Mapped[int]
	images: Mapped[list['ImageModel']] = relationship(back_populates='scene', order_by='ImageModel.position', collection_class=ordering_list('position'), lazy='selectin')