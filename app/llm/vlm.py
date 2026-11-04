'''
Copyright (C) 2026  Ruben Giuriato - Licensed under GNU GPLv3
'''

from app.settings import settings
from langchain.agents import create_agent
from langchain.agents.middleware import ToolRetryMiddleware
from langchain.chat_models import init_chat_model
from langchain.tools import BaseTool

class Vlm:
	def __init__(self):
		self._model = init_chat_model(
			model=settings.get('OPENROUTER_MODEL'),
			model_provider='openrouter',
			api_key=settings.get('OPENROUTER_API_KEY')
		)

	def __call__(self, chat_history: list[dict], tools: list[BaseTool] | None = None) -> str:
		if not chat_history:
			raise ValueError('chat_history must contain at least one message')
		agent = create_agent(self._model, tools=tools or [], middleware=[ToolRetryMiddleware(max_retries=3)])
		response = agent.invoke({'messages': chat_history})
		return response['messages'][-1].content