"""FastAPI host compatibility without FastAPI handler ownership."""

from __future__ import annotations

from fastapi import FastAPI
from pyganini import csrf
from starlette.staticfiles import StaticFiles
from starlette.testclient import TestClient

from app._pyganini.asgi import create_router
from app.contacts import ContactRepository
from app.dependencies import Dependencies
from app.errors import route_error_handler
from app.main import ASSET_DIRECTORY
from app.security import ExamplePolicyMiddleware, ImmutableAssetCacheMiddleware
from assets import pyganini_assets_gen as assets

from .client import as_example_client


def test_fastapi_keeps_api_openapi_static_and_mount_ownership() -> None:
    host = FastAPI()

    async def health() -> dict[str, str]:
        return {"status": "ok"}

    host.add_api_route("/api/health", health, methods=["GET"])

    host.state.dependencies = Dependencies(
        repository=ContactRepository(),
        csrf=csrf.Guard(secret=b"fastapi-secret-" + b"3" * 20),
    )
    host.add_middleware(csrf.TokenMiddleware, guard=host.state.dependencies.csrf)
    host.add_middleware(ExamplePolicyMiddleware)
    host.mount(
        "/directory/assets",
        ImmutableAssetCacheMiddleware(
            StaticFiles(directory=ASSET_DIRECTORY),
            fingerprinted_paths=tuple(
                asset.path.removeprefix("/assets/")
                for asset in assets.manifest().values()
            ),
        ),
        name="directory-assets",
    )
    host.mount("/directory", create_router(error_handler=route_error_handler))

    with TestClient(host) as raw_client:
        client = as_example_client(raw_client)
        api = client.get("/api/health")
        assert api.status_code == 200
        assert api.json() == {"status": "ok"}
        assert "/api/health" in client.get("/openapi.json").json()["paths"]

        users = client.get("/directory/users")
        assert users.status_code == 200
        assert 'data-route-policy="users"' in users.text
        assert 'href="/directory/users"' in users.text
        assert 'hx-post="/directory/users/create"' in users.text
        assert (
            'href="/directory/users/42?_pyganini_nav_trail_key=from-contacts&amp;'
            '_pyganini_return_to=%2Fdirectory%2Fusers"' in users.text
        )
        assert f'href="{assets.path("app.css", base_path="/directory")}"' in users.text
        assert (
            f'src="{assets.path("vendor/htmx.min.js", base_path="/directory")}"'
            in users.text
        )
        assert f'src="{assets.path("app.js", base_path="/directory")}"' in users.text
        settings_users = client.get("/directory/settings/users")
        assert settings_users.status_code == 200
        assert 'data-route-policy="settings-users"' in settings_users.text
        assert 'hx-get="/directory/settings/users/table?status=active"' in (
            settings_users.text
        )
        assert 'hx-post="/directory/settings/users/create"' not in settings_users.text
        assert client.post("/directory/settings/users/create").status_code == 404
        assert client.get("/directory/users/42").status_code == 200
        detail = client.get(
            "/directory/users/42?_pyganini_nav_trail_key=from-contacts&"
            "_pyganini_return_to=%2Fdirectory%2Fusers%2Ftable%3Fstatus%3Dactive"
        )
        assert 'href="/directory/">Home</a>' in detail.text
        assert 'href="/directory/users">Contacts</a>' in detail.text
        assert (
            'href="/directory/users/table?status=active">Back to Contacts</a>'
            in detail.text
        )
        missing = client.get("/directory/missing")
        assert missing.status_code == 404
        assert 'data-layout="root"' in missing.text
        assert 'href="/directory/users"' in missing.text
        matched = client.get(
            "/directory/users", headers={"X-Example-Route-Error": "matched"}
        )
        matched_head = raw_client.head(
            "/directory/users", headers={"X-Example-Route-Error": "matched"}
        )
        assert matched.status_code == 418
        assert "Matched route failed" in matched.text
        assert matched.text.index('data-layout="root"') < matched.text.index(
            'data-layout="users"'
        )
        assert matched.text.index('data-layout="users"') < matched.text.index(
            'data-layout="mounted-contact-directory"'
        )
        assert 'href="/directory/users"' in matched.text
        assert matched_head.status_code == 418
        assert matched_head.content == b""
        assert matched_head.headers["content-length"] == str(len(matched.content))
        fragment_error = client.get(
            "/directory/missing", headers={"HX-Request": "true"}
        )
        assert fragment_error.status_code == 404
        assert 'data-presentation="fragment"' in fragment_error.text
        assert 'data-layout="root"' not in fragment_error.text
        css = client.get(assets.path("app.css", base_path="/directory"))
        assert css.status_code == 200
        assert css.headers["cache-control"] == ("public, max-age=31536000, immutable")
        assert (
            client.get(
                assets.path("vendor/htmx.min.js", base_path="/directory")
            ).status_code
            == 200
        )
        app_script = client.get(assets.path("app.js", base_path="/directory"))
        assert app_script.status_code == 200
