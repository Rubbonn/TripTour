'''
Copyright (C) 2026  Ruben Giuriato - Licensed under GNU GPLv3
'''

from app.llm.embedders import get_image_embedder
from app.utils import reverse_geocode
from datetime import datetime
from functools import cached_property
from pathlib import Path
from PIL import Image as PILImage, ExifTags, ImageFilter
import re
from typing import cast, TYPE_CHECKING
if TYPE_CHECKING:
	from torch import Tensor

class Image:
	def __init__(self, path: str):
		path_obj = Path(path)
		if not path_obj.exists() or not path_obj.is_file():
			raise FileNotFoundError(f"The file {path} does not exist.")

		path_obj = path_obj.resolve()
		self.path = str(path_obj)
		self.filename = path_obj.name
		self.gps_coordinates: tuple[float, float] | None = self._extract_gps_coordinates_from_exif()
		self.address: str | None = self._reverse_geocode()
		self.date: datetime | None = self._extract_date_from_exif() or self._extract_date_from_filename() or self._extract_date_from_system()
		self.description: str | None = None
		self.laplacian_variance: float = self._calc_laplacian_variance()

	@cached_property
	def embedding(self) -> 'Tensor':
		image_embedder = get_image_embedder()
		return image_embedder.embed(self.path)

	def read(self) -> bytes:
		return Path(self.path).read_bytes()

	def cosine_similarity(self, other: 'Image') -> float:
		from torch.nn.functional import cosine_similarity
		return cosine_similarity(self.embedding.unsqueeze(0), other.embedding.unsqueeze(0)).item()

	def _extract_gps_coordinates_from_exif(self) -> tuple[float, float] | None:
		pil_image = PILImage.open(self.path)
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

	def _extract_date_from_exif(self) -> datetime | None:
		pil_image = PILImage.open(self.path)
		exif = pil_image.getexif()

		date = exif.get(ExifTags.Base.DateTimeDigitized) or exif.get(ExifTags.Base.DateTimeOriginal) or exif.get(ExifTags.Base.DateTime)
		if date:
			date = datetime.strptime(date, "%Y:%m:%d %H:%M:%S")

		return date

	def _extract_date_from_filename(self) -> datetime | None:
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
			match = re.match(pattern, self.filename, re.IGNORECASE)
			if match:
				year = int(match.group("year"))
				month = int(match.group("month"))
				day = int(match.group("day"))
				hour = int(match.group("hour"))
				minute = int(match.group("minute"))
				second = int(match.group("second"))
				return datetime(year, month, day, hour, minute, second)
		return None

	def _extract_date_from_system(self) -> datetime | None:
		stats = Path(self.path).stat()
		date = datetime.fromtimestamp(stats.st_birthtime if hasattr(stats, 'st_birthtime') else stats.st_ctime)
		return date

	def _calc_laplacian_variance(self) -> float:
		pil_image = PILImage.open(self.path)
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

	def _reverse_geocode(self) -> str | None:
		if self.gps_coordinates:
			try:
				return reverse_geocode(self.gps_coordinates[0], self.gps_coordinates[1])
			except ValueError as e:
				print(f"Reverse geocoding failed for {self.filename}: {e}")

		return None
	
	def __str__(self):
		return f"Image(path='{self.path}', filename='{self.filename}', gps_coordinates={self.gps_coordinates}, address={self.address}, description={self.description}, date={self.date}, laplacian_variance={self.laplacian_variance})"

def remove_duplicate_images(images: list[Image]) -> list[Image]:
	for i, image in enumerate(images):
		for j in range(i + 1, len(images)):
			if image.cosine_similarity(images[j]) > 0.9:
				pass