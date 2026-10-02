from __future__ import annotations

import contextlib
import json
import os
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from ..constants import DATE_FMT_ISO
from . import DailyUsage, ModelTokens, ProjectUsage, UsageData, history
from .history import DayRecord, history_file, history_start
from .instance import Instance, discover_instances, newest_jsonl_mtime, resolve_profile

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


def _daily_usage(date_str: str, rec: DayRecord) -> DailyUsage:
    return DailyUsage(
        date=date_str,
        message_count=rec.messages,
        session_count=rec.sessions,
        input_tokens=sum(t[0] for t in rec.tokens.values()),
        output_tokens=sum(t[1] for t in rec.tokens.values()),
        cache_read_tokens=sum(t[2] for t in rec.tokens.values()),
        cache_creation_tokens=sum(t[3] for t in rec.tokens.values()),
    )


def _model_tokens(rec: DayRecord) -> list[ModelTokens]:
    by_model: dict[str, ModelTokens] = {}
    for (model, _speed), t in rec.tokens.items():
        mt = by_model.get(model)
        if mt is None:
            mt = by_model[model] = ModelTokens(model=model)
        mt.input_tokens += t[0]
        mt.output_tokens += t[1]
        mt.cache_read_tokens += t[2]
        mt.cache_creation_tokens += t[3]
    return list(by_model.values())


_MAX_CACHE_ENTRIES = 1000

class LocalProvider:
    def __init__(self, config: Config | None = None) -> None:
        # Cache parsed JSONL keyed by (filepath, mtime) -> list of parsed records
        self._file_cache: dict[tuple[str, float], list[dict]] = {}
        self._config = config
        # Instance path -> (day, newest transcript mtime) at its last archive pass
        self._archived: dict[Path, tuple[date, float | None]] = {}

    def fetch(self, days: int) -> UsageData:
        try:
            return self._fetch(days)
        except PermissionError:
            return UsageData(error="Local: cannot read Claude data files")
        except OSError as e:
            return UsageData(error=f"Local: file access error — {e}")
        except Exception as e:
            return UsageData(error=f"Local: {e}")

    def _fetch(self, days: int) -> UsageData:
        instance = resolve_profile(self._config)
        today = datetime.now().date()

        # Records are bucketed by local day (see _parse_jsonl), so the window
        # is bounded in local time too.
        cutoff_date = (today - timedelta(days=days - 1)).strftime(DATE_FMT_ISO)

        # The transcripts are the primary source for the whole window: they
        # carry the per-category breakdown the stats cache lacks, and so are
        # the only source a day can be priced from. CTFL's own history fills
        # the days whose transcripts are gone (cleanupPeriodDays), and the
        # stats cache, which Claude Code refreshes only when /stats is opened,
        # whatever is still missing.
        start = history_start(today).strftime(DATE_FMT_ISO)
        records = self._update_history(
            instance, self._scan_jsonl_files(instance.projects_dir, min(cutoff_date, start)), today
        )
        self._archive_other_instances(instance, today)

        daily_map: dict[str, DailyUsage] = {}
        models_by_day: dict[str, list[ModelTokens]] = {}
        projects_by_day: dict[str, list[ProjectUsage]] = {}
        for date_str, rec in records.items():
            if date_str < cutoff_date:
                continue
            daily_map[date_str] = _daily_usage(date_str, rec)
            models_by_day[date_str] = _model_tokens(rec)
            projects_by_day[date_str] = [
                ProjectUsage(name=name, path=path, total_tokens=tokens, message_count=messages)
                for path, (name, tokens, messages) in rec.projects.items()
            ]

        cache_data = self._read_stats_cache(instance.stats_file)
        activity_by_date = {
            a["date"]: a for a in cache_data.get("dailyActivity", [])
        }
        tokens_by_date = {
            t["date"]: t.get("tokensByModel", {})
            for t in cache_data.get("dailyModelTokens", [])
        }

        # The two lists are written independently and do not always cover the
        # same dates.
        for date_str in activity_by_date.keys() | tokens_by_date.keys():
            if date_str < cutoff_date or date_str in daily_map:
                continue
            activity = activity_by_date.get(date_str, {})
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
            models_by_day[date_str] = [
                ModelTokens(model=model, input_tokens=total, breakdown_available=False)
                for model, total in model_tokens.items()
            ]

        # Estimate costs from per-model token data when enabled
        if self._config and self._config.estimate_costs:
            from .pricing import estimate_daily_cost
            for date_str, rec in records.items():
                if date_str < cutoff_date or not rec.tokens:
                    continue
                # Cache writes are split by TTL because the two are billed at
                # different rates (1.25x input for 5-minute, 2x for 1-hour),
                # and speed is in the key because fast mode is billed at a
                # premium for the same model.
                model_map = {
                    key: (t[0], t[1], t[2], t[4], t[5]) for key, t in rec.tokens.items()
                }
                daily_map[date_str].cost_usd = estimate_daily_cost(model_map, date=date_str)
                for mt in models_by_day[date_str]:
                    mt.cost_usd = estimate_daily_cost(
                        {key: tokens for key, tokens in model_map.items() if key[0] == mt.model},
                        date=date_str,
                    )

        # Sort daily by date descending, filter to requested range
        daily_list = sorted(daily_map.values(), key=lambda d: d.date, reverse=True)

        return UsageData(
            daily=daily_list,
            models_by_day=models_by_day,
            projects_by_day=projects_by_day,
        )

    def _update_history(
        self, instance: Instance, scanned: dict[str, DayRecord], today: date
    ) -> dict[str, DayRecord]:
        """Fold the finished scanned days into the instance's history and
        return the scanned days completed from it.

        Claude Code deletes transcripts file by file, so a day at the edge of
        its cleanup window can survive only in part. A day's message count
        only ever drops through deletion, so the record with more messages is
        the more complete one, whichever source it comes from.
        """
        path = history_file(instance.path)
        stored = history.load(path)
        if stored is None:
            return scanned

        start = history_start(today).strftime(DATE_FMT_ISO)
        today_str = today.strftime(DATE_FMT_ISO)
        kept = {d: r for d, r in stored.items() if start <= d < today_str}
        for date_str, rec in scanned.items():
            if start <= date_str < today_str:
                old = kept.get(date_str)
                if old is None or rec.messages >= old.messages:
                    kept[date_str] = rec
        if kept != stored:
            try:
                history.save(path, kept)
            except OSError:
                pass

        merged = dict(scanned)
        for date_str, rec in kept.items():
            current = merged.get(date_str)
            if current is None or rec.messages > current.messages:
                merged[date_str] = rec
        return merged

    def _archive_other_instances(self, shown: Instance, today: date) -> None:
        """Keep the history of the instances not on display too: Claude Code
        cleans an instance up as it starts, before CTFL can switch to it."""
        start = history_start(today).strftime(DATE_FMT_ISO)
        for instance in discover_instances():
            if instance.path == shown.path:
                continue
            # A new day turns the last scan's today into a finished day.
            signature = (today, newest_jsonl_mtime(instance.projects_dir))
            if self._archived.get(instance.path) == signature:
                continue
            # Best effort: a transcript this instance cannot parse must not
            # cost the one on display its data.
            with contextlib.suppress(Exception):
                self._update_history(
                    instance, self._scan_jsonl_files(instance.projects_dir, start), today
                )
                self._archived[instance.path] = signature

    def _read_stats_cache(self, stats_file: Path) -> dict:
        if not stats_file.exists():
            return {}
        try:
            with open(stats_file) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def _scan_jsonl_files(self, projects_dir: Path, cutoff_date: str) -> dict[str, DayRecord]:
        days: dict[str, DayRecord] = {}
        session_ids: dict[str, set[str]] = defaultdict(set)
        # Spans the whole scan, not just one file, so a request logged in more
        # than one place is still counted once.
        seen_requests: set[str] = set()

        if not projects_dir.exists():
            return days

        # A file last written before the window opened (local midnight) cannot
        # hold a record dated inside it.
        try:
            cutoff_ts = datetime.strptime(cutoff_date, DATE_FMT_ISO).timestamp()
        except ValueError:
            cutoff_ts = 0

        jsonl_files: list[Path] = []
        for pattern in ["*/*.jsonl", "*/*/subagents/*.jsonl"]:
            for p in projects_dir.glob(pattern):
                try:
                    if p.stat().st_mtime >= cutoff_ts:
                        jsonl_files.append(p)
                except OSError:
                    continue

        # Other instances share the cache, so only this tree's entries go.
        prefix = str(projects_dir) + os.sep
        scanned = {str(p) for p in jsonl_files}
        for key in [k for k in self._file_cache if k[0].startswith(prefix) and k[0] not in scanned]:
            del self._file_cache[key]

        names: dict[str, str] = {}
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

                # One API request appears as several assistant records, each
                # carrying an identical copy of the usage. Count it once, or
                # every token, message and cost figure is inflated ~2x.
                request_id = rec.get("request_id", "")
                if request_id:
                    if request_id in seen_requests:
                        continue
                    seen_requests.add(request_id)

                day = days.get(date_str)
                if day is None:
                    day = days[date_str] = DayRecord()
                day.messages += 1

                session_id = rec.get("session_id", "")
                if session_id:
                    session_ids[date_str].add(session_id)

                key = (rec["model"], rec["speed"])
                t = day.tokens.get(key, (0, 0, 0, 0, 0, 0))
                day.tokens[key] = (
                    t[0] + rec["input_tokens"],
                    t[1] + rec["output_tokens"],
                    t[2] + rec["cache_read"],
                    t[3] + rec["cache_creation"],
                    t[4] + rec["cache_creation_5m"],
                    t[5] + rec["cache_creation_1h"],
                )

                if project_dir:
                    if project_dir not in names:
                        names[project_dir] = _resolve_project_name(projects_dir / project_dir)
                    name, tokens, messages = day.projects.get(project_dir, (names[project_dir], 0, 0))
                    day.projects[project_dir] = (
                        name,
                        tokens + rec["input_tokens"] + rec["output_tokens"]
                        + rec["cache_read"] + rec["cache_creation"],
                        messages + 1,
                    )

        for date_str, sessions in session_ids.items():
            days[date_str].sessions = len(sessions)
        return days

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
                    cache_creation = usage.get("cache_creation_input_tokens", 0)
                    ttl_split = usage.get("cache_creation") or {}
                    cc_1h = ttl_split.get("ephemeral_1h_input_tokens", 0)
                    cc_5m = ttl_split.get("ephemeral_5m_input_tokens", 0)
                    # Records that predate the TTL breakdown (or omit it) carry
                    # only the aggregate. Bill the unattributed remainder at the
                    # 5-minute rate, which is the cheaper of the two.
                    cc_5m += max(0, cache_creation - cc_5m - cc_1h)
                    records.append({
                        "date": date_str,
                        "model": msg.get("model", "unknown"),
                        "input_tokens": usage.get("input_tokens", 0),
                        "output_tokens": usage.get("output_tokens", 0),
                        "cache_read": usage.get("cache_read_input_tokens", 0),
                        "cache_creation": cache_creation,
                        "cache_creation_5m": cc_5m,
                        "cache_creation_1h": cc_1h,
                        # Fast mode is billed at a premium, so it is part of the
                        # pricing key. Absent on records predating the field.
                        "speed": usage.get("speed") or "standard",
                        # Claude Code writes one record per assistant content
                        # block (text / thinking / tool_use), each repeating the
                        # same usage object. This identifies the API request so
                        # the aggregation loop counts it once.
                        "request_id": (
                            obj.get("requestId") or msg.get("id") or obj.get("uuid") or ""
                        ),
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
