import keyring

from .constants import APP_NAME

_SERVICE = APP_NAME
_KEY_NAME = "anthropic_admin_api_key"
_SESSION_KEY_NAME = "claude_session_key"
_CF_CLEARANCE_NAME = "claude_cf_clearance"


class Credentials:
    def get_api_key(self) -> str | None:
        try:
            return keyring.get_password(_SERVICE, _KEY_NAME)
        except Exception:
            return None

    def set_api_key(self, key: str) -> None:
        try:
            keyring.set_password(_SERVICE, _KEY_NAME, key)
        except Exception as e:
            raise RuntimeError(f"Failed to save API key: {e}") from e

    def delete_api_key(self) -> None:
        try:
            keyring.delete_password(_SERVICE, _KEY_NAME)
        except keyring.errors.PasswordDeleteError:
            pass

    def get_session_key(self) -> str | None:
        try:
            return keyring.get_password(_SERVICE, _SESSION_KEY_NAME)
        except Exception:
            return None

    def set_session_key(self, key: str) -> None:
        try:
            keyring.set_password(_SERVICE, _SESSION_KEY_NAME, key)
        except Exception as e:
            raise RuntimeError(f"Failed to save session key: {e}") from e

    def delete_session_key(self) -> None:
        try:
            keyring.delete_password(_SERVICE, _SESSION_KEY_NAME)
        except keyring.errors.PasswordDeleteError:
            pass

    def get_cf_clearance(self) -> str | None:
        try:
            return keyring.get_password(_SERVICE, _CF_CLEARANCE_NAME)
        except Exception:
            return None

    def set_cf_clearance(self, key: str) -> None:
        try:
            keyring.set_password(_SERVICE, _CF_CLEARANCE_NAME, key)
        except Exception as e:
            raise RuntimeError(f"Failed to save cf_clearance: {e}") from e

    def delete_cf_clearance(self) -> None:
        try:
            keyring.delete_password(_SERVICE, _CF_CLEARANCE_NAME)
        except keyring.errors.PasswordDeleteError:
            pass
