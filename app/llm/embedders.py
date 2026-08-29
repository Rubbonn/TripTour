from PIL import Image as PILImage
import torch
from transformers import AutoImageProcessor, AutoModel

class ImageEmbedder:
	def __init__(self):
		self._processor = AutoImageProcessor.from_pretrained('google/siglip2-base-patch16-512', cache_dir='./.model_cache')
		self._model = AutoModel.from_pretrained('google/siglip2-base-patch16-512', cache_dir='./.model_cache')

	def embed(self, image: PILImage.Image | str):
		if isinstance(image, str):
			image = PILImage.open(image)
		processed_image = self._processor(images=image, return_tensors='pt')
		with torch.no_grad():
			return self._model.get_image_features(**processed_image).pooler_output

_instance: ImageEmbedder | None = None

def get_image_embedder() -> ImageEmbedder:
	global _instance
	if _instance is None:
		_instance = ImageEmbedder()
	return _instance