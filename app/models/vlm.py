from json import dumps
from transformers import pipeline
from typing import Callable

class Vlm:
	def __init__(self):
		self._pipeline = pipeline(
			'image-text-to-text',
			model='google/gemma-4-E2B-it',
			assistant_model='google/gemma-4-E2B-it-assistant',
			dtype='auto',
			device_map='auto',
			model_kwargs={'cache_dir': './.model_cache', 'attn_implementation': 'sdpa'}
		)
		self._pipeline.generation_config.update(max_new_tokens = 32768)

	def __call__(self, chat_history: list[dict], tools: list[Callable] = []) -> str:
		tool_list = [tool.__name__ for tool in tools]
		while True:
			print(f'Chat history: {chat_history}')
			chat_history = self._pipeline(text=chat_history, enable_thinking=False, tools=tools)[0]['generated_text'] #type: ignore[call-overload]
			print(f'Received: {chat_history[-1]}')
			if 'tool_calls' in chat_history[-1]:
				chat_history[-1]['content'] = ''
				for tool in chat_history[-1]['tool_calls']:
					tool_name = tool['function']['name']
					tool_args = tool['function']['arguments']
					if tool_name in tool_list:
						print(f'Calling tool {tool_name} with args {tool_args}')
						tool_result = tools[tool_list.index(tool_name)](**tool_args)
						tool_response = {'role': 'tool', 'content': dumps(tool_result)}
						print(f'Got tool response: {tool_response}')
						chat_history.append(tool_response)
			else:
				return chat_history[-1]['content']