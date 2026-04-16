from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import Config

CLAUDE_HOME = Path.home() / ".claude"
CCS_INSTANCES_ROOT = Path.home() / ".ccs" / "instances"
_PROFILE_AUTO = "auto"


@dataclass(frozen=True)
class Instance:
    name: str           # Display name (e.g. "default", "personal", "work")
    path: Path          # Absolute path to the instance directory

    @property
    def projects_dir(self) -> Path:
        return self.path / "projects"

    @property
    def stats_file(self) -> Path:
        return self.path / "stats-cache.json"

    @property
    def credentials_file(self) -> Path:
        return self.path / ".credentials.json"


def discover_instances() -> list[Instance]:
    """Discover all known Claude Code data directories.

    Always includes ~/.claude as "default" when it exists (or is the only
    candidate), followed by each ~/.ccs/instances/*/ entry, alphabetically.
    """
    found: list[Instance] = []
    if CLAUDE_HOME.is_dir():
        found.append(Instance(name="default", path=CLAUDE_HOME))
    if CCS_INSTANCES_ROOT.is_dir():
        for child in sorted(CCS_INSTANCES_ROOT.iterdir()):
            if child.name.startswith("."):
                continue  # skip .locks/, etc.
            if not child.is_dir():
                continue
            found.append(Instance(name=child.name, path=child.resolve()))
    if not found:
        # No data yet — fall back to the legacy location so downstream
        # "file does not exist" handling can do its thing.
        found.append(Instance(name="default", path=CLAUDE_HOME))
    return found


def detect_active_instance(
    instances: list[Instance], proc_root: Path | None = None
) -> Instance | None:
    """Find the instance whose path matches CLAUDE_CONFIG_DIR on a running
    claude process. Returns None if no match is found.

    Scans /proc/<pid>/environ for our own processes. Silently tolerates
    PermissionError (other users' processes) and races (process exit).
    """
    if proc_root is None:
        proc_root = Path("/proc")
    if not proc_root.is_dir():
        return None

    by_path = {inst.path.resolve(): inst for inst in instances}
    our_uid = os.getuid()

    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            st = entry.stat()
        except (FileNotFoundError, PermissionError):
            continue
        if st.st_uid != our_uid:
            continue
        env_path = entry / "environ"
        try:
            raw = env_path.read_bytes()
        except (FileNotFoundError, PermissionError, OSError):
            continue
        config_dir = _extract_env(raw, b"CLAUDE_CONFIG_DIR")
        if not config_dir:
            continue
        try:
            resolved = Path(config_dir).resolve()
        except (OSError, ValueError):
            continue
        match = by_path.get(resolved)
        if match:
            return match
    return None


def _extract_env(environ_bytes: bytes, key: bytes) -> str | None:
    prefix = key + b"="
    for entry in environ_bytes.split(b"\0"):
        if entry.startswith(prefix):
            try:
                return entry[len(prefix):].decode()
            except UnicodeDecodeError:
                return None
    return None


def newest_activity_instance(instances: list[Instance]) -> Instance | None:
    """Return the instance whose projects/ tree has the most recently
    modified JSONL file. Returns None if nothing has activity.
    """
    best: tuple[float, Instance] | None = None
    for inst in instances:
        projects = inst.projects_dir
        if not projects.is_dir():
            continue
        newest = _newest_jsonl_mtime(projects)
        if newest is None:
            continue
        if best is None or newest > best[0]:
            best = (newest, inst)
    return best[1] if best else None


_JSONL_GLOBS = ("*/*.jsonl", "*/*/subagents/*.jsonl")


def _newest_jsonl_mtime(projects_dir: Path) -> float | None:
    newest: float | None = None
    try:
        for pattern in _JSONL_GLOBS:
            for path in projects_dir.glob(pattern):
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
                if newest is None or mtime > newest:
                    newest = mtime
    except OSError:
        return None
    return newest


def resolve_profile(config: Config | None = None) -> Instance:
    """Resolve the instance to monitor based on config.

    - If config.profile is an absolute path matching a discovered instance
      (or simply exists on disk), use it.
    - Otherwise ("auto" or unrecognized), detect from running processes, then
      fall back to newest-activity, then to the first discovered instance.
    """
    instances = discover_instances()
    pinned = None
    if config is not None:
        pinned = getattr(config, "profile", _PROFILE_AUTO)

    if pinned and pinned != _PROFILE_AUTO:
        pinned_path = Path(pinned).expanduser()
        for inst in instances:
            if inst.path == pinned_path:
                return inst
        # Pinned path exists on disk but wasn't discovered (manual setup) —
        # honor it anyway so a user can point at a custom location.
        if pinned_path.is_dir():
            return Instance(name=pinned_path.name or "custom", path=pinned_path)

    active = detect_active_instance(instances)
    if active is not None:
        return active

    recent = newest_activity_instance(instances)
    if recent is not None:
        return recent

    return instances[0]
