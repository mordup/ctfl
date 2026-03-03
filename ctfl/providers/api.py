from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import json

from . import DailyUsage, ModelTokens, UsageData
from ..constants import DATE_FMT_ISO

BASE_URL = "https://api.anthropic.com/v1/organizations"


class ApiProvider:
    def __init__(self, get_api_key) -> None:
        self._get_api_key = get_api_key

    def fetch(self, days: int) -> UsageData:
        api_key = self._get_api_key()
        if not api_key:
            return UsageData(error="No Admin API key configured")
        try:
            return self._fetch(api_key, days)
        except HTTPError as e:
            if e.code == 401:
                return UsageData(error="API: invalid API key")
            if e.code == 403:
                return UsageData(error="API: key lacks admin permissions")
            if e.code == 429:
                return UsageData(error="API: rate limited, try again later")
            return UsageData(error=f"API: HTTP {e.code}")
        except (URLError, OSError) as e:
            return UsageData(error=f"API: network error — {e}")
        except Exception as e:
            return UsageData(error=f"API: {e}")

    def _fetch(self, api_key: str, days: int) -> UsageData:
        end = datetime.now(timezone.utc).strftime(DATE_FMT_ISO)
        start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(DATE_FMT_ISO)

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        # Fetch usage report
        usage_url = f"{BASE_URL}/usage?start_date={start}&end_date={end}"
        usage_data = self._request(usage_url, headers)

        # Fetch cost report
        cost_url = f"{BASE_URL}/cost?start_date={start}&end_date={end}"
        try:
            cost_data = self._request(cost_url, headers)
        except Exception:
            cost_data = {}

        return self._parse(usage_data, cost_data)

    def _request(self, url: str, headers: dict) -> dict:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())

    def _parse(self, usage_data: dict, cost_data: dict) -> UsageData:
        if not isinstance(usage_data.get("data"), list):
            return UsageData(error="API: unexpected response structure")

        daily: list[DailyUsage] = []
        by_model: dict[str, ModelTokens] = {}

        cost_by_date = {}
        for item in cost_data.get("data", []):
            cost_by_date[item.get("date", "")] = item.get("cost_usd", 0)

        for item in usage_data["data"]:
            date = item.get("date", "")
            day = DailyUsage(
                date=date,
                input_tokens=item.get("input_tokens", 0),
                output_tokens=item.get("output_tokens", 0),
                cache_read_tokens=item.get("cache_read_input_tokens", 0),
                cache_creation_tokens=item.get("cache_creation_input_tokens", 0),
                cost_usd=cost_by_date.get(date),
            )
            daily.append(day)

            model = item.get("model", "unknown")
            if model not in by_model:
                by_model[model] = ModelTokens(model=model)
            mt = by_model[model]
            mt.input_tokens += day.input_tokens
            mt.output_tokens += day.output_tokens
            mt.cache_read_tokens += day.cache_read_tokens
            mt.cache_creation_tokens += day.cache_creation_tokens

        daily.sort(key=lambda d: d.date, reverse=True)
        model_list = sorted(by_model.values(), key=lambda m: m.total, reverse=True)
        return UsageData(daily=daily, by_model=model_list)
