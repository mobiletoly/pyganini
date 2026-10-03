"""Real-browser proof shared by the two example-owned development loops."""

from __future__ import annotations

import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def _wait(predicate: Callable[[], bool], timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("Authoring observation timed out")
        time.sleep(0.01)


def exercise_authoring(source: Path, temporary: Path) -> None:
    root = temporary / source.name
    shutil.copytree(
        source,
        root,
        ignore=shutil.ignore_patterns(
            ".venv",
            ".playwright",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
        ),
    )
    shutil.copyfile(source.parent / "dev_support.py", temporary / "dev_support.py")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    log = temporary / "supervisor.log"
    coordination: Path | None = None
    child_pids: set[int] = set()
    with log.open("wb") as output:
        supervisor = subprocess.Popen(
            [
                sys.executable,
                str(root / "dev.py"),
                "--port",
                str(port),
                "--reload-path",
                "content",
            ],
            cwd=root,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:

            def ready() -> bool:
                return (
                    "Uvicorn running on" in log.read_text()
                    or supervisor.poll() is not None
                )

            _wait(ready)
            assert supervisor.poll() is None, log.read_text()
            revision_match = re.search(r"revision file: (.+)", log.read_text())
            assert revision_match is not None
            coordination = Path(revision_match[1])

            def child_pid() -> int:
                matches = re.findall(
                    r"Started server process \[(\d+)\]", log.read_text()
                )
                assert matches
                pid = int(matches[-1])
                child_pids.add(pid)
                return pid

            initial_pid = child_pid()
            generated = {
                path: (path.read_bytes(), path.stat().st_mtime_ns)
                for path in (root / "app/_pyganini").glob("*.py")
            }
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page()
                external: list[str] = []
                page.on(
                    "request",
                    lambda request: (
                        external.append(request.url)
                        if urlsplit(request.url).netloc != f"127.0.0.1:{port}"
                        else None
                    ),
                )
                page.add_init_script("""
                    window.reloadRevisions = [];
                    const NativeEventSource = window.EventSource;
                    window.EventSource = class extends NativeEventSource {
                        constructor(url) {
                            super(url);
                            this.addEventListener('reload', event => {
                                window.reloadRevisions.push(event.data);
                            });
                        }
                    };
                """)
                try:
                    page.goto(origin + "/privacy")
                    page.wait_for_function("window.reloadRevisions.length === 1")
                    revision = page.evaluate("window.reloadRevisions[0]")
                    assert coordination.read_text() == revision
                    body = root / "content/privacy/body.html"
                    with page.expect_navigation(wait_until="domcontentloaded"):
                        body.write_text('<p data-authoring="edited">Edited live</p>')
                    assert (
                        page.locator('[data-authoring="edited"]').inner_text()
                        == "Edited live"
                    )
                    metadata = root / "content/privacy/page.json"
                    with page.expect_navigation(
                        wait_until="domcontentloaded"
                    ) as failed:
                        metadata.write_text('{"title":null}')
                    assert failed.value is not None and failed.value.status == 500
                    page.wait_for_function("window.reloadRevisions.length === 1")
                    with page.expect_navigation(wait_until="domcontentloaded"):
                        metadata.write_text('{"title":"Repaired"}')
                    assert page.title() == "Repaired"
                    nested = root / "content/privacy/new-page"
                    nested.mkdir()
                    with page.expect_navigation(wait_until="domcontentloaded"):
                        (nested / "page.json").write_text('{"title":"New page"}')
                        (nested / "body.md").write_text("# New nested page")
                    page.goto(origin + "/privacy/new-page")
                    assert page.locator("#new-nested-page").count() == 1
                    page.wait_for_function("window.reloadRevisions.length === 1")
                    # Disconnect, save, and reconnect: the native EventSource keeps
                    # its last revision and compares the initial event on reconnect.
                    page.context.set_offline(True)
                    old = coordination.read_text()
                    (nested / "body.md").write_text("# Missed edit")
                    _wait(lambda: coordination.read_text() != old)
                    with page.expect_navigation(wait_until="domcontentloaded"):
                        page.context.set_offline(False)
                    assert page.locator("#missed-edit").count() == 1
                    template = root / "app/routes/layout.jinja"
                    page.wait_for_function("window.reloadRevisions.length === 1")
                    with page.expect_navigation(wait_until="domcontentloaded"):
                        template.write_text(
                            template.read_text().replace(
                                "</body>", '<p id="jinja-edit">Jinja edit</p></body>'
                            )
                        )
                    assert page.locator("#jinja-edit").count() == 1
                    assert child_pid() == initial_pid
                    assert generated == {
                        path: (path.read_bytes(), path.stat().st_mtime_ns)
                        for path in generated
                    }
                    page.wait_for_function("window.reloadRevisions.length === 1")
                    python_source = root / "app/main.py"
                    with page.expect_navigation(wait_until="domcontentloaded"):
                        python_source.write_text(
                            python_source.read_text() + "\n# Authoring restart proof.\n"
                        )
                    _wait(lambda: child_pid() != initial_pid)
                    assert page.locator("#jinja-edit").count() == 1
                    assert external == []
                finally:
                    page.close()
                    browser.close()
        finally:
            supervisor.send_signal(signal.SIGTERM)
            try:
                supervisor.wait(timeout=12)
            except subprocess.TimeoutExpired:
                supervisor.kill()
                supervisor.wait(timeout=3)
                raise AssertionError("Supervisor cleanup timed out") from None
    assert supervisor.returncode == 0, log.read_text()
    assert coordination is not None and not coordination.parent.exists()
    for pid in child_pids:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            pass
        else:
            raise AssertionError(f"Child process remains: {pid}")
