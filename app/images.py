'''
Copyright (C) 2026  Ruben Giuriato - Licensed under GNU GPLv3
'''

from app.llm.embedders import get_image_embedder
from app.models import ImageModel
from app.utils import reverse_geocode
from datetime import datetime
from functools import cached_property
try:
	from mimetypes import guess_file_type
except:
	from mimetypes import guess_type as guess_file_type
from pathlib import Path
from PIL import Image as PILImage, ExifTags, ImageFilter
import re
from typing import cast, TYPE_CHECKING
if TYPE_CHECKING:
	from torch import Tensor

class Image:
	def __init__(self, path: str, filename: str, mime: str, gps_coordinates: tuple[float, float] | None, address: str | None, date: datetime | None, description: str | None, laplacian_variance: float, embedding: 'Tensor | None'):
		self.path = path
		self.filename = filename
		self.mime = mime
		self.gps_coordinates = gps_coordinates
		self.address = address
		self.date = date
		self.description = description
		self.laplacian_variance = laplacian_variance
		if embedding is not None:
			self.embedding = embedding

	@cached_property
	def embedding(self) -> 'Tensor':
		image_embedder = get_image_embedder()
		return image_embedder.embed(self.path)

	@classmethod
	def from_file(cls, path: str | Path) -> 'Image':
		if isinstance(path, str):
			path_obj = Path(path)
		else:
			path_obj = path
		if not path_obj.exists() or not path_obj.is_file():
			raise FileNotFoundError(f"The file {path_obj} does not exist.")

		path_obj = path_obj.resolve()
		path = str(path_obj)
		filename = path_obj.name
		mime = guess_file_type(path)[0]
		if mime is None:
			raise ValueError(f"Could not determine MIME type for file {path}")

		gps_coordinates: tuple[float, float] | None = cls._extract_gps_coordinates_from_exif(path)
		if gps_coordinates:
			try:
				address: str | None = reverse_geocode(gps_coordinates[0], gps_coordinates[1])
			except ValueError as e:
				print(f"Reverse geocoding failed for {filename}: {e}")
				address = None
		else:
			address = None
		date: datetime | None = cls._extract_date_from_exif(path) or cls._extract_date_from_filename(filename) or cls._extract_date_from_system(path)
		description: str | None = None
		laplacian_variance: float = cls._calc_laplacian_variance(path)

		return cls(
			path=path,
			filename=filename,
			mime=mime,
			gps_coordinates=gps_coordinates,
			address=address,
			date=date,
			description=description,
			laplacian_variance=laplacian_variance,
			embedding=None,
		)

	@classmethod
	def from_model(cls, model: ImageModel) -> 'Image':
		return cls(
			path=model.path,
			filename=model.filename,
			mime=model.mime,
			gps_coordinates=(model.latitude, model.longitude) if model.latitude and model.longitude else None,
			address=model.address,
			date=model.date,
			description=model.description,
			laplacian_variance=model.laplacian_variance,
			embedding=model.embedding,
		)

	def to_model(self) -> ImageModel:
		return ImageModel(
			path=self.path,
			filename=self.filename,
			mime=self.mime,
			latitude=self.gps_coordinates[0] if self.gps_coordinates else None,
			longitude=self.gps_coordinates[1] if self.gps_coordinates else None,
			address=self.address,
			date=self.date,
			description=self.description,
			laplacian_variance=self.laplacian_variance,
			embedding=self.embedding,
		)

	def read(self) -> bytes:
		return Path(self.path).read_bytes()

	def cosine_similarity(self, other: 'Image') -> float:
		from torch.nn.functional import cosine_similarity
		return cosine_similarity(self.embedding, other.embedding).item()

	@classmethod
	def _extract_gps_coordinates_from_exif(cls, path: str) -> tuple[float, float] | None:
		pil_image = PILImage.open(path)
		exif = pil_image.getexif()
		ifd_gps = exif.get_ifd(ExifTags.IFD.GPSInfo)

		if (exif.get(ExifTags.GPS.GPSLatitude) and exif.get(ExifTags.GPS.GPSLongitude)) or ifd_gps:
			lat = exif.get(ExifTags.GPS.GPSLatitude, ifd_gps[ExifTags.GPS.GPSLatitude])
			lon = exif.get(ExifTags.GPS.GPSLongitude, ifd_gps[ExifTags.GPS.GPSLongitude])
			lat_ref = exif.get(ExifTags.GPS.GPSLatitudeRef, ifd_gps[ExifTags.GPS.GPSLatitudeRef])
			lon_ref = exif.get(ExifTags.GPS.GPSLongitudeRef, ifd_gps[ExifTags.GPS.GPSLongitudeRef])

			lat = float(lat[0] + lat[1] / 60 + lat[2] / 3600)
			lon = float(lon[0] + lon[1] / 60 + lon[2] / 3600)

			if lat_ref == "S":
				lat = -lat
			if lon_ref == "W":
				lon = -lon

			return (lat, lon)
		return None

	@classmethod
	def _extract_date_from_exif(cls, path: str) -> datetime | None:
		pil_image = PILImage.open(path)
		exif = pil_image.getexif()

		date = exif.get(ExifTags.Base.DateTimeDigitized) or exif.get(ExifTags.Base.DateTimeOriginal) or exif.get(ExifTags.Base.DateTime)
		if date:
			date = datetime.strptime(date, "%Y:%m:%d %H:%M:%S")

		return date

	@classmethod
	def _extract_date_from_filename(cls, filename: str) -> datetime | None:
		patterns = [
			# IMG_20260725_143012
			r"^(?:IMG|VID|MVIMG)_(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})_(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})$",
			# PXL_20260725_143012123  (millisecondi opzionali)
			r"^PXL_(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})_(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})(?P<millis>\d{3})?$",
			# 20260725_143012
			r"^(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})_(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})$",
			# 2026-07-25_14-30-12  oppure 2026-07-25 14.30.12
			r"^(?P<year>\d{4})[-_](?P<month>\d{2})[-_](?P<day>\d{2})[ _](?P<hour>\d{2})[.\-:](?P<minute>\d{2})[.\-:](?P<second>\d{2})$",
			# Screenshot_20260725-143012
			r"^Screenshot_(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})[-_](?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})$",
			# Screenshot 2026-07-25 at 14.30.12
			r"^Screenshot[ _](?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})[ _]at[ _](?P<hour>\d{2})[.\-:](?P<minute>\d{2})[.\-:](?P<second>\d{2})$",
			# signal-2026-07-25-143012
			r"^signal-(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})-(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})$",
		]
		for pattern in patterns:
			match = re.match(pattern, filename, re.IGNORECASE)
			if match:
				year = int(match.group("year"))
				month = int(match.group("month"))
				day = int(match.group("day"))
				hour = int(match.group("hour"))
				minute = int(match.group("minute"))
				second = int(match.group("second"))
				return datetime(year, month, day, hour, minute, second)
		return None

	@classmethod
	def _extract_date_from_system(cls, path: str) -> datetime | None:
		stats = Path(path).stat()
		date = datetime.fromtimestamp(stats.st_birthtime if hasattr(stats, 'st_birthtime') else stats.st_ctime)
		return date

	@classmethod
	def _calc_laplacian_variance(cls, path: str) -> float:
		pil_image = PILImage.open(path)
		gray_image = pil_image.convert('L')
		gray_image.thumbnail((1024, 1024), PILImage.Resampling.BILINEAR)
		gray_image = gray_image.filter(ImageFilter.GaussianBlur(radius=0.5))
		w, h = gray_image.size
		if w < 3 or h < 3:
			return 0.0

		px = cast(dict[tuple[int, int], float], gray_image.load())
		lap_values = []
		step = 1
		for y in range(1, h - 1, step):
			for x in range(1, w - 1, step):
				c = px[x, y]
				lap = (
					px[x - 1, y] + px[x + 1, y] +
					px[x, y - 1] + px[x, y + 1] -
					4 * c
				)
				lap_values.append(float(lap))
		if not lap_values:
			return 0.0

		mean = sum(lap_values) / len(lap_values)
		var = sum((v - mean) ** 2 for v in lap_values) / len(lap_values)
		return float(var)
	
	def __repr__(self):
		return f"Image(path='{self.path}', filename='{self.filename}', mime={self.mime}, gps_coordinates={self.gps_coordinates}, address={self.address}, date={self.date}, description={self.description}, laplacian_variance={self.laplacian_variance})"

def remove_duplicate_images(images: list[Image]) -> list[Image]:
	while True:
		removed: bool = False
		for i, image in enumerate(images):
			for j in range(i + 1, len(images)):
				print(f'Comparing {image.filename} with {images[j].filename}, cosine_similarity={image.cosine_similarity(images[j])}')
				if image.cosine_similarity(images[j]) > 0.95:
					print(f'Removing duplicate: {image.filename} vs {images[j].filename}, laplacian_variance={image.laplacian_variance} vs {images[j].laplacian_variance}')
					images.pop(j) if images[j].laplacian_variance < image.laplacian_variance else images.pop(i)
					removed = True
					break
			if removed:
				break

		if not removed:
			return images

def read_dir(directory: str | Path) -> list[Image]:
	if isinstance(directory, str):
		directory = Path(directory)
	directory = directory.resolve()
	images: list[Image] = []
	for file in directory.iterdir():
		if file.is_file() and file.suffix.lower() in ['.jpg', '.jpeg', '.png', '.webp']:
			images.append(Image.from_file(file))
	return images

def order_images_by_date(images: list[Image]) -> list[Image]:
	dated_images = sorted(
		(img for img in images if img.date is not None),
		key=lambda img: img.date
	)
	dated_iter = iter(dated_images)

	return [
		img if img.date is None else next(dated_iter)
		for img in images
	]