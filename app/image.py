from pathlib import Path
from PIL import Image as PILImage, ExifTags
from datetime import datetime
import re

class Image:
	def __init__(self, path: str):
		path_obj = Path(path)
		if not path_obj.exists() or not path_obj.is_file():
			raise FileNotFoundError(f"The file {path} does not exist.")

		path_obj = path_obj.resolve()
		self.path = str(path_obj)
		self.filename = path_obj.name
		self.gps_coordinates: tuple[float, float] | None = self._extract_gps_coordinates_from_exif()
		

		self.date: datetime | None = self._extract_date_from_exif() or self._extract_date_from_filename()

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

	def __str__(self):
		return f"Image(path='{self.path}', filename='{self.filename}', gps_coordinates={self.gps_coordinates}, date={self.date})"