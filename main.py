from app.models.vlm import Vlm

vlm = Vlm()
vlm([
	{'role': 'user', 'content': 'Ciao come stai?'}
])