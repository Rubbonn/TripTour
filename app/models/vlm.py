from app.settings import settings, SETTINGS_LIST
from langchain.agents import create_agent
from langchain.agents.middleware import ToolRetryMiddleware
from langchain.chat_models import init_chat_model
from langchain.tools import BaseTool

class Vlm:
	def __init__(self):
		self._model = init_chat_model(
			model=settings.get(SETTINGS_LIST.vlm_model.value),
			model_provider='openai',
			base_url=settings.get(SETTINGS_LIST.vlm_base_url.value),
			api_key=settings.get(SETTINGS_LIST.vlm_api_key.value)
		)

	def __call__(self, chat_history: list[dict], tools: list[BaseTool] = []) -> str:
		agent = create_agent(self._model, tools=tools, middleware=[ToolRetryMiddleware(max_retries=3)])
		response = agent.invoke({'messages': chat_history})
		return response['messages'][-1].content