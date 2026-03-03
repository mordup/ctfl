import keyring

from .constants import APP_NAME

_SERVICE = APP_NAME
_KEY_NAME = "anthropic_admin_api_key"


class Credentials:
    def get_api_key(self) -> str | None:
        try:
            return keyring.get_password(_SERVICE, _KEY_NAME)
        except Exception:
            return None

    def set_api_key(self, key: str) -> None:
        keyring.set_password(_SERVICE, _KEY_NAME, key)

    def delete_api_key(self) -> None:
        try:
            keyring.delete_password(_SERVICE, _KEY_NAME)
        except keyring.errors.PasswordDeleteError:
            pass
