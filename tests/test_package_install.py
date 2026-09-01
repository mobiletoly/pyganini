import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest
from conftest import PackageBuild


def _run(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def _smoke_install(
    *,
    artifact: Path,
    python_line: str,
    root: Path,
) -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["UV_CACHE_DIR"] = str(root / "uv-cache")
    virtual_environment = root / "venv"
    subprocess.run(
        ["uv", "venv", "--python", python_line, str(virtual_environment)],
        env=environment,
        check=True,
    )
    python = virtual_environment / "bin" / "python"
    subprocess.run(
        ["uv", "pip", "install", "--python", str(python), str(artifact)],
        env=environment,
        check=True,
    )

    outside = root / "outside-checkout"
    outside.mkdir()
    command = virtual_environment / "bin" / "pyganini"
    assert not (virtual_environment / "bin" / "uv").exists()
    imported = _run(
        [
            str(python),
            "-c",
            (
                "import pyganini; "
                "from pyganini.request_data import (Body, Form, Upload, "
                "capture_body, capture_form); "
                "assert Body(b'body').content == b'body'; "
                'assert Form((("name", "Ada"),)).values("name") == ("Ada",); '
                "assert Upload(\"a.txt\", \"text/plain\", b'a').content == b'a'; "
                "assert capture_body(max_bytes=1).max_bytes == 1; "
                "assert capture_form(max_files=1, max_fields=1, "
                "max_part_size=1, max_upload_size=1).max_upload_size == 1; "
                "from pyganini import (ActionDef, Destination, FragmentResponse, "
                "FragmentRouteDef, "
                "FragmentRouteResponse, Page, PageMetadata, PageRouteResponse, "
                "KitActionDef, KitFragmentRouteDef, KitRouteDef, "
                "KitRouteMount, MountRoute, NavTrail, NavTrailStep, Navigation, "
                "NavigationBack, NavigationCurrent, RequestNav, RouteDef, "
                "RouteErrorHandler, RouteMeta, RouteNav, RouteResponse, "
                "TemplateInspectionMode, "
                "RouteTarget, action, "
                "create_environment, "
                "browser, csrf, fragment_route, hx, kit_action, kit_fragment_route, "
                "route, sse, "
                "current_nav_step, mount_route, nav, nav_step, route_mount, "
                "route_kit, to); "
                "from importlib.metadata import entry_points, requires; "
                "assert set(pyganini.__all__) == "
                "{'ActionDef', 'Destination', 'FragmentResponse', 'FragmentRouteDef', "
                "'FragmentRouteResponse', 'KitActionDef', 'KitFragmentRouteDef', "
                "'KitRouteDef', 'KitRouteMount', 'MountRoute', 'NavTrail', "
                "'NavTrailStep', 'Navigation', 'NavigationBack', "
                "'NavigationCurrent', 'Page', "
                "'PageMetadata', 'PageRouteResponse', "
                "'RequestNav', 'RouteDef', 'RouteErrorHandler', 'RouteMeta', "
                "'RouteNav', 'RouteResponse', 'TemplateInspectionMode', "
                "'RouteTarget', 'action', 'create_environment', "
                "'browser', 'current_nav_step', 'csrf', 'fragment_route', 'hx', "
                "'kit_action', "
                "'kit_fragment_route', "
                "'mount_route', 'nav', 'nav_step', 'route', 'route_kit', "
                "'route_mount', 'sse', 'to'}; "
                "assert not hasattr(pyganini, 'Event'); "
                "assert not hasattr(pyganini, 'encode_event'); "
                "assert not hasattr(pyganini, 'MEDIA_TYPE'); "
                "labels = {'area': 'users'}; metadata = RouteMeta(labels=labels); "
                "labels['area'] = 'changed'; "
                "assert dict(metadata.labels) == {'area': 'users'}; "
                "assert route(page=lambda request: None, name='users', "
                "title='Users', meta=metadata).meta is metadata; "
                "assert all(item.__doc__ for item in "
                "(ActionDef, Destination, FragmentResponse, FragmentRouteDef, "
                "FragmentRouteResponse, KitActionDef, KitFragmentRouteDef, "
                "KitRouteDef, KitRouteMount, MountRoute, Page, PageMetadata, "
                "NavTrailStep, Navigation, NavigationBack, NavigationCurrent, "
                "PageRouteResponse, RequestNav, RouteDef, RouteMeta, RouteNav, "
                "RouteResponse, "
                "RouteTarget, action, create_environment, current_nav_step, "
                "csrf, fragment_route, hx, kit_action, kit_fragment_route, "
                "mount_route, "
                "nav, nav_step, route, route_kit, route_mount, to)); "
                "entries = entry_points(group='console_scripts', name='pyganini'); "
                "entry = next(iter(entries)); "
                "assert entry.value == 'pyganini._cli:main'; "
                "assert all(not item.lower().startswith('uv') "
                "for item in (requires('pyganini') or [])); "
                "assert 'python-multipart>=0.0.32,<0.0.33' in "
                "(requires('pyganini') or []); "
                "assert sse.encode_event(sse.Event(id='42', data='hello')) == "
                "b'id: 42\\ndata: hello\\n\\n'; "
                "assert sse.encode_comment('connected') == b': connected\\n\\n'; "
                "assert browser.SSE_EVENT_HELPER_PATH == '/pyganini-sse-event.js'; "
                "assert browser.TEMPLATE_INSPECTOR_HELPER_PATH == "
                "'/pyganini-template-inspector.js'; "
                "import hashlib, importlib.resources; "
                "helper_bytes=importlib.resources.files('pyganini.browser').joinpath("
                "'pyganini-sse-event.js').read_bytes(); "
                "assert hashlib.sha256(helper_bytes).hexdigest() == "
                "'beaea931c38ac5c67f07ebe787bccd96ec4a7a0f85176103a58f41370de24941'; "
                "inspector_bytes=importlib.resources.files('pyganini.browser').joinpath("
                "'pyganini-template-inspector.js').read_bytes(); "
                "assert hashlib.sha256(inspector_bytes).hexdigest() == "
                "'8229d016bc7d4b2f74acab19fa75019a83cd0128988302ca1ccc53c803daba59'; "
                "assert hx.HEADER_RETARGET == 'HX-Retarget'; "
                "from pyganini.csrf import Guard; "
                "assert csrf.DEFAULT_COOKIE_NAME == 'pyganini_csrf'; "
                "assert isinstance("
                "Guard(secret=b'0123456789abcdef0123456789abcdef'), Guard); "
                "import asyncio, json; from http.cookies import SimpleCookie; "
                "from starlette.requests import Request; "
                "scope={'type':'http','asgi':{'version':'3.0',"
                "'spec_version':'2.4'},'http_version':'1.1','method':'GET',"
                "'scheme':'http','path':'/','raw_path':b'/','query_string':b'',"
                "'headers':[],'client':('127.0.0.1',1234),"
                "'server':('testserver',80)}; captured=[]; messages=[]; "
                "assert sse.last_event_id(Request({**scope,'headers': "
                "[(b'last-event-id', b'42')]})) == '42'; "
                'exec("async def installed_app(child_scope, receive, send):\\n'
                "    captured.append(child_scope)\\n"
                "    await send({'type':'http.response.start','status':204})\\n"
                "    await send({'type':'http.response.body','body':b''})\\n"
                "async def receive():\\n"
                "    raise AssertionError('body read')\\n"
                "async def send(message):\\n"
                '    messages.append(message)\\n"); '
                "guard=Guard(secret=b'0123456789abcdef0123456789abcdef'); "
                "middleware=csrf.TokenMiddleware(installed_app, guard=guard); "
                "asyncio.run(middleware(scope, receive, send)); "
                "issued=csrf.token(Request(captured[0])); "
                "assert json.loads(csrf.headers(issued)) == "
                "{'X-CSRF-Token': issued}; "
                "set_cookie=next(value for header,value in messages[0]['headers'] "
                "if header == b'set-cookie'); cookies=SimpleCookie(); "
                "cookies.load(set_cookie.decode('latin-1')); "
                "cookie=cookies[csrf.DEFAULT_COOKIE_NAME].value; "
                "guard.validate(Request({**scope,'method':'POST','headers': "
                "[(b'cookie', ('pyganini_csrf=' + cookie).encode('ascii'))]}), cookie)"
            ),
        ],
        cwd=outside,
        environment=environment,
    )
    assert imported.stdout == ""
    assert (
        _run([str(command), "--version"], cwd=outside, environment=environment).stdout
        == "pyganini 0.1.1\n"
    )
    assert (
        _run(
            [str(python), "-m", "pyganini", "--version"],
            cwd=outside,
            environment=environment,
        ).stdout
        == "pyganini 0.1.1\n"
    )
    assert (
        "app/_pyganini"
        in _run([str(command), "--help"], cwd=outside, environment=environment).stdout
    )

    application = root / "consumer application"
    routes = application / "app" / "routes"
    routes.mkdir(parents=True)
    (application / "pyproject.toml").write_text("[tool.pyganini]\n", encoding="ascii")
    (application / "app" / "__init__.py").write_text("", encoding="ascii")
    (routes / "middleware.py").write_text(
        "from starlette.middleware import Middleware\n"
        "class InstalledMiddleware:\n"
        "    def __init__(self, app): self.app = app\n"
        "    async def __call__(self, scope, receive, send):\n"
        "        async def send_wrapper(message):\n"
        "            if message['type'] == 'http.response.start':\n"
        "                message = {**message, 'headers': [\n"
        "                    *message['headers'],\n"
        "                    (b'x-installed-middleware', b'active')\n"
        "                ]}\n"
        "            await send(message)\n"
        "        await self.app(scope, receive, send_wrapper)\n"
        "MIDDLEWARE: tuple[Middleware, ...] = (Middleware(InstalledMiddleware),)\n",
        encoding="ascii",
    )
    (routes / "__init__.py").write_text("", encoding="ascii")
    (routes / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (routes / "layout.jinja").write_text(
        "<html><title>{{ metadata.title }}</title>{{ child }}</html>",
        encoding="ascii",
    )
    (routes / "error_page.jinja").write_text(
        "<section>{{ message }}</section>", encoding="ascii"
    )
    (routes / "error_fragment.jinja").write_text(
        "<aside>{{ message }}</aside>", encoding="ascii"
    )
    (routes / "route.py").write_text(
        "from pyganini import route\n"
        "Route = route(\n"
        " error_page_template='error_page.jinja',\n"
        " error_fragment_template='error_fragment.jinja',\n"
        ")\n",
        encoding="ascii",
    )
    users = routes / "users"
    users.mkdir()
    (users / "__init__.py").write_text("", encoding="ascii")
    (users / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (users / "layout.jinja").write_text(
        "<main data-nav='{{ layout.navigation }}'>{{ child }}</main>",
        encoding="ascii",
    )
    (users / "page.jinja").write_text("<h1>{{ name }}</h1>", encoding="ascii")
    (users / "table.jinja").write_text("<p>{{ rows }}</p>", encoding="ascii")
    (users / "form.jinja").write_text("<form>{{ saved }}</form>", encoding="ascii")
    (users / "custom.jinja").write_text("{{ value | shout }}", encoding="ascii")
    (routes / "reference-inventory.jinja").write_text(
        '<button hx-get="/users"></button>', encoding="ascii"
    )
    (users / "route.py").write_text(
        "from pyganini import action, fragment_route, route\n"
        "from .handlers import custom, direct, page, save, table\n"
        "Route = route(\n"
        " page=page, template='page.jinja',\n"
        " fragments=(fragment_route('/table', table, template='table.jinja'),),\n"
        " actions=(\n"
        "  action('POST', '/save', save, template='form.jinja'),\n"
        "  action('PATCH', '/custom', custom, template='custom.jinja'),\n"
        "  action('DELETE', '/direct', direct),\n"
        " ),\n"
        ")\n",
        encoding="ascii",
    )
    (users / "handlers.py").write_text(
        "from pyganini import FragmentResponse, Page, PageMetadata\n"
        "from starlette.responses import RedirectResponse\n"
        "def page(request):\n"
        " return Page(context={'name':'external'}, "
        "metadata=PageMetadata(title='Users'), layout={'navigation':'people'})\n"
        "def table(request): return FragmentResponse(context={'rows':'one'})\n"
        "async def save(request):\n"
        " async with request.form("
        "max_files=8, max_fields=64, max_part_size=1048576) as form:\n"
        "  saved = form.get('saved', 'missing')\n"
        " return Page(context={'saved':str(saved)}, "
        "metadata=PageMetadata(title='Saved'), "
        "layout={'navigation':'save'}, status_code=201)\n"
        "def custom(request): return FragmentResponse(context={'value':'hello'})\n"
        "def direct(request): return RedirectResponse('/users', status_code=303)\n",
        encoding="ascii",
    )
    assets = application / "assets"
    (assets / "build").mkdir(parents=True)
    (assets / "__init__.py").write_text("", encoding="ascii")
    (assets / "build" / "app.css").write_bytes(b"body{}\n")
    asset_dist = _run(
        [str(command), "assets", "dist"], cwd=application, environment=environment
    )
    assert (
        asset_dist.stdout == "Pyganini asset state: written=3 unchanged=0 removed=0.\n"
    )
    asset_check = _run(
        [str(python), "-m", "pyganini", "assets", "check"],
        cwd=application,
        environment=environment,
    )
    assert asset_check.stdout == "Pyganini asset state is current.\n"
    listed_assets = _run(
        [str(command), "assets", "list", "--json"],
        cwd=application,
        environment=environment,
    )
    listed_assets_module = _run(
        [str(python), "-m", "pyganini", "assets", "list", "--json"],
        cwd=application,
        environment=environment,
    )
    assert listed_assets.stdout == listed_assets_module.stdout
    assert json.loads(listed_assets.stdout)["assets"][0]["name"] == "app.css"
    generated = _run(
        [str(command), "generate"], cwd=application, environment=environment
    )
    assert generated.stdout == (
        "Pyganini generated state: written=4 unchanged=0 removed=0.\n"
        "Pyganini asset state: written=0 unchanged=3 removed=0.\n"
    )
    checked = _run([str(command), "check"], cwd=routes, environment=environment)
    assert checked.stdout == (
        "Pyganini generated state is current.\nPyganini asset state is current.\n"
    )
    assert (application / "app" / "_pyganini" / ".pyganini-root").read_bytes() == (
        b"pyganini-generated-directory-v1\n"
    )
    assert (application / "app" / "_pyganini" / "__init__.py").read_bytes() == (
        b"# Code generated by pyganini; DO NOT EDIT.\n"
        b'"""Generated Pyganini application package."""\n'
    )
    listed = _run(
        [str(command), "routes", "list"], cwd=application, environment=environment
    )
    assert listed.stdout.splitlines()[0].split()[:3] == ["KIND", "METHOD", "PATH"]
    assert "/users" in listed.stdout
    refs = _run(
        [str(command), "routes", "refs"], cwd=application, environment=environment
    )
    module_refs = _run(
        [str(python), "-m", "pyganini", "routes", "refs"],
        cwd=application,
        environment=environment,
    )
    assert refs.stdout == module_refs.stdout
    assert refs.stderr == module_refs.stderr == ""
    assert "resolved" in refs.stdout
    assert "app/routes/reference-inventory.jinja:1:1" in refs.stdout
    refs_json = _run(
        [str(command), "routes", "refs", "--json"],
        cwd=application,
        environment=environment,
    )
    refs_payload = json.loads(refs_json.stdout)
    assert refs_payload["schema"] == "pyganini.refs.v1"
    assert any(
        reference["value"] == "/users" and reference["status"] == "resolved"
        for reference in refs_payload["references"]
    )
    layouts = _run(
        [str(command), "routes", "layouts"],
        cwd=application,
        environment=environment,
    )
    assert layouts.stdout.startswith("LAYOUT MAP\n/\n")
    assert (
        "layouts=[app/routes/layout.py:1:1 > app/routes/users/layout.py:1:1]"
        in layouts.stdout
    )
    module_layouts = _run(
        [str(python), "-m", "pyganini", "routes", "layouts"],
        cwd=application,
        environment=environment,
    )
    assert module_layouts.stdout == layouts.stdout
    explained = _run(
        [str(command), "routes", "explain", "/users"],
        cwd=application,
        environment=environment,
    )
    module_explained = _run(
        [str(python), "-m", "pyganini", "routes", "explain", "/users"],
        cwd=application,
        environment=environment,
    )
    assert explained.stdout == module_explained.stdout
    assert explained.stderr == module_explained.stderr == ""
    assert "status=matched" in explained.stdout
    assert "route=/users" in explained.stdout
    inspected = _run(
        [str(command), "routes", "list", "--json"],
        cwd=application,
        environment=environment,
    )
    inspected_data = json.loads(inspected.stdout)
    assert inspected_data["schema"] == "pyganini.routes.v1"
    assert any(row["path"] == "/users" for row in inspected_data["routes"])
    render_units = _run(
        [str(command), "routes", "render-units"],
        cwd=application,
        environment=environment,
    )
    module_render_units = _run(
        [str(python), "-m", "pyganini", "routes", "render-units"],
        cwd=application,
        environment=environment,
    )
    assert render_units.stdout == module_render_units.stdout
    assert render_units.stderr == module_render_units.stderr == ""
    assert "routes/users/page.jinja" in render_units.stdout
    assert "routes/users/table.jinja" in render_units.stdout
    assert "routes/users/form.jinja" in render_units.stdout
    assert "routes/error_page.jinja" not in render_units.stdout
    assert "routes/error_fragment.jinja" not in render_units.stdout
    assert "/users/direct" not in render_units.stdout
    render_units_json = _run(
        [str(command), "routes", "render-units", "--json"],
        cwd=application,
        environment=environment,
    )
    module_render_units_json = _run(
        [str(python), "-m", "pyganini", "routes", "render-units", "--json"],
        cwd=application,
        environment=environment,
    )
    assert render_units_json.stdout == module_render_units_json.stdout
    assert render_units_json.stderr == module_render_units_json.stderr == ""
    render_units_data = json.loads(render_units_json.stdout)
    assert render_units_data["schema"] == "pyganini.render_units.v1"
    assert any(
        row["route"] == "/users" and row["layout_mode"] == "page"
        for row in render_units_data["render_units"]
    )
    request = _run(
        [
            str(python),
            "-c",
            (
                "import asyncio\n"
                "from app._pyganini.asgi import create_router, router\n"
                "from app._pyganini.urls import urls\n"
                "from jinja2 import PackageLoader\n"
                "from pyganini import (FragmentResponse, Page, PageMetadata, "
                "RouteErrorHandler, TemplateInspectionMode, browser, "
                "create_environment)\n"
                "from importlib.resources import files\n"
                "from starlette.applications import Starlette\n"
                "from starlette.responses import PlainTextResponse\n"
                "from starlette.routing import Mount\n"
                "async def request(app,path,method='GET',body=b'',headers=()):\n"
                " messages=[]\n"
                " scope={'type':'http','asgi':{'version':'3.0'},"
                "'http_version':'1.1','method':method,'scheme':'http',"
                "'path':path,'raw_path':path.encode(),'query_string':b'',"
                "'root_path':'','headers':[(name.encode(),value.encode()) "
                "for name,value in headers],"
                "'client':None,'server':None}\n"
                " async def receive():\n"
                "  return {'type':'http.request','body':body,'more_body':False}\n"
                " async def send(message):\n"
                "  messages.append(message)\n"
                " await app(scope,receive,send)\n"
                " return messages\n"
                "def body(messages):\n"
                " return b''.join(m.get('body',b'') for m in messages)\n"
                "assert urls.users.path == '/users'\n"
                "assert urls.with_base_path('/html').users.path == '/html/users'\n"
                "page=asyncio.run(request(router,'/users'))\n"
                "assert page[0]['status']==200\n"
                "assert (dict(page[0]['headers'])[b'x-installed-middleware']\n"
                "        == b'active')\n"
                'assert body(page)==b"<html><title>Users</title><main '
                "data-nav='people'><h1>external</h1></main></html>\"\n"
                "inspection_router=create_router("
                "template_inspection=TemplateInspectionMode.COMMENTS)\n"
                "inspected=asyncio.run(request(inspection_router,'/users'))\n"
                "assert b'<!--pyganini:start id=u' in body(inspected)\n"
                "fragment=asyncio.run(request(router,'/users/table'))\n"
                "assert body(fragment)==b'<p>one</p>'\n"
                "action=asyncio.run(request(router,'/users/save','POST',b'saved=parsed',"
                "[('content-type','application/x-www-form-urlencoded')]))\n"
                "assert action[0]['status']==201\n"
                'assert body(action)==b"<html><title>Saved</title><main '
                "data-nav='save'><form>parsed</form></main></html>\"\n"
                "direct=asyncio.run(request(router,'/users/direct','DELETE'))\n"
                "assert direct[0]['status']==303\n"
                "environment=create_environment(loader=PackageLoader('app',package_path=''))\n"
                "environment.filters['shout']=lambda value: str(value).upper()+'!'\n"
                "custom_router=create_router(environment=environment)\n"
                "custom=asyncio.run(request(custom_router,'/users/custom','PATCH'))\n"
                "assert body(custom)==b'HELLO!'\n"
                "def present_error(request, error):\n"
                " mode=request.headers.get('x-error-mode')\n"
                " if mode == 'fragment':\n"
                "  return FragmentResponse(context={'message':'fragment'}, "
                "status_code=404)\n"
                " if mode == 'direct':\n"
                "  return PlainTextResponse('direct', status_code=404)\n"
                " if mode == 'delegate': return None\n"
                " return Page(context={'message':'page'}, "
                "metadata=PageMetadata(title='Error'), status_code=404)\n"
                "callback: RouteErrorHandler = present_error\n"
                "callback_router=create_router(error_handler=callback)\n"
                "presented=asyncio.run(request(callback_router,'/missing'))\n"
                "assert presented[0]['status']==404\n"
                "assert body(presented)==b'<html><title>Error</title>"
                "<section>page</section></html>'\n"
                "fragment_error=asyncio.run(request(callback_router,'/missing',"
                "headers=[('x-error-mode','fragment')]))\n"
                "assert body(fragment_error)==b'<aside>fragment</aside>'\n"
                "direct_error=asyncio.run(request(callback_router,'/missing',"
                "headers=[('x-error-mode','direct')]))\n"
                "assert body(direct_error)==b'direct'\n"
                "delegated=asyncio.run(request(callback_router,'/missing',"
                "headers=[('x-error-mode','delegate')]))\n"
                "assert delegated[0]['status']==404\n"
                "assert body(delegated)==b'Not Found'\n"
                "assert b''.join("
                "m.get('body',b'') for m in direct"
                ")==b''\n"
                "host=Starlette(routes=[Mount('/html',app=router)])\n"
                "mounted=asyncio.run(request(host,'/html/users/table'))\n"
                "assert mounted[0]['status']==200\n"
                "assert body(mounted)==b'<p>one</p>'\n"
                "browser_host=Starlette(routes=[Mount('/helpers',app=browser.create_app())])\n"
                "helper_bytes=files('pyganini.browser').joinpath('pyganini-sse-event.js').read_bytes()\n"
                "helper=asyncio.run(request(browser_host,'/helpers/pyganini-sse-event.js'))\n"
                "assert helper[0]['status']==200\n"
                "helper_headers=dict(helper[0]['headers'])\n"
                "assert helper_headers[b'etag']=="
                "b'\"beaea931c38ac5c67f07ebe787bccd96ec4a7a0f85176103a58f41370de24941\"'\n"
                "assert body(helper)==helper_bytes\n"
                "inspector_bytes=files('pyganini.browser').joinpath("
                "'pyganini-template-inspector.js').read_bytes()\n"
                "inspector=asyncio.run(request("
                "browser_host,'/helpers/pyganini-template-inspector.js'))\n"
                "assert inspector[0]['status']==200\n"
                "inspector_headers=dict(inspector[0]['headers'])\n"
                "assert inspector_headers[b'etag']=="
                "b'\"8229d016bc7d4b2f74acab19fa75019a83cd0128988302ca1ccc53c803daba59\"'\n"
                "assert body(inspector)==inspector_bytes\n"
                "cached=asyncio.run(request(browser_host,'/helpers/pyganini-sse-event.js',"
                "headers=[('if-none-match',helper_headers[b'etag'].decode())]))\n"
                "assert cached[0]['status']==304 and body(cached)==b''\n"
                "inspector_cached=asyncio.run(request("
                "browser_host,'/helpers/pyganini-template-inspector.js',"
                "headers=[('if-none-match',"
                "inspector_headers[b'etag'].decode())]))\n"
                "assert inspector_cached[0]['status']==304\n"
                "assert body(inspector_cached)==b''"
            ),
        ],
        cwd=application,
        environment=environment,
    )
    assert request.stdout == ""


@pytest.mark.parametrize("python_line", ["3.13", "3.14"])
def test_external_wheel_install(package_build: PackageBuild, python_line: str) -> None:
    with tempfile.TemporaryDirectory(
        prefix=f"pyganini-wheel-{python_line}-"
    ) as temporary:
        _smoke_install(
            artifact=package_build.wheel,
            python_line=python_line,
            root=Path(temporary),
        )


@pytest.mark.parametrize("python_line", ["3.13", "3.14"])
def test_external_source_distribution_install(
    package_build: PackageBuild, python_line: str
) -> None:
    with tempfile.TemporaryDirectory(
        prefix=f"pyganini-sdist-{python_line}-"
    ) as temporary:
        _smoke_install(
            artifact=package_build.sdist,
            python_line=python_line,
            root=Path(temporary),
        )


@pytest.mark.parametrize("python_line", ["3.13", "3.14"])
def test_external_sdist_built_wheel_install(
    package_build: PackageBuild, python_line: str
) -> None:
    with tempfile.TemporaryDirectory(
        prefix=f"pyganini-sdist-wheel-{python_line}-"
    ) as temporary:
        _smoke_install(
            artifact=package_build.sdist_wheel,
            python_line=python_line,
            root=Path(temporary),
        )
