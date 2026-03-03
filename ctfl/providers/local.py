from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import DailyUsage, ModelTokens, UsageData

CLAUDE_DIR = Path.home() / ".claude"
STATS_FILE = CLAUDE_DIR / "stats-cache.json"
PROJECTS_DIR = CLAUDE_DIR / "projects"


class LocalProvider:
    def __init__(self) -> None:
        # Cache parsed JSONL keyed by (filepath, mtime) -> list of parsed records
        self._file_cache: dict[tuple[str, float], list[dict]] = {}

    def fetch(self, days: int) -> UsageData:
        try:
            return self._fetch(days)
        except Exception as e:
            return UsageData(error=str(e))

    def _fetch(self, days: int) -> UsageData:
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        cache_data = self._read_stats_cache()
        cache_cutoff = cache_data.get("lastComputedDate", "")

        # Build daily data from cache
        daily_map: dict[str, DailyUsage] = {}
        model_totals: dict[str, ModelTokens] = {}

        # Process cached daily activity
        activity_by_date = {
            a["date"]: a for a in cache_data.get("dailyActivity", [])
        }
        tokens_by_date = {
            t["date"]: t.get("tokensByModel", {})
            for t in cache_data.get("dailyModelTokens", [])
        }

        for date_str, activity in activity_by_date.items():
            if date_str < cutoff_date:
                continue
            if date_str > cache_cutoff:
                continue
            day = DailyUsage(
                date=date_str,
                message_count=activity.get("messageCount", 0),
                session_count=activity.get("sessionCount", 0),
            )
            # dailyModelTokens only has combined totals per model
            model_tokens = tokens_by_date.get(date_str, {})
            total = sum(model_tokens.values())
            day.input_tokens = total  # best we can do from cache
            daily_map[date_str] = day

        # Process cached model usage for overall totals
        for model, usage in cache_data.get("modelUsage", {}).items():
            model_totals[model] = ModelTokens(
                model=model,
                input_tokens=usage.get("inputTokens", 0),
                output_tokens=usage.get("outputTokens", 0),
                cache_read_tokens=usage.get("cacheReadInputTokens", 0),
                cache_creation_tokens=usage.get("cacheCreationInputTokens", 0),
            )

        # Scan JSONL files for data after cache cutoff
        jsonl_daily, jsonl_models = self._scan_jsonl_files(cache_cutoff, cutoff_date)

        # JSONL data takes precedence for overlapping dates
        for date_str, day in jsonl_daily.items():
            daily_map[date_str] = day

        # Merge model data: for models that appear in JSONL, add to cache totals
        for model, tokens in jsonl_models.items():
            if model in model_totals:
                mt = model_totals[model]
                mt.input_tokens += tokens.input_tokens
                mt.output_tokens += tokens.output_tokens
                mt.cache_read_tokens += tokens.cache_read_tokens
                mt.cache_creation_tokens += tokens.cache_creation_tokens
            else:
                model_totals[model] = tokens

        # Sort daily by date descending, filter to requested range
        daily_list = sorted(daily_map.values(), key=lambda d: d.date, reverse=True)
        model_list = sorted(
            (m for m in model_totals.values() if m.total > 0),
            key=lambda m: m.total,
            reverse=True,
        )

        return UsageData(daily=daily_list, by_model=model_list)

    def _read_stats_cache(self) -> dict:
        if not STATS_FILE.exists():
            return {}
        try:
            with open(STATS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def _scan_jsonl_files(
        self, cache_cutoff: str, cutoff_date: str
    ) -> tuple[dict[str, DailyUsage], dict[str, ModelTokens]]:
        daily_map: dict[str, DailyUsage] = {}
        model_totals: dict[str, ModelTokens] = defaultdict(
            lambda: ModelTokens(model="")
        )
        session_dates: dict[str, set[str]] = defaultdict(set)

        if not PROJECTS_DIR.exists():
            return daily_map, dict(model_totals)

        # Find all JSONL files, filter by mtime for performance
        if cache_cutoff:
            try:
                cutoff_ts = datetime.strptime(cache_cutoff, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                ).timestamp()
            except ValueError:
                cutoff_ts = 0
        else:
            cutoff_ts = 0

        jsonl_files: list[Path] = []
        for pattern in ["*/*.jsonl", "*/*/subagents/*.jsonl"]:
            for p in PROJECTS_DIR.glob(pattern):
                try:
                    if p.stat().st_mtime >= cutoff_ts:
                        jsonl_files.append(p)
                except OSError:
                    continue

        for filepath in jsonl_files:
            records = self._parse_jsonl(filepath)
            for rec in records:
                date_str = rec["date"]
                if date_str < cutoff_date:
                    continue
                if cache_cutoff and date_str <= cache_cutoff:
                    continue

                model = rec["model"]

                if date_str not in daily_map:
                    daily_map[date_str] = DailyUsage(date=date_str)
                day = daily_map[date_str]
                day.message_count += 1
                day.input_tokens += rec["input_tokens"]
                day.output_tokens += rec["output_tokens"]
                day.cache_read_tokens += rec["cache_read"]
                day.cache_creation_tokens += rec["cache_creation"]

                session_id = rec.get("session_id", "")
                if session_id:
                    session_dates[date_str].add(session_id)

                mt = model_totals[model]
                mt.model = model
                mt.input_tokens += rec["input_tokens"]
                mt.output_tokens += rec["output_tokens"]
                mt.cache_read_tokens += rec["cache_read"]
                mt.cache_creation_tokens += rec["cache_creation"]

        for date_str, sessions in session_dates.items():
            if date_str in daily_map:
                daily_map[date_str].session_count = len(sessions)

        return daily_map, dict(model_totals)

    def _parse_jsonl(self, filepath: Path) -> list[dict]:
        try:
            mtime = filepath.stat().st_mtime
        except OSError:
            return []

        cache_key = (str(filepath), mtime)
        if cache_key in self._file_cache:
            return self._file_cache[cache_key]

        # Evict stale entries for same filepath
        self._file_cache = {
            k: v for k, v in self._file_cache.items() if k[0] != str(filepath)
        }

        records: list[dict] = []
        try:
            with open(filepath) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("type") != "assistant":
                        continue
                    msg = obj.get("message", {})
                    usage = msg.get("usage", {})
                    ts = obj.get("timestamp", "")
                    if not ts:
                        continue
                    try:
                        date_str = ts[:10]  # "2026-03-03" from ISO timestamp
                    except (IndexError, TypeError):
                        continue
                    records.append({
                        "date": date_str,
                        "model": msg.get("model", "unknown"),
                        "input_tokens": usage.get("input_tokens", 0),
                        "output_tokens": usage.get("output_tokens", 0),
                        "cache_read": usage.get("cache_read_input_tokens", 0),
                        "cache_creation": usage.get("cache_creation_input_tokens", 0),
                        "session_id": obj.get("sessionId", ""),
                    })
        except OSError:
            return []

        self._file_cache[cache_key] = records
        return records
