from app.utils import WikipediaSearch

def wikipedia_search_keyword(keyword: str) -> dict[str, str]:
	"""
	Search Wikipedia articles by keywords

	Args:
		keyword: (string) The keywords to perform the full text search

	Returns:
		A list of articles indexed by their titles
	"""
	return WikipediaSearch.searchByKeyword(keyword)