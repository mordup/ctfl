from PyQt6.QtCore import QSettings

from .constants import APP_NAME
from .dates import PERIODS


class Config:
    def __init__(self) -> None:
        self._s = QSettings(APP_NAME, APP_NAME)
        # Settings earlier versions stored and nothing reads any more.
        for key in ("popup_geometry", "days_to_show"):
            self._s.remove(key)

    def sync(self) -> None:
        """Flush pending writes to disk.

        QSettings otherwise flushes when its destructor runs, which is too late
        for _restart: the replacement process reads the file while the outgoing
        one is still shutting down.
        """
        self._s.sync()

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
    def period(self) -> str:
        """The popup's reporting period: one of dates.PERIODS."""
        v = self._get("period", "week")
        return v if v in PERIODS else "week"

    @period.setter
    def period(self, v: str) -> None:
        self._s.setValue("period", v)

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

    @property
    def estimate_costs(self) -> bool:
        return self._get("estimate_costs", False, bool)

    @estimate_costs.setter
    def estimate_costs(self, v: bool) -> None:
        self._s.setValue("estimate_costs", v)

    @property
    def update_check_interval(self) -> int:
        """Hours between automatic update checks. 0 = disabled."""
        return self._get("update_check_interval", 24, int)

    @update_check_interval.setter
    def update_check_interval(self, v: int) -> None:
        self._s.setValue("update_check_interval", v)

    @property
    def profile(self) -> str:
        """Which Claude data directory to monitor.

        "auto" (default) detects the active instance via running processes
        and JSONL activity. Any other value is an absolute path to pin a
        specific instance (e.g. "/home/morgan/.ccs/instances/personal").
        """
        return self._get("profile", "auto")

    @profile.setter
    def profile(self, v: str) -> None:
        self._s.setValue("profile", v)

