'''
Copyright (C) 2026  Ruben Giuriato - Licensed under GNU GPLv3
'''

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

class EnrichmentState(TypedDict):
	images: list[Image]

class EnrichmentWorkflow:
	def __init__(self):
		workflow = StateGraph(EnrichmentState)

		def find_anchors(images: list[Image], index: int) -> tuple[Image | None, Image | None]:
			# Find the nearest anchor image before the current image
			anchor_before = None
			for i in range(index - 1, -1, -1):
				if images[i].is_anchor:
					anchor_before = images[i]
					break

			# Find the nearest anchor image after the current image
			anchor_after = None
			for i in range(index + 1, len(images)):
				if images[i].is_anchor:
					anchor_after = images[i]
					break

			return anchor_before, anchor_after
		
		def propagate_positions(images: list[Image]) -> list[Image]:
			anchors = [(image, index) for index, image in enumerate(images) if image.is_anchor]
			for i, image in enumerate(images):
				if image.is_anchor:
					continue
				if image.date_confidence > 2: # Data non affidabile
					anchor_before, anchor_after = find_anchors(images, i)
					if anchor_before is None and anchor_after is None:
						image.gps_coordinates = None
						image.gps_confidence = 4
						image.address = None
						image.address_confidence = 4
					elif anchor_before is None and anchor_after is not None or anchor_before is not None and anchor_after is None:
						anchor = anchor_before if anchor_after is None else anchor_after
						assert anchor is not None
						image.gps_coordinates = anchor.gps_coordinates
						image.gps_confidence = 3
						image.address = anchor.address
						image.address_confidence = 3
					elif anchor_before is not None and anchor_after is not None:
						from app.utils import coordinates_distance
						anchor_distance = coordinates_distance(anchor_before.gps_coordinates, anchor_after.gps_coordinates)
						if anchor_distance <= 150:
							pass
				elif image.date_confidence <= 2: # Data affidabile
					pass

		# Add nodes and edges for enrichment steps here
		self._workflow = workflow.compile()

	def __call__(self, images: list[Image]) -> list[Image]:
		return self._workflow.invoke({'images': images})['images']