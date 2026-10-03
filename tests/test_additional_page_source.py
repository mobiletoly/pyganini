import threading
from collections.abc import Callable
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Mount
from starlette.testclient import TestClient
from test_dispatch_generation import _generated_module

from pyganini import (
    AdditionalPage,
    PageMetadata,
    TemplateInspectionMode,
)
from pyganini._cli import main
from pyganini._dispatch import DispatchError


def write(root: Path, name: str, value: str) -> None:
    path = root / "app/routes" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    for directory in [path.parent, *path.parent.parents]:
        if directory == root / "app":
            break
        (directory / "__init__.py").touch()
    path.write_text(value, encoding="ascii")


def test_source_is_only_called_on_router_miss_and_sync_work_is_offloaded(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    root = make_app(tmp_path / "application")
    write(
        root,
        "route.py",
        (
            "from pyganini import route\n"
            "from starlette.responses import PlainTextResponse\n"
            "def page(request): return PlainTextResponse('declared')\n"
            "Route = route(page=page)\n"
        ),
    )
    assert main(["generate", "--app-root", str(root)]) == 0
    calls: list[str] = []
    threads: list[int] = []

    def source(request: Request) -> AdditionalPage | None:
        calls.append(request.url.path)
        threads.append(threading.get_ident())
        return AdditionalPage("<b>trusted</b>", metadata=PageMetadata("<Title>"))

    with (
        _generated_module(root) as generated,
        TestClient(generated.create_router(additional_page_source=source)) as client,
    ):
        assert client.get("/").text == "declared"
        assert client.post("/").status_code == 405
        response = client.get("/privacy")
        assert response.text == "<b>trusted</b>"
        assert client.head("/privacy").content == b""
        assert calls == ["/privacy", "/privacy"]
        assert all(thread != threading.get_ident() for thread in threads)


def test_static_source_only_layouts_and_middleware_select_original_whole_prefix(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    root = make_app(tmp_path / "application")
    write(root, "layout.py", "LAYOUT = 'layout.jinja'\n")
    write(root, "layout.jinja", "<root>{{ metadata.title }}{{ child }}</root>")
    write(root, "privacy/layout.py", "LAYOUT = 'layout.jinja'\n")
    write(root, "privacy/layout.jinja", "<section>{{ child }}</section>")
    write(
        root,
        "privacy/middleware.py",
        (
            "from starlette.middleware import Middleware\n"
            "class Tag:\n"
            "    def __init__(self, app): self.app = app\n"
            "    async def __call__(self, scope, receive, send):\n"
            "        scope['tag'] = 'privacy'\n"
            "        scope['path'] = '/changed'\n"
            "        await self.app(scope, receive, send)\n"
            "MIDDLEWARE = (Middleware(Tag),)\n"
        ),
    )
    assert main(["generate", "--app-root", str(root)]) == 0

    def source(request: Request) -> AdditionalPage:
        return AdditionalPage(
            "<b>" + request.scope.get("tag", "none") + "</b>",
            metadata=PageMetadata("<Title>"),
        )

    with _generated_module(root) as generated:
        # Importing the default router does not load otherwise unused middleware.
        import sys

        assert "app.routes.privacy.middleware" not in sys.modules
        router = generated.create_router(
            additional_page_source=source,
            template_inspection=TemplateInspectionMode.COMMENTS,
        )
        host = Starlette(
            routes=[Mount("/pre", app=Starlette(routes=[Mount("/fix", app=router)]))]
        )
        with TestClient(host) as client:
            body = client.get("/pre/fix/privacy/deep").text
            assert "<section>" in body and "<b>privacy</b>" in body
            assert "&lt;Title&gt;" in body
            assert "kind=layout" in body
            assert "kind=page" not in body
            assert client.get("/pre%2Ffix/privacy/deep").text == body
            assert "<section>" not in client.get("/pre/fix/privacy-extra").text


@pytest.mark.parametrize("failure", ["source", "middleware", "decline"])
def test_source_error_callback_diagnostic_keeps_original_local_path(
    tmp_path: Path, make_app: Callable[..., Path], failure: str
) -> None:
    root = make_app(tmp_path / "application")
    write(
        root,
        "privacy/middleware.py",
        (
            "from starlette.middleware import Middleware\n"
            "class Change:\n"
            "    def __init__(self, app): self.app = app\n"
            "    async def __call__(self, scope, receive, send):\n"
            "        scope['path'] = '/changed'\n"
            + (
                "        raise RuntimeError('middleware failed')\n"
                if failure == "middleware"
                else "        await self.app(scope, receive, send)\n"
            )
            + "MIDDLEWARE = (Middleware(Change),)\n"
        ),
    )
    assert main(["generate", "--app-root", str(root)]) == 0
    with _generated_module(root) as generated:
        router = generated.create_router(
            additional_page_source=lambda request: (
                None if failure == "decline" else 123
            ),
            error_handler=lambda request, error: PlainTextResponse(
                "bad", status_code=400
            ),
        )
        with (
            TestClient(Starlette(routes=[Mount("/host", app=router)])) as client,
            pytest.raises(DispatchError) as result,
        ):
            client.get("/host/privacy/page")
        assert result.value.code == "PYGANINI019"
        assert "normalized path: /privacy/page" in result.value.details
        assert "generated source: app/_pyganini/asgi.py" in result.value.details


def test_source_decline_errors_and_direct_responses(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    root = make_app(tmp_path / "application")
    assert main(["generate", "--app-root", str(root)]) == 0
    calls: list[str] = []

    async def source(request: Request) -> AdditionalPage | Response | None:
        if request.url.path == "/direct":
            return PlainTextResponse("direct", headers={"x-source": "yes"})
        if request.url.path == "/error":
            raise HTTPException(403, headers={"x-required": "yes"})
        if request.url.path == "/handled":
            return AdditionalPage("handled", status_code=404)
        return None

    def error(request: Request, exc: Exception) -> Response:
        calls.append(request.url.path)
        return PlainTextResponse("error", status_code=exc.status_code)

    with (
        _generated_module(root) as generated,
        TestClient(
            generated.create_router(additional_page_source=source, error_handler=error)
        ) as client,
    ):
        assert client.get("/missing").status_code == 404
        assert client.get("/error").headers["x-required"] == "yes"
        assert client.get("/handled").text == "handled"
        assert client.get("/direct").headers["x-source"] == "yes"
        assert calls == ["/missing", "/error"]


def test_source_contract_diagnostic_and_immutable_value(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    root = make_app(tmp_path / "application")
    assert main(["generate", "--app-root", str(root)]) == 0
    with _generated_module(root) as generated:
        with pytest.raises(DispatchError) as invalid:
            generated.create_router(additional_page_source=lambda: None)
        assert invalid.value.code == "PYGANINI023"
        assert any(
            "test_source_contract_diagnostic" in detail
            for detail in invalid.value.details
        )
        with (
            TestClient(
                generated.create_router(additional_page_source=lambda request: "bad")
            ) as client,
            pytest.raises(DispatchError) as result,
        ):
            client.get("/miss")
        assert result.value.code == "PYGANINI023"
    layout = {"x": "before"}
    page = AdditionalPage("{{ untouched }}", layout=layout)
    layout["x"] = "after"
    assert page.layout["x"] == "before"
    with pytest.raises(TypeError):
        AdditionalPage(123)


def test_source_error_pages_use_only_live_root_layouts(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    from pyganini import Page

    root = make_app(tmp_path / "application")
    write(root, "layout.py", '"""Root layout."""\n')
    write(root, "layout.jinja", "<root>{{ child }}</root>")
    write(root, "privacy/layout.py", '"""Section layout."""\n')
    write(root, "privacy/layout.jinja", "<section>{{ child }}</section>")
    write(
        root,
        "route.py",
        (
            "from pyganini import route\nRoute = route(error_p"
            "age_template='error.jinja')\n"
        ),
    )
    write(root, "error.jinja", "failure")
    assert main(["generate", "--app-root", str(root)]) == 0

    def source(request: Request) -> None:
        raise HTTPException(403)

    def error(request: Request, exc: Exception) -> Page:
        return Page(status_code=403)

    with (
        _generated_module(root) as generated,
        TestClient(
            generated.create_router(additional_page_source=source, error_handler=error)
        ) as client,
    ):
        assert client.get("/privacy/deep").text == "<root>failure</root>"


def test_dynamic_ancestry_excluded_and_declared_404_never_resolves(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    root = make_app(tmp_path / "application")
    write(root, "item/by_id/layout.py", '"""Dynamic layout."""\n')
    write(root, "item/by_id/layout.jinja", "<dynamic>{{ child }}</dynamic>")
    write(
        root,
        "item/by_id/route.py",
        (
            "from pyganini import route\nfrom starlette.except"
            "ions import HTTPException\ndef page(request): rai"
            "se HTTPException(404)\nRoute = route(page=page)\n"
        ),
    )
    assert main(["generate", "--app-root", str(root)]) == 0
    calls: list[str] = []

    def source(request: Request) -> AdditionalPage:
        calls.append(request.url.path)
        return AdditionalPage("content")

    with (
        _generated_module(root) as generated,
        TestClient(
            Starlette(
                routes=[
                    Mount(
                        "/", app=generated.create_router(additional_page_source=source)
                    )
                ]
            )
        ) as client,
    ):
        assert client.get("/item/value").status_code == 404
        assert calls == []
        assert client.get("/item/value/missing").text == "content"
        assert calls == ["/item/value/missing"]


def test_source_render_failure_uses_existing_render_diagnostic(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    root = make_app(tmp_path / "application")
    write(root, "layout.py", '"""Root layout."""\n')
    write(root, "layout.jinja", "{{ layout.missing }}{{ child }}")
    assert main(["generate", "--app-root", str(root)]) == 0
    with (
        _generated_module(root) as generated,
        TestClient(
            generated.create_router(
                additional_page_source=lambda request: AdditionalPage("body")
            )
        ) as client,
        pytest.raises(DispatchError) as invalid,
    ):
        client.get("/privacy")
    assert invalid.value.code == "PYGANINI015"
    assert invalid.value.phase == "render-template"


def test_sync_source_keeps_asgi_loop_responsive(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    root = make_app(tmp_path / "application")
    write(
        root,
        "route.py",
        "from pyganini import route\n"
        "from starlette.responses import PlainTextResponse\n"
        "async def page(request): return PlainTextResponse('ready')\n"
        "Route = route(page=page)\n",
    )
    assert main(["generate", "--app-root", str(root)]) == 0
    entered, release = threading.Event(), threading.Event()

    def source(request: Request) -> AdditionalPage:
        entered.set()
        assert release.wait(5)
        return AdditionalPage("finished")

    with (
        _generated_module(root) as generated,
        TestClient(generated.create_router(additional_page_source=source)) as client,
        ThreadPoolExecutor(max_workers=2) as workers,
    ):
        waiting = workers.submit(client.get, "/slow")
        try:
            assert entered.wait(2)
            ready = workers.submit(client.get, "/")
            assert ready.result(timeout=2).text == "ready"
        finally:
            release.set()
        assert waiting.result(timeout=2).text == "finished"


def test_direct_streaming_head_and_post_start_error_do_not_reenter_hook(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    from collections.abc import AsyncIterator

    from starlette.responses import StreamingResponse

    root = make_app(tmp_path / "application")
    assert main(["generate", "--app-root", str(root)]) == 0
    callbacks: list[Exception] = []
    broken = RuntimeError("stream failed")

    async def source(request: Request) -> Response:
        async def body() -> AsyncIterator[bytes]:
            yield b"first"
            if request.url.path == "/broken":
                raise broken
            yield b"second"

        return StreamingResponse(body(), headers={"x-source": "stream"})

    def error(request: Request, exc: Exception) -> Response:
        callbacks.append(exc)
        return PlainTextResponse("failed", status_code=500)

    with (
        _generated_module(root) as generated,
        TestClient(
            generated.create_router(additional_page_source=source, error_handler=error)
        ) as client,
    ):
        assert client.get("/stream").text == "firstsecond"
        head = client.head("/stream")
        assert head.content == b"" and head.headers["x-source"] == "stream"
        with pytest.raises(RuntimeError) as invalid:
            client.get("/broken")
        assert invalid.value is broken
        assert callbacks == []


@pytest.mark.parametrize(
    "key",
    ["pyganini.additional_page_error_attempted", "pyganini.additional_page_path"],
)
def test_source_restores_preexisting_host_scope_state(
    tmp_path: Path, make_app: Callable[..., Path], key: str
) -> None:
    root = make_app(tmp_path / "application")
    assert main(["generate", "--app-root", str(root)]) == 0
    from starlette.types import Receive, Scope, Send

    original = object()
    observed: list[object] = []
    with _generated_module(root) as generated:
        router = generated.create_router(additional_page_source=lambda _: None)

        async def host(scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] != "http":
                await router(scope, receive, send)
                return
            scope[key] = original
            try:
                await router(scope, receive, send)
            finally:
                observed.append(scope.get(key))
                assert (
                    "pyganini.additional_page_path"
                    if key == "pyganini.additional_page_error_attempted"
                    else "pyganini.additional_page_error_attempted"
                ) not in scope

        with TestClient(host) as client:
            assert client.get("/missing").status_code == 404
    assert observed == [original]


def test_mounted_matches_are_terminal_and_miss_uses_only_live_owner_layouts(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    root = make_app(tmp_path / "application")
    write(root, "layout.py", "")
    write(root, "layout.jinja", "<root>{{ child }}</root>")
    write(root, "users/layout.py", "")
    write(root, "users/layout.jinja", "<owner>{{ child }}</owner>")
    write(
        root,
        "users/route.py",
        "from pyganini import route_mount\ndef create(request): return object()\n"
        "Route = route_mount(create=create, mount='directory')\n",
    )
    directory = root / "app/mounts/directory"
    directory.mkdir(parents=True)
    (directory.parent / "__init__.py").touch()
    (directory / "__init__.py").touch()
    (directory / "layout.py").touch()
    (directory / "layout.jinja").write_text("<mounted>{{ child }}</mounted>")
    (directory / "page.jinja").write_text("declared")
    (directory / "route.py").write_text(
        "from pyganini import route_kit, Page\n"
        "def page(kit, request): return Page(status_code=404)\n"
        "Route = route_kit(page=page, template='page.jinja')\n"
    )
    assert main(["generate", "--app-root", str(root)]) == 0
    calls: list[str] = []

    def source(request: Request) -> AdditionalPage:
        calls.append(request.url.path)
        return AdditionalPage("content")

    with (
        _generated_module(root) as generated,
        TestClient(generated.create_router(additional_page_source=source)) as client,
    ):
        assert client.get("/users").status_code == 404
        assert client.post("/users").status_code == 405
        assert calls == []
        assert (
            client.get("/users/unmatched").text == "<root><owner>content</owner></root>"
        )
        assert calls == ["/users/unmatched"]


def test_source_only_runtime_autoescape_validation_is_opt_in(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    from jinja2 import DictLoader, Environment, StrictUndefined

    root = make_app(tmp_path / "application")
    write(root, "privacy/layout.py", "")
    write(root, "privacy/layout.jinja", "{{ child }}")
    assert main(["generate", "--app-root", str(root)]) == 0
    environment = Environment(
        loader=DictLoader({}), autoescape=False, undefined=StrictUndefined
    )
    with _generated_module(root) as generated:
        generated.create_router(environment=environment)
        with pytest.raises(DispatchError) as invalid:
            generated.create_router(
                environment=environment,
                additional_page_source=lambda _: AdditionalPage("x"),
            )
        assert invalid.value.code == "PYGANINI015"
        assert "template: routes/privacy/layout.jinja" in invalid.value.details
