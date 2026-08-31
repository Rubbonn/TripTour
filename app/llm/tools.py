'''
Copyright (C) 2026  Ruben Giuriato - Licensed under GNU GPLv3
'''

from app.utils import WikipediaSearch
from langchain.tools import tool

@tool
def wikipedia_search_keyword(keyword: str) -> dict[str, str]:
	"""
	Search Wikipedia articles by keywords

	Args:
		keyword: (string) The keywords to perform the full text search

	Returns:
		A list of articles indexed by their titles
	"""
	return WikipediaSearch.search_by_keyword(keyword)