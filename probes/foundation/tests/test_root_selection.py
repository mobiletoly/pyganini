from pathlib import Path

import pytest

from foundation_probes.root_selection import RootSelectionError, select_root

FIXTURES = Path(__file__).parent / "fixtures" / "roots"
OUTER = FIXTURES / "outer"
NESTED = OUTER / "nested"
WORK = NESTED / "work"
EMPTY = FIXTURES / "empty"


def test_marker_free_fixture_directories_have_tracked_sentinels() -> None:
    assert (EMPTY / ".gitkeep").is_file()
    assert (WORK / ".gitkeep").is_file()


def test_application_root_selects_itself() -> None:
    assert (
        select_root(explicit=None, start=NESTED, boundary=FIXTURES) == NESTED.resolve()
    )


def test_nested_working_directory_uses_nearest_candidate() -> None:
    assert select_root(explicit=None, start=WORK, boundary=FIXTURES) == NESTED.resolve()


def test_pytest_process_uses_supplied_start_not_stack_frames() -> None:
    assert select_root(explicit=None, start=WORK, boundary=OUTER) == NESTED.resolve()


def test_editor_process_with_unrelated_cwd_uses_explicit_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(EMPTY)
    assert (
        select_root(explicit=NESTED, start=Path.cwd(), boundary=FIXTURES)
        == NESTED.resolve()
    )


def test_installed_tool_needs_no_source_checkout_when_root_is_explicit(
    tmp_path: Path,
) -> None:
    installed_app = tmp_path / "installed-app"
    installed_app.mkdir()
    (installed_app / ".pyganini-probe-root").write_text("probe\n", encoding="ascii")
    assert (
        select_root(explicit=installed_app, start=tmp_path, boundary=tmp_path)
        == installed_app.resolve()
    )


def test_no_marker_has_actionable_bounded_diagnostic() -> None:
    with pytest.raises(RootSelectionError, match="no project marker") as captured:
        select_root(explicit=None, start=EMPTY, boundary=FIXTURES)
    assert str(FIXTURES.resolve()) in str(captured.value)


def test_explicit_root_precedes_nearer_search_candidate() -> None:
    assert select_root(explicit=OUTER, start=WORK, boundary=FIXTURES) == OUTER.resolve()


def test_multiple_markers_at_one_candidate_are_ambiguous(tmp_path: Path) -> None:
    (tmp_path / "marker-a").write_text("a", encoding="ascii")
    (tmp_path / "marker-b").write_text("b", encoding="ascii")
    with pytest.raises(RootSelectionError, match="ambiguous markers"):
        select_root(
            explicit=None,
            start=tmp_path,
            boundary=tmp_path,
            marker_names=("marker-a", "marker-b"),
        )


def test_search_never_crosses_boundary() -> None:
    with pytest.raises(RootSelectionError, match="no project marker"):
        select_root(
            explicit=None,
            start=EMPTY,
            boundary=EMPTY,
        )


def test_symlink_start_resolves_to_physical_candidate(tmp_path: Path) -> None:
    link = tmp_path / "linked-work"
    link.symlink_to(WORK, target_is_directory=True)
    assert select_root(explicit=None, start=link, boundary=FIXTURES) == NESTED.resolve()


def test_start_outside_boundary_is_rejected() -> None:
    with pytest.raises(RootSelectionError, match="outside boundary"):
        select_root(explicit=None, start=OUTER, boundary=EMPTY)


@pytest.mark.parametrize("role", ["explicit root", "start", "boundary"])
def test_missing_root_input_has_localized_diagnostic(tmp_path: Path, role: str) -> None:
    missing = tmp_path / "missing"
    explicit: Path | None = None
    start = tmp_path
    boundary = tmp_path
    if role == "explicit root":
        explicit = missing
    elif role == "start":
        start = missing
    else:
        boundary = missing

    with pytest.raises(
        RootSelectionError,
        match=rf"root-selection phase: {role} .* cannot be resolved",
    ) as captured:
        select_root(explicit=explicit, start=start, boundary=boundary)
    assert isinstance(captured.value.__cause__, OSError)


def test_explicit_root_does_not_resolve_unused_search_inputs(tmp_path: Path) -> None:
    explicit = tmp_path / "application"
    explicit.mkdir()
    (explicit / ".pyganini-probe-root").write_text("probe\n", encoding="ascii")
    assert (
        select_root(
            explicit=explicit,
            start=tmp_path / "missing-start",
            boundary=tmp_path / "missing-boundary",
        )
        == explicit.resolve()
    )
