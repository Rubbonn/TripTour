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
			anchor_before = next((image for image in reversed(images[:index]) if image.is_anchor), None)
			anchor_after = next((image for image in images[index + 1:] if image.is_anchor), None)
			return anchor_before, anchor_after

		def inherit_position(image: Image, anchor: Image, confidence: int) -> None:
			image.gps_coordinates = anchor.gps_coordinates
			image.gps_confidence = confidence
			if anchor.address is not None:
				image.address = anchor.address
				image.address_confidence = confidence
		
		def propagate_positions(images: list[Image]) -> list[Image]:
			from app.utils import coordinates_distance
			distance_threshold = 150
			time_threshold = 3600
			for i, image in enumerate(images):
				if image.gps_coordinates is not None:
					continue

				anchor_before, anchor_after = find_anchors(images, i)
				if anchor_before is None or anchor_after is None:
					# Al massimo un'àncora: lo spostamento non si può stimare
					anchor = anchor_before or anchor_after
					if anchor is not None and (image.date_confidence > 2 or abs(image.date - anchor.date).total_seconds() <= time_threshold):
						inherit_position(image, anchor, 3)
					continue

				anchor_distance = coordinates_distance(anchor_before.gps_coordinates, anchor_after.gps_coordinates)
				if image.date_confidence > 2: # Data non affidabile: vale solo l'ordine, la foto è tra le due àncore
					most_similar_anchor = anchor_before if image.cosine_similarity(anchor_before) > image.cosine_similarity(anchor_after) else anchor_after
					anchor_date_difference = (anchor_after.date - anchor_before.date).total_seconds()
					inherit_position(image, most_similar_anchor, 2 if anchor_distance <= distance_threshold and anchor_date_difference <= time_threshold else 3)
					continue

				gap_before = (image.date - anchor_before.date).total_seconds()
				gap_after = (anchor_after.date - image.date).total_seconds()
				nearest_anchor, nearest_gap = (anchor_before, gap_before) if gap_before <= gap_after else (anchor_after, gap_after)
				if gap_before <= time_threshold and gap_after <= time_threshold:
					# Moto uniforme tra le due àncore: spostamento stimato rispetto all'àncora più vicina nel tempo
					displacement = anchor_distance * nearest_gap / (gap_before + gap_after) if gap_before + gap_after > 0 else 0.0
					inherit_position(image, nearest_anchor, 2 if displacement <= distance_threshold else 3)
				elif nearest_gap <= time_threshold or anchor_distance <= distance_threshold:
					# Una sola àncora entro l'ora, oppure àncore nello stesso luogo ma lontane nel tempo
					inherit_position(image, nearest_anchor, 3)
			return images

		workflow.add_node('propagate_positions', lambda state: {'images': propagate_positions(state['images'])})
		workflow.add_edge(START, 'propagate_positions')
		workflow.add_edge('propagate_positions', END)
		self._workflow = workflow.compile()

	def __call__(self, images: list[Image]) -> list[Image]:
		return self._workflow.invoke({'images': images})['images']