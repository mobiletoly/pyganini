"""Anchored filesystem operations for the private generation lifecycle."""

from __future__ import annotations

import os
import secrets
import stat
from collections.abc import Generator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from pyganini._paths import ProjectPaths

_ROOT_NAME = "_pyganini"
_STAGING_PREFIX = "._pyganini-"
_CURRENT_DIRECTORY = PurePosixPath(".")


class EntryKind(Enum):
    REGULAR = "regular file"
    DIRECTORY = "directory"
    SYMLINK = "symlink or reparse point"
    OTHER = "non-regular filesystem entry"


@dataclass(frozen=True)
class FilesystemEntry:
    relative_path: PurePosixPath
    kind: EntryKind
    info: os.stat_result | None = None


@dataclass(frozen=True)
class StagedFile:
    parent: tuple[str, ...]
    temporary_name: str
    destination_name: str
    physical_path: Path


class FilesystemOperationError(OSError):
    """An operation failed at a generated-root-relative path."""

    def __init__(
        self,
        relative_path: PurePosixPath,
        message: str,
        *,
        mutations: Sequence[PurePosixPath] = (),
    ) -> None:
        super().__init__(message)
        self.relative_path = relative_path
        self.mutations = tuple(mutations)


def _kind(info: os.stat_result) -> EntryKind:
    if getattr(info, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT:
        return EntryKind.SYMLINK
    mode = info.st_mode
    if stat.S_ISREG(mode):
        return EntryKind.REGULAR
    if stat.S_ISDIR(mode):
        return EntryKind.DIRECTORY
    if stat.S_ISLNK(mode):
        return EntryKind.SYMLINK
    return EntryKind.OTHER


def _is_transient(name: str, kind: EntryKind) -> bool:
    if kind is EntryKind.DIRECTORY:
        return name == "__pycache__"
    return name.endswith((".pyc", ".pyo"))


class GeneratedFilesystem(Protocol):
    def close(self) -> None: ...

    def verify_root(self) -> None: ...

    def subdirectory(
        self,
        relative: PurePosixPath,
        *,
        expected: os.stat_result | None = None,
        own_parent: bool = False,
    ) -> AnchoredFilesystem: ...

    def root_kind(self) -> EntryKind | None: ...

    def create_root(self) -> None: ...

    def entries(
        self,
        relative: PurePosixPath = _CURRENT_DIRECTORY,
        *,
        skip_transient: bool = True,
    ) -> tuple[FilesystemEntry, ...]: ...

    def entry_kind(self, relative: PurePosixPath) -> os.stat_result | None: ...

    def read_regular(
        self,
        relative: PurePosixPath,
        *,
        expected: os.stat_result | None = None,
    ) -> bytes: ...

    def ensure_parents(self, relative: PurePosixPath) -> tuple[PurePosixPath, ...]: ...

    def stage(self, relative: PurePosixPath, content: bytes) -> StagedFile: ...

    def replace(self, staged: StagedFile) -> None: ...

    def replace_no_clobber(
        self, staged: StagedFile, *, expected: os.stat_result | None
    ) -> None: ...

    def discard(self, staged: StagedFile) -> None: ...

    def remove(
        self, entry: FilesystemEntry, *, expected: os.stat_result | None = None
    ) -> None: ...


class AnchoredFilesystem(Protocol):
    def close(self) -> None: ...

    def verify_root(self) -> None: ...

    def subdirectory(
        self,
        relative: PurePosixPath,
        *,
        expected: os.stat_result | None = None,
        own_parent: bool = False,
    ) -> AnchoredFilesystem: ...

    def entries(
        self,
        relative: PurePosixPath = _CURRENT_DIRECTORY,
        *,
        skip_transient: bool = True,
    ) -> tuple[FilesystemEntry, ...]: ...

    def entry_kind(self, relative: PurePosixPath) -> os.stat_result | None: ...

    def read_regular(
        self,
        relative: PurePosixPath,
        *,
        expected: os.stat_result | None = None,
    ) -> bytes: ...

    def ensure_parents(self, relative: PurePosixPath) -> tuple[PurePosixPath, ...]: ...

    def stage(self, relative: PurePosixPath, content: bytes) -> StagedFile: ...

    def replace(self, staged: StagedFile) -> None: ...

    def replace_no_clobber(
        self, staged: StagedFile, *, expected: os.stat_result | None
    ) -> None: ...

    def discard(self, staged: StagedFile) -> None: ...

    def remove(
        self, entry: FilesystemEntry, *, expected: os.stat_result | None = None
    ) -> None: ...


class _PosixAnchoredFilesystem:
    def __init__(self, root: Path) -> None:
        self._root_path = root
        self._staged_parents: dict[StagedFile, int] = {}
        self._parent_filesystem: _PosixAnchoredFilesystem | None = None
        self._close_parent = False
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        self._anchor_fd: int | None = os.open(root.parent, flags)
        try:
            self._root_fd: int | None = os.open(
                root.name, flags, dir_fd=self._anchor_fd
            )
        except BaseException:
            os.close(self._anchor_fd)
            self._anchor_fd = None
            raise

    def close(self) -> None:
        failure: OSError | None = None
        for descriptor in self._staged_parents.values():
            try:
                os.close(descriptor)
            except OSError as error:
                if failure is None:
                    failure = error
        self._staged_parents.clear()
        for attribute in ("_root_fd", "_anchor_fd"):
            descriptor = getattr(self, attribute)
            if descriptor is None:
                continue
            try:
                os.close(descriptor)
            except OSError as error:
                if failure is None:
                    failure = error
            finally:
                setattr(self, attribute, None)
        parent_filesystem = self._parent_filesystem
        self._parent_filesystem = None
        if self._close_parent and parent_filesystem is not None:
            try:
                parent_filesystem.close()
            except OSError as error:
                if failure is None:
                    failure = error
        if failure is not None:
            raise failure

    def verify_root(self) -> None:
        if self._parent_filesystem is not None:
            self._parent_filesystem.verify_root()
        if self._anchor_fd is None or self._root_fd is None:
            raise OSError("anchored filesystem is closed")
        try:
            current = os.stat(
                self._root_path.name,
                dir_fd=self._anchor_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError as error:
            raise FilesystemOperationError(
                _CURRENT_DIRECTORY, "anchored directory changed during operation"
            ) from error
        held = os.fstat(self._root_fd)
        if current.st_dev != held.st_dev or current.st_ino != held.st_ino:
            raise FilesystemOperationError(
                _CURRENT_DIRECTORY, "anchored directory changed during operation"
            )

    def subdirectory(
        self,
        relative: PurePosixPath,
        *,
        expected: os.stat_result | None = None,
        own_parent: bool = False,
    ) -> AnchoredFilesystem:
        try:
            with self._parent_fd(relative) as parent:
                anchor = os.dup(parent)
                try:
                    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                    root = os.open(relative.name, flags, dir_fd=anchor)
                except BaseException:
                    os.close(anchor)
                    raise
        except OSError as error:
            raise FilesystemOperationError(relative, str(error)) from error
        try:
            info = os.fstat(root)
            if expected is not None and (
                info.st_dev != expected.st_dev or info.st_ino != expected.st_ino
            ):
                raise FilesystemOperationError(
                    relative, "anchored directory changed during operation"
                )
            child = object.__new__(_PosixAnchoredFilesystem)
            child._root_path = self._root_path.joinpath(*relative.parts)
            child._staged_parents = {}
            child._parent_filesystem = self
            child._close_parent = own_parent
            child._anchor_fd = anchor
            child._root_fd = root
            return child
        except BaseException:
            os.close(root)
            os.close(anchor)
            raise

    def _open_root(self) -> int:
        if self._root_fd is None:
            raise OSError("anchored filesystem is closed")
        return self._root_fd

    @contextmanager
    def _directory_fd(self, relative: PurePosixPath) -> Generator[int]:
        descriptor = os.dup(self._open_root())
        try:
            for part in relative.parts:
                flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                next_descriptor = os.open(part, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = next_descriptor
            yield descriptor
        finally:
            os.close(descriptor)

    @contextmanager
    def _parent_fd(self, relative: PurePosixPath) -> Generator[int]:
        with self._directory_fd(relative.parent) as parent:
            yield parent

    def entries(
        self,
        relative: PurePosixPath = _CURRENT_DIRECTORY,
        *,
        skip_transient: bool = True,
    ) -> tuple[FilesystemEntry, ...]:
        found: list[FilesystemEntry] = []

        def visit(descriptor: int, parent: PurePosixPath) -> None:
            for name in sorted(os.listdir(descriptor)):
                info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                kind = _kind(info)
                if skip_transient and _is_transient(name, kind):
                    continue
                relative = parent / name
                found.append(FilesystemEntry(relative, kind, info))
                if kind is EntryKind.DIRECTORY:
                    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                    child = os.open(name, flags, dir_fd=descriptor)
                    try:
                        visit(child, relative)
                    finally:
                        os.close(child)

        with self._directory_fd(relative) as root:
            visit(root, PurePosixPath())
        return tuple(sorted(found, key=lambda item: item.relative_path.as_posix()))

    def entry_kind(self, relative: PurePosixPath) -> os.stat_result | None:
        try:
            with self._parent_fd(relative) as parent:
                return os.stat(
                    relative.name,
                    dir_fd=parent,
                    follow_symlinks=False,
                )
        except FileNotFoundError:
            return None

    def read_regular(
        self,
        relative: PurePosixPath,
        *,
        expected: os.stat_result | None = None,
    ) -> bytes:
        try:
            with self._parent_fd(relative) as parent:
                flags = os.O_RDONLY | os.O_NOFOLLOW
                if hasattr(os, "O_NONBLOCK"):
                    flags |= os.O_NONBLOCK
                descriptor = os.open(relative.name, flags, dir_fd=parent)
                try:
                    info = os.fstat(descriptor)
                    if _kind(info) is not EntryKind.REGULAR:
                        raise FilesystemOperationError(
                            relative, "expected generated file has a conflicting type"
                        )
                    if expected is not None and (
                        info.st_dev != expected.st_dev or info.st_ino != expected.st_ino
                    ):
                        raise FilesystemOperationError(
                            relative, "file changed while it was being read"
                        )
                    with os.fdopen(descriptor, "rb", closefd=False) as source:
                        return source.read()
                finally:
                    os.close(descriptor)
        except FilesystemOperationError:
            raise
        except OSError as error:
            raise FilesystemOperationError(relative, str(error)) from error

    def ensure_parents(self, relative: PurePosixPath) -> tuple[PurePosixPath, ...]:
        created: list[PurePosixPath] = []
        descriptor = os.dup(self._open_root())
        current = PurePosixPath()
        try:
            for part in relative.parts[:-1]:
                current /= part
                try:
                    os.mkdir(part, dir_fd=descriptor)
                except FileExistsError:
                    pass
                else:
                    created.append(current)
                    os.fsync(descriptor)
                flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                next_descriptor = os.open(part, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = next_descriptor
        except FilesystemOperationError:
            raise
        except OSError as error:
            raise FilesystemOperationError(
                relative, str(error), mutations=tuple(created)
            ) from error
        finally:
            os.close(descriptor)
        return tuple(created)

    def stage(self, relative: PurePosixPath, content: bytes) -> StagedFile:
        temporary_name = f"{_STAGING_PREFIX}{secrets.token_hex(12)}"
        with self._parent_fd(relative) as parent:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
            descriptor = os.open(temporary_name, flags, 0o600, dir_fd=parent)
            primary: BaseException | None = None
            close_error: BaseException | None = None
            try:
                with os.fdopen(descriptor, "wb", closefd=False) as target:
                    target.write(content)
                    target.flush()
                    os.fsync(descriptor)
            except BaseException as error:
                primary = error
            try:
                os.close(descriptor)
            except BaseException as error:
                close_error = error
                if primary is None:
                    primary = error
            if primary is not None:
                cleanup_error: OSError | None = None
                try:
                    os.unlink(temporary_name, dir_fd=parent)
                except OSError as error:
                    cleanup_error = error
                if not isinstance(primary, Exception):
                    raise primary
                message = f"could not stage generated file: {primary}"
                if close_error is not None and close_error is not primary:
                    message += f"; could not close staging file: {close_error}"
                if cleanup_error is not None:
                    message += (
                        f"; could not remove staging file {temporary_name}: "
                        f"{cleanup_error}"
                    )
                raise FilesystemOperationError(relative, message) from primary
            staged = StagedFile(
                relative.parts[:-1],
                temporary_name,
                relative.name,
                self._root_path.joinpath(*relative.parts[:-1], temporary_name),
            )
            try:
                self._staged_parents[staged] = os.dup(parent)
            except OSError as error:
                with suppress(OSError):
                    os.unlink(temporary_name, dir_fd=parent)
                raise FilesystemOperationError(
                    relative, f"could not retain staging parent: {error}"
                ) from error
        return staged

    def _staged_parent(self, staged: StagedFile) -> int:
        parent = self._staged_parents.get(staged)
        if parent is None:
            raise OSError("staging file is no longer active")
        relative = PurePosixPath(*staged.parent, staged.destination_name)
        try:
            with self._parent_fd(relative) as current:
                current_info = os.fstat(current)
        except OSError as error:
            raise FilesystemOperationError(
                relative, "staged parent changed during operation"
            ) from error
        held_info = os.fstat(parent)
        if (
            current_info.st_dev != held_info.st_dev
            or current_info.st_ino != held_info.st_ino
        ):
            raise FilesystemOperationError(
                relative, "staged parent changed during operation"
            )
        return parent

    def _release_staged_parent(self, staged: StagedFile) -> None:
        descriptor = self._staged_parents.pop(staged, None)
        if descriptor is not None:
            os.close(descriptor)

    def replace(self, staged: StagedFile) -> None:
        parent = self._staged_parent(staged)
        try:
            os.replace(
                staged.temporary_name,
                staged.destination_name,
                src_dir_fd=parent,
                dst_dir_fd=parent,
            )
        except OSError:
            raise
        else:
            self._release_staged_parent(staged)

    def replace_no_clobber(
        self, staged: StagedFile, *, expected: os.stat_result | None
    ) -> None:
        relative = PurePosixPath(*staged.parent, staged.destination_name)
        parent = self._staged_parent(staged)
        installed = False
        try:
            try:
                current = os.stat(
                    staged.destination_name,
                    dir_fd=parent,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                current = None
            if expected is None:
                if current is not None:
                    raise FileExistsError(staged.destination_name)
                os.link(
                    staged.temporary_name,
                    staged.destination_name,
                    src_dir_fd=parent,
                    dst_dir_fd=parent,
                    follow_symlinks=False,
                )
                installed = True
                os.unlink(staged.temporary_name, dir_fd=parent)
            else:
                if current is None or (
                    current.st_dev != expected.st_dev
                    or current.st_ino != expected.st_ino
                ):
                    raise FileExistsError(staged.destination_name)
                os.replace(
                    staged.temporary_name,
                    staged.destination_name,
                    src_dir_fd=parent,
                    dst_dir_fd=parent,
                )
                installed = True
            os.fsync(parent)
        except OSError as error:
            if installed:
                raise FilesystemOperationError(
                    relative,
                    str(error),
                    mutations=(relative,),
                ) from error
            raise
        else:
            self._release_staged_parent(staged)

    def discard(self, staged: StagedFile) -> None:
        parent = self._staged_parents.get(staged)
        if parent is None:
            return
        try:
            with suppress(FileNotFoundError):
                os.unlink(staged.temporary_name, dir_fd=parent)
        finally:
            self._release_staged_parent(staged)

    def remove(
        self, entry: FilesystemEntry, *, expected: os.stat_result | None = None
    ) -> None:
        with self._parent_fd(entry.relative_path) as parent:
            current_info = os.stat(
                entry.relative_path.name,
                dir_fd=parent,
                follow_symlinks=False,
            )
            if expected is not None and (
                current_info.st_dev != expected.st_dev
                or current_info.st_ino != expected.st_ino
            ):
                raise FileNotFoundError(entry.relative_path.name)
            current = _kind(current_info)
            if current is EntryKind.DIRECTORY:
                os.rmdir(entry.relative_path.name, dir_fd=parent)
            else:
                os.unlink(entry.relative_path.name, dir_fd=parent)
            os.fsync(parent)


class _PosixGeneratedFilesystem(_PosixAnchoredFilesystem):
    def __init__(self, paths: ProjectPaths) -> None:
        self._paths = paths
        self._root_path = paths.generated
        self._staged_parents: dict[StagedFile, int] = {}
        self._parent_filesystem: _PosixAnchoredFilesystem | None = None
        self._close_parent = False
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        self._app_fd = os.open(paths.app, flags)
        self._root_fd: int | None = None
        self._root_name = paths.generated.name

    def close(self) -> None:
        failure: OSError | None = None
        for descriptor in self._staged_parents.values():
            try:
                os.close(descriptor)
            except OSError as error:
                if failure is None:
                    failure = error
        self._staged_parents.clear()
        if self._root_fd is not None:
            try:
                os.close(self._root_fd)
            except OSError as error:
                failure = error
            self._root_fd = None
        try:
            os.close(self._app_fd)
        except OSError as error:
            if failure is None:
                failure = error
        if failure is not None:
            raise failure

    def verify_root(self) -> None:
        if self._root_fd is None:
            raise OSError("generated filesystem root is not open")
        try:
            current = os.stat(
                self._root_name,
                dir_fd=self._app_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError as error:
            raise FilesystemOperationError(
                _CURRENT_DIRECTORY, "generated directory changed during operation"
            ) from error
        held = os.fstat(self._root_fd)
        if current.st_dev != held.st_dev or current.st_ino != held.st_ino:
            raise FilesystemOperationError(
                _CURRENT_DIRECTORY, "generated directory changed during operation"
            )

    def root_kind(self) -> EntryKind | None:
        try:
            info = os.stat(self._root_name, dir_fd=self._app_fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        return _kind(info)

    def create_root(self) -> None:
        os.mkdir(self._root_name, dir_fd=self._app_fd)
        try:
            self._open_root()
        except OSError as error:
            raise FilesystemOperationError(
                PurePosixPath("."), str(error), mutations=(PurePosixPath("."),)
            ) from error

    def _open_root(self) -> int:
        if self._root_fd is None:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            self._root_fd = os.open(self._root_name, flags, dir_fd=self._app_fd)
        return self._root_fd


_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_GENERIC_READ = 0x80000000
_OPEN_EXISTING = 3
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400


class _Win32Api:
    """Small injectable wrapper for the directory-handle containment contract."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        ctypes_module: Any = ctypes
        self._ctypes = ctypes_module
        win_dll = ctypes_module.WinDLL
        self._kernel32 = win_dll("kernel32", use_last_error=True)
        self._kernel32.CreateFileW.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        self._kernel32.CreateFileW.restype = wintypes.HANDLE
        self._kernel32.GetFileAttributesW.argtypes = (wintypes.LPCWSTR,)
        self._kernel32.GetFileAttributesW.restype = wintypes.DWORD
        self._kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self._kernel32.CloseHandle.restype = wintypes.BOOL

    def _invalid(self, handle: Any) -> bool:
        return handle in (-1, self._ctypes.c_void_p(-1).value)

    def open_directory(self, path: Path) -> Any:
        handle = self._kernel32.CreateFileW(
            str(path),
            0,
            _FILE_SHARE_READ | _FILE_SHARE_WRITE,
            None,
            _OPEN_EXISTING,
            _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
            None,
        )
        if self._invalid(handle):
            raise self._ctypes.WinError(self._ctypes.get_last_error())
        attributes = self._kernel32.GetFileAttributesW(str(path))
        if attributes == 0xFFFFFFFF or attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
            self._kernel32.CloseHandle(handle)
            raise OSError("generated path is a reparse point")
        return handle

    def read_regular(self, path: Path) -> bytes:
        import msvcrt

        msvcrt_module: Any = msvcrt
        handle = self._kernel32.CreateFileW(
            str(path),
            _GENERIC_READ,
            _FILE_SHARE_READ | _FILE_SHARE_WRITE,
            None,
            _OPEN_EXISTING,
            _FILE_FLAG_OPEN_REPARSE_POINT,
            None,
        )
        if self._invalid(handle):
            raise self._ctypes.WinError(self._ctypes.get_last_error())
        attributes = self._kernel32.GetFileAttributesW(str(path))
        if attributes == 0xFFFFFFFF or attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
            self._kernel32.CloseHandle(handle)
            raise OSError("generated file is a reparse point")
        descriptor = msvcrt_module.open_osfhandle(int(handle), os.O_RDONLY)
        try:
            if _kind(os.fstat(descriptor)) is not EntryKind.REGULAR:
                raise OSError("expected generated file has a conflicting type")
            with os.fdopen(descriptor, "rb", closefd=False) as source:
                return source.read()
        finally:
            os.close(descriptor)

    def close(self, handle: Any) -> None:
        self._kernel32.CloseHandle(handle)


class _WindowsAnchoredFilesystem:
    """Path operations protected by non-delete-shared directory handles."""

    def __init__(self, root: Path, api: _Win32Api | None = None) -> None:
        self._root_path = root
        self._api = api or _Win32Api()
        self._handles: dict[Path, Any] = {}
        self._parent_filesystem: _WindowsAnchoredFilesystem | None = None
        self._close_parent = False
        self._hold(root)
        self._root_info: os.stat_result | None = root.lstat()

    def _hold(self, directory: Path) -> None:
        if directory not in self._handles:
            self._handles[directory] = self._api.open_directory(directory)

    def _hold_parents(self, relative: PurePosixPath) -> None:
        current = self._root_path
        self._hold(current)
        for part in relative.parts[:-1]:
            current /= part
            self._hold(current)

    def close(self) -> None:
        failure: OSError | None = None
        for handle in reversed(tuple(self._handles.values())):
            try:
                self._api.close(handle)
            except OSError as error:
                if failure is None:
                    failure = error
        self._handles.clear()
        parent_filesystem = self._parent_filesystem
        self._parent_filesystem = None
        if self._close_parent and parent_filesystem is not None:
            try:
                parent_filesystem.close()
            except OSError as error:
                if failure is None:
                    failure = error
        if failure is not None:
            raise failure

    def verify_root(self) -> None:
        if self._parent_filesystem is not None:
            self._parent_filesystem.verify_root()
        expected = self._root_info
        if expected is None:
            raise OSError("anchored filesystem root is not open")
        try:
            current = self._root_path.lstat()
        except FileNotFoundError as error:
            raise FilesystemOperationError(
                _CURRENT_DIRECTORY, "anchored directory changed during operation"
            ) from error
        if current.st_dev != expected.st_dev or current.st_ino != expected.st_ino:
            raise FilesystemOperationError(
                _CURRENT_DIRECTORY, "anchored directory changed during operation"
            )

    def subdirectory(
        self,
        relative: PurePosixPath,
        *,
        expected: os.stat_result | None = None,
        own_parent: bool = False,
    ) -> AnchoredFilesystem:
        physical = self._root_path.joinpath(*relative.parts)
        self._hold(physical)
        info = physical.lstat()
        if expected is not None and (
            info.st_dev != expected.st_dev or info.st_ino != expected.st_ino
        ):
            raise FilesystemOperationError(
                relative, "anchored directory changed during operation"
            )
        child = _WindowsAnchoredFilesystem(physical, self._api)
        child._parent_filesystem = self
        child._close_parent = own_parent
        return child

    def entries(
        self,
        relative: PurePosixPath = _CURRENT_DIRECTORY,
        *,
        skip_transient: bool = True,
    ) -> tuple[FilesystemEntry, ...]:
        base = self._root_path.joinpath(*relative.parts)
        self._hold(base)
        found: list[FilesystemEntry] = []

        def visit(base: Path, parent: PurePosixPath) -> None:
            self._hold(base)
            with os.scandir(base) as scan:
                children = sorted(scan, key=lambda entry: entry.name)
                for child in children:
                    name = child.name
                    physical = base / name
                    info = physical.lstat()
                    kind = _kind(info)
                    if skip_transient and _is_transient(name, kind):
                        continue
                    relative = parent / name
                    found.append(FilesystemEntry(relative, kind, info))
                    if kind is EntryKind.DIRECTORY:
                        self._hold(physical)
                        visit(physical, relative)

        visit(base, PurePosixPath())
        return tuple(sorted(found, key=lambda item: item.relative_path.as_posix()))

    def entry_kind(self, relative: PurePosixPath) -> os.stat_result | None:
        self._hold_parents(relative)
        physical = self._root_path.joinpath(*relative.parts)
        try:
            return physical.lstat()
        except FileNotFoundError:
            return None

    def read_regular(
        self,
        relative: PurePosixPath,
        *,
        expected: os.stat_result | None = None,
    ) -> bytes:
        self._hold_parents(relative)
        physical = self._root_path.joinpath(*relative.parts)
        info = physical.lstat()
        if _kind(info) is not EntryKind.REGULAR:
            raise FilesystemOperationError(
                relative, "expected generated file has a conflicting type"
            )
        if expected is not None and (
            info.st_dev != expected.st_dev or info.st_ino != expected.st_ino
        ):
            raise FilesystemOperationError(
                relative, "file changed while it was being read"
            )
        return self._api.read_regular(physical)

    def ensure_parents(self, relative: PurePosixPath) -> tuple[PurePosixPath, ...]:
        created: list[PurePosixPath] = []
        current = self._root_path
        logical = PurePosixPath()
        self._hold(current)
        try:
            for part in relative.parts[:-1]:
                current /= part
                logical /= part
                try:
                    current.mkdir()
                except FileExistsError:
                    pass
                else:
                    created.append(logical)
                self._hold(current)
        except OSError as error:
            raise FilesystemOperationError(
                relative, str(error), mutations=tuple(created)
            ) from error
        return tuple(created)

    def stage(self, relative: PurePosixPath, content: bytes) -> StagedFile:
        self._hold_parents(relative)
        temporary_name = f"{_STAGING_PREFIX}{secrets.token_hex(12)}"
        parent = self._root_path.joinpath(*relative.parts[:-1])
        physical = parent / temporary_name
        descriptor = os.open(physical, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        primary: BaseException | None = None
        close_error: BaseException | None = None
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as target:
                target.write(content)
                target.flush()
                os.fsync(descriptor)
        except BaseException as error:
            primary = error
        try:
            os.close(descriptor)
        except BaseException as error:
            close_error = error
            if primary is None:
                primary = error
        if primary is not None:
            cleanup_error: OSError | None = None
            try:
                physical.unlink()
            except OSError as error:
                cleanup_error = error
            if not isinstance(primary, Exception):
                raise primary
            message = f"could not stage generated file: {primary}"
            if close_error is not None and close_error is not primary:
                message += f"; could not close staging file: {close_error}"
            if cleanup_error is not None:
                message += (
                    f"; could not remove staging file {temporary_name}: {cleanup_error}"
                )
            raise FilesystemOperationError(relative, message) from primary
        return StagedFile(relative.parts[:-1], temporary_name, relative.name, physical)

    def replace(self, staged: StagedFile) -> None:
        self._hold_parents(PurePosixPath(*staged.parent, staged.destination_name))
        destination = staged.physical_path.with_name(staged.destination_name)
        os.replace(staged.physical_path, destination)

    def replace_no_clobber(
        self, staged: StagedFile, *, expected: os.stat_result | None
    ) -> None:
        self._hold_parents(PurePosixPath(*staged.parent, staged.destination_name))
        destination = staged.physical_path.with_name(staged.destination_name)
        try:
            current = destination.lstat()
        except FileNotFoundError:
            current = None
        if expected is None:
            if current is not None:
                raise FileExistsError(destination)
            os.link(staged.physical_path, destination)
            staged.physical_path.unlink()
            return
        if current is None or (
            current.st_dev != expected.st_dev or current.st_ino != expected.st_ino
        ):
            raise FileExistsError(destination)
        os.replace(staged.physical_path, destination)

    def discard(self, staged: StagedFile) -> None:
        self._hold_parents(PurePosixPath(*staged.parent, staged.destination_name))
        staged.physical_path.unlink(missing_ok=True)

    def remove(
        self, entry: FilesystemEntry, *, expected: os.stat_result | None = None
    ) -> None:
        self._hold_parents(entry.relative_path)
        physical = self._root_path.joinpath(*entry.relative_path.parts)
        current_info = physical.lstat()
        if expected is not None and (
            current_info.st_dev != expected.st_dev
            or current_info.st_ino != expected.st_ino
        ):
            raise FileNotFoundError(entry.relative_path)
        current = _kind(current_info)
        if current is EntryKind.DIRECTORY:
            physical.rmdir()
        else:
            physical.unlink()


class _WindowsGeneratedFilesystem(_WindowsAnchoredFilesystem):
    def __init__(self, paths: ProjectPaths, api: _Win32Api | None = None) -> None:
        self._paths = paths
        self._root_path = paths.generated
        self._api = api or _Win32Api()
        self._handles: dict[Path, Any] = {}
        self._parent_filesystem: _WindowsAnchoredFilesystem | None = None
        self._close_parent = False
        self._root_info: os.stat_result | None = None
        self._hold(paths.app)

    def root_kind(self) -> EntryKind | None:
        try:
            info = self._paths.generated.lstat()
        except FileNotFoundError:
            return None
        if _kind(info) is EntryKind.DIRECTORY:
            self._hold(self._paths.generated)
            if self._root_info is None:
                self._root_info = info
        return _kind(info)

    def create_root(self) -> None:
        self._paths.generated.mkdir()
        try:
            self._hold(self._paths.generated)
            self._root_info = self._paths.generated.lstat()
        except OSError as error:
            raise FilesystemOperationError(
                PurePosixPath("."), str(error), mutations=(PurePosixPath("."),)
            ) from error


def open_anchored_filesystem(root: Path) -> AnchoredFilesystem:
    """Open an existing directory as a no-follow, rooted filesystem."""
    if os.name == "nt":
        return _WindowsAnchoredFilesystem(root)
    return _PosixAnchoredFilesystem(root)


def open_generated_filesystem(paths: ProjectPaths) -> GeneratedFilesystem:
    """Open the application package as the anchor for generated operations."""
    if os.name == "nt":
        return _WindowsGeneratedFilesystem(paths)
    return _PosixGeneratedFilesystem(paths)
