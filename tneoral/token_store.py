#токен в диспетчере учётных данных Windows в файлах его нет

import keyring
from keyring.errors import PasswordDeleteError

SERVICE = "TNeoRal"
USER = "tinvest_token"


def load_token():
    try:
        return keyring.get_password(SERVICE, USER)
    except Exception:
        # на системе без хранилища,просто попросим ввести заново
        return None


def save_token(token):
    keyring.set_password(SERVICE, USER, token.strip())


def delete_token():
    try:
        keyring.delete_password(SERVICE, USER)
    except PasswordDeleteError:
        pass


def mask(token):
    if not token:
        return ""
    if len(token) < 12:
        return "***"
    return token[:4] + "..." + token[-4:]
