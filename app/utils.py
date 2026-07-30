import httpx

class WikipediaSearch:
	_base_url = 'https://wikipedia.org/w/api.php'

	@classmethod
	def getHtmlByPageid(cls, pageid: int) -> str:
		with httpx.Client(headers={'User-Agent': 'TripTour/1.0'}, follow_redirects=True) as client:
			response = client.get(cls._base_url, params={
				'format': 'json',
				'action': 'parse',
				'pageid': pageid,
				'prop': 'text',
				'disableeditsection': ''
			}).json()

			return response['parse']['text']['*']

	@classmethod
	def htmlToMarkdown(cls, html: str) -> str:
		from markitdown import MarkItDown
		from io import BytesIO
		markdown = MarkItDown()
		return markdown.convert_stream(BytesIO(html.encode('utf-8')), file_extension='.html').markdown
	
	@classmethod
	def searchByCoordinates(cls, lat: float, lon: float) -> dict[str, str]:
		with httpx.Client(headers={'User-Agent': 'TripTour/1.0'}, follow_redirects=True) as client:
			response = client.get(cls._base_url, params={
				'format': 'json',
				'action': 'query',
				'list': 'geosearch',
				'gscoord': f'{lat}|{lon}',
				'gslimit': 1
			}).json()
			if len(response['query']['geosearch']) == 0:
				return {}

			results = {article['title']: cls.htmlToMarkdown(cls.getHtmlByPageid(article['pageid'])) for article in response['query']['geosearch']}
			return results

	@classmethod
	def searchByKeyword(cls, keyword: str) -> dict[str, str]:
		with httpx.Client(headers={'User-Agent': 'TripTour/1.0'}, follow_redirects=True) as client:
			response = client.get(cls._base_url, params={
				'format': 'json',
				'action': 'query',
				'list': 'search',
				'srsearch': keyword,
				'srenablerewrites': '1',
				'srlimit': 3
			}).json()
			if len(response['query']['search']) == 0:
				return {}

			results = {article['title']: cls.htmlToMarkdown(cls.getHtmlByPageid(article['pageid'])) for article in response['query']['search']}
			return results