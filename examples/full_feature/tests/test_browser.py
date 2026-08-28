"""Local Chromium proof for the progressive-enhancement workflow."""

from __future__ import annotations

import hashlib
import re
import socket
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from importlib import resources
from urllib.parse import urlsplit

import pytest
import uvicorn
from playwright.sync_api import Error, Page, Route, sync_playwright
from pyganini import TemplateInspectionMode, sse
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from starlette.routing import Mount
from starlette.routing import Route as StarletteRoute

from app.main import create_app
from assets import pyganini_assets_gen as assets

_NO_RECONNECT = '{"sse":{"reconnect":false,"pauseOnBackground":false}}'
_MARKER_LITERALS = frozenset(
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/:._~{}"
)


def _encode_marker(value: str) -> str:
    return "".join(
        chr(byte) if byte in _MARKER_LITERALS else f"%{byte:02X}"
        for byte in value.encode("utf-8")
    )


def _inspection_pair(
    route: str,
    *,
    kind: str = "page",
    surface: str = "page",
    digest: str | None = None,
    encoded_route: str | None = None,
    encoded_label: str | None = None,
    identity_label: str | None = None,
    source: str = "app/routes/page.jinja:1:1",
) -> tuple[str, str, str]:
    evidence = (
        kind,
        surface,
        route,
        "routes/page.jinja",
        source,
        "none",
        "app/routes/route.py:1:1",
        "app.routes.handlers:page",
        "none",
    )
    marker_digest = hashlib.sha256()
    for value in (
        *evidence,
        *((identity_label,) if identity_label is not None else ()),
    ):
        raw = value.encode("utf-8")
        marker_digest.update(str(len(raw)).encode("ascii") + b":" + raw)
    identifier = "u" + (digest or marker_digest.hexdigest())
    values = tuple(_encode_marker(value) for value in evidence)
    if encoded_route is not None:
        values = (*values[:2], encoded_route, *values[3:])
    fields = " ".join(
        f"{name}={value}"
        for name, value in zip(
            (
                "kind",
                "surface",
                "route",
                "template",
                "source",
                "declaration",
                "owner",
                "handler",
                "mount",
            ),
            values,
            strict=True,
        )
    )
    if encoded_label is not None:
        fields += f" label={encoded_label}"
    return (
        f"<!--pyganini:start id={identifier} {fields}-->",
        f"<!--pyganini:end id={identifier}-->",
        identifier,
    )


def _record_page_error(errors: list[str]) -> Callable[[Error], None]:
    def record(error: Error) -> None:
        errors.append(str(error))

    return record


def _wait_for_contact_event(
    page: Page,
    *,
    local_requests: list[str],
    page_errors: list[str],
    console_errors: list[str],
) -> None:
    try:
        page.locator('[data-sse-event="contact"]').wait_for()
    except Error as error:
        target = page.locator("#named-sse-events")
        pytest.fail(
            "named SSE contact did not render: "
            f"target={target.evaluate('(element) => element.outerHTML')!r}; "
            f"requests={local_requests!r}; page_errors={page_errors!r}; "
            f"console_errors={console_errors!r}; cause={error}"
        )


async def _probe_page(_request: Request) -> HTMLResponse:
    core = assets.path("vendor/htmx.min.js", base_path="/directory")
    extension = assets.path("vendor/hx-sse.min.js", base_path="/directory")
    return HTMLResponse(
        f"""<!doctype html><html><body>
<div id="unnamed" hx-sse:connect="/probe-events/unnamed"
  hx-config='{_NO_RECONNECT}' hx-swap="innerHTML"></div>
<div id="named-without" hx-sse:connect="/probe-events/named"
  hx-config='{_NO_RECONNECT}' hx-swap="innerHTML"></div>
<div id="matching" hx-sse:connect="/probe-events/named"
  pyganini-sse-event="  contact  " hx-config='{_NO_RECONNECT}'
  hx-swap="innerHTML"></div>
<div id="repeated" hx-sse:connect="/probe-events/repeated"
  pyganini-sse-event="contact" hx-config='{_NO_RECONNECT}'
  hx-swap="beforeend"></div>
<div id="new-content" hx-sse:connect="/probe-events/new"
  hx-config='{_NO_RECONNECT}' hx-swap="innerHTML"></div>
<script src="{core}"></script>
<script src="{extension}"></script>
<script src="/probe-capture.js"></script>
<script src="/directory/pyganini/pyganini-sse-event.js"></script>
<script>
document.querySelector('#named-without').addEventListener(
  'contact', function (event) {{ this.dataset.domEvent = event.detail.data; }}
);
</script>
</body></html>"""
    )


async def _probe_capture(_request: Request) -> Response:
    return Response(
        "window.__pyganiniExtensions = {};"
        "var originalRegister = window.htmx.registerExtension;"
        "window.htmx.registerExtension = function (name, extension) {"
        "window.__pyganiniExtensions[name] = extension;"
        "return originalRegister.call(window.htmx, name, extension);"
        "};",
        media_type="text/javascript",
    )


async def _probe_events(request: Request) -> Response:
    case = request.path_params["case"]
    frames: dict[str, bytes] = {
        "unnamed": sse.encode_event(
            sse.Event(data='<span data-probe="unnamed">Unnamed swap</span>')
        ),
        "named": sse.encode_event(
            sse.Event(
                name="contact",
                data='<span data-probe="named">Named message</span>',
            )
        ),
        "repeated": (
            sse.encode_event(
                sse.Event(name="contact", data='<i data-probe="first">First</i>')
            )
            + sse.encode_event(
                sse.Event(name="contact", data='<i data-probe="second">Second</i>')
            )
        ),
        "new": sse.encode_event(
            sse.Event(
                data=(
                    '<div data-probe="new-child" '
                    'hx-sse:connect="/probe-events/nested" '
                    'pyganini-sse-event="contact" '
                    f"hx-config='{_NO_RECONNECT}' hx-swap=\"innerHTML\"></div>"
                )
            )
        ),
        "nested": sse.encode_event(
            sse.Event(
                name="contact",
                data='<span data-probe="nested">Nested named swap</span>',
            )
        ),
    }
    return Response(frames[case], media_type=sse.MEDIA_TYPE)


@contextmanager
def _local_server() -> Generator[str]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    host, port = listener.getsockname()
    server = uvicorn.Server(
        uvicorn.Config(
            Starlette(
                routes=[
                    StarletteRoute("/probe", _probe_page),
                    StarletteRoute("/probe-capture.js", _probe_capture),
                    StarletteRoute("/probe-events/{case}", _probe_events),
                    Mount(
                        "/directory",
                        app=create_app(
                            template_inspection=TemplateInspectionMode.OVERLAY
                        ),
                    ),
                ]
            ),
            log_config=None,
            access_log=False,
            log_level="error",
        )
    )
    failures: list[BaseException] = []

    def run() -> None:
        try:
            server.run(sockets=[listener])
        except BaseException as error:
            failures.append(error)

    thread = threading.Thread(target=run, name="pyganini-example-uvicorn")
    thread.start()
    deadline = time.monotonic() + 10
    try:
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        if failures:
            raise RuntimeError("example server failed to start") from failures[0]
        if not server.started:
            raise RuntimeError("example server did not start within 10 seconds")
        yield f"http://{host}:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        if thread.is_alive():
            pytest.fail("example server did not stop")
        listener.close()
        if failures:
            raise RuntimeError("example server failed") from failures[0]


def _inspector_source() -> str:
    return (
        resources.files("pyganini.browser")
        .joinpath("pyganini-template-inspector.js")
        .read_text(encoding="ascii")
    )


def test_template_inspector_discovers_document_level_root_layout() -> None:
    start, end, _ = _inspection_pair("/", kind="layout")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        try:
            page.set_content(
                f"{start}<!doctype html><html><body><p>root</p></body></html>{end}"
            )
            page.add_script_tag(content=_inspector_source())
            handle = page.locator('[aria-label="layout render unit details"]')
            handle.wait_for(timeout=2_000)
            handle.focus()
            assert page.get_by_text("route: /", exact=True).count() == 1
        finally:
            page.close()
            browser.close()


def test_template_inspector_rejects_noncanonical_and_inconsistent_markers() -> None:
    valid_start, valid_end, _ = _inspection_pair("/valid")
    digest_start, digest_end, _ = _inspection_pair("/digest", digest="0" * 64)
    escaped_start, escaped_end, _ = _inspection_pair(
        "/escaped", encoded_route="%2Fescaped"
    )
    surface_start, surface_end, _ = _inspection_pair(
        "/surface", kind="page", surface="fragment"
    )
    label_start, label_end, _ = _inspection_pair(
        "/label", encoded_label="%GG", identity_label="null"
    )
    html = "".join(
        (
            valid_start,
            "<span>valid</span>",
            valid_end,
            digest_start,
            "<span>bad digest</span>",
            digest_end,
            escaped_start,
            "<span>bad encoding</span>",
            escaped_end,
            surface_start,
            "<span>bad surface</span>",
            surface_end,
            label_start,
            "<span>bad label</span>",
            label_end,
        )
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        try:
            page.set_content(f"<!doctype html><html><body>{html}</body></html>")
            page.add_script_tag(content=_inspector_source())
            handles = page.locator('[aria-label$="render unit details"]')
            handles.first.wait_for(timeout=2_000)
            assert handles.count() == 1
            handles.first.focus()
            assert page.get_by_text("route: /valid", exact=True).count() == 1
        finally:
            page.close()
            browser.close()


def test_digest_invalid_unclosed_start_does_not_poison_valid_outer_pair() -> None:
    outer_start, outer_end, _ = _inspection_pair("/outer")
    invalid_start, _, _ = _inspection_pair("/invalid", digest="0" * 64)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        try:
            page.set_content(
                "<!doctype html><html><body>"
                f"{outer_start}<div>{invalid_start}<span>content</span></div>{outer_end}"
                "</body></html>"
            )
            page.add_script_tag(content=_inspector_source())
            handle = page.locator('[aria-label="page render unit details"]')
            handle.wait_for(timeout=2_000)
            assert handle.count() == 1
            handle.focus()
            assert page.get_by_text("route: /outer", exact=True).count() == 1
        finally:
            page.close()
            browser.close()


def test_template_inspector_next_selects_from_off_in_one_activation() -> None:
    start, end, _ = _inspection_pair("/one")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        try:
            page.set_content(
                f"<!doctype html><html><body>{start}<span>one</span>{end}</body></html>"
            )
            page.add_script_tag(content=_inspector_source())
            page.get_by_role("button", name="Off").click()
            page.get_by_role("button", name="Next render unit").click()
            page.get_by_text("route: /one", exact=True).wait_for(timeout=2_000)
        finally:
            page.close()
            browser.close()


def test_template_inspector_reexecution_before_body_owns_one_instance() -> None:
    start, end, _ = _inspection_pair("/one")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        try:
            page.evaluate(
                """(input) => {
                  document.body.remove();
                  window.eval(input.source);
                  window.eval(input.source);
                  const body = document.createElement('body');
                  body.innerHTML = input.markup;
                  document.documentElement.appendChild(body);
                  document.dispatchEvent(new Event('DOMContentLoaded'));
                }""",
                {
                    "source": _inspector_source(),
                    "markup": f"{start}<span>one</span>{end}",
                },
            )
            controls = page.locator('[aria-label="Pyganini template inspection"]')
            controls.first.wait_for(timeout=2_000)
            assert controls.count() == 1
        finally:
            page.close()
            browser.close()


def test_template_inspector_markerless_document_has_no_overlay() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        try:
            page.set_content("<!doctype html><html><body><p>plain</p></body></html>")
            page.add_script_tag(content=_inspector_source())
            page.wait_for_timeout(100)
            assert page.locator("[data-pyganini-template-inspector]").count() == 0
            assert (
                page.locator('[aria-label="Pyganini template inspection"]').count() == 0
            )
        finally:
            page.close()
            browser.close()


def test_template_inspector_invalid_only_document_has_no_overlay() -> None:
    start, end, _ = _inspection_pair("/invalid", digest="0" * 64)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        try:
            page.set_content(
                f"<!doctype html><html><body>{start}<p>invalid</p>{end}</body></html>"
            )
            page.add_script_tag(content=_inspector_source())
            page.wait_for_timeout(100)
            assert page.locator("[data-pyganini-template-inspector]").count() == 0
            assert (
                page.locator('[aria-label="Pyganini template inspection"]').count() == 0
            )
        finally:
            page.close()
            browser.close()


def test_template_inspector_zero_area_only_loses_and_restores_ui() -> None:
    start, end, identifier = _inspection_pair("/zero")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        try:
            page.set_content(f"<!doctype html><html><body>{start}{end}</body></html>")
            page.add_script_tag(content=_inspector_source())
            page.wait_for_timeout(100)
            assert page.locator("[data-pyganini-template-inspector]").count() == 0
            assert (
                page.locator('[aria-label="Pyganini template inspection"]').count() == 0
            )

            page.evaluate(
                """(identifier) => {
                  const comments = [];
                  const walker = document.createTreeWalker(
                    document, NodeFilter.SHOW_COMMENT
                  );
                  let node;
                  while ((node = walker.nextNode())) {
                    if (node.data.includes(identifier)) { comments.push(node); }
                  }
                  const content = document.createElement('span');
                  content.id = 'drawable-content';
                  content.textContent = 'now drawable';
                  comments[1].parentNode.insertBefore(content, comments[1]);
                }""",
                identifier,
            )
            controls = page.locator('[aria-label="Pyganini template inspection"]')
            controls.wait_for(timeout=2_000)
            page.get_by_role("button", name="Next render unit").click()
            page.get_by_text("route: /zero", exact=True).wait_for(timeout=2_000)

            page.locator("#drawable-content").evaluate("node => node.remove()")
            page.wait_for_function(
                """() => !document.querySelector(
                  '[aria-label="Pyganini template inspection"]'
                )""",
                timeout=2_000,
            )
            assert page.locator("[data-pyganini-template-inspector]").count() == 0

            page.evaluate(
                """(identifier) => {
                  const walker = document.createTreeWalker(
                    document, NodeFilter.SHOW_COMMENT
                  );
                  let end;
                  let node;
                  while ((node = walker.nextNode())) {
                    if (node.data === 'pyganini:end id=' + identifier) { end = node; }
                  }
                  const content = document.createElement('span');
                  content.textContent = 'drawable again';
                  end.parentNode.insertBefore(content, end);
                }""",
                identifier,
            )
            controls.wait_for(timeout=2_000)
            assert (
                page.get_by_role("button", name="Next render unit").get_attribute(
                    "aria-pressed"
                )
                == "false"
            )
        finally:
            page.close()
            browser.close()


def test_template_inspector_strict_stack_keeps_only_completed_valid_pairs() -> None:
    _, orphan_end, _ = _inspection_pair("/orphan-end")
    before_start, before_end, _ = _inspection_pair("/before-mismatch")
    outer_start, outer_end, _ = _inspection_pair("/mismatch-outer")
    inner_start, inner_end, _ = _inspection_pair("/mismatch-inner")
    after_start, after_end, _ = _inspection_pair("/after-mismatch")
    unclosed_start, _, _ = _inspection_pair("/unclosed")
    html = "".join(
        (
            orphan_end,
            before_start,
            "<span>before</span>",
            before_end,
            outer_start,
            inner_start,
            "<span>mismatched</span>",
            outer_end,
            inner_end,
            after_start,
            "<span>after</span>",
            after_end,
            unclosed_start,
            "<span>unclosed</span>",
        )
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        try:
            page.set_content(f"<!doctype html><html><body>{html}</body></html>")
            page.add_script_tag(content=_inspector_source())
            handles = page.locator('[aria-label="page render unit details"]')
            handles.first.wait_for(timeout=2_000)
            assert handles.count() == 2
            handles.nth(0).focus()
            page.get_by_text("route: /before-mismatch", exact=True).wait_for(
                timeout=2_000
            )
            handles.nth(1).focus()
            page.get_by_text("route: /after-mismatch", exact=True).wait_for(
                timeout=2_000
            )
            for rejected in (
                "/orphan-end",
                "/mismatch-outer",
                "/mismatch-inner",
                "/unclosed",
            ):
                assert page.get_by_text(f"route: {rejected}", exact=True).count() == 0
        finally:
            page.close()
            browser.close()


@pytest.mark.parametrize("operation", ["getItem", "setItem"])
def test_template_inspector_contains_local_storage_failures(operation: str) -> None:
    start, end, _ = _inspection_pair("/storage")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page_errors: list[str] = []
        page.on("pageerror", _record_page_error(page_errors))
        try:
            page.set_content(
                "<!doctype html><html><body>"
                f"{start}<span>unit</span>{end}</body></html>"
            )
            page.evaluate(
                """(operation) => {
                  const original = Storage.prototype[operation];
                  Storage.prototype[operation] = function () {
                    throw new Error(operation + ' failed');
                  };
                  window.__pyganiniRestoreStorage = () => {
                    Storage.prototype[operation] = original;
                  };
                }""",
                operation,
            )
            page.add_script_tag(content=_inspector_source())
            controls = page.locator('[aria-label="Pyganini template inspection"]')
            controls.wait_for(timeout=2_000)
            if operation == "setItem":
                page.get_by_role("button", name="Off").click()
                page.wait_for_timeout(100)
            assert page_errors == []
            assert controls.count() == 1
        finally:
            page.evaluate("() => window.__pyganiniRestoreStorage?.()")
            page.close()
            browser.close()


def test_template_inspector_all_view_copy_control_is_operable() -> None:
    start, end, _ = _inspection_pair("/copy")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        try:
            page.set_content(
                f"<!doctype html><html><body>{start}<p>copy</p>{end}</body></html>"
            )
            page.evaluate(
                """() => Object.defineProperty(navigator, 'clipboard', {
                  configurable: true,
                  value: {writeText(value) {
                    window.__pyganiniCopied = value;
                    return Promise.resolve();
                  }}
                })"""
            )
            page.add_script_tag(content=_inspector_source())
            handle = page.locator('[aria-label="page render unit details"]')
            handle.wait_for(timeout=2_000)
            handle.focus()
            copy = page.get_by_role("button", name="Copy source path")
            copy.focus()
            assert copy.count() == 1
            copy.click()
            page.wait_for_function(
                "() => window.__pyganiniCopied === 'app/routes/page.jinja:1:1'"
            )
        finally:
            page.close()
            browser.close()


@pytest.mark.parametrize("failure", ["rejected", "synchronous"])
def test_template_inspector_next_view_copy_failure_is_silent(failure: str) -> None:
    start, end, _ = _inspection_pair("/copy-failure")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page_errors: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        try:
            page.set_content(
                f"<!doctype html><html><body>{start}<p>copy</p>{end}</body></html>"
            )
            page.evaluate(
                """(failure) => Object.defineProperty(navigator, 'clipboard', {
                  configurable: true,
                  value: {writeText() {
                    if (failure === 'synchronous') { throw new Error('copy failed'); }
                    return Promise.reject(new Error('copy failed'));
                  }}
                })""",
                failure,
            )
            page.add_script_tag(content=_inspector_source())
            page.get_by_role("button", name="Next render unit").click()
            copy = page.get_by_role("button", name="Copy source path")
            copy.wait_for(timeout=2_000)
            copy.click()
            page.wait_for_timeout(100)
            assert page_errors == []
        finally:
            page.close()
            browser.close()


@pytest.mark.parametrize("view", ["all", "next"])
def test_template_inspector_copy_lookup_failure_is_silent(view: str) -> None:
    start, end, _ = _inspection_pair("/copy-lookup")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page_errors: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        try:
            page.set_content(
                f"<!doctype html><html><body>{start}<p>copy</p>{end}</body></html>"
            )
            page.evaluate(
                """() => Object.defineProperty(navigator, 'clipboard', {
                  configurable: true,
                  value: Object.defineProperty({}, 'writeText', {
                    get() { throw new Error('writeText lookup failed'); }
                  })
                })"""
            )
            page.add_script_tag(content=_inspector_source())
            if view == "next":
                page.get_by_role("button", name="Next render unit").click()
            else:
                page.locator('[aria-label="page render unit details"]').focus()
            page.wait_for_timeout(100)
            assert page_errors == []
            assert page.get_by_role("button", name="Copy source path").count() == 0
        finally:
            page.close()
            browser.close()


def test_template_inspector_cleanup_releases_every_owned_resource() -> None:
    start, end, _ = _inspection_pair("/cleanup")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        try:
            page.set_content(
                f"<!doctype html><html><body>{start}<p>cleanup</p>{end}</body></html>"
            )
            page.evaluate(
                """() => {
                  window.__pyganiniCleanupState = {
                    observerDisconnects: 0,
                    listenerAdds: 0,
                    listenerRemoves: 0,
                    cancelledFrames: [],
                    clearedTimeouts: []
                  };
                  const NativeObserver = window.MutationObserver;
                  window.MutationObserver = class extends NativeObserver {
                    disconnect() {
                      window.__pyganiniCleanupState.observerDisconnects += 1;
                      return super.disconnect();
                    }
                  };
                  const add = EventTarget.prototype.addEventListener;
                  const remove = EventTarget.prototype.removeEventListener;
                  const fromInspector = () => new Error().stack.includes(
                    'pyganini-template-inspector-cleanup-test.js'
                  );
                  EventTarget.prototype.addEventListener = function (...args) {
                    if (fromInspector()) {
                      window.__pyganiniCleanupState.listenerAdds += 1;
                    }
                    return add.apply(this, args);
                  };
                  EventTarget.prototype.removeEventListener = function (...args) {
                    if (fromInspector()) {
                      window.__pyganiniCleanupState.listenerRemoves += 1;
                    }
                    return remove.apply(this, args);
                  };
                }"""
            )
            page.add_script_tag(
                content=_inspector_source()
                + "\n//# sourceURL=pyganini-template-inspector-cleanup-test.js"
            )
            page.wait_for_timeout(100)
            assert page.evaluate(
                "() => !!document.querySelector("
                "'[aria-label=\"page render unit details\"]')"
            )
            page.evaluate(
                """() => {
                  let nextTimeout = 1000;
                  let nextFrame = 2000;
                  window.setTimeout = () => {
                    const id = nextTimeout++;
                    return id;
                  };
                  window.clearTimeout = (id) => {
                    window.__pyganiniCleanupState.clearedTimeouts.push(id);
                  };
                  window.requestAnimationFrame = () => {
                    const id = nextFrame++;
                    window.__pyganiniPendingFrame = id;
                    return id;
                  };
                  window.cancelAnimationFrame = (id) => {
                    window.__pyganiniCleanupState.cancelledFrames.push(id);
                  };
                }"""
            )
            page.evaluate(
                """() => {
                  const handle = document.querySelector(
                    '[aria-label="page render unit details"]'
                  );
                  handle.focus();
                  handle.blur();
                  window.dispatchEvent(new Event('resize'));
                }"""
            )
            page.evaluate("() => window.__pyganiniTemplateInspectorCleanup()")
            state = page.evaluate(
                """() => ({
                  ...window.__pyganiniCleanupState,
                  pendingFrame: window.__pyganiniPendingFrame,
                  ownedDom: document.querySelectorAll(
                    '[data-pyganini-template-inspector]'
                  ).length,
                  hookOwned: Object.prototype.hasOwnProperty.call(
                    window, '__pyganiniTemplateInspectorCleanup'
                  )
                })"""
            )
            assert state["observerDisconnects"] == 1
            assert state["listenerAdds"] > 0
            assert state["listenerRemoves"] == state["listenerAdds"]
            assert state["clearedTimeouts"]
            assert state["cancelledFrames"] == [state["pendingFrame"]]
            assert state["ownedDom"] == 0
            assert not state["hookOwned"]
        finally:
            page.close()
            browser.close()


@pytest.mark.parametrize("view", ["all", "next"])
def test_template_inspector_long_detail_stays_inside_small_viewport(view: str) -> None:
    start, end, _ = _inspection_pair(
        "/long", source="app/routes/" + "very-long-metadata/" * 300 + "page.jinja:1:1"
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        try:
            page.set_content(
                f"<!doctype html><html><body>{start}<p>long</p>{end}</body></html>"
            )
            page.add_script_tag(content=_inspector_source())
            if view == "next":
                page.get_by_role("button", name="Next render unit").click()
            else:
                page.locator('[aria-label="page render unit details"]').focus()
            panel = page.get_by_text("route: /long", exact=True).locator("..")
            panel.wait_for(timeout=2_000)
            box = panel.bounding_box()
            assert box is not None
            assert box["y"] >= 8
            assert box["y"] + box["height"] <= 836
        finally:
            page.close()
            browser.close()


def test_template_inspector_resets_removed_selection_and_skips_zero_area() -> None:
    zero_start, zero_end, _ = _inspection_pair("/zero")
    first_start, first_end, first_id = _inspection_pair("/a")
    second_start, second_end, _ = _inspection_pair("/b")
    html = "".join(
        (
            zero_start,
            zero_end,
            first_start,
            '<span id="selected-a">A</span>',
            first_end,
            second_start,
            '<span id="selected-b">B</span>',
            second_end,
        )
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        try:
            page.set_content(f"<!doctype html><html><body>{html}</body></html>")
            page.add_script_tag(content=_inspector_source())
            next_button = page.get_by_role("button", name="Next render unit")
            next_button.click()
            page.get_by_text("route: /a", exact=True).wait_for(timeout=2_000)
            page.evaluate(
                """(identifier) => {
                  Array.from(document.body.childNodes).forEach((node) => {
                    if ((node.nodeType === Node.COMMENT &&
                         node.data.includes(identifier)) ||
                        (node.nodeType === Node.ELEMENT_NODE &&
                         node.id === 'selected-a')) {
                      node.remove();
                    }
                  });
                }""",
                first_id,
            )
            page.wait_for_function(
                """() => document.querySelector(
                  '[aria-label="Next render unit"]'
                ).getAttribute('aria-pressed') === 'false'""",
                timeout=2_000,
            )
            next_button.click()
            page.get_by_text("route: /b", exact=True).wait_for(timeout=2_000)
        finally:
            page.close()
            browser.close()


def test_template_inspector_replaces_stale_htmx_frames_and_discovers_units() -> None:
    first_start, first_end, _ = _inspection_pair("/a")
    second_start, second_end, _ = _inspection_pair("/b")
    third_start, third_end, _ = _inspection_pair("/c")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        try:
            page.set_content(
                "<!doctype html><html><body><div id=target>"
                f"{first_start}<span>A</span>{first_end}</div></body></html>"
            )
            page.add_script_tag(content=_inspector_source())
            handle = page.locator('[aria-label$="render unit details"]')
            handle.wait_for(timeout=2_000)
            assert handle.count() == 1
            page.evaluate(
                """(markup) => {
                  const target = document.querySelector('#target');
                  target.innerHTML = markup;
                  window.dispatchEvent(new CustomEvent('htmx:afterSwap'));
                }""",
                f"{second_start}<span>B</span>{second_end}",
            )
            page.wait_for_timeout(100)
            handle.first.focus()
            page.get_by_text("route: /b", exact=True).wait_for(timeout=2_000)
            assert page.get_by_text("route: /a", exact=True).count() == 0
            page.evaluate(
                """(markup) => {
                  const target = document.querySelector('#target');
                  target.outerHTML = '<div id="target">' + markup + '</div>';
                  window.dispatchEvent(new CustomEvent('htmx:afterSettle'));
                }""",
                f"{third_start}<span>C</span>{third_end}",
            )
            page.wait_for_timeout(100)
            handle.first.focus()
            page.get_by_text("route: /c", exact=True).wait_for(timeout=2_000)
            assert handle.count() == 1
            assert page.get_by_text("route: /b", exact=True).count() == 0
        finally:
            page.close()
            browser.close()


def test_browser_full_local_workflow() -> None:
    with _local_server() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page: Page = browser.new_page()
        page_errors: list[str] = []
        console_errors: list[str] = []
        page.on("pageerror", _record_page_error(page_errors))
        page.on(
            "console",
            lambda message: (
                console_errors.append(message.text) if message.type == "error" else None
            ),
        )
        external_requests: list[str] = []
        local_requests: list[str] = []
        local_origin = urlsplit(base_url)

        def is_local_request(request_url: str) -> bool:
            request_origin = urlsplit(request_url)
            return (
                request_origin.scheme == local_origin.scheme
                and request_origin.netloc == local_origin.netloc
            )

        def handle_request(route: Route) -> None:
            request_url = route.request.url
            if is_local_request(request_url):
                local_requests.append(request_url)
                route.continue_()
                return
            external_requests.append(request_url)
            route.abort()

        page.route("**/*", handle_request)
        try:
            page.goto(f"{base_url}/probe")
            page.locator('[data-probe="unnamed"]').wait_for()
            page.locator('#matching [data-probe="named"]').wait_for()
            page.locator('#repeated [data-probe="second"]').wait_for()
            page.locator('[data-probe="nested"]').wait_for()
            assert page.locator("#named-without").inner_html() == ""
            assert "Named message" in (
                page.locator("#named-without").get_attribute("data-dom-event") or ""
            )
            assert page.locator('#repeated [data-probe="first"]').count() == 1
            assert page.locator('#repeated [data-probe="second"]').count() == 1
            assert page.evaluate(
                """() => {
                  const extension = window.__pyganiniExtensions['pyganini-sse-event'];
                  const hook = extension.htmx_before_sse_message;
                  hook(null, null);
                  hook(document.body, null);
                  hook(document.body, {});
                  hook(document.body, {message: null});
                  const missing = {message: {
                    event: 'contact', data: 'x', id: '7', cancelled: false
                  }};
                  hook(document.createElement('div'), missing);
                  const empty = document.createElement('div');
                  empty.setAttribute('pyganini-sse-event', '');
                  hook(empty, missing);
                  const caseMismatch = document.createElement('div');
                  caseMismatch.setAttribute('pyganini-sse-event', 'Contact');
                  hook(caseMismatch, missing);
                  const unnamed = document.createElement('div');
                  unnamed.setAttribute('pyganini-sse-event', 'contact');
                  const unnamedDetail = {message: {
                    event: '', data: 'x', id: '7', cancelled: false
                  }};
                  hook(unnamed, unnamedDetail);
                  const matching = document.createElement('div');
                  matching.setAttribute('pyganini-sse-event', '  contact  ');
                  const detail = {message: {
                    event: 'contact', data: 'x', id: '7', cancelled: false
                  }};
                  hook(matching, detail);
                  hook(matching, detail);
                  return missing.message.event === 'contact'
                    && unnamedDetail.message.event === ''
                    && detail.message.event === ''
                    && detail.message.data === 'x'
                    && detail.message.id === '7'
                    && detail.message.cancelled === false;
                }"""
            )

            helper_source = (
                resources.files("pyganini.browser")
                .joinpath("pyganini-sse-event.js")
                .read_text(encoding="ascii")
            )
            for setup in ("", "window.htmx = {};"):
                guard_page = browser.new_page()
                guard_errors: list[str] = []
                guard_page.on("pageerror", _record_page_error(guard_errors))
                try:
                    guard_page.set_content(f"<script>{setup}</script>")
                    guard_page.add_script_tag(content=helper_source)
                    assert guard_errors == []
                finally:
                    guard_page.close()

            page.close()
            page = browser.new_page()
            page.on("pageerror", _record_page_error(page_errors))
            page.on(
                "console",
                lambda message: (
                    console_errors.append(message.text)
                    if message.type == "error"
                    else None
                ),
            )
            page.route("**/*", handle_request)
            page.set_viewport_size({"width": 1280, "height": 900})
            page.goto(f"{base_url}/directory/")
            _wait_for_contact_event(
                page,
                local_requests=local_requests,
                page_errors=page_errors,
                console_errors=console_errors,
            )
            assert page.locator('[data-sse-event="contact"]').inner_text() == (
                "Named SSE contact; last-event-id: start"
            )
            assert page.locator('[data-sse-event="ignored"]').count() == 0
            assert any(url.endswith("/directory/events") for url in local_requests)
            assert any(
                "/directory/assets/vendor/hx-sse.min." in url for url in local_requests
            )
            assert any(
                url.endswith("/directory/pyganini/pyganini-sse-event.js")
                for url in local_requests
            )
            assert page.evaluate(
                "() => document.documentElement.scrollWidth <= window.innerWidth"
            )

            page.close()
            page = browser.new_page()
            page.on("pageerror", _record_page_error(page_errors))
            page.on(
                "console",
                lambda message: (
                    console_errors.append(message.text)
                    if message.type == "error"
                    else None
                ),
            )
            page.route("**/*", handle_request)
            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(f"{base_url}/directory/")
            _wait_for_contact_event(
                page,
                local_requests=local_requests,
                page_errors=page_errors,
                console_errors=console_errors,
            )
            assert page.locator('[data-sse-event="ignored"]').count() == 0
            assert page.evaluate(
                "() => document.documentElement.scrollWidth <= window.innerWidth"
            )

            page.goto(f"{base_url}/directory/users")
            page.get_by_role("group", name="Pyganini template inspection").wait_for()
            assert page.get_by_role("button", name="All").count() == 1
            assert page.get_by_role("button", name="Off").count() == 1
            assert page.get_by_role("button", name="Next render unit").count() == 1
            assert page.locator("[data-pyganini-template-inspector]").count() >= 2
            inspector_source = (
                resources.files("pyganini.browser")
                .joinpath("pyganini-template-inspector.js")
                .read_text(encoding="ascii")
            )
            page.add_script_tag(content=inspector_source)
            page.get_by_role("group", name="Pyganini template inspection").wait_for()
            assert (
                page.get_by_role("group", name="Pyganini template inspection").count()
                == 1
            )
            detail_handle = page.locator('[aria-label$="render unit details"]').first
            detail_handle.focus()
            assert page.get_by_text(re.compile(r"^kind: ")).count() == 1
            detail_handle.blur()
            page.get_by_role("button", name="Next render unit").press("Enter")
            page.wait_for_function(
                """() => document.querySelector(
                  '[aria-label="Next render unit"]'
                ).getAttribute('aria-pressed') === 'true'"""
            )
            assert (
                page.get_by_role("button", name="Next render unit").get_attribute(
                    "aria-pressed"
                )
                == "true"
            )
            page.get_by_role("button", name="All").click()
            page.evaluate(
                """() => {
                  const start = document.createComment(
                    'pyganini:start id=u' + '0'.repeat(64) +
                    ' kind=page surface=page route=raw-value template=x source=x' +
                    ' declaration=x owner=x handler=x mount=x'
                  );
                  document.body.append(start, document.createComment(
                    'pyganini:end id=u' + '0'.repeat(64)
                  ));
                  Object.defineProperty(Storage.prototype, 'setItem', {
                    configurable: true,
                    value: function () { throw new Error('storage disabled'); }
                  });
                }"""
            )
            page.add_script_tag(content=inspector_source)
            page.get_by_role("button", name="Off").click()
            page.get_by_role("button", name="All").click()
            assert (
                page.get_by_role("group", name="Pyganini template inspection").count()
                == 1
            )
            assert page.evaluate(
                """() => Array.from(document.querySelectorAll(
                  '[data-pyganini-template-inspector]'
                )).every((node) => {
                  const box = node.getBoundingClientRect();
                  return box.left >= 0 && box.top >= 0 &&
                    box.right <= window.innerWidth && box.bottom <= window.innerHeight;
                })"""
            )
            assert page.locator('[data-layout="root"]').count() == 1
            assert page.locator('[data-layout="users"]').count() == 1
            assert (
                page.locator(
                    f'link[href="{assets.path("app.css", base_path="/directory")}"]'
                ).count()
                == 1
            )
            assert (
                page.locator(
                    'script[src="'
                    + assets.path("vendor/htmx.min.js", base_path="/directory")
                    + '"]'
                ).count()
                == 1
            )
            assert (
                page.locator(
                    f'script[src="{assets.path("app.js", base_path="/directory")}"]'
                ).count()
                == 1
            )
            assert page.locator("html").get_attribute("data-pyganini-js") == "ready"
            assert page.evaluate("() => window.htmx.version") == "4.0.0-beta6"

            with page.expect_response(
                lambda response: (
                    response.request.method == "POST"
                    and response.url.endswith("/directory/users/create")
                )
            ) as invalid_response:
                page.locator("#contact-name").fill("")
                page.get_by_role("button", name="Add contact").click()
            assert invalid_response.value.status == 422
            assert page.locator("#contact-name-error").inner_text() == (
                "Name is required."
            )

            page.locator("#contact-name").fill("Blocked Contact")
            page.locator('input[name="csrf_token"]').evaluate(
                "(element) => { element.value = 'invalid-token'; }"
            )
            with page.expect_response(
                lambda response: (
                    response.request.method == "POST"
                    and response.url.endswith("/directory/users/create")
                )
            ) as csrf_response:
                page.get_by_role("button", name="Add contact").click()
            assert csrf_response.value.status == 403
            assert page.locator("#users-directory").count() == 1
            assert page.locator("#contact-name").input_value() == "Blocked Contact"

            page.reload()
            page.locator("#contact-name").fill("Browser Contact")
            page.locator("#contact-avatar").set_input_files(
                {
                    "name": "browser.txt",
                    "mimeType": "text/plain",
                    "buffer": b"browser upload",
                }
            )
            with page.expect_response(
                lambda response: (
                    response.request.method == "POST" and response.status == 200
                )
            ):
                page.get_by_role("button", name="Add contact").click()
            assert page.locator("#upload-filename").inner_text() == "browser.txt"
            assert page.locator("text=Browser Contact").count() >= 1

            with page.expect_response(
                lambda response: (
                    response.request.method == "GET"
                    and "/directory/users/table?status=inactive" in response.url
                )
            ):
                page.get_by_role("link", name="Inactive only").click()
            assert (
                page.locator("#users-table-slot").inner_text().find("Katherine Johnson")
                >= 0
            )
            assert page.locator("#users-table-slot [data-layout]").count() == 0
            assert (
                page.get_by_role("group", name="Pyganini template inspection").count()
                == 1
            )

            page.get_by_role("link", name="All").click()
            page.get_by_role("link", name="Ada Lovelace").click()
            page.wait_for_url(
                f"{base_url}/directory/users/42?"
                "_pyganini_nav_trail_key=from-contacts&"
                "_pyganini_return_to=%2Fdirectory%2Fusers%2Ftable"
            )
            assert page.locator('[data-layout="root"]').count() == 1
            assert page.locator('[data-layout="users"]').count() == 1
            assert (
                page.locator('[data-page="contact-detail"]')
                .inner_text()
                .find("Ada Lovelace")
                >= 0
            )
            assert page.get_by_role("link", name="Home").get_attribute("href") == (
                "/directory/"
            )
            assert (
                page.get_by_role(
                    "link", name="Back to Contacts", exact=True
                ).get_attribute("href")
                == "/directory/users/table"
            )
            canonical_detail = page.goto(f"{base_url}/directory/users/42")
            assert canonical_detail is not None
            assert canonical_detail.status == 200
            breadcrumb = page.get_by_role("navigation", name="Breadcrumb")
            canonical_home = breadcrumb.get_by_role("link", name="Home", exact=True)
            assert canonical_home.get_attribute("href") == "/directory/"
            canonical_home.click()
            page.wait_for_url(f"{base_url}/directory/")
            assert page.locator('[data-page="home"]').count() == 1

            page.set_viewport_size({"width": 1280, "height": 900})
            page.set_extra_http_headers({"X-Example-Route-Error": "matched"})
            error_response = page.goto(f"{base_url}/directory/users")
            assert error_response is not None
            assert error_response.status == 418
            assert page.locator('[data-layout="root"]').count() == 1
            assert page.locator('[data-layout="users"]').count() == 1
            assert (
                page.locator('[data-layout="mounted-contact-directory"]').count() == 1
            )
            assert page.locator('[data-presentation="page"]').is_visible()

            page.set_viewport_size({"width": 390, "height": 844})
            narrow_error = page.goto(f"{base_url}/directory/users")
            assert narrow_error is not None
            assert narrow_error.status == 418
            assert page.locator('[data-layout="root"]').count() == 1
            assert page.locator('[data-layout="users"]').count() == 1
            assert (
                page.locator('[data-layout="mounted-contact-directory"]').count() == 1
            )
            assert page.locator('[data-presentation="page"]').is_visible()
            assert page.evaluate(
                "() => document.documentElement.scrollWidth <= window.innerWidth"
            )
        finally:
            page.close()
            browser.close()
        assert external_requests == []
        assert page_errors == []
        assert all(
            any(status in message for status in ("403", "418", "422"))
            for message in console_errors
        )
