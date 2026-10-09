from app.images import Image, order_images_by_date, remove_duplicate_images
from langgraph.graph import StateGraph, START, END
from typing import TypedDict

class PreFilterState(TypedDict):
		images: list[Image]
		
class PreFilterWorkflow:
	def __init__(self):
		workflow = StateGraph(PreFilterState)
		workflow.add_node('order_images_by_date', lambda state: {'images': order_images_by_date(state['images'])})
		workflow.add_node('remove_duplicate_images', lambda state: {'images': remove_duplicate_images(state['images'])})
		workflow.add_edge(START, 'order_images_by_date')
		workflow.add_edge('order_images_by_date', 'remove_duplicate_images')
		workflow.add_edge('remove_duplicate_images', END)
		self._workflow = workflow.compile()

	def __call__(self, images: list[Image]) -> list[Image]:
		return self._workflow.invoke({'images': images})['images']