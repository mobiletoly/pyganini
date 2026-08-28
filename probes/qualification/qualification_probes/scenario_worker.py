from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, cast


class Finding(RuntimeError):
    """Report an observed product-contract mismatch."""


class InfrastructureFailure(RuntimeError):
    """Report an unavailable or incomplete qualification environment."""


_Q043_HANDLER_MODULE = "app.routes.users.handlers"
_Q043_IMPORT_TRACE_PREFIX = "PYGANINI-Q043-IMPORT:"
_Q043_IMPORT_TRACE_SCRIPT = f"""
import runpy
import sys

target = sys.argv[1]
entrypoint = sys.argv[2]

def trace_import(event, arguments):
    if event == "import" and arguments and arguments[0] == target:
        print("{_Q043_IMPORT_TRACE_PREFIX}" + target, file=sys.stderr, flush=True)

sys.addaudithook(trace_import)
sys.argv = sys.argv[2:]
runpy.run_path(entrypoint, run_name="__main__")
"""


@dataclass(frozen=True, slots=True)
class FixtureEnvironment:
    root: Path
    python: Path
    pyganini: Path


def _emit_stream(target: object, payload: bytes) -> None:
    buffer = cast(BinaryIO, getattr(target, "buffer", target))
    buffer.write(payload)
    buffer.flush()


def _run(
    command: Sequence[str | Path],
    *,
    cwd: Path,
    allowed: tuple[int, ...] = (0,),
    failure: type[RuntimeError] = Finding,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    fixed = [str(item) for item in command]
    print(f"$ {shlex.join(fixed)}", flush=True)
    selected_environment = os.environ.copy()
    if environment is not None:
        selected_environment.update(environment)
    selected_environment.update({"LANG": "C", "LC_ALL": "C"})
    selected_environment.pop("PYTHONPATH", None)
    try:
        completed = subprocess.run(
            fixed,
            cwd=cwd,
            env=selected_environment,
            shell=False,
            check=False,
            capture_output=True,
        )
    except OSError as error:
        raise InfrastructureFailure(
            f"command did not start: {fixed!r}: {error}"
        ) from error
    _emit_stream(sys.stdout, completed.stdout)
    _emit_stream(sys.stderr, completed.stderr)
    if completed.returncode not in allowed:
        raise failure(
            f"command returned {completed.returncode}; expected {allowed}: "
            f"{shlex.join(fixed)}"
        )
    return completed


def _snapshot_generated(root: Path) -> dict[str, tuple[int, str]]:
    generated = root / "app" / "_pyganini"
    if not generated.exists():
        return {}
    snapshot: dict[str, tuple[int, str]] = {}
    for path in sorted(generated.rglob("*")):
        if path.is_file() and path.suffix not in {".pyc", ".pyo"}:
            relative = path.relative_to(root).as_posix()
            payload = path.read_bytes()
            snapshot[relative] = (len(payload), hashlib.sha256(payload).hexdigest())
    return snapshot


@contextmanager
def generated_products_unchanged(root: Path, scenario_id: str) -> Generator[None]:
    before = _snapshot_generated(root)
    try:
        yield
    finally:
        if _snapshot_generated(root) != before:
            raise Finding(f"{scenario_id} changed generated source state")


def _snapshot_full_feature_products(root: Path) -> dict[str, tuple[int, str]]:
    snapshot = _snapshot_generated(root)
    asset_roots = (root / "assets" / ".pyganini", root / "assets" / "dist")
    asset_files = (root / "assets" / "pyganini_assets_gen.py",)
    paths = [
        path
        for asset_root in asset_roots
        if asset_root.exists()
        for path in asset_root.rglob("*")
        if path.is_file()
    ]
    paths.extend(path for path in asset_files if path.is_file())
    for path in sorted(paths):
        payload = path.read_bytes()
        snapshot[path.relative_to(root).as_posix()] = (
            len(payload),
            hashlib.sha256(payload).hexdigest(),
        )
    return snapshot


def _assert_text(payload: bytes, *needles: str) -> None:
    text = payload.decode("utf-8", errors="replace")
    missing = [needle for needle in needles if needle not in text]
    if missing:
        raise Finding(f"command output omitted required evidence: {missing!r}\n{text}")


def _assert_text_absent(payload: bytes, forbidden: str) -> None:
    text = payload.decode("utf-8", errors="replace")
    if forbidden in text:
        raise Finding(
            "unsupported-declaration generation imported an application module: "
            f"{forbidden}"
        )


def _assert_q042_command_result(
    result: subprocess.CompletedProcess[bytes],
    *,
    command_name: str,
    generated_unchanged: bool,
) -> None:
    if result.returncode != 1:
        raise Finding(
            f"Q042 {command_name} returned {result.returncode}; expected exit 1"
        )
    if result.stdout:
        raise Finding(f"Q042 {command_name} emitted unexpected stdout product output")
    diagnostic = result.stderr.decode("utf-8", errors="replace")
    required = (
        "PYGANINI009",
        "route-filesystem",
        "app/routes/users/page.jinja",
        "cannot inspect required template file",
    )
    missing = [item for item in required if item not in diagnostic]
    if missing:
        raise Finding(
            f"Q042 {command_name} omitted required diagnostic evidence: {missing!r}"
        )
    if "Traceback (most recent call last):" in diagnostic:
        raise Finding(f"Q042 {command_name} emitted a Python traceback")
    if not generated_unchanged:
        raise Finding(f"Q042 {command_name} changed generated products")


def _assert_q043_observation(
    observation: object,
    *,
    source_only_sentinel_absent: bool,
    source_only_import_absent: bool,
    generated_unchanged: bool,
) -> None:
    if not isinstance(observation, dict):
        raise Finding("Q043 startup observation is not an object")
    value = cast(dict[str, object], observation)
    expected = {
        "startup_raised": True,
        "wrapper_type": "DispatchError",
        "wrapper_code": "PYGANINI012",
        "wrapper_phase": "route-import",
        "wrapper_path": "app/routes/users/route.py",
        "wrapper_message": "cannot import route module 'app.routes.users.route'",
        "cause_present": True,
        "cause_is_runtime_error": True,
        "cause_type": "RuntimeError",
        "cause_message": "qualification import failure",
    }
    mismatches = [
        key
        for key, expected_value in expected.items()
        if value.get(key) != expected_value
    ]
    if mismatches:
        raise Finding(f"Q043 startup evidence disagreed for: {mismatches!r}")
    cause_traceback = value.get("cause_traceback")
    if not isinstance(cause_traceback, str):
        raise Finding("Q043 cause traceback is not text")
    if "app/routes/users/handlers.py" not in cause_traceback:
        raise Finding("Q043 cause traceback omitted the application handler path")
    if 'raise RuntimeError("qualification import failure")' not in cause_traceback:
        raise Finding("Q043 cause traceback omitted the application sentinel line")
    if not source_only_sentinel_absent:
        raise Finding("Q043 source-only commands executed the application sentinel")
    if not source_only_import_absent:
        raise Finding("Q043 source-only command imported application handler")
    if not generated_unchanged:
        raise Finding("Q043 changed generated source state")


def clean_candidate_mirror(root: Path) -> None:
    _run(
        ["git", "clean", "-ffdX"],
        cwd=root,
        failure=InfrastructureFailure,
    )
    status = _run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root,
        failure=InfrastructureFailure,
    )
    if status.stdout:
        raise InfrastructureFailure(
            "candidate mirror scenario cleanup left tracked or non-ignored changes"
        )


@contextmanager
def mirror_cleanup(root: Path) -> Generator[None]:
    try:
        yield
    except Exception as primary:
        try:
            clean_candidate_mirror(root)
        except (InfrastructureFailure, OSError) as cleanup_error:
            raise InfrastructureFailure(
                f"scenario failed: {primary}; mirror cleanup failed: {cleanup_error}"
            ) from primary
        raise
    else:
        clean_candidate_mirror(root)


@contextmanager
def _fixture(
    *, temporary_root: Path, wheel: Path, python_line: str
) -> Generator[FixtureEnvironment]:
    fixture_source = Path(__file__).resolve().parents[1] / "fixtures" / "refactor_app"
    with tempfile.TemporaryDirectory(
        prefix=f"fixture-{python_line}-", dir=temporary_root
    ) as temporary:
        root = Path(temporary) / "application"
        shutil.copytree(fixture_source, root)
        fixture_configuration = tomllib.loads(
            (root / "pyproject.toml").read_text(encoding="utf-8")
        )
        fixture_tool = fixture_configuration.get("tool")
        if not isinstance(fixture_tool, dict):
            raise InfrastructureFailure("refactor fixture is missing [tool.pyganini]")
        fixture_tool_configuration = cast(dict[str, object], fixture_tool)
        if not isinstance(fixture_tool_configuration.get("pyganini"), dict):
            raise InfrastructureFailure("refactor fixture is missing [tool.pyganini]")
        environment_root = Path(temporary) / "environment"
        _run(
            ["uv", "venv", "--python", python_line, environment_root],
            cwd=temporary_root,
            failure=InfrastructureFailure,
        )
        python = environment_root / "bin" / "python"
        _run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                python,
                wheel,
                "fastapi==0.141.1",
                "httpx==0.28.1",
                "httpx2==2.12.0",
                "mypy==2.3.1",
                "pyright==1.1.411",
            ],
            cwd=root,
            failure=InfrastructureFailure,
        )
        pyganini = environment_root / "bin" / "pyganini"
        yield FixtureEnvironment(root=root, python=python, pyganini=pyganini)


def _generate(fixture: FixtureEnvironment) -> None:
    _run([fixture.pyganini, "generate", "--app-root", fixture.root], cwd=fixture.root)


def _check(
    fixture: FixtureEnvironment, *, allowed: tuple[int, ...] = (0,)
) -> subprocess.CompletedProcess[bytes]:
    return _run(
        [fixture.pyganini, "check", "--app-root", fixture.root],
        cwd=fixture.root,
        allowed=allowed,
    )


def _parse_routes_json(result: subprocess.CompletedProcess[bytes]) -> dict[str, object]:
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise Finding(f"route inventory is not JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise Finding("route inventory omitted the pyganini.routes.v1 schema")
    value = cast(dict[str, object], parsed)
    if value.get("schema") != "pyganini.routes.v1":
        raise Finding("route inventory omitted the pyganini.routes.v1 schema")
    return value


def _routes_json_result(
    fixture: FixtureEnvironment,
) -> tuple[dict[str, object], subprocess.CompletedProcess[bytes]]:
    result = _run(
        [fixture.pyganini, "routes", "list", "--app-root", fixture.root, "--json"],
        cwd=fixture.root,
    )
    value = _parse_routes_json(result)
    return value, result


def _routes_json(fixture: FixtureEnvironment) -> dict[str, object]:
    value, _ = _routes_json_result(fixture)
    return value


def _q043_source_command(
    fixture: FixtureEnvironment, arguments: Sequence[str | Path]
) -> subprocess.CompletedProcess[bytes]:
    return _run(
        [
            fixture.python,
            "-B",
            "-c",
            _Q043_IMPORT_TRACE_SCRIPT,
            _Q043_HANDLER_MODULE,
            fixture.pyganini,
            *arguments,
        ],
        cwd=fixture.root,
    )


def _run_typing(fixture: FixtureEnvironment) -> None:
    typing_environment = {"VIRTUAL_ENV": str(fixture.python.parents[1])}
    _run(
        [fixture.python, "-m", "mypy", "app"],
        cwd=fixture.root,
        environment=typing_environment,
    )
    _run(
        [
            fixture.python,
            "-m",
            "pyright",
            "--pythonpath",
            fixture.python,
            "app",
        ],
        cwd=fixture.root,
        environment=typing_environment,
    )


_RUNTIME_SCRIPT = """
import asyncio
from app._pyganini.asgi import router

async def request(path):
    messages = []
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "GET", "scheme": "http", "path": path,
        "raw_path": path.encode(), "query_string": b"", "root_path": "",
        "headers": [], "client": None, "server": None,
    }
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    async def send(message):
        messages.append(message)
    await router(scope, receive, send)
    return messages

def body(messages):
    return b"".join(message.get("body", b"") for message in messages)

messages = asyncio.run(request(PATH))
assert messages[0]["status"] == 200
assert EXPECTED in body(messages)
"""


def _runtime_request(fixture: FixtureEnvironment, path: str, expected: bytes) -> None:
    script = f"PATH = {path!r}\nEXPECTED = {expected!r}\n{_RUNTIME_SCRIPT}"
    _run([fixture.python, "-c", script], cwd=fixture.root)


def _q001(_: argparse.Namespace) -> None:
    print("candidate identity and prerequisite capture completed by the parent runner")


def _q010(arguments: argparse.Namespace) -> None:
    root = arguments.candidate_root
    with mirror_cleanup(root):
        _run(["uv", "lock", "--check"], cwd=root, failure=InfrastructureFailure)
        _run(
            ["uv", "sync", "--locked", "--all-groups", "--python", "3.14"],
            cwd=root,
            failure=InfrastructureFailure,
        )
        commands = (
            [
                "uv",
                "run",
                "--locked",
                "--python",
                "3.14",
                "ruff",
                "format",
                "--check",
                ".",
            ],
            ["uv", "run", "--locked", "--python", "3.14", "ruff", "check", "."],
            ["uv", "run", "--locked", "--python", "3.14", "mypy", "src/pyganini"],
            [
                "uv",
                "run",
                "--locked",
                "--python",
                "3.14",
                "pyright",
                "src/pyganini",
            ],
            [
                "uv",
                "run",
                "--locked",
                "--python",
                "3.14",
                "pytest",
                "-q",
                "tests/test_csrf_typing.py",
                "tests/test_sse_typing.py",
                "tests/test_assets.py::test_generated_asset_consumers_are_checked_by_both_type_checkers",
            ],
            [
                "uv",
                "run",
                "--locked",
                "--python",
                "3.14",
                "pytest",
                "-q",
                "tests/test_packaging.py",
                "tests/test_package_install.py",
            ],
        )
        failed_commands: list[str] = []
        for command in commands:
            completed = _run(command, cwd=root, allowed=(0, 1))
            if completed.returncode != 0:
                failed_commands.append(shlex.join(command))
        distribution = arguments.temporary_root / "q010-dist"
        distribution.mkdir()
        built = _run(
            ["uv", "build", "--out-dir", distribution], cwd=root, allowed=(0, 1)
        )
        if built.returncode != 0:
            failed_commands.append("uv build --out-dir <qualification-temp>/q010-dist")
        if (
            len(tuple(distribution.glob("*.whl"))) != 1
            or len(tuple(distribution.glob("*.tar.gz"))) != 1
        ):
            raise Finding(
                "root build did not produce one wheel and one source distribution"
            )
        if failed_commands:
            raise Finding(
                "Q010 root validation commands failed: " + "; ".join(failed_commands)
            )


def _q011(arguments: argparse.Namespace) -> None:
    root = arguments.candidate_root
    with mirror_cleanup(root):
        _run(
            ["uv", "sync", "--locked", "--all-groups", "--python", "3.13"],
            cwd=root,
            failure=InfrastructureFailure,
        )
        _run(
            ["uv", "run", "--locked", "--python", "3.13", "pytest", "-q"],
            cwd=root,
        )


def _q020(arguments: argparse.Namespace) -> None:
    with _fixture(
        temporary_root=arguments.temporary_root,
        wheel=arguments.wheel,
        python_line="3.14",
    ) as fixture:
        _generate(fixture)
        _check(fixture)
        inventory = _routes_json(fixture)
        if not inventory.get("routes"):
            raise Finding("clean fixture route inventory is empty")
        before = _snapshot_generated(fixture.root)
        _generate(fixture)
        if _snapshot_generated(fixture.root) != before:
            raise Finding("repeat fixture generation changed generated bytes")
        _run_typing(fixture)
        _runtime_request(fixture, "/users", b"<h1>Users</h1>")


def _q030(arguments: argparse.Namespace) -> None:
    with _fixture(
        temporary_root=arguments.temporary_root,
        wheel=arguments.wheel,
        python_line="3.14",
    ) as fixture:
        _generate(fixture)
        before = _snapshot_generated(fixture.root)
        settings = fixture.root / "app" / "routes" / "settings"
        settings.mkdir()
        (settings / "__init__.py").write_text("", encoding="ascii")
        (settings / "handlers.py").write_text(
            "from pyganini import Page, PageMetadata\n"
            "from starlette.requests import Request\n"
            "def page(_: Request) -> Page:\n"
            "    return Page(context={}, metadata=PageMetadata(title='Settings'), "
            "layout={'section': 'settings'})\n",
            encoding="ascii",
        )
        (settings / "route.py").write_text(
            "from pyganini import route\nfrom .handlers import page\n"
            "Route = route(page=page, template='page.jinja')\n",
            encoding="ascii",
        )
        (settings / "page.jinja").write_text("<h1>Settings</h1>\n", encoding="ascii")
        stale = _check(fixture, allowed=(1,))
        _assert_text(stale.stderr + stale.stdout, "stale")
        if _snapshot_generated(fixture.root) != before:
            raise Finding("stale check changed generated bytes")
        _generate(fixture)
        _check(fixture)
        inventory = json.dumps(_routes_json(fixture), sort_keys=True)
        if '"/settings"' not in inventory or "settings" not in inventory:
            raise Finding("settings route or helper is absent after generation")
        typing_usage = fixture.root / "app" / "typing_usage.py"
        typing_usage.write_text(
            typing_usage.read_text(encoding="ascii")
            + "settings_path: str = urls.settings.path\n",
            encoding="ascii",
        )
        _run_typing(fixture)
        _runtime_request(fixture, "/settings", b"<h1>Settings</h1>")


def _q031(arguments: argparse.Namespace) -> None:
    with _fixture(
        temporary_root=arguments.temporary_root,
        wheel=arguments.wheel,
        python_line="3.14",
    ) as fixture:
        _generate(fixture)
        before = _snapshot_generated(fixture.root)
        users = fixture.root / "app" / "routes" / "users"
        source = users / "by_user_id"
        destination = users / "by_account_id"
        source.rename(destination)
        for path in destination.rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="ascii")
                path.write_text(
                    text.replace("user_id", "account_id").replace(
                        "user-id", "account-id"
                    ),
                    encoding="ascii",
                )
        typing_usage = fixture.root / "app" / "typing_usage.py"
        typing_usage.write_text(
            typing_usage.read_text(encoding="ascii").replace(
                "by_user_id", "by_account_id"
            ),
            encoding="ascii",
        )
        stale = _check(fixture, allowed=(1,))
        _assert_text(stale.stderr + stale.stdout, "stale")
        if _snapshot_generated(fixture.root) != before:
            raise Finding("dynamic rename stale check changed generated bytes")
        _generate(fixture)
        _check(fixture)
        generated_urls = (fixture.root / "app" / "_pyganini" / "urls.py").read_text(
            encoding="ascii"
        )
        if "by_user_id" in generated_urls or "by_account_id" not in generated_urls:
            raise Finding(
                "dynamic helper rename left an old surface or omitted the new surface"
            )
        inventory = json.dumps(_routes_json(fixture), sort_keys=True)
        if "account_id" not in inventory or "user_id" in inventory:
            raise Finding("dynamic route inventory did not adopt account_id")
        _run_typing(fixture)
        _runtime_request(fixture, "/users/42", b'data-account-id="42"')


def _assert_failed_without_generation_change(
    fixture: FixtureEnvironment, before: dict[str, tuple[int, str]], *evidence: str
) -> subprocess.CompletedProcess[bytes]:
    result = _run(
        [fixture.pyganini, "generate", "--app-root", fixture.root],
        cwd=fixture.root,
        allowed=(1,),
    )
    _assert_text(result.stderr + result.stdout, *evidence)
    if _snapshot_generated(fixture.root) != before:
        raise Finding("failed generation changed generated products")
    return result


def _q040(arguments: argparse.Namespace) -> None:
    with _fixture(
        temporary_root=arguments.temporary_root,
        wheel=arguments.wheel,
        python_line="3.14",
    ) as fixture:
        _generate(fixture)
        before = _snapshot_generated(fixture.root)
        route_path = fixture.root / "app" / "routes" / "users" / "route.py"
        source = route_path.read_text(encoding="ascii")
        route_path.write_text(
            source.replace(
                'actions=(action("POST", "/save", save),),',
                "actions=("
                'action("POST", "/save", save), '
                'action("POST", "/save", save)),',
            ),
            encoding="ascii",
        )
        _assert_failed_without_generation_change(
            fixture, before, "PYGANINI011", "normalized action POST /save"
        )
    with _fixture(
        temporary_root=arguments.temporary_root,
        wheel=arguments.wheel,
        python_line="3.14",
    ) as fixture:
        _generate(fixture)
        before = _snapshot_generated(fixture.root)
        users = fixture.root / "app" / "routes" / "users"
        shutil.copytree(users / "by_user_id", users / "by_account_id")
        _assert_failed_without_generation_change(
            fixture, before, "PYGANINI011", "overlaps"
        )


def _q041(arguments: argparse.Namespace) -> None:
    with _fixture(
        temporary_root=arguments.temporary_root,
        wheel=arguments.wheel,
        python_line="3.14",
    ) as fixture:
        _generate(fixture)
        before = _snapshot_generated(fixture.root)
        handlers = fixture.root / "app" / "routes" / "handlers.py"
        handlers.write_text(
            handlers.read_text(encoding="ascii")
            + '\nraise RuntimeError("qualification static import sentinel")\n',
            encoding="ascii",
        )
        route_path = fixture.root / "app" / "routes" / "route.py"
        route_path.write_text(
            "from pyganini import route\nfrom .handlers import page\n"
            "OPTIONS = {'page': page, 'template': 'page.jinja'}\n"
            "Route = route(**OPTIONS)\n",
            encoding="ascii",
        )
        result = _assert_failed_without_generation_change(
            fixture, before, "PYGANINI010", "route.py", "keyword"
        )
        _assert_text_absent(
            result.stderr + result.stdout,
            "qualification static import sentinel",
        )


def _q042(arguments: argparse.Namespace) -> None:
    with _fixture(
        temporary_root=arguments.temporary_root,
        wheel=arguments.wheel,
        python_line="3.14",
    ) as fixture:
        _generate(fixture)
        before = _snapshot_generated(fixture.root)
        (fixture.root / "app" / "routes" / "users" / "page.jinja").unlink()
        commands: tuple[tuple[str, list[str | Path]], ...] = (
            ("generate", [fixture.pyganini, "generate", "--app-root", fixture.root]),
            ("check", [fixture.pyganini, "check", "--app-root", fixture.root]),
            (
                "routes list --json",
                [
                    fixture.pyganini,
                    "routes",
                    "list",
                    "--app-root",
                    fixture.root,
                    "--json",
                ],
            ),
        )
        for command_name, command in commands:
            try:
                result = _run(command, cwd=fixture.root, allowed=(0, 1))
            finally:
                if _snapshot_generated(fixture.root) != before:
                    raise Finding(f"Q042 {command_name} changed generated products")
            _assert_q042_command_result(
                result,
                command_name=command_name,
                generated_unchanged=True,
            )


def _q043(arguments: argparse.Namespace) -> None:
    with _fixture(
        temporary_root=arguments.temporary_root,
        wheel=arguments.wheel,
        python_line="3.14",
    ) as fixture:
        _generate(fixture)
        with generated_products_unchanged(fixture.root, "Q043"):
            before = _snapshot_generated(fixture.root)
            handlers = fixture.root / "app" / "routes" / "users" / "handlers.py"
            handlers.write_text(
                handlers.read_text(encoding="ascii")
                + '\nraise RuntimeError("qualification import failure")\n',
                encoding="ascii",
            )
            sentinel = "qualification import failure"
            checked = _q043_source_command(
                fixture, ["check", "--app-root", fixture.root]
            )
            inventory_result = _q043_source_command(
                fixture,
                ["routes", "list", "--app-root", fixture.root, "--json"],
            )
            inventory = _parse_routes_json(inventory_result)
            source_only_sentinel_absent = (
                sentinel.encode() not in checked.stdout + checked.stderr
                and sentinel.encode()
                not in inventory_result.stdout + inventory_result.stderr
                and sentinel not in json.dumps(inventory, sort_keys=True)
            )
            import_trace_marker = (
                _Q043_IMPORT_TRACE_PREFIX + _Q043_HANDLER_MODULE
            ).encode()
            source_only_import_absent = (
                import_trace_marker not in checked.stderr
                and import_trace_marker not in inventory_result.stderr
            )
            script = """
import json
import traceback
try:
    import app._pyganini.asgi
except RuntimeError as error:
    cause = error.__cause__
    print(json.dumps({
        "startup_raised": True,
        "wrapper_type": type(error).__name__,
        "wrapper_code": getattr(error, "code", None),
        "wrapper_phase": getattr(error, "phase", None),
        "wrapper_path": getattr(error, "path", None),
        "wrapper_message": str(error),
        "cause_present": cause is not None,
        "cause_is_runtime_error": type(cause) is RuntimeError,
        "cause_type": None if cause is None else type(cause).__name__,
        "cause_message": None if cause is None else str(cause),
        "cause_traceback": "" if cause is None else "".join(
            traceback.format_exception(cause)
        ),
    }, sort_keys=True))
else:
    print(json.dumps({"startup_raised": False}, sort_keys=True))
"""
            observed = _run([fixture.python, "-c", script], cwd=fixture.root)
            try:
                observation = json.loads(observed.stdout)
            except json.JSONDecodeError as error:
                raise Finding(
                    f"Q043 startup observation is not JSON: {error}"
                ) from error
            _assert_q043_observation(
                observation,
                source_only_sentinel_absent=source_only_sentinel_absent,
                source_only_import_absent=source_only_import_absent,
                generated_unchanged=_snapshot_generated(fixture.root) == before,
            )


def _q044(arguments: argparse.Namespace) -> None:
    with _fixture(
        temporary_root=arguments.temporary_root,
        wheel=arguments.wheel,
        python_line="3.14",
    ) as fixture:
        _generate(fixture)
        with generated_products_unchanged(fixture.root, "Q044 callback failure"):
            callback_script = """
import asyncio
from starlette.responses import PlainTextResponse
from app._pyganini.asgi import create_router

seen = []
def callback(request, error):
    seen.append(error)
    response = PlainTextResponse(
        "presented", status_code=500, headers={"X-Qualification":"callback"}
    )
    return response

async def run():
    messages = []
    scope = {"type":"http","asgi":{"version":"3.0"},"http_version":"1.1",
             "method":"GET","scheme":"http","path":"/problem","raw_path":b"/problem",
             "query_string":b"","root_path":"","headers":[],"client":None,"server":None}
    async def receive():
        return {"type":"http.request","body":b"","more_body":False}
    async def send(message): messages.append(message)
    try:
        await create_router(error_handler=callback)(scope, receive, send)
    except RuntimeError as error:
        assert str(error) == "qualification request failure"
    else:
        raise AssertionError("request failure was not re-raised")
    assert len(seen) == 1
    assert messages[0]["status"] == 500
    assert dict(messages[0]["headers"])[b"x-qualification"] == b"callback"
    assert b"".join(message.get("body", b"") for message in messages) == b"presented"
asyncio.run(run())
"""
            _run([fixture.python, "-c", callback_script], cwd=fixture.root)
        handlers = fixture.root / "app" / "routes" / "problem" / "handlers.py"
        handlers.write_text(
            "from starlette.requests import Request\n"
            "from starlette.responses import Response\n"
            "class Started(Response):\n"
            "    async def __call__(self, scope, receive, send):\n"
            "        await send({'type':'http.response.start',"
            "'status':200,'headers':[]})\n"
            "        raise RuntimeError('qualification post-start failure')\n"
            "def page(_: Request) -> Response:\n"
            "    return Started()\n",
            encoding="ascii",
        )
        with generated_products_unchanged(fixture.root, "Q044 post-start failure"):
            post_start_script = """
import asyncio
from starlette.responses import PlainTextResponse
from app._pyganini.asgi import create_router

seen = []
def callback(request, error):
    seen.append(error)
    return PlainTextResponse("unexpected", status_code=500)

async def run():
    messages = []
    scope = {"type":"http","asgi":{"version":"3.0"},"http_version":"1.1",
             "method":"GET","scheme":"http","path":"/problem",
             "raw_path":b"/problem","query_string":b"","root_path":"",
             "headers":[],"client":None,"server":None}
    async def receive():
        return {"type":"http.request","body":b"","more_body":False}
    async def send(message): messages.append(message)
    try:
        await create_router(error_handler=callback)(scope, receive, send)
    except RuntimeError as error:
        assert str(error) == "qualification post-start failure"
    else:
        raise AssertionError("post-start failure was not re-raised")
    assert seen == []
    assert messages == [
        {"type":"http.response.start","status":200,"headers":[]}
    ]
asyncio.run(run())
"""
            _run([fixture.python, "-c", post_start_script], cwd=fixture.root)


def _q050(arguments: argparse.Namespace) -> None:
    with _fixture(
        temporary_root=arguments.temporary_root,
        wheel=arguments.wheel,
        python_line="3.14",
    ) as fixture:
        _generate(fixture)
        script = """
from fastapi import FastAPI
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.testclient import TestClient
from app._pyganini.asgi import create_router, router

async def health(request): return JSONResponse({"status":"ok"})
direct = TestClient(router)
assert direct.get("/users").status_code == 200
starlette_host = Starlette(
    routes=[Route("/health", health), Mount("/", app=create_router())]
)
starlette_host.state.owner = "application"
with TestClient(starlette_host, root_path="/root") as client:
    assert client.get("/health").json() == {"status":"ok"}
    assert client.get("/users").status_code == 200
    assert starlette_host.state.owner == "application"
prefixed = Starlette(routes=[Mount("/html", app=create_router())])
with TestClient(prefixed) as client:
    assert client.get("/html/users").status_code == 200
fastapi_host = FastAPI()
fastapi_host.add_api_route("/api/health", lambda: {"status":"ok"})
fastapi_host.mount("/html", create_router())
with TestClient(fastapi_host) as client:
    assert client.get("/api/health").json() == {"status":"ok"}
    assert client.get("/html/users").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/health" in paths
    assert all(not path.startswith("/html") for path in paths)
"""
        _run([fixture.python, "-c", script], cwd=fixture.root)
    root = arguments.candidate_root
    with mirror_cleanup(root):
        _run(
            [
                "uv",
                "run",
                "--locked",
                "--python",
                "3.14",
                "pytest",
                "-q",
                "tests/test_dispatch_generation.py",
                "-k",
                "starlette_host or fastapi or root_path or lifespan",
            ],
            cwd=root,
        )


def _q060(arguments: argparse.Namespace) -> None:
    root = arguments.candidate_root
    example = root / "examples" / "full_feature"
    browser_root = arguments.temporary_root / "q060-playwright"
    browser_environment = {"PLAYWRIGHT_BROWSERS_PATH": str(browser_root)}
    with mirror_cleanup(root):
        _run(
            ["uv", "sync", "--locked", "--all-groups", "--python", "3.14"],
            cwd=example,
            failure=InfrastructureFailure,
        )
        before = _snapshot_full_feature_products(example)
        commands_314 = (
            ["uv", "run", "--locked", "--python", "3.14", "pyganini", "check"],
            [
                "uv",
                "run",
                "--locked",
                "--python",
                "3.14",
                "pyganini",
                "assets",
                "check",
            ],
            [
                "uv",
                "run",
                "--locked",
                "--python",
                "3.14",
                "ruff",
                "format",
                "--check",
                ".",
            ],
            ["uv", "run", "--locked", "--python", "3.14", "ruff", "check", "."],
            ["uv", "run", "--locked", "--python", "3.14", "mypy", "app", "tests"],
            ["uv", "run", "--locked", "--python", "3.14", "pyright", "app", "tests"],
        )
        for command in commands_314:
            _run(command, cwd=example)
        _run(
            [
                "uv",
                "run",
                "--locked",
                "--python",
                "3.14",
                "playwright",
                "install",
                "chromium",
            ],
            cwd=example,
            failure=InfrastructureFailure,
            environment=browser_environment,
        )
        _run(
            [
                "uv",
                "run",
                "--locked",
                "--python",
                "3.14",
                "pytest",
                "-q",
                "tests",
                "--ignore=tests/test_browser.py",
            ],
            cwd=example,
        )
        run_full_feature_browser_tests(example, browser_environment)
        _run(
            ["uv", "run", "--locked", "--python", "3.14", "pyganini", "generate"],
            cwd=example,
        )
        if _snapshot_full_feature_products(example) != before:
            raise Finding("full-feature repeat generation changed committed products")
        _run(
            ["uv", "sync", "--locked", "--all-groups", "--python", "3.13"],
            cwd=example,
            failure=InfrastructureFailure,
        )
        commands_313 = (
            ["uv", "run", "--locked", "--python", "3.13", "pyganini", "check"],
            [
                "uv",
                "run",
                "--locked",
                "--python",
                "3.13",
                "pyganini",
                "assets",
                "check",
            ],
            ["uv", "run", "--locked", "--python", "3.13", "mypy", "app", "tests"],
            ["uv", "run", "--locked", "--python", "3.13", "pyright", "app", "tests"],
            [
                "uv",
                "run",
                "--locked",
                "--python",
                "3.13",
                "pytest",
                "-q",
                "tests",
                "--ignore=tests/test_browser.py",
            ],
        )
        for command in commands_313:
            _run(command, cwd=example)


def run_client_island_check(root: Path) -> None:
    _run(
        ["bash", "scripts/check-client-islands.sh"],
        cwd=root,
        failure=InfrastructureFailure,
    )


def run_full_feature_browser_tests(root: Path, environment: dict[str, str]) -> None:
    _run(
        [
            "uv",
            "run",
            "--locked",
            "--python",
            "3.14",
            "pytest",
            "-q",
            "tests/test_browser.py",
        ],
        cwd=root,
        failure=InfrastructureFailure,
        environment=environment,
    )


def _q070(arguments: argparse.Namespace) -> None:
    root: Path = arguments.candidate_root
    with mirror_cleanup(root):
        run_client_island_check(root)


def audit_candidate_mirror(root: Path) -> None:
    status = _run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root,
        failure=InfrastructureFailure,
    )
    if status.stdout:
        raise InfrastructureFailure("candidate mirror is dirty at final cleanup check")
    ignored = _run(
        ["git", "status", "--porcelain=v1", "--ignored", "--untracked-files=all"],
        cwd=root,
        failure=InfrastructureFailure,
    )
    ignored_lines = [
        line for line in ignored.stdout.splitlines() if line.startswith(b"!! ")
    ]
    if ignored_lines:
        raise InfrastructureFailure(
            f"candidate mirror retains ignored products: {ignored_lines[:5]!r}"
        )
    print("candidate mirror is clean and contains no ignored scenario products")


def _q080(arguments: argparse.Namespace) -> None:
    audit_candidate_mirror(arguments.candidate_root)


_HANDLERS = {
    "Q001": _q001,
    "Q010": _q010,
    "Q011": _q011,
    "Q020": _q020,
    "Q030": _q030,
    "Q031": _q031,
    "Q040": _q040,
    "Q041": _q041,
    "Q042": _q042,
    "Q043": _q043,
    "Q044": _q044,
    "Q050": _q050,
    "Q060": _q060,
    "Q070": _q070,
    "Q080": _q080,
}


def _parse_args(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True, choices=tuple(_HANDLERS))
    parser.add_argument("--candidate-root", required=True, type=Path)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--temporary-root", required=True, type=Path)
    parser.add_argument("--python", action="append", dest="python_lines", default=[])
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    parsed = _parse_args(arguments)
    try:
        _HANDLERS[parsed.scenario](parsed)
    except Finding as error:
        print(f"product finding: {error}", file=sys.stderr)
        return 10
    except (InfrastructureFailure, OSError) as error:
        print(f"infrastructure error: {error}", file=sys.stderr)
        return 20
    except AssertionError as error:
        print(f"product finding: {error}", file=sys.stderr)
        return 10
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
