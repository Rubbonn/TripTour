from app.image import Image

class Scene:
    def __init__(self, title: str, images: list[Image] = []):
        self.title = title
        self.images = images