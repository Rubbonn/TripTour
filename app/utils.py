from app.constants import _USER_AGENT_
import httpx
import re
from typing import Any

class WikipediaSearch:
	_base_url = 'https://wikipedia.org/w/api.php'

	@classmethod
	def _make_request(cls, params: dict) -> dict:
		import time
		tries = 3
		last_exception = None
		default_retry_after = 5  # Default retry time in seconds for rate limiting
		while tries > 0:
			tries -= 1
			try:
				with httpx.Client(headers={'User-Agent': _USER_AGENT_}, follow_redirects=True) as client:
					response = client.get(cls._base_url, params=params).raise_for_status().json()
					return response
			except httpx.HTTPStatusError as e:
				print(f'Status error while making request to Wikipedia API: {e}')
				last_exception = e
				retry_after = default_retry_after
				if e.response.status_code == 429:
					retry_after = e.response.headers.get('Retry-After', default_retry_after)
					try:
						retry_after = int(retry_after)
					except (TypeError, ValueError):
						retry_after = default_retry_after
					print(f'Rate limit exceeded. Retrying in {retry_after} seconds...')
				if tries > 0:
					time.sleep(retry_after)
					continue
			except (httpx.TimeoutException, httpx.RequestError) as e:
				print(f'Network error while making request to Wikipedia API: {e}')
				last_exception = e
				if tries > 0:
					time.sleep(default_retry_after)
					continue
		raise Exception('Failed to make request to Wikipedia API after 3 attempts') from last_exception


	@classmethod
	def get_html_by_pageid(cls, pageid: int) -> str:
		try:
			response = cls._make_request({
				'format': 'json',
				'action': 'parse',
				'pageid': pageid,
				'prop': 'text',
				'disableeditsection': ''
			})
			return response['parse']['text']['*']
		except Exception as e:
			print(f'Error while fetching HTML by pageid: {e}')
			raise Exception(f'Error while fetching HTML by pageid') from e

	@classmethod
	def _clear_unused_sections(cls, md: str) -> str:
		# Sezioni Wikipedia da rimuovere dall'articolo Markdown
		regex = [
			"See also",
			"References and sources",
			"References",
			"Bibliography",
			"External links",
			"Sources",
			"Sources and external links",
			"Other projects"
		]

		# Combina i nomi in un'unica espressione con alternanza
		alt = "|".join(re.escape(s) for s in regex)

		# ^##[ \t]+         intestazione di livello 2 a inizio riga
		# (?:alt|...)       uno dei nomi consentiti
		# [ \t]*\n          fine dell'intestazione
		# [\s\S]*?          contenuto della sezione (multiriga, non-greedy)
		# (?=^##[ \t]+|\Z)  lookahead: stop alla prossima intestazione o EOF
		pattern = rf"^##[ \t]+(?:{alt})[ \t]*\n[\s\S]*?(?=^##[ \t]+|\Z)"

		return re.sub(pattern, "", md, flags=re.MULTILINE)
	
	@classmethod
	def search_by_coordinates(cls, lat: float, lon: float) -> dict[str, str]:
		try:
			response = cls._make_request({
				'format': 'json',
				'action': 'query',
				'prop': '',
				'list': 'geosearch',
				'gscoord': f'{lat}|{lon}',
				'gslimit': 3,
				'gsprop': ''
			})
			if len(response['query']['geosearch']) == 0:
				return {}

			results = {article['title']: cls._clear_unused_sections(html_to_markdown(cls.get_html_by_pageid(article['pageid']))) for article in response['query']['geosearch']}
			return results
		except Exception as e:
			print(f'Error while searching by coordinates: {e}')
			raise Exception(f'Error while searching by coordinates') from e

	@classmethod
	def search_by_keyword(cls, keyword: str) -> dict[str, str]:
		try:
			response = cls._make_request({
				'format': 'json',
				'action': 'query',
				'prop': '',
				'list': 'search',
				'srsearch': keyword,
				'srenablerewrites': '1',
				'srlimit': 3,
				'srprop': ''
			})
			if len(response['query']['search']) == 0:
				return {}

			results = {article['title']: cls._clear_unused_sections(html_to_markdown(cls.get_html_by_pageid(article['pageid']))) for article in response['query']['search']}
			return results
		except Exception as e:
			print(f'Error while searching by keyword: {e}')
			raise Exception(f'Error while searching by keyword') from e

def reverse_geocode(lat: float, lon: float) -> str:
	with httpx.Client(headers={'User-Agent': _USER_AGENT_}, follow_redirects=True) as client:
		response = client.get('https://nominatim.openstreetmap.org/reverse', params={
			'format': 'json',
			'lat': lat,
			'lon': lon,
			'zoom': 18,
			'addressdetails': 1,
			'extratags': 1,
			'layer': 'poi'
		}).json()
		if 'error' in response:
			raise ValueError(f"Reverse geocoding failed: {response['error']}")
		
		return response['display_name']

def html_to_markdown(html: str) -> str:
	from markitdown import MarkItDown
	from io import BytesIO
	markdown = MarkItDown()
	return markdown.convert_stream(BytesIO(html.encode('utf-8')), file_extension='.html').markdown

def truncate(value: Any, max_length: int = 100) -> Any:
	# Tronca ricorsivamente le stringhe dentro dizionari e liste, per print di debug leggibili
	if isinstance(value, dict):
		return {key: truncate(item, max_length) for key, item in value.items()}
	if isinstance(value, (list, tuple)):
		return type(value)(truncate(item, max_length) for item in value)
	if isinstance(value, str) and len(value) > max_length:
		return value[:max_length] + '...'

	return value