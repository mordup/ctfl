from pathlib import Path

from ctfl.providers.local import _resolve_project_name


def test_simple_path(tmp_path):
    # Simulate: -home-user-Projects-ctfl where /home/user/Projects/ctfl exists
    home = tmp_path / "home" / "user" / "Projects" / "ctfl"
    home.mkdir(parents=True)
    dirname = str(tmp_path / "home" / "user" / "Projects" / "ctfl").replace("/", "-")
    project_dir = tmp_path / dirname
    project_dir.mkdir()
    result = _resolve_project_name(project_dir)
    assert result == "Ctfl"


def test_hyphenated_project_name(tmp_path):
    # Simulate: -home-user-my-project where /home/user/my-project exists
    real_dir = tmp_path / "home" / "user" / "my-project"
    real_dir.mkdir(parents=True)
    dirname = str(tmp_path / "home" / "user" / "my-project").replace("/", "-")
    project_dir = tmp_path / dirname
    project_dir.mkdir()
    result = _resolve_project_name(project_dir)
    assert result == "My-project"


def test_deleted_project(tmp_path):
    # Directory encoded but original path no longer exists
    # Only /tmp exists, not /tmp/gone/project
    dirname = "-tmp-gone-project"
    project_dir = tmp_path / dirname
    project_dir.mkdir()
    result = _resolve_project_name(project_dir)
    # Falls back gracefully — last resolvable segment(s)
    assert isinstance(result, str)
    assert len(result) > 0


def test_no_leading_dash():
    project_dir = Path("/some/path/myproject")
    result = _resolve_project_name(project_dir)
    assert result == "Myproject"


def test_capitalizes_output(tmp_path):
    real_dir = tmp_path / "home" / "user" / "lowercase"
    real_dir.mkdir(parents=True)
    dirname = str(tmp_path / "home" / "user" / "lowercase").replace("/", "-")
    project_dir = tmp_path / dirname
    project_dir.mkdir()
    result = _resolve_project_name(project_dir)
    assert result[0].isupper()
