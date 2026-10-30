from app.images import Image
from app.models import TourModel
from app.scenes import Scene
from datetime import datetime

class Tour:
	def __init__(self, id: int | None, title: str, language: str, created_at: datetime, scenes: list[Scene] = []):
		self.id = id
		self.title = title
		self.language = language
		self.created_at = created_at
		self.scenes = scenes

	@property
	def images(self) -> list[Image]:
		return [image for scene in self.scenes for image in scene.images]

	@classmethod
	def from_model(cls, model: TourModel) -> 'Tour':
		return cls(id=model.id, title=model.title, language=model.language, created_at=model.created_at, scenes=[Scene.from_model(scene_model) for scene_model in model.scenes])

	def to_model(self) -> TourModel:
		return TourModel(id=self.id, title=self.title, language=self.language, created_at=self.created_at, scenes=[scene.to_model() for scene in self.scenes])

	def __repr__(self):
		return f'Tour(id={self.id}, title="{self.title}", language="{self.language}", created_at="{self.created_at}", scenes={self.scenes})'