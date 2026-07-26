from transformers import pipeline

class Vlm:
	def __init__(self):
		self._pipeline = pipeline('image-text-to-text', model='google/gemma-4-E2B-it', dtype='auto', device_map='auto', model_kwargs={'cache_dir': './.model_cache'})

	def __call__(self, chat_history: list[dict[str, str]]) -> str:
		response = self._pipeline(chat_history)
		print(response)