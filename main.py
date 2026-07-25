from pathlib import Path
from PIL import Image as PILImage

class Image:
	def __init__(self, path: str):
		path_obj = Path(path)
		if not path_obj.exists() or not path_obj.is_file():
			raise FileNotFoundError(f"The file {path} does not exist.")

		path_obj = path_obj.resolve()
		self.path = str(path_obj)
		self.filename = path_obj.name
		pil_image = PILImage.open(self.path)

		from PIL import ExifTags
		self.gps_coordinates: tuple[float, float] | None = None
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

			self.gps_coordinates = (lat, lon)

	def __str__(self):
		return f"Image(path='{self.path}', filename='{self.filename}', gps_coordinates={self.gps_coordinates})"

img1 = Image('/home/ruben/Scrivania/Copilot_20250605_082746.png')
img2 = Image('IMG_20260715_104924.jpg')
print(img1)
print(img2)