from app.images import Image
from app.scenes import Scene
from datetime import datetime

class Tour:
	def __init__(self, id: int | None, title: str, language: str, created_at: datetime, images: list[Image] | None = None, scenes: list[Scene] | None = None):
		self.id = id
		self.title = title
		self.language = language
		self.created_at = created_at
		self.images = images if images is not None else []
		self.scenes = scenes if scenes is not None else []

	@property
	def unassigned_images(self) -> list[Image]:
		'''
		Foto del tour non ancora assegnate a una scena (prima del clustering).
		'''
		assigned = {image.id for scene in self.scenes for image in scene.images}
		return [image for image in self.images if image.id not in assigned]

	@property
	def assigned_images(self) -> list[Image]:
		'''
		Foto del tour già assegnate a una scena (dopo il clustering).
		'''
		return [image for scene in self.scenes for image in scene.images]

	def __repr__(self):
		return f'Tour(id={self.id}, title="{self.title}", language="{self.language}", created_at="{self.created_at}", images={self.images}, scenes={self.scenes})'