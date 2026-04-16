from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from ..constants import DATE_FMT_ISO
from . import DailyUsage, ModelTokens, ProjectUsage, UsageData
from .instance import resolve_profile

if TYPE_CHECKING:
    from ..config import Config


def _resolve_project_name(project_path: Path) -> str:
    """Derive a human-readable name for a project directory.

    The directory name under <instance>/projects/ is a path-encoded string
    like '-home-morgan-Projects-ctfl'. We can't simply replace - with /
    because path components may contain hyphens (e.g. 'my-project').
    Walk the filesystem to reconstruct the real path.
    """
    dirname = project_path.name
    if not dirname.startswith("-"):
        return dirname.capitalize()

    segments = dirname[1:].split("-")  # strip leading -, split on -
    resolved = Path("/")
    i = 0
    while i < len(segments):
        # Try joining progressively more segments (longest first)
        # to handle hyphenated directory names like "my-project"
        matched = False
        for j in range(len(segments), i, -1):
            candidate = "-".join(segments[i:j])
            if (resolved / candidate).is_dir():
                resolved = resolved / candidate
                i = j
                matched = True
                break
        if not matched:
            # Directory doesn't exist (deleted project); use remaining as-is
            resolved = resolved / "-".join(segments[i:])
            break

    return resolved.name.capitalize()


_MAX_CACHE_ENTRIES = 200


class LocalProvider:
    def __init__(self, config: Config | None = None) -> None:
        # Cache parsed JSONL keyed by (filepath, mtime) -> list of parsed records
        self._file_cache: dict[tuple[str, float], list[dict]] = {}
        self._config = config

    def fetch(self, days: int) -> UsageData:
        try:
            return self._fetch(days)
        except json.JSONDecodeError:
            return UsageData(error="Local: corrupt stats-cache file")
        except PermissionError:
            return UsageData(error="Local: cannot read Claude data files")
        except OSError as e:
            return UsageData(error=f"Local: file access error — {e}")
        except Exception as e:
            return UsageData(error=f"Local: {e}")

    def _fetch(self, days: int) -> UsageData:
        instance = resolve_profile(self._config)
        stats_file = instance.stats_file
        projects_dir = instance.projects_dir

        cutoff_date = (datetime.now(UTC) - timedelta(days=days)).strftime(DATE_FMT_ISO)
        cache_data = self._read_stats_cache(stats_file)
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
            # stats-cache only stores combined totals per model per day
            # (no input/output/cache breakdown). Store total in input_tokens
            # so total_tokens property works, but mark breakdown as unavailable
            # to avoid showing misleading per-category data.
            model_tokens = tokens_by_date.get(date_str, {})
            day.input_tokens = sum(model_tokens.values())
            day.breakdown_available = False
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
        jsonl_daily, jsonl_models, by_project, daily_model_tokens = self._scan_jsonl_files(
            projects_dir, cache_cutoff, cutoff_date
        )

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

        # Estimate costs from per-model token data when enabled
        if self._config and self._config.estimate_costs and daily_model_tokens:
            from .pricing import estimate_daily_cost
            for date_str, model_map in daily_model_tokens.items():
                if date_str in daily_map and daily_map[date_str].cost_usd is None:
                    cost = estimate_daily_cost(model_map)
                    if cost is not None:
                        daily_map[date_str].cost_usd = cost

        # Sort daily by date descending, filter to requested range
        daily_list = sorted(daily_map.values(), key=lambda d: d.date, reverse=True)
        model_list = sorted(
            (m for m in model_totals.values() if m.total > 0),
            key=lambda m: m.total,
            reverse=True,
        )

        return UsageData(daily=daily_list, by_model=model_list, by_project=by_project)

    def _read_stats_cache(self, stats_file: Path) -> dict:
        if not stats_file.exists():
            return {}
        try:
            with open(stats_file) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def _scan_jsonl_files(
        self, projects_dir: Path, cache_cutoff: str, cutoff_date: str
    ) -> tuple[dict[str, DailyUsage], dict[str, ModelTokens], list[ProjectUsage],
               dict[str, dict[str, tuple[int, int, int, int]]]]:
        daily_map: dict[str, DailyUsage] = {}
        model_totals: dict[str, ModelTokens] = defaultdict(
            lambda: ModelTokens(model="")
        )
        session_dates: dict[str, set[str]] = defaultdict(set)
        project_agg: dict[str, dict] = {}  # project_dir -> {tokens, messages}
        # Per-day per-model token breakdown for cost estimation
        daily_model_tokens: dict[str, dict[str, list[int]]] = defaultdict(
            lambda: defaultdict(lambda: [0, 0, 0, 0])
        )

        if not projects_dir.exists():
            return daily_map, dict(model_totals), [], {}

        # Find all JSONL files, filter by mtime for performance
        if cache_cutoff:
            try:
                cutoff_ts = datetime.strptime(cache_cutoff, DATE_FMT_ISO).replace(
                    tzinfo=UTC
                ).timestamp()
            except ValueError:
                cutoff_ts = 0
        else:
            cutoff_ts = 0

        jsonl_files: list[Path] = []
        for pattern in ["*/*.jsonl", "*/*/subagents/*.jsonl"]:
            for p in projects_dir.glob(pattern):
                try:
                    if p.stat().st_mtime >= cutoff_ts:
                        jsonl_files.append(p)
                except OSError:
                    continue

        for filepath in jsonl_files:
            # Determine project directory from file path
            try:
                rel = filepath.relative_to(projects_dir)
                project_dir = rel.parts[0]
            except (ValueError, IndexError):
                project_dir = ""

            records = self._parse_jsonl(filepath)
            for rec in records:
                date_str = rec["date"]
                if date_str < cutoff_date:
                    continue
                if cache_cutoff and date_str <= cache_cutoff:
                    continue

                model = rec["model"]
                rec_tokens = rec["input_tokens"] + rec["output_tokens"] + rec["cache_read"] + rec["cache_creation"]

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

                # Per-day per-model tokens for cost estimation
                dmt = daily_model_tokens[date_str][model]
                dmt[0] += rec["input_tokens"]
                dmt[1] += rec["output_tokens"]
                dmt[2] += rec["cache_read"]
                dmt[3] += rec["cache_creation"]

                # Aggregate per-project
                if project_dir:
                    if project_dir not in project_agg:
                        project_agg[project_dir] = {"tokens": 0, "messages": 0}
                    project_agg[project_dir]["tokens"] += rec_tokens
                    project_agg[project_dir]["messages"] += 1

        for date_str, sessions in session_dates.items():
            if date_str in daily_map:
                daily_map[date_str].session_count = len(sessions)

        # Build project usage list
        projects = []
        for project_dir, agg in project_agg.items():
            name = _resolve_project_name(projects_dir / project_dir)
            projects.append(ProjectUsage(
                name=name,
                path=project_dir,
                total_tokens=agg["tokens"],
                message_count=agg["messages"],
            ))
        projects.sort(key=lambda p: p.total_tokens, reverse=True)

        # Convert daily_model_tokens lists to tuples
        dmt_out: dict[str, dict[str, tuple[int, int, int, int]]] = {
            date: {m: tuple(v) for m, v in models.items()}  # type: ignore[misc]
            for date, models in daily_model_tokens.items()
        }
        return daily_map, dict(model_totals), projects, dmt_out

    def _parse_jsonl(self, filepath: Path) -> list[dict]:
        try:
            mtime = filepath.stat().st_mtime
        except OSError:
            return []

        cache_key = (str(filepath), mtime)
        if cache_key in self._file_cache:
            return self._file_cache[cache_key]

        # Evict stale entry for same filepath
        for k in [k for k in self._file_cache if k[0] == str(filepath)]:
            del self._file_cache[k]

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
                        date_str = datetime.fromisoformat(ts).astimezone().strftime(DATE_FMT_ISO)
                    except (ValueError, TypeError):
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
        # Evict oldest entries if cache is too large
        if len(self._file_cache) > _MAX_CACHE_ENTRIES:
            oldest = sorted(self._file_cache, key=lambda k: k[1])
            for k in oldest[: len(self._file_cache) - _MAX_CACHE_ENTRIES]:
                del self._file_cache[k]
        return records
