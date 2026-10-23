from app.images import Image
from app.models import TourModel
from app.scenes import Scene

class Tour:
	def __init__(self, title: str, language: str, scenes: list[Scene] = []):
		self.title = title
		self.language = language
		self.scenes = scenes

	@property
	def images(self) -> list[Image]:
		return [image for scene in self.scenes for image in scene.images]

	@classmethod
	def from_model(cls, model: TourModel) -> 'Tour':
		return cls(title=model.title, language=model.language, scenes=[Scene.from_model(scene_model) for scene_model in model.scenes])

	def to_model(self) -> TourModel:
		return TourModel(title=self.title, language=self.language, scenes=[scene.to_model() for scene in self.scenes])