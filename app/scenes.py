from app.images import Image

class Scene:
	def __init__(self, id: int | None, title: str, images: list[Image] | None = None):
		self.id = id
		self.title = title
		self.images = images if images is not None else []

	def __repr__(self):
		return f'Scene(id={self.id}, title="{self.title}", images={self.images})'