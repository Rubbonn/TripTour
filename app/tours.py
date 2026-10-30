from app.images import Image
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

	def __repr__(self):
		return f'Tour(id={self.id}, title="{self.title}", language="{self.language}", created_at="{self.created_at}", scenes={self.scenes})'