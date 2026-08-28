# pyright: reportPrivateUsage=false

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import FrozenInstanceError
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any, cast

import pytest
from typing_contract_support import assert_checker_result

import pyganini._assets as assets_module
import pyganini._cli as cli_module
import pyganini._filesystem as filesystem_module
from pyganini._assets import (
    AssetError,
    check_assets,
    clean_assets,
    prepare_assets,
    render_asset_list,
    write_assets,
)
from pyganini._cli import main
from pyganini._paths import select_project_paths

ROOT = Path(__file__).resolve().parents[1]
ASSET_FIXTURES = ROOT / "tests" / "fixtures"
CURRENT_DIRECTORY = PurePosixPath(".")
_ASSET_EXPECTED_DIAGNOSTICS = {
    "mypy": (
        (
            ":5:",
            'Argument 1 to "path"',
            'incompatible type "int"',
            'expected "str"',
            "[arg-type]",
        ),
        (
            ":6:",
            'Argument "base_path" to "lookup"',
            'incompatible type "int"',
            'expected "str"',
            "[arg-type]",
        ),
        (
            ":7:",
            "Incompatible types in assignment",
            'expression has type "str | None"',
            'variable has type "Asset"',
            "[assignment]",
        ),
        (
            ":8:",
            "Incompatible types in assignment",
            'expression has type "int"',
            'variable has type "str"',
            "[assignment]",
        ),
    ),
    "pyright": (
        (
            ":5:",
            "Literal[42]",
            'parameter "name"',
            'type "str"',
            'function "path"',
            "reportArgumentType",
        ),
        (
            ":6:",
            "Literal[42]",
            'parameter "base_path"',
            'type "str"',
            'function "lookup"',
            "reportArgumentType",
        ),
        (
            ":7:",
            'Type "str | None" is not assignable to declared type "Asset"',
            "reportAssignmentType",
        ),
        (
            ":8:",
            'Type "int" is not assignable to declared type "str"',
            "reportAssignmentType",
        ),
    ),
}


def _asset_application(make_app: Callable[..., Path], root: Path) -> Path:
    application = make_app(root)
    assets = application / "assets"
    (assets / "build" / "vendor").mkdir(parents=True)
    (assets / "__init__.py").write_text("", encoding="ascii")
    (assets / "build" / "app.css").write_bytes(b"body { color: red; }\n")
    (assets / "build" / "vendor" / "htmx.min.js").write_bytes(b"htmx\n")
    return application


def _empty_asset_application(make_app: Callable[..., Path], root: Path) -> Path:
    application = make_app(root)
    assets = application / "assets"
    (assets / "build").mkdir(parents=True)
    (assets / "__init__.py").write_text("", encoding="ascii")
    return application


def _generated_module(application: Path) -> ModuleType:
    path = application / "assets" / "pyganini_assets_gen.py"
    specification = importlib.util.spec_from_file_location("generated_assets", path)
    assert specification is not None
    loader = specification.loader
    assert loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    try:
        loader.exec_module(module)
    finally:
        sys.modules.pop(specification.name, None)
    return module


def test_dist_renders_fingerprints_state_and_typed_lookup(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    paths = select_project_paths(explicit=application, start=application)

    first = write_assets(prepare_assets(paths, "dist"))
    assert len(first.written) == 4
    assert not first.unchanged
    assert not first.removed
    css_hash = hashlib.sha256(b"body { color: red; }\n").hexdigest()[:8]
    js_hash = hashlib.sha256(b"htmx\n").hexdigest()[:8]
    css = application / "assets" / "dist" / f"app.{css_hash}.css"
    javascript = application / "assets" / "dist" / "vendor" / f"htmx.min.{js_hash}.js"
    assert css.read_bytes() == b"body { color: red; }\n"
    assert javascript.read_bytes() == b"htmx\n"
    state = json.loads(
        (application / "assets" / ".pyganini" / "assets.json").read_text(
            encoding="ascii"
        )
    )
    assert list(state) == ["schema", "managed"]
    assert state["schema"] == "pyganini.assets-state.v1"
    assert [row["logical"] for row in state["managed"]] == [
        "app.css",
        "vendor/htmx.min.js",
    ]
    assert all(list(row) == ["logical", "dist", "hash"] for row in state["managed"])

    generated = _generated_module(application)
    assert generated.path("app.css") == f"/assets/app.{css_hash}.css"
    assert generated.lookup("missing") is None
    assert generated.path("app.css", base_path="directory///") == (
        f"/directory/assets/app.{css_hash}.css"
    )
    assert generated.manifest()["app.css"].hash == css_hash
    assert generated.manifest() is not generated.manifest()
    with pytest.raises(FrozenInstanceError):
        generated.manifest()["app.css"].hash = "00000000"
    with pytest.raises(KeyError, match="unknown asset: missing"):
        generated.path("missing")
    with pytest.raises(TypeError, match="name must be str"):
        generated.path(42)
    with pytest.raises(ValueError, match="empty path segments"):
        generated.path("app.css", base_path="////")

    assert not check_assets(paths)
    second = write_assets(prepare_assets(paths, "dist"))
    assert not second.written
    assert len(second.unchanged) == 4


def test_empty_build_has_empty_products_and_manifest(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = _empty_asset_application(make_app, tmp_path / "application")
    paths = select_project_paths(explicit=application, start=application)

    result = write_assets(prepare_assets(paths, "dist"))
    assert result.written == (
        PurePosixPath("assets/pyganini_assets_gen.py"),
        PurePosixPath("assets/.pyganini/assets.json"),
    )
    assert not check_assets(paths)
    generated = _generated_module(application)
    assert generated.__all__ == ("Asset", "lookup", "manifest", "path")
    assert generated.manifest() == {}
    assert generated.manifest() is not generated.manifest()
    listing = render_asset_list(prepare_assets(paths, "list"), json_output=False)
    assert listing == "Logical asset  URL path  Size\n"


def test_missing_application_package_marker_is_rejected(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    (application / "assets" / "build").mkdir(parents=True)
    paths = select_project_paths(explicit=application, start=application)

    with pytest.raises(AssetError, match=r"assets/__init__\.py"):
        prepare_assets(paths, "list")


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="requires symlink support")
def test_symlinked_build_boundary_and_input_are_rejected(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    assets = application / "assets"
    assets.mkdir()
    (assets / "__init__.py").write_text("", encoding="ascii")
    outside = tmp_path / "outside-build"
    outside.mkdir()
    (outside / "app.css").write_bytes(b"outside\n")
    (assets / "build").symlink_to(outside, target_is_directory=True)
    paths = select_project_paths(explicit=application, start=application)
    with pytest.raises(AssetError, match="must not be a symlink"):
        prepare_assets(paths, "list")

    (assets / "build").unlink()
    (assets / "build").mkdir()
    (assets / "build" / "app.css").symlink_to(outside / "app.css")
    with pytest.raises(AssetError, match="asset inputs must not be symlinks"):
        prepare_assets(paths, "list")


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="requires symlink support")
def test_build_root_swap_after_anchor_cannot_redirect_source_scan(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    assets = application / "assets"
    outside = tmp_path / "outside-build"
    outside.mkdir()
    (outside / "outside.css").write_bytes(b"outside\n")
    held = assets / "build-held"
    paths = select_project_paths(explicit=application, start=application)
    original_entries = filesystem_module._PosixAnchoredFilesystem.entries
    swapped = False

    def swap_build_before_traversal(
        filesystem: Any,
        relative: PurePosixPath = CURRENT_DIRECTORY,
        *,
        skip_transient: bool = True,
    ) -> tuple[filesystem_module.FilesystemEntry, ...]:
        nonlocal swapped
        if (
            relative == CURRENT_DIRECTORY
            and filesystem._root_path == assets / "build"
            and not swapped
        ):
            swapped = True
            (assets / "build").rename(held)
            (assets / "build").symlink_to(outside, target_is_directory=True)
        return original_entries(filesystem, relative, skip_transient=skip_transient)

    monkeypatch.setattr(
        filesystem_module._PosixAnchoredFilesystem,
        "entries",
        swap_build_before_traversal,
    )
    with pytest.raises(AssetError):
        prepare_assets(paths, "list")
    assert (assets / "build").is_symlink()
    assert (held / "app.css").read_bytes() == b"body { color: red; }\n"
    assert (outside / "outside.css").read_bytes() == b"outside\n"


def test_real_build_root_swap_after_validation_cannot_redirect_source_scan(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    assets = application / "assets"
    replacement = tmp_path / "replacement-build"
    replacement.mkdir()
    (replacement / "outside.css").write_bytes(b"outside\n")
    held = assets / "build-held"
    paths = select_project_paths(explicit=application, start=application)
    original_scan = assets_module._scan_build
    swapped = False

    def swap_build_before_scan(paths_arg: Any, filesystem: Any) -> Any:
        nonlocal swapped
        if not swapped:
            swapped = True
            (assets / "build").rename(held)
            replacement.rename(assets / "build")
        return original_scan(paths_arg, filesystem)

    monkeypatch.setattr(assets_module, "_scan_build", swap_build_before_scan)

    with pytest.raises(AssetError, match="changed"):
        prepare_assets(paths, "list")

    assert (held / "app.css").read_bytes() == b"body { color: red; }\n"
    assert (assets / "build" / "outside.css").read_bytes() == b"outside\n"


def test_asset_root_swap_between_prepare_and_write_cannot_redirect_output(
    tmp_path: Path,
    make_app: Callable[..., Path],
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    paths = select_project_paths(explicit=application, start=application)
    plan = prepare_assets(paths, "dist")
    assets = application / "assets"
    held = application / "assets-held"
    replacement = tmp_path / "replacement-assets"
    (replacement / "build").mkdir(parents=True)
    (replacement / "__init__.py").write_text("", encoding="ascii")
    assets.rename(held)
    replacement.rename(assets)

    with pytest.raises(AssetError, match="changed"):
        write_assets(plan)
    assert not (assets / "dist").exists()
    assert not (held / "dist").exists()


def test_application_root_swap_between_prepare_and_write_cannot_redirect_output(
    tmp_path: Path,
    make_app: Callable[..., Path],
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    paths = select_project_paths(explicit=application, start=application)
    plan = prepare_assets(paths, "dist")
    held = application.with_name("application-held")
    replacement = tmp_path / "replacement-application"
    (replacement / "assets" / "build").mkdir(parents=True)
    (replacement / "assets" / "__init__.py").write_text("", encoding="ascii")
    application.rename(held)
    replacement.rename(application)

    with pytest.raises(AssetError, match="changed"):
        write_assets(plan)

    assert not (application / "assets" / "dist").exists()
    assert not (held / "assets" / "dist").exists()


def test_suffixless_and_case_colliding_names_are_validated(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    paths = select_project_paths(explicit=application, start=application)
    favicon = application / "assets" / "build" / "favicon"
    favicon.write_bytes(b"icon\n")
    write_assets(prepare_assets(paths, "dist"))
    digest = hashlib.sha256(b"icon\n").hexdigest()[:8]
    assert (application / "assets" / "dist" / f"favicon.{digest}").exists()

    collision_a = application / "assets" / "build" / "A.css"
    collision_b = application / "assets" / "build" / "a.css"
    collision_a.write_bytes(b"a\n")
    collision_b.write_bytes(b"b\n")
    if collision_a.samefile(collision_b):
        pytest.skip("filesystem is case-insensitive")
    with pytest.raises(AssetError, match="collides"):
        prepare_assets(paths, "list")


def test_list_is_deterministic_and_does_not_read_managed_output(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    assert main(["assets", "list", "--app-root", str(application)]) == 0
    first = capsys.readouterr()
    assert first.err == ""
    assert first.out.splitlines()[0].split() == [
        "Logical",
        "asset",
        "URL",
        "path",
        "Size",
    ]
    assert "app.css" in first.out
    assert "/assets/app." in first.out

    payload = ["assets", "list", "--app-root", str(application), "--json"]
    assert main(payload) == 0
    json_first = capsys.readouterr()
    assert json.loads(json_first.out)["schema"] == "pyganini.assets.v1"
    (application / "assets" / "dist").mkdir()
    (application / "assets" / "dist" / "unrecorded.txt").write_text(
        "application-owned\n", encoding="ascii"
    )
    assert main(payload) == 0
    json_second = capsys.readouterr()
    assert json_second.out == json_first.out


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="requires symlink support")
def test_list_ignores_symlinked_managed_output(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    outside = tmp_path / "outside-dist"
    outside.mkdir()
    (application / "assets" / "dist").symlink_to(outside, target_is_directory=True)

    assert main(["assets", "list", "--app-root", str(application)]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert "app.css" in output.out
    assert not tuple(outside.iterdir())


def test_expected_output_race_never_clobbers_new_application_file(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    paths = select_project_paths(explicit=application, start=application)
    plan = prepare_assets(paths, "dist")
    target = next(asset for asset in plan.assets if asset.logical == "app.css").dist
    destination = application / target
    real_replace = assets_module._replace
    raced = False

    def create_application_file_before_install(
        filesystem: Any,
        relative: PurePosixPath,
        staged: Any,
        expected: os.stat_result | None,
        journal: Any,
    ) -> None:
        nonlocal raced
        if relative == target and not raced:
            raced = True
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"application-owned race\n")
        real_replace(filesystem, relative, staged, expected, journal)

    monkeypatch.setattr(
        assets_module, "_replace", create_application_file_before_install
    )
    with pytest.raises(AssetError, match="ownership changed"):
        write_assets(plan)

    assert destination.read_bytes() == b"application-owned race\n"


def test_recorded_output_race_never_clobbers_new_application_file(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    paths = select_project_paths(explicit=application, start=application)
    write_assets(prepare_assets(paths, "dist"))
    plan = prepare_assets(paths, "dist")
    target = next(asset for asset in plan.assets if asset.logical == "app.css").dist
    destination = application / target
    real_precheck = assets_module._unowned_current_outputs
    raced = False

    def replace_recorded_file_after_precheck(plan_arg: Any, filesystem: Any) -> Any:
        nonlocal raced
        result = real_precheck(plan_arg, filesystem)
        if not raced:
            raced = True
            destination.unlink()
            destination.write_bytes(b"application-owned recorded race\n")
        return result

    monkeypatch.setattr(
        assets_module,
        "_unowned_current_outputs",
        replace_recorded_file_after_precheck,
    )

    with pytest.raises(AssetError, match="changed"):
        write_assets(plan)

    assert destination.read_bytes() == b"application-owned recorded race\n"


def test_staged_parent_swap_cannot_redirect_installation(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    paths = select_project_paths(explicit=application, start=application)
    plan = prepare_assets(paths, "dist")
    target = next(
        asset.dist for asset in plan.assets if asset.logical == "vendor/htmx.min.js"
    )
    parent = application / target.parent
    held = parent.with_name("vendor-held")
    real_replace = assets_module._replace
    swapped = False

    def swap_parent_before_install(
        filesystem: Any,
        relative: PurePosixPath,
        staged: Any,
        expected: os.stat_result | None,
        journal: Any,
    ) -> None:
        nonlocal swapped
        if relative == target and not swapped:
            swapped = True
            parent.rename(held)
            parent.mkdir()
            (parent / staged.temporary_name).write_bytes(b"redirected\n")
        real_replace(filesystem, relative, staged, expected, journal)

    monkeypatch.setattr(assets_module, "_replace", swap_parent_before_install)

    with pytest.raises(AssetError, match=r"parent.*changed"):
        write_assets(plan)

    assert not (parent / target.name).exists()
    assert not any(path.name.startswith("._pyganini-") for path in held.iterdir())


@pytest.mark.parametrize("failure_target", ["asset", "generated", "state"])
def test_changed_fingerprint_recovers_after_each_replacement_failure(
    failure_target: str,
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    paths = select_project_paths(explicit=application, start=application)
    write_assets(prepare_assets(paths, "dist"))
    old_css = next((application / "assets" / "dist").glob("app.*.css"))
    (application / "assets" / "build" / "app.css").write_bytes(b"changed\n")
    plan = prepare_assets(paths, "dist")
    new_css = next(asset for asset in plan.assets if asset.logical == "app.css").dist
    targets = {
        "asset": new_css,
        "generated": PurePosixPath("assets/pyganini_assets_gen.py"),
        "state": PurePosixPath("assets/.pyganini/assets.json"),
    }
    real_replace = assets_module._replace

    def fail_after_target_replacement(
        filesystem: Any,
        relative: PurePosixPath,
        staged: Any,
        expected: os.stat_result | None,
        journal: Any,
    ) -> None:
        real_replace(filesystem, relative, staged, expected, journal)
        if relative == targets[failure_target]:
            raise OSError("injected post-replacement failure")

    monkeypatch.setattr(assets_module, "_replace", fail_after_target_replacement)
    with pytest.raises(AssetError, match="rerun pyganini assets dist"):
        write_assets(plan)

    monkeypatch.setattr(assets_module, "_replace", real_replace)
    write_assets(prepare_assets(paths, "dist"))

    assert not check_assets(paths)
    assert (application / new_css).read_bytes() == b"changed\n"
    assert not old_css.exists()


def test_state_replacement_failure_before_install_is_recoverable(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    paths = select_project_paths(explicit=application, start=application)
    write_assets(prepare_assets(paths, "dist"))
    old_css = next((application / "assets" / "dist").glob("app.*.css"))
    changed = b"changed before state failure\n"
    (application / "assets" / "build" / "app.css").write_bytes(changed)
    plan = prepare_assets(paths, "dist")
    new_relative = next(
        asset.dist for asset in plan.assets if asset.logical == "app.css"
    )
    new_css = application / new_relative
    real_replace = assets_module._replace

    def fail_before_state_install(
        filesystem: Any,
        relative: PurePosixPath,
        staged: Any,
        expected: os.stat_result | None,
        journal: Any,
    ) -> None:
        if relative == PurePosixPath("assets/.pyganini/assets.json"):
            raise OSError("injected pre-state replacement failure")
        real_replace(filesystem, relative, staged, expected, journal)

    monkeypatch.setattr(assets_module, "_replace", fail_before_state_install)
    with pytest.raises(AssetError, match="rerun pyganini assets dist"):
        write_assets(plan)

    assert new_css.read_bytes() == changed
    assert not old_css.exists()

    monkeypatch.setattr(assets_module, "_replace", real_replace)
    new_css.unlink()
    new_css.write_bytes(b"application-owned conflict\n")
    with pytest.raises(AssetError, match="unrecorded file"):
        write_assets(prepare_assets(paths, "dist"))
    assert new_css.read_bytes() == b"application-owned conflict\n"

    new_css.unlink()
    new_css.write_bytes(changed)
    write_assets(prepare_assets(paths, "dist"))
    assert not check_assets(paths)


def test_empty_json_list_is_deterministic(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = _empty_asset_application(make_app, tmp_path / "application")

    assert main(["assets", "list", "--app-root", str(application), "--json"]) == 0
    output = capsys.readouterr()

    assert output.err == ""
    assert output.out == '{\n  "schema": "pyganini.assets.v1",\n  "assets": []\n}\n'


def test_list_stdout_failure_is_localized(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = _asset_application(make_app, tmp_path / "application")

    class FailingWriter:
        def write(self, _text: str) -> int:
            raise OSError("injected stdout failure")

        def flush(self) -> None:
            return None

    monkeypatch.setattr(sys, "stdout", FailingWriter())
    assert main(["assets", "list", "--app-root", str(application)]) == 1
    output = capsys.readouterr()

    assert output.out == ""
    assert "pyganini: PYGANINI022 asset-write" in output.err
    assert "injected stdout failure" in output.err
    assert "Traceback" not in output.err


def test_stale_cleanup_preserves_unrecorded_dist_files(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    paths = select_project_paths(explicit=application, start=application)
    write_assets(prepare_assets(paths, "dist"))
    old = next((application / "assets" / "dist").glob("app.*.css"))
    (application / "assets" / "build" / "app.css").unlink()
    unrecorded = application / "assets" / "dist" / "keep.txt"
    unrecorded.write_text("keep\n", encoding="ascii")

    result = write_assets(prepare_assets(paths, "dist"))
    assert (PurePosixPath("assets/dist") / old.name) in result.removed
    assert not old.exists()
    assert unrecorded.read_text(encoding="ascii") == "keep\n"
    assert not check_assets(paths)


def test_existing_unrecorded_expected_output_fails_closed(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    paths = select_project_paths(explicit=application, start=application)
    content = b"body { color: red; }\n"
    digest = hashlib.sha256(content).hexdigest()[:8]
    destination = application / "assets" / "dist" / f"app.{digest}.css"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"application-owned\n")

    differences = check_assets(paths)
    assert [(item.code, item.path.as_posix()) for item in differences] == [
        ("PYGANINI020", destination.relative_to(application).as_posix())
    ]
    with pytest.raises(AssetError, match="unrecorded file"):
        write_assets(prepare_assets(paths, "dist"))
    assert destination.read_bytes() == b"application-owned\n"
    assert not (application / "assets" / ".pyganini" / "assets.json").exists()


def test_malformed_state_stops_before_stale_cleanup(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    paths = select_project_paths(explicit=application, start=application)
    write_assets(prepare_assets(paths, "dist"))
    old = next((application / "assets" / "dist").glob("app.*.css"))
    (application / "assets" / "build" / "app.css").unlink()
    state = application / "assets" / ".pyganini" / "assets.json"
    state.write_text(
        '{"schema":"pyganini.assets-state.v1","managed":[],"managed":[]}\n',
        encoding="ascii",
    )

    with pytest.raises(AssetError, match="invalid"):
        write_assets(prepare_assets(paths, "dist"))
    assert old.exists()


@pytest.mark.parametrize(
    "state_content",
    [
        "not json\n",
        '{"schema":"pyganini.assets-state.v0","managed":[]}\n',
        '{"managed":[],"schema":"pyganini.assets-state.v1"}\n',
        '{"schema":"pyganini.assets-state.v1","managed":{}}\n',
        '{"schema":"pyganini.assets-state.v1","managed":[{}]}\n',
        (
            '{"schema":"pyganini.assets-state.v1","managed":['
            '{"logical":"../escape.css","dist":"assets/dist/escape.css",'
            '"hash":"00000000"}]}\n'
        ),
        (
            '{"schema":"pyganini.assets-state.v1","managed":['
            '{"logical":"app.css","dist":"/tmp/escape.css",'
            '"hash":"00000000"}]}\n'
        ),
        (
            '{"schema":"pyganini.assets-state.v1","managed":['
            '{"logical":"app.css","dist":"assets/dist/../escape.css",'
            '"hash":"00000000"}]}\n'
        ),
        (
            '{"schema":"pyganini.assets-state.v1","managed":['
            '{"logical":"app.css","dist":"assets/dist/app.css",'
            '"hash":"ABCDEF12"}]}\n'
        ),
        (
            '{"schema":"pyganini.assets-state.v1","managed":['
            '{"logical":"app.css","dist":"assets/dist/app.css",'
            '"hash":"00000000","extra":true}]}\n'
        ),
        (
            '{"schema":"pyganini.assets-state.v1","managed":['
            '{"logical":"app.css","dist":"assets/dist/app.css",'
            '"hash":"00000000"},'
            '{"logical":"app.css","dist":"assets/dist/other.css",'
            '"hash":"00000000"}]}\n'
        ),
        '{"schema":"pyganini.assets-state.v1","managed":[],"managed":[]}\n',
    ],
)
def test_invalid_state_variants_fail_before_cleanup(
    tmp_path: Path, make_app: Callable[..., Path], state_content: str
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    paths = select_project_paths(explicit=application, start=application)
    write_assets(prepare_assets(paths, "dist"))
    old = next((application / "assets" / "dist").glob("app.*.css"))
    (application / "assets" / "build" / "app.css").unlink()
    (application / "assets" / ".pyganini" / "assets.json").write_text(
        state_content, encoding="ascii"
    )

    with pytest.raises(AssetError) as captured:
        write_assets(prepare_assets(paths, "dist"))

    assert captured.value.code == "PYGANINI020"
    assert old.exists()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="requires symlink support")
def test_symlinked_stale_target_stops_before_deletion(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    paths = select_project_paths(explicit=application, start=application)
    write_assets(prepare_assets(paths, "dist"))
    old = next((application / "assets" / "dist").glob("app.*.css"))
    outside = tmp_path / "outside.css"
    outside.write_bytes(b"outside\n")
    old.unlink()
    old.symlink_to(outside)
    (application / "assets" / "build" / "app.css").unlink()

    with pytest.raises(AssetError, match="stale managed asset"):
        write_assets(prepare_assets(paths, "dist"))
    assert outside.read_bytes() == b"outside\n"
    assert old.is_symlink()


def test_clean_requires_state_and_only_removes_owned_stale_files(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    paths = select_project_paths(explicit=application, start=application)
    write_assets(prepare_assets(paths, "dist"))
    old = next((application / "assets" / "dist").glob("app.*.css"))
    (application / "assets" / "build" / "app.css").unlink()
    before = (application / "assets" / "pyganini_assets_gen.py").read_bytes()
    result = clean_assets(prepare_assets(paths, "clean"))
    assert result.removed == (PurePosixPath("assets/dist") / old.name,)
    assert not old.exists()
    assert (application / "assets" / "pyganini_assets_gen.py").read_bytes() == before

    state = application / "assets" / ".pyganini" / "assets.json"
    state.unlink()
    unowned = application / "assets" / "dist" / "unowned.txt"
    unowned.write_text("safe\n", encoding="ascii")
    with pytest.raises(AssetError, match="managed asset state is missing"):
        clean_assets(prepare_assets(paths, "clean"))
    assert unowned.exists()


def test_clean_does_not_recreate_missing_dist(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    paths = select_project_paths(explicit=application, start=application)
    write_assets(prepare_assets(paths, "dist"))
    dist = application / "assets" / "dist"
    for child in dist.iterdir():
        if child.is_dir():
            for nested in child.iterdir():
                nested.unlink()
            child.rmdir()
        else:
            child.unlink()
    dist.rmdir()

    result = clean_assets(prepare_assets(paths, "clean"))
    assert result.written == ()
    assert result.unchanged == (PurePosixPath("assets/.pyganini/assets.json"),)
    assert not dist.exists()


def test_invalid_inputs_fail_before_output_mutation(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    paths = select_project_paths(explicit=application, start=application)
    write_assets(prepare_assets(paths, "dist"))
    before = sorted(
        path.relative_to(application).as_posix()
        for path in application.rglob("*")
        if path.is_file()
    )
    (application / "assets" / "build" / "bad name?").write_bytes(b"bad")
    with pytest.raises(AssetError) as captured:
        prepare_assets(paths, "dist")
    assert captured.value.code == "PYGANINI020"
    after = sorted(
        path.relative_to(application).as_posix()
        for path in application.rglob("*")
        if path.is_file()
    )
    assert set(before).issubset(after)
    assert "assets/build/bad name?" in after


@pytest.mark.parametrize(
    "name",
    ["bad\\name.css", "\u00e9.css", "bad.css ", "bad.css.", "CON.txt", "bad?.css"],
)
def test_invalid_portable_names_fail_before_mutation(
    tmp_path: Path, make_app: Callable[..., Path], name: str
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    paths = select_project_paths(explicit=application, start=application)
    (application / "assets" / "build" / name).write_bytes(b"bad")

    with pytest.raises(AssetError) as captured:
        prepare_assets(paths, "dist")

    assert captured.value.code == "PYGANINI020"
    assert not (application / "assets" / "dist").exists()


def test_read_failure_is_localized_before_asset_mutation(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    paths = select_project_paths(explicit=application, start=application)
    real_read = filesystem_module._PosixAnchoredFilesystem.read_regular

    def fail_source(
        filesystem: Any,
        relative: PurePosixPath,
        *,
        expected: os.stat_result | None = None,
    ) -> bytes:
        if relative == PurePosixPath("app.css"):
            raise PermissionError("injected read failure")
        return real_read(filesystem, relative, expected=expected)

    monkeypatch.setattr(
        filesystem_module._PosixAnchoredFilesystem, "read_regular", fail_source
    )
    with pytest.raises(AssetError) as captured:
        prepare_assets(paths, "list")

    assert captured.value.code == "PYGANINI020"
    assert captured.value.phase == "asset-filesystem"
    assert captured.value.path == "assets/build/app.css"
    assert not (application / "assets" / "dist").exists()


def test_staged_files_are_removed_after_injected_failure(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    paths = select_project_paths(explicit=application, start=application)
    write_assets(prepare_assets(paths, "dist"))
    old_css = next((application / "assets" / "dist").glob("app.*.css"))
    (application / "assets" / "build" / "app.css").write_bytes(b"changed\n")
    state_before = (application / "assets" / ".pyganini" / "assets.json").read_bytes()
    real_stage = assets_module._stage
    calls = 0

    def fail_second_stage(
        filesystem: Any, relative: PurePosixPath, content: bytes
    ) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected staging failure")
        return real_stage(filesystem, relative, content)

    monkeypatch.setattr(assets_module, "_stage", fail_second_stage)
    with pytest.raises(AssetError) as captured:
        write_assets(prepare_assets(paths, "dist"))

    assert captured.value.code == "PYGANINI022"
    assert not any(
        ".pyganini-" in path.name
        for path in (application / "assets").rglob("*")
        if path.is_file()
    )
    assert old_css.exists()
    assert (
        application / "assets" / ".pyganini" / "assets.json"
    ).read_bytes() == state_before


def test_partial_mutation_reports_journal_and_rerun_recovers(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    paths = select_project_paths(explicit=application, start=application)
    write_assets(prepare_assets(paths, "dist"))
    old_css = next((application / "assets" / "dist").glob("app.*.css"))
    (application / "assets" / "build" / "app.css").unlink()
    real_replace = assets_module._replace
    calls = 0

    def fail_first_replace(
        filesystem: Any,
        relative: PurePosixPath,
        staged: Any,
        expected: os.stat_result | None,
        journal: Any,
    ) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            real_replace(filesystem, relative, staged, expected, journal)
            raise OSError("injected post-replacement failure")
        real_replace(filesystem, relative, staged, expected, journal)

    monkeypatch.setattr(assets_module, "_replace", fail_first_replace)
    with pytest.raises(AssetError) as captured:
        write_assets(prepare_assets(paths, "dist"))

    assert captured.value.code == "PYGANINI022"
    assert any(
        detail.startswith("completed mutation:") for detail in captured.value.details
    )
    assert old_css.exists()

    monkeypatch.setattr(assets_module, "_replace", real_replace)
    recovered = write_assets(prepare_assets(paths, "dist"))

    assert (PurePosixPath("assets/dist") / old_css.name) in recovered.removed
    assert not old_css.exists()
    assert not check_assets(paths)


def test_read_rejects_regular_file_replaced_before_open(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    source = application / "assets" / "build" / "app.css"
    expected = source.lstat()
    replacement = source.with_name("replacement.css")
    filesystem = filesystem_module.open_anchored_filesystem(application / "assets")
    real_open: Any = os.open
    swapped = False

    def replace_before_open(
        path: object, flags: int, *arguments: object, **kwargs: object
    ) -> int:
        nonlocal swapped
        if path == "app.css" and not swapped:
            swapped = True
            source.rename(replacement)
            source.write_bytes(b"replacement\n")
        return cast(int, real_open(path, flags, *arguments, **kwargs))

    monkeypatch.setattr(os, "open", replace_before_open)
    try:
        with pytest.raises(AssetError, match="changed while it was being read"):
            assets_module._read_regular(
                filesystem,
                PurePosixPath("assets/build/app.css"),
                expected=expected,
            )
    finally:
        filesystem.close()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="requires POSIX FIFO support")
def test_read_rejects_regular_file_replaced_by_fifo_before_open(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    source = application / "assets" / "build" / "app.css"
    expected = source.lstat()
    replacement = source.with_name("replacement.css")
    filesystem = filesystem_module.open_anchored_filesystem(application / "assets")
    real_open: Any = os.open
    swapped = False

    def replace_with_fifo_before_open(
        path: object, flags: int, *arguments: object, **kwargs: object
    ) -> int:
        nonlocal swapped
        if path == "app.css" and not swapped:
            swapped = True
            source.rename(replacement)
            os.mkfifo(source)
        return cast(int, real_open(path, flags, *arguments, **kwargs))

    monkeypatch.setattr(os, "open", replace_with_fifo_before_open)
    try:
        with pytest.raises(AssetError, match="conflicting type"):
            assets_module._read_regular(
                filesystem,
                PurePosixPath("assets/build/app.css"),
                expected=expected,
            )
    finally:
        filesystem.close()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="requires symlink support")
def test_symlinked_managed_parent_is_rejected_without_following(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    paths = select_project_paths(explicit=application, start=application)
    write_assets(prepare_assets(paths, "dist"))
    dist = application / "assets" / "dist"
    vendor = dist / "vendor"
    outside = tmp_path / "outside"
    vendor.rename(outside)
    vendor.symlink_to(outside, target_is_directory=True)

    with pytest.raises(AssetError, match="managed asset parent"):
        check_assets(paths)


def test_normal_commands_coordinate_enabled_assets(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    root = str(application)
    assert main(["generate", "--app-root", root]) == 0
    generated = capsys.readouterr()
    assert generated.out == (
        "Pyganini generated state: written=4 unchanged=0 removed=0.\n"
        "Pyganini asset state: written=4 unchanged=0 removed=0.\n"
    )
    assert generated.err == ""

    assert main(["check", "--app-root", root]) == 0
    checked = capsys.readouterr()
    assert checked.out == (
        "Pyganini generated state is current.\nPyganini asset state is current.\n"
    )
    assert checked.err == ""


def test_normal_generation_fails_before_route_mutation_for_missing_build(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    assets = application / "assets"
    assets.mkdir()
    (assets / "__init__.py").write_text("", encoding="ascii")
    (assets / "pyganini_assets_gen.py").write_text(
        "# managed indicator\n", encoding="ascii"
    )

    assert main(["generate", "--app-root", str(application)]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "assets/build: PYGANINI020 asset-filesystem" in output.err
    assert not (application / "app" / "_pyganini").exists()


def test_normal_commands_ignore_unenabled_asset_package(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    assets = application / "assets"
    assets.mkdir()
    (assets / "__init__.py").write_text("", encoding="ascii")

    assert main(["generate", "--app-root", str(application)]) == 0
    generated = capsys.readouterr()
    assert (
        generated.out == "Pyganini generated state: written=4 unchanged=0 removed=0.\n"
    )
    assert generated.err == ""
    assert not (assets / "dist").exists()
    assert not (assets / "pyganini_assets_gen.py").exists()


def test_asset_only_commands_do_not_build_route_graph(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = _asset_application(make_app, tmp_path / "application")

    def fail_route_graph(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("asset-only commands must not build a route graph")

    monkeypatch.setattr(cli_module, "build_route_graph", fail_route_graph)
    assert main(["assets", "list", "--app-root", str(application)]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert "app.css" in output.out


@pytest.mark.parametrize(
    "arguments",
    [
        ["assets"],
        ["assets", "list", "--app-ro", "application"],
        ["assets", "list", "unexpected"],
        ["assets", "dist", "--json"],
    ],
)
def test_asset_parser_rejects_usage_errors(
    arguments: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(arguments) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "usage:" in output.err


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="requires POSIX FIFO support")
def test_special_file_input_is_rejected(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    fifo = application / "assets" / "build" / "stream"
    os.mkfifo(fifo)
    paths = select_project_paths(explicit=application, start=application)
    with pytest.raises(AssetError, match="regular files"):
        prepare_assets(paths, "list")


def test_cli_asset_commands_have_expected_outputs(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    arguments = ["assets", "dist", "--app-root", str(application)]
    assert main(arguments) == 0
    first = capsys.readouterr()
    assert first.out == "Pyganini asset state: written=4 unchanged=0 removed=0.\n"
    assert first.err == ""
    assert main(arguments) == 0
    second = capsys.readouterr()
    assert second.out == "Pyganini asset state: written=0 unchanged=4 removed=0.\n"
    assert main(["assets", "check", "--app-root", str(application)]) == 0
    checked = capsys.readouterr()
    assert checked.out == "Pyganini asset state is current.\n"
    assert checked.err == ""


def _run_asset_checker(
    checker: str, application: Path, consumer: Path
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(application), str(ROOT / "src")))
    if checker == "pyright":
        (application / "pyrightconfig.json").write_text(
            '{"typeCheckingMode":"strict","pythonVersion":"3.13",'
            '"include":["assets_consumer.py"]}\n',
            encoding="ascii",
        )
        command = [str(Path(sys.executable).parent / "pyright"), str(consumer)]
    else:
        command = [
            sys.executable,
            "-m",
            "mypy",
            "--strict",
            "--python-version",
            "3.13",
            str(consumer),
        ]
    return subprocess.run(
        command,
        cwd=application,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("checker", ["mypy", "pyright"])
@pytest.mark.parametrize(
    ("fixture", "accepted"),
    [
        ("assets_consumer_valid.py", True),
        ("assets_consumer_invalid.py", False),
    ],
)
def test_generated_asset_consumers_are_checked_by_both_type_checkers(
    tmp_path: Path,
    make_app: Callable[..., Path],
    checker: str,
    fixture: str,
    accepted: bool,
) -> None:
    application = _asset_application(make_app, tmp_path / "application")
    paths = select_project_paths(explicit=application, start=application)
    write_assets(prepare_assets(paths, "dist"))
    consumer = application / "assets_consumer.py"
    consumer.write_text(
        (ASSET_FIXTURES / fixture).read_text(encoding="ascii"), encoding="ascii"
    )

    result = _run_asset_checker(checker, application, consumer)
    assert_checker_result(
        result,
        checker=checker,
        accepted=accepted,
        expected_diagnostics=_ASSET_EXPECTED_DIAGNOSTICS,
    )
