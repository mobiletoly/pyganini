# pyright: reportPrivateUsage=false

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from watchfiles import Change

import dev


def _config(tmp_path: Path) -> dev._Config:
    root = tmp_path / "example"
    app = root / "app"
    generated = app / "_pyganini"
    generated.mkdir(parents=True)
    asset_build = root / "assets" / "build"
    asset_build.mkdir(parents=True)
    return dev._Config(
        root=root,
        watch_root=app,
        asset_build_root=asset_build,
        generated_root=generated,
        asset_output_root=root / "assets" / "dist",
        server_command=("fake-server",),
        host="127.0.0.1",
        port=8000,
    )


def _changes(*paths: Path) -> set[tuple[Change, str]]:
    return {(Change.modified, str(path)) for path in paths}


def test_parser_defaults_and_fixed_flags() -> None:
    arguments = dev._parser().parse_args([])
    assert arguments.host == "127.0.0.1"
    assert arguments.port == 8000

    selected = dev._parser().parse_args(["--host", "0.0.0.0", "--port", "9001"])
    assert selected.host == "0.0.0.0"
    assert selected.port == 9001


@pytest.mark.parametrize(
    "arguments",
    [["--host", ""], ["--port", "0"], ["--port", "65536"], ["--po", "9001"]],
)
def test_parser_rejects_invalid_or_abbreviated_flags(
    arguments: list[str],
) -> None:
    with pytest.raises(SystemExit) as error:
        dev._parser().parse_args(arguments)
    assert error.value.code == 2


def test_unsupported_platform_fails_before_running_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unsupported_platform() -> bool:
        return False

    monkeypatch.setattr(dev, "_supported_platform", unsupported_platform)
    assert dev.main([]) == 2


def test_config_uses_dev_file_when_invoked_from_another_cwd(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    config = dev._config("localhost", 8123)
    assert config.root == Path(dev.__file__).resolve().parent
    assert config.watch_root == config.root / "app"
    assert config.asset_build_root == config.root / "assets" / "build"
    assert config.generated_root == config.root / "app" / "_pyganini"
    assert config.asset_output_root == config.root / "assets" / "dist"
    assert config.server_command == (
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:create_development_app",
        "--factory",
        "--host",
        "localhost",
        "--port",
        "8123",
    )


def test_prepare_runs_public_generate_then_check_with_inherited_streams(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def fake_run(
        command: Sequence[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append((tuple(command), kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert dev._prepare(config, server_alive=True) is True
    assert [call[0] for call in calls] == [
        (
            sys.executable,
            "-m",
            "pyganini",
            "generate",
            "--app-root",
            str(config.root),
        ),
        (
            sys.executable,
            "-m",
            "pyganini",
            "check",
            "--app-root",
            str(config.root),
        ),
    ]
    assert all(call[1]["cwd"] == config.root for call in calls)
    assert all(call[1]["shell"] is False for call in calls)
    assert all(call[1]["check"] is False for call in calls)
    assert all("stdout" not in call[1] and "stderr" not in call[1] for call in calls)


def test_prepare_generation_failure_skips_check_and_retains_server(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _config(tmp_path)
    calls: list[tuple[str, ...]] = []

    def fake_run(
        command: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(command))
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert dev._prepare(config, server_alive=True) is False
    assert len(calls) == 1
    output = capsys.readouterr().out
    assert "generation failed" in output
    assert "server retained" in output


def test_prepare_check_failure_skips_restart(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    results = iter((0, 1))
    calls: list[tuple[str, ...]] = []

    def fake_run(
        command: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(command))
        return subprocess.CompletedProcess(command, next(results))

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert dev._prepare(config, server_alive=True) is False
    assert len(calls) == 2
    assert calls[1][3] == "check"


def test_filter_accepts_python_and_final_asset_build_files(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    source = config.watch_root / "z.py"
    other_source = config.watch_root / "nested" / "a.py"
    other_source.parent.mkdir()
    source.touch()
    other_source.touch()
    generated_source = config.generated_root / "generated.py"
    generated_source.touch()
    template = config.watch_root / "page.jinja"
    template.touch()
    asset = config.asset_build_root / "bundle.any-name"
    asset.touch()
    asset_output = config.asset_output_root / "bundle.12345678.js"
    asset_output.parent.mkdir(parents=True)
    asset_output.touch()
    directory = config.watch_root / "folder.py"
    directory.mkdir()
    outside = config.root.parent / "outside.py"
    outside.touch()

    assert dev._watch_filter(config, Change.modified, str(source)) is True
    assert dev._watch_filter(config, Change.added, str(other_source)) is True
    assert dev._watch_filter(config, Change.modified, str(generated_source)) is False
    assert dev._watch_filter(config, Change.modified, str(template)) is False
    assert dev._watch_filter(config, Change.modified, str(directory)) is False
    assert dev._watch_filter(config, Change.modified, str(asset)) is True
    assert dev._watch_filter(config, Change.modified, str(asset_output)) is False
    assert dev._watch_filter(config, Change.modified, str(outside)) is False

    accepted = dev._accepted_paths(
        config, _changes(source, other_source, generated_source, asset)
    )
    assert accepted == (other_source, source, asset)


def test_watch_filter_rejects_deleted_python_directory_event(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    directory = config.watch_root / "deleted.py"
    directory.mkdir()
    seen: dict[str, object] = {}

    def fake_watch(
        *_paths: Path | str, **kwargs: object
    ) -> Iterator[set[tuple[Change, str]]]:
        seen.update(kwargs)
        return iter(())

    monkeypatch.setattr(dev, "watch", fake_watch)
    assert tuple(dev._watch(config)) == ()
    directory.rmdir()

    watch_filter = cast(Callable[[Change, str], bool], seen["watch_filter"])
    assert watch_filter(Change.deleted, str(directory)) is False


def test_watch_filter_accepts_deleted_python_file(tmp_path: Path) -> None:
    config = _config(tmp_path)
    source = config.watch_root / "deleted.py"
    source.touch()
    source.unlink()

    assert dev._watch_filter(config, Change.deleted, str(source)) is True
    assert dev._accepted_paths(config, {(Change.deleted, str(source))}) == (source,)


def test_watch_filter_accepts_deleted_asset_file(tmp_path: Path) -> None:
    config = _config(tmp_path)
    asset = config.asset_build_root / "deleted-output"
    asset.touch()
    asset.unlink()

    assert dev._watch_filter(config, Change.deleted, str(asset)) is True
    assert dev._accepted_paths(config, {(Change.deleted, str(asset))}) == (asset,)


def test_watch_uses_locked_configuration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    seen: dict[str, object] = {}

    def fake_watch(
        *paths: Path | str, **kwargs: object
    ) -> Iterator[set[tuple[Change, str]]]:
        seen["paths"] = paths
        seen.update(kwargs)
        return iter(())

    monkeypatch.setattr(dev, "watch", fake_watch)
    assert tuple(dev._watch(config)) == ()
    assert seen["paths"] == (config.watch_root, config.asset_build_root)
    assert seen["debounce"] == 200
    assert seen["step"] == 50
    assert seen["rust_timeout"] == 250
    assert seen["yield_on_timeout"] is True
    assert seen["recursive"] is True
    assert seen["raise_interrupt"] is True
    assert seen["ignore_permission_denied"] is False
    assert seen["force_polling"] is None


def test_server_start_failure_is_reported_without_a_child(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _config(tmp_path)

    def fail_start(*_args: object, **_kwargs: object) -> subprocess.Popen[bytes]:
        raise OSError("fake start failure")

    monkeypatch.setattr(subprocess, "Popen", fail_start)
    assert dev._start_server(config) is None
    assert "server start failed" in capsys.readouterr().out


def _real_child(script: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-c", script],
        start_new_session=True,
    )


def _server(child: subprocess.Popen[bytes]) -> dev._Server:
    return dev._Server(process=child, process_group=child.pid)


def test_stop_server_reaps_graceful_fake_child(tmp_path: Path) -> None:
    config = replace(_config(tmp_path), sigint_timeout=1.0)
    server = _server(
        _real_child(
            "import signal, sys, time; "
            "signal.signal(signal.SIGINT, lambda *_: sys.exit(0)); "
            "time.sleep(30)"
        )
    )
    try:
        time.sleep(0.1)
        assert dev._stop_server(server, config) is True
        assert server.process.poll() is not None
    finally:
        if server.process.poll() is None:
            server.process.kill()
            server.process.wait(timeout=5)


def test_stop_server_escalates_and_reaps_process_group(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = replace(
        _config(tmp_path),
        sigint_timeout=0.1,
        sigterm_timeout=0.1,
        sigkill_timeout=1.0,
    )
    server = _server(
        _real_child(
            "import signal, time; "
            "signal.signal(signal.SIGINT, signal.SIG_IGN); "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "time.sleep(30)"
        )
    )
    try:
        time.sleep(0.1)
        assert dev._stop_server(server, config) is True
        assert server.process.poll() is not None
        output = capsys.readouterr().out
        assert "SIGINT timed out" in output
        assert "SIGTERM timed out" in output
    finally:
        if server.process.poll() is None:
            server.process.kill()
            server.process.wait(timeout=5)


def test_stop_server_signals_a_descendant_in_the_same_process_group(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "descendant-term.txt"
    script = (
        "import os, signal, sys, time; "
        "marker = sys.argv[1]; "
        "child = os.fork(); "
        "signal.signal(signal.SIGINT, signal.SIG_IGN); "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN) if child else None; "
        "signal.signal(signal.SIGINT, signal.SIG_IGN) if not child else None; "
        "signal.signal(signal.SIGTERM, "
        "lambda *_: (open(marker, 'w').write('term'), os._exit(0))) "
        "if not child else None; "
        "time.sleep(30)"
    )
    config = replace(
        _config(tmp_path),
        server_command=(sys.executable, "-c", script, str(marker)),
        sigint_timeout=0.1,
        sigterm_timeout=1.0,
        sigkill_timeout=1.0,
    )
    server = dev._start_server(config)
    assert server is not None
    try:
        time.sleep(0.1)
        assert dev._stop_server(server, config) is True
        assert marker.read_text() == "term"
    finally:
        if server.process.poll() is None:
            server.process.kill()
            server.process.wait(timeout=5)


def test_stop_server_escalates_after_direct_child_exits_with_live_descendant(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "descendant-escalated.txt"
    script = (
        "import os, signal, sys, time; "
        "marker = sys.argv[1]; "
        "child = os.fork(); "
        "signal.signal(signal.SIGINT, "
        "(lambda *_: sys.exit(0)) if child else signal.SIG_IGN); "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN) if child else "
        "signal.signal(signal.SIGTERM, "
        "lambda *_: (open(marker, 'w').write('term'), os._exit(0))); "
        "time.sleep(30)"
    )
    config = replace(
        _config(tmp_path),
        server_command=(sys.executable, "-c", script, str(marker)),
        sigint_timeout=0.1,
        sigterm_timeout=1.0,
        sigkill_timeout=1.0,
    )
    server = dev._start_server(config)
    assert server is not None
    process_group = server.process_group
    try:
        time.sleep(0.1)
        assert dev._stop_server(server, config) is True
        assert marker.read_text() == "term"
    finally:
        with suppress(ProcessLookupError):
            os.killpg(process_group, signal.SIGKILL)
        if server.process.poll() is None:
            server.process.wait(timeout=5)


def test_stop_server_cleans_descendant_when_direct_child_already_exited(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "already-exited-descendant.txt"
    script = (
        "import os, signal, sys, time; "
        "marker = sys.argv[1]; "
        "child = os.fork(); "
        "os._exit(0) if child else None; "
        "signal.signal(signal.SIGINT, signal.SIG_IGN); "
        "signal.signal(signal.SIGTERM, "
        "lambda *_: (open(marker, 'w').write('term'), os._exit(0))); "
        "time.sleep(30)"
    )
    config = replace(
        _config(tmp_path),
        server_command=(sys.executable, "-c", script, str(marker)),
        sigint_timeout=0.1,
        sigterm_timeout=1.0,
        sigkill_timeout=1.0,
    )
    server = dev._start_server(config)
    assert server is not None
    process_group = server.process_group
    try:
        time.sleep(0.1)
        assert server.process.poll() is not None
        assert dev._stop_server(server, config) is True
        assert marker.read_text() == "term"
    finally:
        with suppress(ProcessLookupError):
            os.killpg(process_group, signal.SIGKILL)
        if server.process.poll() is None:
            server.process.wait(timeout=5)


def test_run_loop_cleans_unexpected_group_before_replacement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    marker = tmp_path / "unexpected-descendant-term.txt"
    ready = tmp_path / "unexpected-descendant-ready.txt"
    script = (
        "import os, signal, sys, time; "
        "marker, ready = sys.argv[1:3]; "
        "child = os.fork(); "
        "os._exit(3) if child else None; "
        "signal.signal(signal.SIGINT, signal.SIG_IGN); "
        "signal.signal(signal.SIGTERM, "
        "lambda *_: (open(marker, 'w').write('term'), os._exit(0))); "
        "open(ready, 'w').close(); "
        "time.sleep(30)"
    )
    config = replace(
        _config(tmp_path),
        server_command=(sys.executable, "-c", script, str(marker), str(ready)),
        sigint_timeout=0.1,
        sigterm_timeout=1.0,
        sigkill_timeout=1.0,
    )
    first = _server(
        subprocess.Popen(
            config.server_command,
            cwd=config.root,
            start_new_session=True,
        )
    )
    process_group = first.process_group
    starts = 0
    second_start_saw_cleanup: list[tuple[bool, bool]] = []

    def fake_prepare(
        _config: dev._Config, *, server_alive: bool, initial: bool = False
    ) -> bool:
        return True

    def fake_start(_config: dev._Config) -> dev._Server | None:
        nonlocal starts
        starts += 1
        if starts == 1:
            return first
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            group_exists = False
        else:
            group_exists = True
        second_start_saw_cleanup.append(
            (marker.exists() and marker.read_text() == "term", group_exists)
        )
        return None

    def fake_watch(_config: dev._Config) -> Iterator[set[tuple[Change, str]]]:
        while not ready.exists():
            time.sleep(0.01)
        yield set()
        yield _changes(config.watch_root / "changed.py")
        raise dev._ShutdownRequested

    monkeypatch.setattr(dev, "_prepare", fake_prepare)
    monkeypatch.setattr(dev, "_start_server", fake_start)
    monkeypatch.setattr(dev, "_watch", fake_watch)
    try:
        assert dev._run_loop(config) == 1
        assert starts == 2
        assert second_start_saw_cleanup == [(True, False)]
        assert marker.read_text() == "term"
    finally:
        with suppress(ProcessLookupError):
            os.killpg(process_group, signal.SIGKILL)
        if first.process.poll() is None:
            first.process.wait(timeout=5)


def test_wait_for_exit_uses_one_phase_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]
    wait_timeouts: list[float] = []

    def consume_child_time(timeout: float) -> None:
        wait_timeouts.append(timeout)
        clock[0] += 4.0

    child = _FakeChild(wait_callback=consume_child_time)
    deadlines: list[tuple[int, float]] = []
    remaining: list[float] = []

    monkeypatch.setattr(time, "monotonic", lambda: clock[0])

    def fake_wait_for_group_exit(process_group: int, deadline: float) -> bool:
        deadlines.append((process_group, deadline))
        remaining.append(deadline - clock[0])
        return True

    monkeypatch.setattr(dev, "_wait_for_group_exit", fake_wait_for_group_exit)
    assert dev._wait_for_exit(cast(subprocess.Popen[bytes], child), 5.0, 123) is True
    assert wait_timeouts == [5.0]
    assert deadlines == [(123, 105.0)]
    assert remaining == [1.0]


def test_run_loop_reports_initial_state_before_failed_preparation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _config(tmp_path)

    def fake_prepare(
        _config: dev._Config, *, server_alive: bool, initial: bool = False
    ) -> bool:
        assert server_alive is False
        assert initial is True
        return False

    def fake_watch(_config: dev._Config) -> Iterator[set[tuple[Change, str]]]:
        raise dev._ShutdownRequested
        yield set()

    monkeypatch.setattr(dev, "_prepare", fake_prepare)
    monkeypatch.setattr(dev, "_watch", fake_watch)

    assert dev._run_loop(config) == 0
    launcher_lines = [
        line
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("[full-feature-dev]")
    ]
    assert launcher_lines[:4] == [
        f"[full-feature-dev] application root: {config.root}",
        "[full-feature-dev] server URL: http://127.0.0.1:8000",
        (
            f"[full-feature-dev] watch scope: {config.watch_root} (recursive "
            f"Python files; generated root excluded: {config.generated_root}); "
            f"{config.asset_build_root} (all final build files; asset output "
            f"excluded: {config.asset_output_root})"
        ),
        (
            "[full-feature-dev] manual refresh: Jinja templates reload on request; "
            "asset changes restart the server; refresh the browser"
        ),
    ]


class _FakeChild:
    pid = os.getpid()

    def __init__(
        self,
        exit_code: int | None = None,
        wait_callback: Callable[[float], None] | None = None,
    ) -> None:
        self.exit_code = exit_code
        self.wait_callback = wait_callback
        self.waited = False

    def poll(self) -> int | None:
        return self.exit_code

    def wait(self, **_kwargs: object) -> int:
        self.waited = True
        timeout = _kwargs.get("timeout")
        if self.wait_callback is not None and timeout is not None:
            self.wait_callback(float(cast(float, timeout)))
        return 0 if self.exit_code is None else self.exit_code


def _fake_server(child: _FakeChild) -> dev._Server:
    return dev._Server(
        process=cast(subprocess.Popen[bytes], child),
        process_group=child.pid,
    )


def _copy_example_config(tmp_path: Path) -> dev._Config:
    source = Path(dev.__file__).resolve().parent
    root = tmp_path / "example-copy"
    shutil.copytree(
        source,
        root,
        ignore=shutil.ignore_patterns(
            ".venv",
            ".playwright",
            ".pytest_cache",
            "__pycache__",
        ),
    )
    return dev._Config(
        root=root,
        watch_root=root / "app",
        asset_build_root=root / "assets" / "build",
        generated_root=root / "app" / "_pyganini",
        asset_output_root=root / "assets" / "dist",
        server_command=("fake-server",),
        host="127.0.0.1",
        port=8000,
    )


def _asset_snapshot(config: dev._Config) -> tuple[str, bytes, bytes]:
    content = (config.asset_build_root / "app.js").read_bytes()
    digest = hashlib.sha256(content).hexdigest()[:8]
    target = config.asset_output_root / f"app.{digest}.js"
    state_path = config.root / "assets" / ".pyganini" / "assets.json"
    state_bytes = state_path.read_bytes()
    state = json.loads(state_bytes)
    row = next(item for item in state["managed"] if item["logical"] == "app.js")
    assert row == {
        "logical": "app.js",
        "dist": f"assets/dist/app.{digest}.js",
        "hash": digest,
    }
    return target.name, target.read_bytes(), state_bytes


def test_real_asset_commands_commit_current_bytes_before_replacement_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _copy_example_config(tmp_path)
    first = _fake_server(_FakeChild())
    second = _fake_server(_FakeChild())
    starts: list[tuple[str, bytes, bytes]] = []
    stops: list[dev._Server] = []
    commands: list[str] = []
    changed = b"window.pyganiniAssetIntegration = 'changed';\n"
    real_run = dev._run_command

    def run_real(command: Sequence[str], *, cwd: Path) -> int | None:
        commands.append(command[3])
        return real_run(command, cwd=cwd)

    def fake_start(_config: dev._Config) -> dev._Server:
        starts.append(_asset_snapshot(config))
        return first if len(starts) == 1 else second

    def fake_stop(server: dev._Server, _config: dev._Config) -> bool:
        stops.append(server)
        return True

    def fake_watch(_config: dev._Config) -> Iterator[set[tuple[Change, str]]]:
        source = config.asset_build_root / "app.js"
        source.write_bytes(changed)
        yield _changes(source)
        raise dev._ShutdownRequested

    monkeypatch.setattr(dev, "_run_command", run_real)
    monkeypatch.setattr(dev, "_start_server", fake_start)
    monkeypatch.setattr(dev, "_stop_server", fake_stop)
    monkeypatch.setattr(dev, "_watch", fake_watch)

    assert dev._run_loop(config) == 0
    assert commands == ["generate", "check", "generate", "check"]
    assert len(starts) == 2
    assert starts[1][1] == changed
    assert starts[1][0] == (f"app.{hashlib.sha256(changed).hexdigest()[:8]}.js")
    assert starts[1][2] != starts[0][2]
    assert stops == [first, second]


@pytest.mark.parametrize("failed_operation", ["generate", "check"])
def test_real_asset_command_failure_retains_working_server(
    failed_operation: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _copy_example_config(tmp_path)
    server = _fake_server(_FakeChild())
    starts = 0
    stops = 0
    commands: list[str] = []
    real_run = dev._run_command

    def run_real(command: Sequence[str], *, cwd: Path) -> int | None:
        operation = command[3]
        commands.append(operation)
        result = real_run(command, cwd=cwd)
        if (
            failed_operation == "check"
            and operation == "generate"
            and len(commands) == 3
            and result == 0
        ):
            _, _, state_bytes = _asset_snapshot(config)
            state = json.loads(state_bytes)
            row = next(item for item in state["managed"] if item["logical"] == "app.js")
            (config.root / row["dist"]).write_bytes(b"corrupt after generation\n")
        return result

    def fake_start(_config: dev._Config) -> dev._Server:
        nonlocal starts
        starts += 1
        return server

    def fake_stop(_server: dev._Server, _config: dev._Config) -> bool:
        nonlocal stops
        stops += 1
        return True

    def fake_watch(_config: dev._Config) -> Iterator[set[tuple[Change, str]]]:
        if failed_operation == "generate":
            source = config.asset_build_root / "bad?.js"
            source.write_bytes(b"invalid name\n")
        else:
            source = config.asset_build_root / "app.js"
            source.write_bytes(b"changed before failed check\n")
        yield _changes(source)
        raise dev._ShutdownRequested

    monkeypatch.setattr(dev, "_run_command", run_real)
    monkeypatch.setattr(dev, "_start_server", fake_start)
    monkeypatch.setattr(dev, "_stop_server", fake_stop)
    monkeypatch.setattr(dev, "_watch", fake_watch)

    assert dev._run_loop(config) == 0
    assert starts == 1
    assert stops == 1
    assert commands[:2] == ["generate", "check"]
    assert commands[2:] == (
        ["generate"] if failed_operation == "generate" else ["generate", "check"]
    )
    output = capsys.readouterr().out
    assert "server retained" in output
    assert "requested restart" not in output


def test_asset_event_commits_outputs_before_replacement_server_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    first = _fake_server(_FakeChild())
    second = _fake_server(_FakeChild())
    started: list[tuple[bytes, bytes]] = []
    stopped: list[dev._Server] = []
    commands: list[str] = []
    output = config.asset_output_root / "bundle.12345678.js"
    state = config.root / "assets" / ".pyganini" / "assets.json"

    def fake_run(
        command: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        operation = command[3]
        commands.append(operation)
        if operation == "generate":
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(f"fingerprint-{len(commands)}\n".encode())
            state.parent.mkdir(parents=True, exist_ok=True)
            state.write_bytes(f"state-{len(commands)}\n".encode())
        else:
            assert output.is_file()
            assert state.is_file()
        return subprocess.CompletedProcess(command, 0)

    def fake_start(_config: dev._Config) -> dev._Server:
        started.append((output.read_bytes(), state.read_bytes()))
        return first if len(started) == 1 else second

    def fake_stop(server: dev._Server, _config: dev._Config) -> bool:
        stopped.append(server)
        return True

    def fake_watch(_config: dev._Config) -> Iterator[set[tuple[Change, str]]]:
        yield _changes(config.asset_build_root / "bundle.js")
        raise dev._ShutdownRequested

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(dev, "_start_server", fake_start)
    monkeypatch.setattr(dev, "_stop_server", fake_stop)
    monkeypatch.setattr(dev, "_watch", fake_watch)

    assert dev._run_loop(config) == 0
    assert commands == ["generate", "check", "generate", "check"]
    assert len(started) == 2
    assert started[0][0] == b"fingerprint-1\n"
    assert started[1][0] == b"fingerprint-3\n"
    assert started[0][1] == b"state-1\n"
    assert started[1][1] == b"state-3\n"
    assert stopped == [first, second]


@pytest.mark.parametrize("failed_operation", ["generate", "check"])
def test_asset_preparation_failure_retains_working_server(
    failed_operation: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _config(tmp_path)
    server = _fake_server(_FakeChild())
    starts = 0
    stops = 0
    calls = 0

    def fake_run(
        command: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        operation = command[3]
        if calls > 2 and operation == failed_operation:
            return subprocess.CompletedProcess(command, 1)
        return subprocess.CompletedProcess(command, 0)

    def fake_start(_config: dev._Config) -> dev._Server:
        nonlocal starts
        starts += 1
        return server

    def fake_stop(_server: dev._Server, _config: dev._Config) -> bool:
        nonlocal stops
        stops += 1
        return True

    def fake_watch(_config: dev._Config) -> Iterator[set[tuple[Change, str]]]:
        yield _changes(config.asset_build_root / "bundle.js")
        raise dev._ShutdownRequested

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(dev, "_start_server", fake_start)
    monkeypatch.setattr(dev, "_stop_server", fake_stop)
    monkeypatch.setattr(dev, "_watch", fake_watch)

    assert dev._run_loop(config) == 0
    assert starts == 1
    assert stops == 1
    output = capsys.readouterr().out
    assert "server retained" in output
    assert "requested restart" not in output


def test_one_coalesced_event_causes_one_restart_and_final_reap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    first = _fake_server(_FakeChild())
    second = _fake_server(_FakeChild())
    started: list[dev._Server] = []
    prepared: list[tuple[bool, bool]] = []
    stopped: list[dev._Server] = []
    changes = _changes(config.watch_root / "z.py", config.watch_root / "a.py")

    def fake_prepare(
        _config: dev._Config, *, server_alive: bool, initial: bool = False
    ) -> bool:
        prepared.append((server_alive, initial))
        return True

    def fake_start(_config: dev._Config) -> dev._Server:
        server = first if not started else second
        started.append(server)
        return server

    def fake_stop(server: dev._Server, _config: dev._Config) -> bool:
        stopped.append(server)
        return True

    def fake_watch(_config: dev._Config) -> Iterator[set[tuple[Change, str]]]:
        yield changes
        raise dev._ShutdownRequested

    monkeypatch.setattr(dev, "_prepare", fake_prepare)
    monkeypatch.setattr(dev, "_start_server", fake_start)
    monkeypatch.setattr(dev, "_stop_server", fake_stop)
    monkeypatch.setattr(dev, "_watch", fake_watch)

    assert dev._run_loop(config) == 0
    assert prepared == [(False, True), (True, False)]
    assert started == [first, second]
    assert stopped == [first, second]


def test_run_loop_defers_replacement_when_server_exits_during_preparation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _config(tmp_path)
    child = _FakeChild()
    server = _fake_server(child)
    started: list[dev._Server] = []
    prepared: list[tuple[bool, bool]] = []
    stopped: list[dev._Server] = []

    def fake_prepare(
        _config: dev._Config, *, server_alive: bool, initial: bool = False
    ) -> bool:
        prepared.append((server_alive, initial))
        if not initial:
            child.exit_code = 3
        return True

    def fake_start(_config: dev._Config) -> dev._Server:
        started.append(server)
        return server

    def fake_stop(stopped_server: dev._Server, _config: dev._Config) -> bool:
        stopped.append(stopped_server)
        return True

    def fake_watch(_config: dev._Config) -> Iterator[set[tuple[Change, str]]]:
        yield _changes(config.watch_root / "changed.py")
        raise dev._ShutdownRequested

    monkeypatch.setattr(dev, "_prepare", fake_prepare)
    monkeypatch.setattr(dev, "_start_server", fake_start)
    monkeypatch.setattr(dev, "_stop_server", fake_stop)
    monkeypatch.setattr(dev, "_watch", fake_watch)

    assert dev._run_loop(config) == 0
    assert prepared == [(False, True), (True, False)]
    assert started == [server]
    assert stopped == [server]
    output = capsys.readouterr().out
    assert output.count("unexpected child exit") == 1
    assert "requested restart" not in output


def test_cleanup_failure_prevents_replacement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    server = _fake_server(_FakeChild())
    starts = 0
    stops = 0

    def fake_prepare(
        _config: dev._Config, *, server_alive: bool, initial: bool = False
    ) -> bool:
        return True

    def fake_start(_config: dev._Config) -> dev._Server:
        nonlocal starts
        starts += 1
        return server

    def fake_stop(_server: dev._Server, _config: dev._Config) -> bool:
        nonlocal stops
        stops += 1
        return False

    def fake_watch(_config: dev._Config) -> Iterator[set[tuple[Change, str]]]:
        yield _changes(config.watch_root / "changed.py")
        raise dev._ShutdownRequested

    monkeypatch.setattr(dev, "_prepare", fake_prepare)
    monkeypatch.setattr(dev, "_start_server", fake_start)
    monkeypatch.setattr(dev, "_stop_server", fake_stop)
    monkeypatch.setattr(dev, "_watch", fake_watch)

    assert dev._run_loop(config) == 1
    assert starts == 1
    assert stops == 2


def test_exited_child_is_reported_once_without_crash_loop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _config(tmp_path)
    server = _fake_server(_FakeChild(exit_code=3))
    starts = 0

    def fake_prepare(
        _config: dev._Config, *, server_alive: bool, initial: bool = False
    ) -> bool:
        assert initial is True
        assert server_alive is False
        return True

    def fake_start(_config: dev._Config) -> dev._Server:
        nonlocal starts
        starts += 1
        return server

    def fake_watch(_config: dev._Config) -> Iterator[set[tuple[Change, str]]]:
        yield set()
        raise dev._ShutdownRequested

    monkeypatch.setattr(dev, "_prepare", fake_prepare)
    monkeypatch.setattr(dev, "_start_server", fake_start)
    monkeypatch.setattr(dev, "_watch", fake_watch)

    assert dev._run_loop(config) == 0
    assert starts == 1
    assert capsys.readouterr().out.count("unexpected child exit") == 1
