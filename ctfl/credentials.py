import keyring

SERVICE = "ctfl"
KEY_NAME = "anthropic_admin_api_key"


class Credentials:
    def get_api_key(self) -> str | None:
        try:
            return keyring.get_password(SERVICE, KEY_NAME)
        except Exception:
            return None

    def set_api_key(self, key: str) -> None:
        keyring.set_password(SERVICE, KEY_NAME, key)

    def delete_api_key(self) -> None:
        try:
            keyring.delete_password(SERVICE, KEY_NAME)
        except keyring.errors.PasswordDeleteError:
            pass
