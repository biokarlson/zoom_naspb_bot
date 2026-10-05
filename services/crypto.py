from cryptography.fernet import Fernet

import config

_f = Fernet(config.SETTINGS_KEY.encode())


def encrypt(text: str) -> str:
    return _f.encrypt(text.encode()).decode()


def decrypt(token: str) -> str:
    return _f.decrypt(token.encode()).decode()
