'''
Copyright (C) 2026  Ruben Giuriato - Licensed under GNU GPLv3
'''

from app.settings import settings, SETTINGS_LIST

for setting in SETTINGS_LIST:
	value = input(f'Enter {setting.value.replace("_", " ").title()}: ')
	settings.set(setting.value, value)