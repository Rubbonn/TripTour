'''
Copyright (C) 2026  Ruben Giuriato - Licensed under GNU GPLv3
'''

from app.images import Image, order_images_by_date, remove_duplicate_images
		
class PreFilterWorkflow:
	def __call__(self, images: list[Image]) -> list[Image]:
		images = order_images_by_date(images)
		images = remove_duplicate_images(images)
		return images

class EnrichmentWorkflow:
	@classmethod
	def _find_anchors(cls, images: list[Image], index: int) -> tuple[Image | None, Image | None]:
		anchor_before = next((image for image in reversed(images[:index]) if image.is_anchor), None)
		anchor_after = next((image for image in images[index + 1:] if image.is_anchor), None)
		return anchor_before, anchor_after

	@classmethod
	def _inherit_position(cls, image: Image, anchor: Image, confidence: int) -> None:
		image.gps_coordinates = anchor.gps_coordinates
		image.gps_confidence = confidence
		if anchor.address is not None:
			image.address = anchor.address
			image.address_confidence = confidence

	@classmethod
	def _propagate_positions(cls, images: list[Image]) -> list[Image]:
		from app.utils import coordinates_distance
		distance_threshold = 150
		time_threshold = 3600
		for i, image in enumerate(images):
			if image.gps_coordinates is not None:
				continue

			anchor_before, anchor_after = cls._find_anchors(images, i)
			if anchor_before is None or anchor_after is None:
				# Al massimo un'àncora: lo spostamento non si può stimare
				anchor = anchor_before or anchor_after
				if anchor is not None and (image.date_confidence > 2 or abs(image.date - anchor.date).total_seconds() <= time_threshold):
					cls._inherit_position(image, anchor, 3)
				continue

			anchor_distance = coordinates_distance(anchor_before.gps_coordinates, anchor_after.gps_coordinates)
			if image.date_confidence > 2: # Data non affidabile: vale solo l'ordine, la foto è tra le due àncore
				most_similar_anchor = anchor_before if image.cosine_similarity(anchor_before) > image.cosine_similarity(anchor_after) else anchor_after
				anchor_date_difference = (anchor_after.date - anchor_before.date).total_seconds()
				cls._inherit_position(image, most_similar_anchor, 2 if anchor_distance <= distance_threshold and anchor_date_difference <= time_threshold else 3)
				continue

			gap_before = (image.date - anchor_before.date).total_seconds()
			gap_after = (anchor_after.date - image.date).total_seconds()
			nearest_anchor, nearest_gap = (anchor_before, gap_before) if gap_before <= gap_after else (anchor_after, gap_after)
			if gap_before <= time_threshold and gap_after <= time_threshold:
				# Moto uniforme tra le due àncore: spostamento stimato rispetto all'àncora più vicina nel tempo
				displacement = anchor_distance * nearest_gap / (gap_before + gap_after) if gap_before + gap_after > 0 else 0.0
				cls._inherit_position(image, nearest_anchor, 2 if displacement <= distance_threshold else 3)
			elif nearest_gap <= time_threshold or anchor_distance <= distance_threshold:
				# Una sola àncora entro l'ora, oppure àncore nello stesso luogo ma lontane nel tempo
				cls._inherit_position(image, nearest_anchor, 3)
		return images

	@classmethod
	def _enrich_images(cls, images: list[Image]) -> list[Image]:
		from app.llm.vlm import Vlm
		from app.llm.prompts import photo_enrichment_system_prompt, photo_enrichment_first_picture
		vlm = Vlm()
		for i, image in enumerate(images):
			if image.description is not None:
				continue

	def __call__(self, images: list[Image]) -> list[Image]:
		images = self._propagate_positions(images)
		images = self._enrich_images(images)
		return images