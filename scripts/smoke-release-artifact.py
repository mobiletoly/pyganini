from __future__ import annotations

import argparse
import asyncio
import importlib
import os
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path


def _write(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="ascii")


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def _application(root: Path) -> None:
    _write(root / "pyproject.toml", "[tool.pyganini]\n")
    _write(root / "app" / "__init__.py")
    _write(root / "app" / "routes" / "__init__.py")
    _write(root / "app" / "routes" / "layout.py")
    _write(
        root / "app" / "routes" / "layout.jinja",
        "<html><title>{{ metadata.title }}</title>"
        "<body data-section='{{ layout.section }}'>"
        "<a href='{{ layout.home_url }}'>Home</a>{{ child }}</body></html>\n",
    )
    _write(
        root / "app" / "routes" / "handlers.py",
        "from pyganini import Page, PageMetadata\n"
        "from starlette.requests import Request\n"
        "from app._pyganini.urls import urls\n"
        "def page(request: Request) -> Page:\n"
        "    app_urls = urls.with_base_path(request.scope.get('root_path', ''))\n"
        "    return Page(context={'user_ids': ('ada', 'grace'), "
        "'urls': app_urls}, metadata=PageMetadata(title='Users'), "
        "layout={'home_url': app_urls.root.path, 'section': 'home'})\n",
    )
    _write(
        root / "app" / "routes" / "route.py",
        "from pyganini import route\n"
        "from .handlers import page\n"
        "Route = route(page=page, template='page.jinja')\n",
    )
    _write(
        root / "app" / "routes" / "page.jinja",
        "<main>{% for user_id in user_ids %}"
        "<a href='{{ urls.users.by_user_id(user_id).path }}'>{{ user_id }}</a>"
        "{% endfor %}</main>\n",
    )
    _write(root / "app" / "routes" / "users" / "__init__.py")
    _write(root / "app" / "routes" / "users" / "by_user_id" / "__init__.py")
    _write(
        root / "app" / "routes" / "users" / "by_user_id" / "handlers.py",
        "from pyganini import Page, PageMetadata\n"
        "from starlette.requests import Request\n"
        "from app._pyganini.urls import urls\n"
        "def page(request: Request) -> Page:\n"
        "    app_urls = urls.with_base_path(request.scope.get('root_path', ''))\n"
        "    user_id = request.path_params['user_id']\n"
        "    return Page(context={'user_id': user_id}, "
        "metadata=PageMetadata(title=f'User {user_id}'), "
        "layout={'home_url': app_urls.root.path, 'section': 'users'})\n",
    )
    _write(
        root / "app" / "routes" / "users" / "by_user_id" / "route.py",
        "from pyganini import route\n"
        "from .handlers import page\n"
        "Route = route(page=page, template='page.jinja')\n",
    )
    _write(
        root / "app" / "routes" / "users" / "by_user_id" / "page.jinja",
        "<main data-user-id='{{ user_id }}'>User {{ user_id }}</main>\n",
    )


async def _request(
    router: object, path: str, *, root_path: str = ""
) -> tuple[int, bytes]:
    messages: list[dict[str, object]] = []
    request_available = True

    async def receive() -> dict[str, object]:
        nonlocal request_available
        if request_available:
            request_available = False
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": f"{root_path}{path}".encode("ascii"),
        "root_path": root_path,
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }
    await router(scope, receive, send)  # type: ignore[operator]
    start = next(
        message for message in messages if message["type"] == "http.response.start"
    )
    body = b"".join(
        message.get("body", b"")  # type: ignore[arg-type]
        for message in messages
        if message["type"] == "http.response.body"
    )
    return int(start["status"]), body


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-version", required=True)
    arguments = parser.parse_args()

    import pyganini

    assert pyganini.__file__ is not None
    assert version("pyganini") == arguments.expected_version
    cli_version = _run(
        [sys.executable, "-m", "pyganini", "--version"],
        cwd=Path.cwd(),
    )
    assert cli_version.stdout == f"pyganini {arguments.expected_version}\n"

    with tempfile.TemporaryDirectory(prefix="pyganini-release-smoke-") as value:
        root = Path(value)
        _application(root)
        _run([sys.executable, "-m", "pyganini", "generate"], cwd=root)
        _run([sys.executable, "-m", "pyganini", "check"], cwd=root)
        sys.path.insert(0, str(root))
        try:
            generated_urls = importlib.import_module("app._pyganini.urls")
            generated_asgi = importlib.import_module("app._pyganini.asgi")
            assert generated_urls.urls.root.path == "/"
            assert generated_urls.urls.users.by_user_id("ada").path == "/users/ada"
            root_status, root_body = asyncio.run(
                _request(generated_asgi.router, "/", root_path="/directory")
            )
            user_status, user_body = asyncio.run(
                _request(
                    generated_asgi.router,
                    "/users/ada",
                    root_path="/directory",
                )
            )
            assert root_status == 200
            assert b"href='/directory/'" in root_body
            assert b"href='/directory/users/ada'" in root_body
            assert b"data-section='home'" in root_body
            assert user_status == 200
            assert b"href='/directory/'" in user_body
            assert b"data-user-id='ada'" in user_body
            assert b"data-section='users'" in user_body
        finally:
            sys.path.remove(str(root))


if __name__ == "__main__":
    main()
