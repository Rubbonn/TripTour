from app.images import Image
from app.models import SceneModel

class Scene:
	def __init__(self, id: int | None, title: str, images: list[Image] = []):
		self.id = id
		self.title = title
		self.images = images

	@classmethod
	def from_model(cls, model: SceneModel) -> 'Scene':
		return cls(id=model.id, title=model.title, images=[Image.from_model(image_model) for image_model in model.images])

	def to_model(self) -> SceneModel:
		return SceneModel(id=self.id, title=self.title, images=[image.to_model() for image in self.images])

	def __repr__(self):
		return f'Scene(id={self.id}, title="{self.title}", images={self.images})'