import re
from collections.abc import Callable
from pathlib import Path

import pytest

from pyganini._config import ConfigError, has_pyganini_marker
from pyganini._paths import PathError, select_project_paths


def test_empty_marker_is_the_only_accepted_configuration(tmp_path: Path) -> None:
    project = tmp_path / "pyproject.toml"
    project.write_text("[tool.pyganini]\n", encoding="ascii")
    assert has_pyganini_marker(project, required=True)


def test_unrelated_pyproject_is_not_a_marker(tmp_path: Path) -> None:
    project = tmp_path / "pyproject.toml"
    project.write_text("[project]\nname = 'host'\n", encoding="ascii")
    assert not has_pyganini_marker(project, required=False)


@pytest.mark.parametrize(
    ("document", "reason"),
    [
        ("[tool.pyganini\n", "malformed TOML"),
        ("tool.pyganini = 1\n", "must be a TOML table"),
        ("[tool.pyganini]\nroutes = 'app/routes'\n", "unsupported"),
        ("[project]\nname = 'host'\n", "missing [tool.pyganini]"),
    ],
)
def test_invalid_configuration_is_localized(
    tmp_path: Path, document: str, reason: str
) -> None:
    project = tmp_path / "pyproject.toml"
    project.write_text(document, encoding="ascii")
    with pytest.raises(ConfigError, match=re.escape(reason)) as captured:
        has_pyganini_marker(project, required=True)
    assert captured.value.code == "PYGANINI003"
    assert captured.value.phase == "configuration"
    assert captured.value.path == project


def test_explicit_root_wins_without_resolving_unused_start(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    selected = select_project_paths(
        explicit=application,
        start=tmp_path / "missing working directory",
    )
    assert selected.root == application.resolve()


def test_nearest_physical_marker_wins(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    outer = make_app(tmp_path / "outer")
    inner = make_app(outer / "nested application")
    work = inner / "app" / "routes" / "deep"
    work.mkdir()
    assert select_project_paths(explicit=None, start=work).root == inner.resolve()


def test_symlinked_start_selects_physical_application(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    work = application / "app" / "routes" / "work"
    work.mkdir()
    link = tmp_path / "editor-link"
    link.symlink_to(work, target_is_directory=True)
    assert select_project_paths(explicit=None, start=link).root == application.resolve()


def test_search_stops_at_filesystem_anchor(tmp_path: Path) -> None:
    with pytest.raises(PathError, match=r"no .* marker") as captured:
        select_project_paths(explicit=None, start=tmp_path)
    assert captured.value.code == "PYGANINI001"
    assert captured.value.phase == "root-selection"
    assert str(tmp_path.resolve()) in captured.value.message


@pytest.mark.parametrize(
    ("target", "reason"),
    [
        ("app", "required directory must not be a symlink"),
        ("app/routes", "required directory must not be a symlink"),
        ("app/__init__.py", "required regular file must not be a symlink"),
        ("app/routes/__init__.py", "required regular file must not be a symlink"),
    ],
)
def test_application_boundaries_reject_symlinks(
    tmp_path: Path,
    make_app: Callable[..., Path],
    target: str,
    reason: str,
) -> None:
    application = make_app(tmp_path / "application")
    path = application / target
    replacement = tmp_path / "replacement"
    if path.is_dir():
        path.rename(replacement)
        path.symlink_to(replacement, target_is_directory=True)
    else:
        path.unlink()
        replacement.write_text("", encoding="ascii")
        path.symlink_to(replacement)
    with pytest.raises(PathError, match=reason) as captured:
        select_project_paths(explicit=application, start=tmp_path)
    assert captured.value.code == "PYGANINI004"


def test_missing_route_package_is_a_layout_error(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application", routes=False)
    with pytest.raises(PathError, match="required directory") as captured:
        select_project_paths(explicit=application, start=tmp_path)
    assert captured.value.code == "PYGANINI004"
