"""Application-owned development supervisor shared by two examples."""

from __future__ import annotations

import argparse
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Generator, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import FrameType

from watchfiles import Change, watch


class _ShutdownRequested(Exception):
    pass


class _CleanupError(RuntimeError):
    pass


class _RevisionError(RuntimeError):
    pass


@dataclass(frozen=True)
class _Config:
    root: Path
    watch_root: Path
    asset_build_root: Path
    generated_root: Path
    asset_output_root: Path
    server_command: tuple[str, ...]
    host: str
    port: int
    reload_roots: tuple[Path, ...] = ()
    reload_directories: tuple[Path, ...] = ()
    revision_file: Path | None = None
    sigint_timeout: float = 5.0
    sigterm_timeout: float = 2.0
    sigkill_timeout: float = 1.0


@dataclass(frozen=True)
class _Server:
    process: subprocess.Popen[bytes]
    process_group: int


def _status(message: str) -> None:
    print(f"[example-dev] {message}", flush=True)


def _host_argument(value: str) -> str:
    if not value:
        raise argparse.ArgumentTypeError("host must not be empty")
    return value


def _port_argument(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("port must be an integer") from error
    if not 1 <= port <= 65_535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python dev.py",
        description=(
            "Watch application Python, refresh Pyganini-generated state, and "
            "restart Uvicorn or refresh content and Jinja pages."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        type=_host_argument,
        help="Uvicorn bind host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        default=8000,
        type=_port_argument,
        help="Uvicorn bind port (default: 8000)",
    )
    parser.add_argument(
        "--reload-path",
        action="append",
        default=[],
        help="External refresh-only file or directory (repeatable)",
    )
    return parser


def _supported_platform(platform: str | None = None) -> bool:
    selected = sys.platform if platform is None else platform
    return selected == "darwin" or selected.startswith("linux")


def _ordinary(path: Path) -> bool:
    info = path.lstat()
    return (
        not stat.S_ISLNK(info.st_mode)
        and not getattr(info, "st_file_attributes", 0) & 0x400
        and (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode))
    )


def _reload_paths(root: Path, values: Sequence[str]) -> tuple[Path, ...]:
    paths: list[Path] = []
    forbidden = (
        root / "app",
        root / "assets/build",
        root / "assets/dist",
        root / "assets/.pyganini",
        root / "assets/pyganini_assets_gen.py",
    )
    for value in ("content", *values):
        candidate = Path(os.path.abspath(root / value))
        for part in (candidate, *candidate.parents):
            if not _ordinary(part):
                raise ValueError(
                    f"reload path must be an ordinary file/directory: {part}"
                )
        if candidate in paths:
            continue
        if any(
            candidate.is_relative_to(other) or other.is_relative_to(candidate)
            for other in (*paths, *forbidden)
        ):
            raise ValueError(
                "reload paths must be disjoint from each other and app/assets: "
                f"{candidate}"
            )
        if candidate.is_dir():
            for child in candidate.rglob("*"):
                if not _ordinary(child):
                    raise ValueError(
                        f"reload tree contains a link or special file: {child}"
                    )
        paths.append(candidate)
    return tuple(paths)


def _config(
    root: Path, factory: str, host: str, port: int, reload_paths: Sequence[str] = ()
) -> _Config:
    root = root.resolve()
    roots = _reload_paths(root, reload_paths)
    return _Config(
        root=root,
        watch_root=root / "app",
        asset_build_root=root / "assets/build",
        generated_root=root / "app/_pyganini",
        asset_output_root=root / "assets/dist",
        reload_roots=roots,
        reload_directories=tuple(path for path in roots if path.is_dir()),
        server_command=(
            sys.executable,
            "-m",
            "uvicorn",
            factory,
            "--factory",
            "--host",
            host,
            "--port",
            str(port),
        ),
        host=host,
        port=port,
    )


def _publish(path: Path, session: str, revision: int) -> None:
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_text(f"{session}:{revision}", encoding="ascii")
        temporary.replace(path)
    except OSError as error:
        raise _RevisionError(f"revision publication failed: {error}") from error


def _pyganini_command(config: _Config, command: str) -> tuple[str, ...]:
    return (
        sys.executable,
        "-m",
        "pyganini",
        command,
        "--app-root",
        str(config.root),
    )


def _run_command(command: Sequence[str], *, cwd: Path) -> int | None:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            shell=False,
        )
    except OSError as error:
        _status(f"command start failed: {error}")
        return None
    return result.returncode


def _prepare(config: _Config, *, server_alive: bool, initial: bool = False) -> bool:
    state = "server retained" if server_alive else "server stopped"
    prefix = "initial preparation" if initial else "preparing generated state"
    _status(f"{prefix}: {state}")

    generation = _run_command(_pyganini_command(config, "generate"), cwd=config.root)
    if generation is None or generation != 0:
        exit_text = (
            "process start failed" if generation is None else f"exit {generation}"
        )
        _status(f"generation failed ({exit_text}); {state}")
        return False

    checking = _run_command(_pyganini_command(config, "check"), cwd=config.root)
    if checking is None or checking != 0:
        exit_text = "process start failed" if checking is None else f"exit {checking}"
        _status(f"check failed ({exit_text}); {state}")
        return False

    _status("preparation succeeded")
    return True


def _watch_path(config: _Config, path: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = config.root / candidate
    return Path(os.path.abspath(candidate))


def _known_directories(root: Path) -> set[Path]:
    directories = {root}
    directories.update(path.resolve() for path in root.rglob("*") if path.is_dir())
    return directories


def _watch_root(config: _Config, candidate: Path) -> Path | None:
    for root in (config.watch_root, config.asset_build_root):
        if candidate.is_relative_to(root):
            return root
    for root in config.reload_roots:
        if candidate == root or (
            root in config.reload_directories and candidate.is_relative_to(root)
        ):
            return root
    return None


def _accepted_path(config: _Config, path: str) -> Path | None:
    candidate = _watch_path(config, path)
    root = _watch_root(config, candidate)
    if (
        root is None
        or candidate.is_relative_to(config.generated_root)
        or candidate.is_relative_to(config.root / "assets/.pyganini")
        or candidate == config.root / "assets/pyganini_assets_gen.py"
    ):
        return None
    if any(
        part == "__pycache__" or part.startswith(".#") or part.endswith("~")
        for part in candidate.parts
    ) or candidate.suffix in {".pyc", ".pyo"}:
        return None
    if candidate == config.revision_file or candidate.is_dir():
        return None
    if root == config.watch_root and candidate.suffix not in {".py", ".jinja"}:
        return None
    return candidate


def _restart_path(config: _Config, path: Path) -> bool:
    return path.is_relative_to(config.asset_build_root) or (
        path.is_relative_to(config.watch_root) and path.suffix == ".py"
    )


def _watch_filter(
    config: _Config,
    change: Change,
    path: str,
    *,
    known_directories: dict[Path, set[Path]] | None = None,
) -> bool:
    candidate = _watch_path(config, path)
    root = _watch_root(config, candidate)
    if root is None:
        return False
    if root == config.watch_root and candidate.is_relative_to(config.generated_root):
        return False
    if candidate.is_dir():
        if known_directories is not None:
            known_directories.setdefault(root, set()).add(candidate)
        return False
    if (
        change is Change.deleted
        and known_directories is not None
        and candidate in known_directories.setdefault(root, set())
    ):
        known_directories[root].remove(candidate)
        return False
    return _accepted_path(config, path) is not None


def _accepted_paths(
    config: _Config, changes: set[tuple[Change, str]]
) -> tuple[Path, ...]:
    accepted = {
        candidate
        for _, path in changes
        if (candidate := _accepted_path(config, path)) is not None
    }
    return tuple(
        sorted(
            accepted,
            key=lambda path: path.as_posix(),
        )
    )


def _watch(config: _Config) -> Generator[set[tuple[Change, str]]]:
    known_directories = {
        config.watch_root: _known_directories(config.watch_root),
        config.asset_build_root: _known_directories(config.asset_build_root),
    }
    backend_roots = tuple(
        dict.fromkeys(
            (
                config.watch_root,
                config.asset_build_root,
                *(
                    path if path in config.reload_directories else path.parent
                    for path in config.reload_roots
                ),
            )
        )
    )
    known_directories.update(
        {root: _known_directories(root) for root in config.reload_directories}
    )
    return watch(
        *backend_roots,
        watch_filter=lambda change, path: _watch_filter(
            config,
            change,
            path,
            known_directories=known_directories,
        ),
        debounce=200,
        step=50,
        rust_timeout=250,
        yield_on_timeout=True,
        recursive=True,
        raise_interrupt=True,
        ignore_permission_denied=False,
        force_polling=None,
    )


def _start_server(config: _Config) -> _Server | None:
    try:
        child = subprocess.Popen(
            config.server_command,
            cwd=config.root,
            shell=False,
            start_new_session=True,
            env={
                **os.environ,
                **(
                    {"PYGANINI_EXAMPLE_RELOAD_FILE": str(config.revision_file)}
                    if config.revision_file is not None
                    else {}
                ),
            },
        )
    except OSError as error:
        _status(f"server start failed: {error}; watching without a server")
        return None
    _status(f"server started: http://{config.host}:{config.port}")
    # A new session starts with the child as its process-group leader.
    return _Server(process=child, process_group=child.pid)


def _send_group_signal(process_group: int, signum: signal.Signals) -> bool:
    try:
        os.killpg(process_group, signum)
    except ProcessLookupError:
        return True
    except OSError as error:
        _status(f"fatal cleanup: could not send {signum.name}: {error}")
        return False
    return True


def _wait_for_group_exit(process_group: int, deadline: float) -> bool:
    while True:
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            return True
        except OSError as error:
            _status(f"fatal cleanup: could not inspect process group: {error}")
            return False

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.01, remaining))


def _wait_for_exit(
    child: subprocess.Popen[bytes],
    timeout: float,
    process_group: int | None = None,
) -> bool:
    deadline = time.monotonic() + timeout
    try:
        child.wait(timeout=max(0.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        return False
    except OSError as error:
        _status(f"fatal cleanup: could not reap child: {error}")
        return False
    return process_group is None or _wait_for_group_exit(process_group, deadline)


def _stop_server(server: _Server, config: _Config) -> bool:
    if not _send_group_signal(server.process_group, signal.SIGINT):
        return False
    if _wait_for_exit(server.process, config.sigint_timeout, server.process_group):
        return True

    _status("signal escalation: SIGINT timed out; sending SIGTERM")
    if not _send_group_signal(server.process_group, signal.SIGTERM):
        return False
    if _wait_for_exit(server.process, config.sigterm_timeout, server.process_group):
        return True

    _status("signal escalation: SIGTERM timed out; sending SIGKILL")
    if not _send_group_signal(server.process_group, signal.SIGKILL):
        return False
    if _wait_for_exit(server.process, config.sigkill_timeout, server.process_group):
        return True

    _status("fatal cleanup: child did not exit after SIGKILL")
    return False


def _poll_server(server: _Server, config: _Config) -> int | None:
    if server.process.poll() is None:
        return None
    try:
        exit_code = server.process.wait()
    except OSError as error:
        raise _CleanupError(f"could not reap exited child: {error}") from error
    _status(f"unexpected child exit: status {exit_code}; waiting for Python edit")
    if not _stop_server(server, config):
        raise _CleanupError("could not clean up the unexpectedly exited process group")
    return exit_code


def _handle_sigterm(_signum: int, _frame: FrameType | None) -> None:
    raise _ShutdownRequested


def _run_loop(config: _Config) -> int:
    try:
        with tempfile.TemporaryDirectory(
            prefix="pyganini-example-reload-"
        ) as temporary:
            path = Path(temporary) / "revision"
            session = str(uuid.uuid4())
            _publish(path, session, 0)
            return _supervise(replace(config, revision_file=path), session)
    except (OSError, _RevisionError) as error:
        _status(f"fatal revision state or cleanup error: {error}")
        return 1


def _supervise(config: _Config, session: str) -> int:
    revision = 0
    _status(f"application root: {config.root}")
    _status(f"server URL: http://{config.host}:{config.port}")
    _status(
        "watch scope: "
        f"{config.watch_root} (recursive Python files; generated root excluded: "
        f"{config.generated_root}); {config.asset_build_root} (all final build "
        f"files; asset output excluded: {config.asset_output_root})"
    )
    _status(
        f"refresh-only: Jinja and {config.reload_roots}; "
        f"revision file: {config.revision_file}"
    )

    if not config.watch_root.is_dir():
        _status(
            f"fatal watcher error: watch root is not a directory: {config.watch_root}"
        )
        return 1
    if not config.asset_build_root.is_dir():
        _status(
            "fatal watcher error: asset build root is not a directory: "
            f"{config.asset_build_root}"
        )
        return 1

    server: _Server | None = None
    result = 0
    previous_sigterm = signal.signal(signal.SIGTERM, _handle_sigterm)
    try:
        if _prepare(config, server_alive=False, initial=True):
            server = _start_server(config)
            if server is None:
                result = 1

        try:
            for changes in _watch(config):
                for root in config.reload_directories:
                    if not root.is_dir() or not _ordinary(root):
                        raise OSError(
                            f"reload directory disappeared or changed kind: {root}"
                        )
                if server is not None and _poll_server(server, config) is not None:
                    server = None

                accepted = _accepted_paths(config, changes)
                if not accepted:
                    continue
                relative_paths = ", ".join(
                    str(path.relative_to(config.root))
                    if path.is_relative_to(config.root)
                    else str(path)
                    for path in accepted
                )
                _status(f"accepted changed paths: {relative_paths}")

                if any(_restart_path(config, path) for path in accepted):
                    if not _prepare(config, server_alive=server is not None):
                        continue
                    if server is not None and _poll_server(server, config) is not None:
                        server = None
                        continue
                    _status("requested restart")
                    if server is not None:
                        if not _stop_server(server, config):
                            result = 1
                            break
                        server = None
                    server = _start_server(config)
                    if server is None:
                        result = 1
                        continue
                revision += 1
                assert config.revision_file is not None
                _publish(config.revision_file, session, revision)
                _status(f"published refresh revision: {session}:{revision}")
        except (KeyboardInterrupt, _ShutdownRequested):
            _status("shutdown requested")
        except _RevisionError as error:
            _status(f"fatal revision publication: {error}")
            result = 1
        except _CleanupError as error:
            _status(f"fatal cleanup: {error}")
            result = 1
        except OSError as error:
            _status(f"fatal watcher error: {error}")
            result = 1
    except (KeyboardInterrupt, _ShutdownRequested):
        _status("shutdown requested")
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        if server is not None:
            _status("final shutdown")
            if not _stop_server(server, config):
                result = 1
        else:
            _status("final shutdown: no server")
    return result


def main(root: Path, factory: str, argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    try:
        arguments = parser.parse_args(argv)
    except SystemExit as error:
        return error.code if isinstance(error.code, int) else 1

    if not _supported_platform():
        _status(f"unsupported platform: {sys.platform}")
        return 2

    try:
        config = _config(
            root, factory, arguments.host, arguments.port, arguments.reload_path
        )
    except (OSError, ValueError) as error:
        _status(f"invalid reload configuration: {error}")
        return 2
    return _run_loop(config)
