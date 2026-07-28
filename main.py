from app.image import Image
from app.utils import WikipediaSearch
from app.models.vlm import Vlm

img1 = Image('IMG_20260715_122913.jpg')
articles = WikipediaSearch.searchByCoordinates(img1.gps_coordinates[0], img1.gps_coordinates[1])
vlm = Vlm()
print(vlm([{'role': 'user', 'content': [
	{'type': 'image', 'image': img1.path},
	{'type': 'text', 'text': f'''# Wikipedia articles about the location of the image:
{'\n'.join([f'## {title}\n{content}' for title, content in articles.items()])}
# Instructions:
Describe the image in detail, including its content, context, and any relevant information. Use the Wikipedia articles to provide additional context and background information about the subject and location of the image. The description should be informative and engaging, providing a comprehensive understanding of the image and its significance.
	'''}
]}]))