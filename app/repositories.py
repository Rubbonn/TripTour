'''
Copyright (C) 2026  Ruben Giuriato - Licensed under GNU GPLv3
'''

from app.database import db
from app.images import Image
from app.models import TourModel, ImageModel
from app.scenes import Scene
from app.tours import Tour

class TourRepository:
	def _fill_image(self, image_model: ImageModel) -> Image:
		'''
		Crea un oggetto Image a partire da un ImageModel.
		'''
		image = Image(
			image_model.id,
			image_model.path,
			image_model.filename,
			image_model.mime,
			(image_model.latitude, image_model.longitude) if image_model.latitude is not None and image_model.longitude is not None else None,
			image_model.gps_confidence,
			image_model.address,
			image_model.address_confidence,
			image_model.date,
			image_model.date_confidence,
			image_model.description,
			image_model.laplacian_variance,
			image_model.embedding
		)
		return image

	def _fill_tour(self, tour_model: TourModel) -> Tour:
		'''
		Crea un oggetto Tour a partire da un TourModel.

		Le Image sono costruite una sola volta e condivise tra la lista piatta
		del tour e le scene, così una foto assegnata a una scena è lo stesso
		oggetto presente in tour.images.
		'''
		images_by_id = {image_model.id: self._fill_image(image_model) for image_model in tour_model.images}
		scenes = [
			Scene(
				scene_model.id,
				scene_model.title,
				[images_by_id[image_model.id] for image_model in scene_model.images]
			)
			for scene_model in tour_model.scenes
		]
		tour = Tour(
			tour_model.id,
			tour_model.title,
			tour_model.language,
			tour_model.created_at,
			list(images_by_id.values()),
			scenes
		)
		return tour

	def get(self, tour_id: int) -> Tour | None:
		'''
		Ritorna il tour con l'id specificato, o None se non esiste.
		'''
		tour_model = db.session.get(TourModel, tour_id)
		if tour_model is None:
			return None
		
		return self._fill_tour(tour_model)