from app.images import Image
from app.models import SceneModel

class Scene:
	def __init__(self, title: str, images: list[Image] = []):
		self.title = title
		self.images = images

	@classmethod
	def from_model(cls, model: SceneModel) -> 'Scene':
		return cls(title=model.title, images=[Image.from_model(image_model) for image_model in model.images])

	def to_model(self) -> SceneModel:
		return SceneModel(title=self.title, images=[image.to_model() for image in self.images])