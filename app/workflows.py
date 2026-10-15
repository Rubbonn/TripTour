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
			from app.utils import coordinates_distance
			distance_threshold = 150
			time_threshold = 3600
			for i, image in enumerate(images):
				if image.gps_coordinates is not None:
					continue

				anchor_before, anchor_after = find_anchors(images, i)
				if image.date_confidence > 2: # Data non affidabile
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
						anchor_distance = coordinates_distance(anchor_before.gps_coordinates, anchor_after.gps_coordinates)
						most_similar_anchor = anchor_before if image.cosine_similarity(anchor_before) > image.cosine_similarity(anchor_after) else anchor_after
						if anchor_distance <= distance_threshold:
							anchor_date_difference = (anchor_after.date - anchor_before.date).total_seconds()
							image.gps_coordinates = most_similar_anchor.gps_coordinates
							image.gps_confidence = 2 if anchor_date_difference <= time_threshold else 3
							image.address = most_similar_anchor.address
							image.address_confidence = 2 if anchor_date_difference <= time_threshold else 3
						else:
							image.gps_coordinates = most_similar_anchor.gps_coordinates
							image.gps_confidence = 3
							image.address = most_similar_anchor.address
							image.address_confidence = 3
				elif image.date_confidence <= 2: # Data affidabile
					if anchor_before is not None and (image.date - anchor_before.date).total_seconds() > time_threshold:
						anchor_before = None
					if anchor_after is not None and (anchor_after.date - image.date).total_seconds() > time_threshold:
						anchor_after = None
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
						gap_before = (image.date - anchor_before.date).total_seconds()
						gap_after = (anchor_after.date - image.date).total_seconds()
						nearest_anchor, nearest_gap = (anchor_before, gap_before) if gap_before <= gap_after else (anchor_after, gap_after)
						# Moto uniforme tra le due àncore: spostamento stimato rispetto all'àncora più vicina nel tempo
						anchor_distance = coordinates_distance(anchor_before.gps_coordinates, anchor_after.gps_coordinates)
						total_gap = gap_before + gap_after
						displacement = anchor_distance * nearest_gap / total_gap if total_gap > 0 else 0.0
						confidence = 2 if displacement <= distance_threshold else 3
						image.gps_coordinates = nearest_anchor.gps_coordinates
						image.gps_confidence = confidence
						image.address = nearest_anchor.address
						image.address_confidence = confidence
			return images

		# Add nodes and edges for enrichment steps here
		self._workflow = workflow.compile()

	def __call__(self, images: list[Image]) -> list[Image]:
		return self._workflow.invoke({'images': images})['images']