from PyQt6.QtCore import QSettings

from .constants import APP_NAME


class Config:
    def __init__(self) -> None:
        self._s = QSettings(APP_NAME, APP_NAME)

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

    @property
    def tooltip_today(self) -> bool:
        return self._get("tooltip_today", True, bool)

    @tooltip_today.setter
    def tooltip_today(self, v: bool) -> None:
        self._s.setValue("tooltip_today", v)

    @property
    def tooltip_limits(self) -> bool:
        return self._get("tooltip_limits", True, bool)

    @tooltip_limits.setter
    def tooltip_limits(self, v: bool) -> None:
        self._s.setValue("tooltip_limits", v)

    @property
    def tooltip_sync(self) -> bool:
        return self._get("tooltip_sync", True, bool)

    @tooltip_sync.setter
    def tooltip_sync(self, v: bool) -> None:
        self._s.setValue("tooltip_sync", v)

    @property
    def show_token_breakdown(self) -> bool:
        return self._get("show_token_breakdown", True, bool)

    @show_token_breakdown.setter
    def show_token_breakdown(self, v: bool) -> None:
        self._s.setValue("show_token_breakdown", v)

    @property
    def rate_limit_warning(self) -> bool:
        return self._get("rate_limit_warning", True, bool)

    @rate_limit_warning.setter
    def rate_limit_warning(self, v: bool) -> None:
        self._s.setValue("rate_limit_warning", v)

    @property
    def rate_limit_threshold(self) -> int:
        return self._get("rate_limit_threshold", 80, int)

    @rate_limit_threshold.setter
    def rate_limit_threshold(self, v: int) -> None:
        self._s.setValue("rate_limit_threshold", v)
