from transformers import pipeline

class Vlm:
	def __init__(self):
		self._pipeline = pipeline(
			'image-text-to-text',
			model='google/gemma-4-E2B-it',
			dtype='auto',
			device_map='auto',
			model_kwargs={'cache_dir': './.model_cache', 'attn_implementation': 'sdpa'}
		)
		self._pipeline.generation_config.update(max_new_tokens = 32768)

	def __call__(self, chat_history: str | list[str] | list[dict] | None) -> str:
		response = self._pipeline(text=chat_history, enable_thinking=False) #type: ignore[call-overload]
		return response[0]['generated_text'][-1]['content']