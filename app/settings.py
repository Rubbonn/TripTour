'''
Copyright (C) 2026  Ruben Giuriato - Licensed under GNU GPLv3
'''

from dotenv import dotenv_values

settings = {
	**dotenv_values('.env')
}