'''
Copyright (C) 2026  Ruben Giuriato - Licensed under GNU GPLv3
'''

from os import environ
from pathlib import Path
from dotenv import dotenv_values

# Percorso assoluto: il .env viene trovato anche quando la CWD non è la root
# del progetto (gunicorn, systemd, container con workdir diversa).
_ENV_FILE = Path(__file__).resolve().parent.parent / '.env'

# Chiavi note anche quando il .env non esiste (produzione: i valori arrivano
# dall'orchestratore). Le chiavi presenti nel .env si aggiungono a queste.
_KNOWN_KEYS = frozenset({
	'MARIADB_HOST',
	'MARIADB_USER',
	'MARIADB_PASSWORD',
	'MARIADB_DATABASE',
})

# Le variabili d'ambiente reali hanno priorità sul file .env (12-factor): in
# produzione i valori arrivano dall'orchestratore e il .env resta come fallback
# per lo sviluppo. Si leggono solo le chiavi note, per non trascinare dentro
# PATH, HOME e il resto dell'ambiente di sistema.
_env_file_values = dotenv_values(_ENV_FILE)
_keys = _KNOWN_KEYS | _env_file_values.keys()
settings = {
	**{key: _env_file_values[key] for key in _env_file_values},
	**{key: environ[key] for key in _keys if key in environ},
}