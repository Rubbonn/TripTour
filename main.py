from app.image import Image
from app.utils import WikipediaSearch
from app.models.vlm import Vlm
from app.models.tools import wikipedia_search_keyword
import sys

img1 = Image('IMG_20260715_122913.jpg')
img2 = Image('IMG_20260715_112410.jpg')
img3 = Image('IMG_20260715_104924.jpg')

#articles = WikipediaSearch.search_by_coordinates(img1.gps_coordinates[0], img1.gps_coordinates[1])
vlm = Vlm()
vlm([{'role': 'user', 'content': [
	{'type': 'image', 'image': img1.path},
	{'type': 'text', 'text': f'''# Instructions:
Describe the image in detail, including its content, context, and any relevant information. Use the Wikipedia articles to provide additional context and background information about the subject and location of the image. The description should be informative and engaging, providing a comprehensive understanding of the image.

# Image Metadata
{img1.gps_coordinates and f'- GPS Coordinates: {img1.gps_coordinates[0]}, {img1.gps_coordinates[1]}' or ''}
{img1.address and f'- Address: {img1.address}' or ''}
- Image Filename: {img1.filename}
- Image Date: {img1.date}
'''}
]}], tools=[wikipedia_search_keyword])