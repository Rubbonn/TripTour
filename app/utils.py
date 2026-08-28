from app.constants import _USER_AGENT_
import httpx
import re
from typing import Any

class WikipediaSearch:
	_base_url = 'https://wikipedia.org/w/api.php'

	@classmethod
	def get_html_by_pageid(cls, pageid: int) -> str:
		with httpx.Client(headers={'User-Agent': _USER_AGENT_}, follow_redirects=True) as client:
			response = client.get(cls._base_url, params={
				'format': 'json',
				'action': 'parse',
				'pageid': pageid,
				'prop': 'text',
				'disableeditsection': ''
			}).raise_for_status().json()

			return response['parse']['text']['*']

	@classmethod
	def html_to_markdown(cls, html: str) -> str:
		from markitdown import MarkItDown
		from io import BytesIO
		markdown = MarkItDown()
		return markdown.convert_stream(BytesIO(html.encode('utf-8')), file_extension='.html').markdown

	@classmethod
	def clear_unused_sections(cls, md: str) -> str:
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
		with httpx.Client(headers={'User-Agent': _USER_AGENT_}, follow_redirects=True) as client:
			response = client.get(cls._base_url, params={
				'format': 'json',
				'action': 'query',
				'prop': '',
				'list': 'geosearch',
				'gscoord': f'{lat}|{lon}',
				'gslimit': 3,
				'gsprop': ''
			}).raise_for_status().json()
			if len(response['query']['geosearch']) == 0:
				return {}

			results = {article['title']: cls.clear_unused_sections(cls.html_to_markdown(cls.get_html_by_pageid(article['pageid']))) for article in response['query']['geosearch']}
			return results

	@classmethod
	def search_by_keyword(cls, keyword: str) -> dict[str, str]:
		try:
			with httpx.Client(headers={'User-Agent': _USER_AGENT_}, follow_redirects=True) as client:
				response = client.get(cls._base_url, params={
					'format': 'json',
					'action': 'query',
					'prop': '',
					'list': 'search',
					'srsearch': keyword,
					'srenablerewrites': '1',
					'srlimit': 3,
					'srprop': ''
				}).raise_for_status().json()
				if len(response['query']['search']) == 0:
					return {}

				results = {article['title']: cls.clear_unused_sections(cls.html_to_markdown(cls.get_html_by_pageid(article['pageid']))) for article in response['query']['search']}
				return results
		except httpx.HTTPStatusError as e:
			print(f'Error while searching by keyword: {e}')
			raise Exception(f'Error while searching by keyword: {e}')

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

def truncate(value: Any, max_length: int = 100) -> Any:
	# Tronca ricorsivamente le stringhe dentro dizionari e liste, per print di debug leggibili
	if isinstance(value, dict):
		return {key: truncate(item, max_length) for key, item in value.items()}
	if isinstance(value, (list, tuple)):
		return type(value)(truncate(item, max_length) for item in value)
	if isinstance(value, str) and len(value) > max_length:
		return value[:max_length] + '...'

	return value