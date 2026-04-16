from __future__ import annotations

import os
import time

from ctfl.providers import instance as instance_mod
from ctfl.providers.instance import (
    Instance,
    detect_active_instance,
    discover_instances,
    newest_activity_instance,
    resolve_profile,
)


def _make_env(entries: dict[str, str]) -> bytes:
    return b"\x00".join(f"{k}={v}".encode() for k, v in entries.items()) + b"\x00"


def test_discover_instances_finds_claude_home(tmp_path, monkeypatch):
    claude_home = tmp_path / ".claude"
    claude_home.mkdir()
    monkeypatch.setattr(instance_mod, "CLAUDE_HOME", claude_home)
    monkeypatch.setattr(instance_mod, "CCS_INSTANCES_ROOT", tmp_path / ".ccs" / "instances")

    result = discover_instances()
    assert len(result) == 1
    assert result[0].name == "default"
    assert result[0].path == claude_home


def test_discover_instances_finds_ccs_instances(tmp_path, monkeypatch):
    claude_home = tmp_path / ".claude"
    claude_home.mkdir()
    ccs_root = tmp_path / ".ccs" / "instances"
    (ccs_root / "personal").mkdir(parents=True)
    (ccs_root / "work").mkdir(parents=True)
    (ccs_root / ".locks").mkdir()  # hidden — should be skipped

    monkeypatch.setattr(instance_mod, "CLAUDE_HOME", claude_home)
    monkeypatch.setattr(instance_mod, "CCS_INSTANCES_ROOT", ccs_root)

    result = discover_instances()
    names = [i.name for i in result]
    assert names == ["default", "personal", "work"]


def test_discover_instances_fallback_when_nothing_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(instance_mod, "CLAUDE_HOME", tmp_path / "missing")
    monkeypatch.setattr(instance_mod, "CCS_INSTANCES_ROOT", tmp_path / "nope")

    result = discover_instances()
    assert len(result) == 1
    assert result[0].name == "default"


def test_newest_activity_instance_picks_most_recent(tmp_path):
    inst_a = Instance(name="a", path=tmp_path / "a")
    inst_b = Instance(name="b", path=tmp_path / "b")
    for inst in (inst_a, inst_b):
        (inst.path / "projects" / "proj").mkdir(parents=True)

    old_file = inst_a.projects_dir / "proj" / "old.jsonl"
    new_file = inst_b.projects_dir / "proj" / "new.jsonl"
    old_file.write_text("{}\n")
    new_file.write_text("{}\n")
    now = time.time()
    os.utime(old_file, (now - 1000, now - 1000))
    os.utime(new_file, (now, now))

    result = newest_activity_instance([inst_a, inst_b])
    assert result == inst_b


def test_newest_activity_instance_empty(tmp_path):
    inst = Instance(name="a", path=tmp_path / "a")
    inst.projects_dir.mkdir(parents=True)
    assert newest_activity_instance([inst]) is None


def test_newest_activity_instance_includes_subagent_jsonl(tmp_path):
    inst_a = Instance(name="a", path=tmp_path / "a")
    inst_b = Instance(name="b", path=tmp_path / "b")
    (inst_a.projects_dir / "proj").mkdir(parents=True)
    (inst_b.projects_dir / "proj" / "sess" / "subagents").mkdir(parents=True)

    old_main = inst_a.projects_dir / "proj" / "old.jsonl"
    new_sub = inst_b.projects_dir / "proj" / "sess" / "subagents" / "new.jsonl"
    old_main.write_text("{}\n")
    new_sub.write_text("{}\n")
    now = time.time()
    os.utime(old_main, (now - 1000, now - 1000))
    os.utime(new_sub, (now, now))

    # inst_b only has subagent activity; it must still win over inst_a's older main JSONL.
    assert newest_activity_instance([inst_a, inst_b]) == inst_b


def test_detect_active_instance_via_proc(tmp_path):
    inst_personal = Instance(name="personal", path=tmp_path / "personal")
    inst_work = Instance(name="work", path=tmp_path / "work")
    inst_personal.path.mkdir()
    inst_work.path.mkdir()

    fake_proc = tmp_path / "proc"
    (fake_proc / "123").mkdir(parents=True)
    env_bytes = _make_env({
        "PATH": "/usr/bin",
        "CLAUDE_CONFIG_DIR": str(inst_work.path),
    })
    (fake_proc / "123" / "environ").write_bytes(env_bytes)

    result = detect_active_instance([inst_personal, inst_work], proc_root=fake_proc)
    assert result == inst_work


def test_detect_active_instance_no_match(tmp_path):
    inst = Instance(name="a", path=tmp_path / "a")
    inst.path.mkdir()
    fake_proc = tmp_path / "proc"
    (fake_proc / "1").mkdir(parents=True)
    (fake_proc / "1" / "environ").write_bytes(_make_env({"PATH": "/usr/bin"}))

    assert detect_active_instance([inst], proc_root=fake_proc) is None


def test_resolve_profile_honors_pinned_path(tmp_path, monkeypatch):
    inst_personal = Instance(name="personal", path=tmp_path / "personal")
    inst_work = Instance(name="work", path=tmp_path / "work")
    inst_personal.path.mkdir()
    inst_work.path.mkdir()

    monkeypatch.setattr(
        instance_mod,
        "discover_instances",
        lambda: [inst_personal, inst_work],
    )
    # Detection should not be consulted when a valid pin is present
    monkeypatch.setattr(
        instance_mod,
        "detect_active_instance",
        lambda _instances: (_ for _ in ()).throw(AssertionError("should not call")),
    )

    class _C:
        profile = str(inst_work.path)

    assert resolve_profile(_C()) == inst_work


def test_resolve_profile_auto_falls_back_to_activity(tmp_path, monkeypatch):
    inst_a = Instance(name="a", path=tmp_path / "a")
    inst_b = Instance(name="b", path=tmp_path / "b")
    for inst in (inst_a, inst_b):
        inst.path.mkdir()

    monkeypatch.setattr(instance_mod, "discover_instances", lambda: [inst_a, inst_b])
    monkeypatch.setattr(instance_mod, "detect_active_instance", lambda _ins: None)
    monkeypatch.setattr(instance_mod, "newest_activity_instance", lambda _ins: inst_b)

    class _C:
        profile = "auto"

    assert resolve_profile(_C()) == inst_b


def test_resolve_profile_auto_falls_back_to_first_when_no_activity(tmp_path, monkeypatch):
    inst_a = Instance(name="a", path=tmp_path / "a")
    inst_a.path.mkdir()

    monkeypatch.setattr(instance_mod, "discover_instances", lambda: [inst_a])
    monkeypatch.setattr(instance_mod, "detect_active_instance", lambda _ins: None)
    monkeypatch.setattr(instance_mod, "newest_activity_instance", lambda _ins: None)

    assert resolve_profile(None) == inst_a
