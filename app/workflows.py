'''
Copyright (C) 2026  Ruben Giuriato - Licensed under GNU GPLv3
'''

from app.images import Image, order_images_by_date, remove_duplicate_images
from app.tours import Tour
		
class PreFilterWorkflow:
	def __call__(self, tour: Tour) -> list[Image]:
		images = order_images_by_date(tour.images)
		images = remove_duplicate_images(images)
		return images

class EnrichmentWorkflow:
	@staticmethod
	def _find_anchors(images: list[Image], index: int) -> tuple[Image | None, Image | None]:
		anchor_before = next((image for image in reversed(images[:index]) if image.is_anchor), None)
		anchor_after = next((image for image in images[index + 1:] if image.is_anchor), None)
		return anchor_before, anchor_after

	@staticmethod
	def _inherit_position(image: Image, anchor: Image, confidence: int) -> None:
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
	def _enrich_images(cls, tour: Tour) -> list[Image]:
		for i, image in enumerate(tour.images):
			if image.description is not None:
				continue

			response = cls.enrich_image(tour, i)
			image.description = response
		return tour.images

	@staticmethod
	def enrich_image(tour: Tour, image_index: int) -> str:
		from app.llm.vlm import Vlm
		from app.llm.prompts import photo_enrichment_system_prompt, photo_enrichment_first_picture, photo_enrichment_sliding_window, photo_enrichment_last_picture
		from app.utils import WikipediaSearch, prepare_chat_history
		vlm = Vlm()
		image = tour.images[image_index]
		prev_image = tour.images[image_index - 1] if image_index > 0 else None
		next_image = tour.images[image_index + 1] if image_index < len(tour.images) - 1 else None
		if image.gps_coordinates:
			wikipedia_articles = WikipediaSearch.search_by_coordinates(image.gps_coordinates[0], image.gps_coordinates[1])
		else:
			wikipedia_articles = {}
		if image_index == 0:
			assert next_image is not None
			prompt = photo_enrichment_first_picture.format(
				tour_title=tour.title,
				language_name=tour.language,
				filename=image.filename,
				gps_position=f'{image.gps_coordinates[0]:.6f}, {image.gps_coordinates[1]:.6f}{' (estimated)' if image.gps_confidence > 1 else ''}' if image.gps_coordinates else 'No GPS coordinates available',
				address=f'{image.address}{' (estimated)' if image.address_confidence > 1 else ''}' if image.address else 'No address available',
				date=f'{image.date:%Y-%m-%d %H:%M}{' (estimated)' if image.date_confidence > 1 else ''}' if image.date else 'No date available',
				wikipedia_articles='\n'.join(f'# {title}\n{article}' for title, article in wikipedia_articles.items()) if wikipedia_articles else 'No Wikipedia articles available',
			)
			images_to_attach = [image, next_image]
		elif image_index == len(tour.images) - 1:
			assert prev_image is not None
			prompt = photo_enrichment_last_picture.format(
				tour_title=tour.title,
				language_name=tour.language,
				filename=image.filename,
				gps_position=f'{image.gps_coordinates[0]:.6f}, {image.gps_coordinates[1]:.6f}{' (estimated)' if image.gps_confidence > 1 else ''}' if image.gps_coordinates else 'No GPS coordinates available',
				address=f'{image.address}{' (estimated)' if image.address_confidence > 1 else ''}' if image.address else 'No address available',
				date=f'{image.date:%Y-%m-%d %H:%M}{' (estimated)' if image.date_confidence > 1 else ''}' if image.date else 'No date available',
				wikipedia_articles='\n'.join(f'# {title}\n{article}' for title, article in wikipedia_articles.items()) if wikipedia_articles else 'No Wikipedia articles available',
				previous_filename=prev_image.filename,
				previous_description=prev_image.description or '',
			)
			images_to_attach = [prev_image, image]
		else:
			assert prev_image is not None
			assert next_image is not None
			prompt = photo_enrichment_sliding_window.format(
				tour_title=tour.title,
				language_name=tour.language,
				filename=image.filename,
				gps_position=f'{image.gps_coordinates[0]:.6f}, {image.gps_coordinates[1]:.6f}{' (estimated)' if image.gps_confidence > 1 else ''}' if image.gps_coordinates else 'No GPS coordinates available',
				address=f'{image.address}{' (estimated)' if image.address_confidence > 1 else ''}' if image.address else 'No address available',
				date=f'{image.date:%Y-%m-%d %H:%M}{' (estimated)' if image.date_confidence > 1 else ''}' if image.date else 'No date available',
				wikipedia_articles='\n'.join(f'# {title}\n{article}' for title, article in wikipedia_articles.items()) if wikipedia_articles else 'No Wikipedia articles available',
				previous_filename=prev_image.filename,
				previous_description=prev_image.description or '',
				next_filename=next_image.filename,
			)
			images_to_attach = [prev_image, image, next_image]
		response = vlm(prepare_chat_history(photo_enrichment_system_prompt, prompt, images=images_to_attach))
		return response

	def __call__(self, tour: Tour) -> list[Image]:
		images = self._propagate_positions(tour.images)
		images = self._enrich_images(tour)
		return images