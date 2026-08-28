from app.constants import _APP_ORG_, _APP_NAME_
from enum import Enum
from PySide6.QtCore import QSettings
from typing import Any, cast

SETTINGS_LIST = Enum('SETTINGS_LIST', [('vlm_api_key', 'vlm_api_key'), ('vlm_base_url', 'vlm_base_url'), ('vlm_model', 'vlm_model')])

class SettingsStore:
	def __init__(self):
		self._store = QSettings(_APP_ORG_, _APP_NAME_)

	def get[T](self, key: str, default: Any = None, type: type[T] = str) -> T:
		return cast(T, self._store.value(key, defaultValue=default, type=type))

	def set(self, key: str, value: Any) -> None:
		self._store.setValue(key, value)

settings = SettingsStore()