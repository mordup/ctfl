from PyQt6.QtCore import QSettings


class Config:
    def __init__(self) -> None:
        self._s = QSettings("ctfl", "ctfl")

    def _get(self, key: str, default, typ=None):
        v = self._s.value(key, default)
        if typ is bool:
            if isinstance(v, str):
                return v.lower() in ("true", "1", "yes")
            return bool(v)
        if typ is int:
            try:
                return int(v)
            except (ValueError, TypeError):
                return default
        return v

    @property
    def data_source(self) -> str:
        return self._get("data_source", "local")

    @data_source.setter
    def data_source(self, v: str) -> None:
        self._s.setValue("data_source", v)

    @property
    def auto_refresh(self) -> bool:
        return self._get("auto_refresh", True, bool)

    @auto_refresh.setter
    def auto_refresh(self, v: bool) -> None:
        self._s.setValue("auto_refresh", v)

    @property
    def refresh_interval(self) -> int:
        return self._get("refresh_interval", 60, int)

    @refresh_interval.setter
    def refresh_interval(self, v: int) -> None:
        self._s.setValue("refresh_interval", v)

    @property
    def autostart(self) -> bool:
        return self._get("autostart", False, bool)

    @autostart.setter
    def autostart(self, v: bool) -> None:
        self._s.setValue("autostart", v)

    @property
    def days_to_show(self) -> int:
        return self._get("days_to_show", 7, int)

    @days_to_show.setter
    def days_to_show(self, v: int) -> None:
        self._s.setValue("days_to_show", v)
