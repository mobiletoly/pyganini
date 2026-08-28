# pyright: reportPrivateUsage=false

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import pyganini._filesystem as filesystem_module
from pyganini._generation import GenerationError, bootstrap_plan, generate
from pyganini._paths import select_project_paths


def _void_pointer(_: int) -> SimpleNamespace:
    return SimpleNamespace(value=-1)


def test_posix_root_descriptor_prevents_redirected_write(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = make_app(tmp_path / "application")
    paths = select_project_paths(explicit=application)
    generate(paths, bootstrap_plan())
    (paths.generated / "__init__.py").write_bytes(b"stale\n")
    held = paths.app / "held-generated"
    outside = tmp_path / "outside"
    outside.mkdir()
    original_entries = filesystem_module._PosixGeneratedFilesystem.entries
    redirected = False

    def redirect_after_scan(self: Any) -> object:
        nonlocal redirected
        result = original_entries(self)
        if not redirected:
            paths.generated.rename(held)
            paths.generated.symlink_to(outside, target_is_directory=True)
            redirected = True
        return result

    monkeypatch.setattr(
        filesystem_module._PosixGeneratedFilesystem, "entries", redirect_after_scan
    )
    generate(paths, bootstrap_plan())
    assert (held / "__init__.py").read_bytes().startswith(b"# Code generated")
    assert not tuple(outside.iterdir())


def test_win32_directory_handle_uses_no_delete_share_and_reparse_flags() -> None:
    calls: list[tuple[Any, ...]] = []

    class Kernel:
        def CreateFileW(self, *args: Any) -> int:
            calls.append(args)
            return 17

        def GetFileAttributesW(self, _: str) -> int:
            return 0

        def CloseHandle(self, _: int) -> None:
            raise AssertionError("valid handle must remain held")

    api = filesystem_module._Win32Api.__new__(filesystem_module._Win32Api)
    api._kernel32 = Kernel()
    api._ctypes = SimpleNamespace(
        get_last_error=lambda: 0,
        WinError=OSError,
        c_void_p=_void_pointer,
    )
    assert api.open_directory(Path("C:/application/app")) == 17
    call = calls[0]
    assert call[2] == (
        filesystem_module._FILE_SHARE_READ | filesystem_module._FILE_SHARE_WRITE
    )
    assert call[5] & filesystem_module._FILE_FLAG_BACKUP_SEMANTICS
    assert call[5] & filesystem_module._FILE_FLAG_OPEN_REPARSE_POINT


def test_win32_directory_handle_rejects_reparse_point_and_closes_handle() -> None:
    closed: list[int] = []

    class Kernel:
        def CreateFileW(self, *_: Any) -> int:
            return 19

        def GetFileAttributesW(self, _: str) -> int:
            return filesystem_module._FILE_ATTRIBUTE_REPARSE_POINT

        def CloseHandle(self, handle: int) -> None:
            closed.append(handle)

    api = filesystem_module._Win32Api.__new__(filesystem_module._Win32Api)
    api._kernel32 = Kernel()
    api._ctypes = SimpleNamespace(
        get_last_error=lambda: 0,
        WinError=OSError,
        c_void_p=_void_pointer,
    )
    with pytest.raises(OSError, match="reparse point"):
        api.open_directory(Path("C:/application/app/_pyganini"))
    assert closed == [19]


def test_mocked_win32_entries_hold_each_directory_before_descending(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    paths = select_project_paths(explicit=application)
    generate(paths, bootstrap_plan())
    nested = paths.generated / "nested"
    nested.mkdir()
    (nested / "inside.txt").write_text("inside\n", encoding="ascii")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "escaped.txt").write_text("outside\n", encoding="ascii")

    class Api:
        def __init__(self) -> None:
            self.held: list[Path] = []

        def open_directory(self, path: Path) -> str:
            self.held.append(path)
            if path == nested:
                nested.rename(tmp_path / "held-nested")
                nested.symlink_to(outside, target_is_directory=True)
                raise OSError("injected reparse-point race")
            return str(path)

        def close(self, _: str) -> None:
            return None

    api = Api()
    filesystem = filesystem_module._WindowsGeneratedFilesystem(paths, cast(Any, api))
    try:
        with pytest.raises(OSError, match="reparse-point race"):
            filesystem.entries()
    finally:
        filesystem.close()
    assert (outside / "escaped.txt").read_text(encoding="ascii") == "outside\n"


def test_post_replacement_close_failure_is_partial_generation(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = make_app(tmp_path / "application")
    paths = select_project_paths(explicit=application)
    generate(paths, bootstrap_plan())
    (paths.generated / "__init__.py").write_bytes(b"stale\n")
    original_close = filesystem_module._PosixGeneratedFilesystem.close

    def fail_close(self: Any) -> None:
        original_close(self)
        raise OSError("injected close failure")

    monkeypatch.setattr(
        filesystem_module._PosixGeneratedFilesystem, "close", fail_close
    )
    with pytest.raises(GenerationError) as captured:
        generate(paths, bootstrap_plan())
    assert captured.value.code == "PYGANINI008"
    assert any(
        "replaced app/_pyganini/__init__.py" in item for item in captured.value.details
    )
    assert any("injected close failure" in item for item in captured.value.details)
