from pathlib import Path

from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from app.main import create_app


def test_content_layouts_middleware_and_generated_precedence() -> None:
    with TestClient(create_app()) as client:
        assert "Pyganini Content Pages" in client.get("/").text
        privacy = client.get("/privacy")
        assert privacy.headers["x-content-section"] == "privacy"
        assert 'data-layout="privacy"' in privacy.text
        markdown = client.get("/privacy/part-one").text
        assert 'id="privacy-part-one"' in markdown
        assert "<table>" in markdown
        assert 'data-layout="privacy"' not in client.get("/about").text
        assert client.get("/declared").text == "Declared routes take precedence."
        assert client.post("/declared").status_code == 405
        assert client.head("/privacy").content == b""
        assert client.get("/missing").status_code == 404


def test_live_edit_new_page_and_invalid_save_recovery(tmp_path: Path) -> None:
    page = tmp_path / "privacy"
    page.mkdir()
    metadata = page / "page.json"
    body = page / "body.html"
    metadata.write_text('{"title":"Privacy"}', encoding="ascii")
    body.write_text("first", encoding="ascii")
    with TestClient(
        create_app(content_root=tmp_path), raise_server_exceptions=False
    ) as client:
        assert "first" in client.get("/privacy").text
        body.write_text("second", encoding="ascii")
        assert "second" in client.get("/privacy").text
        metadata.write_text('{"title":null}', encoding="ascii")
        assert client.get("/privacy").status_code == 500
        metadata.write_text('{"title":"Repaired"}', encoding="ascii")
        assert client.get("/privacy").status_code == 200
        child = page / "new-part"
        child.mkdir()
        (child / "page.json").write_text('{"title":"New"}', encoding="ascii")
        (child / "body.md").write_text("# New part", encoding="ascii")
        assert 'id="new-part"' in client.get("/privacy/new-part").text


def test_content_and_asset_paths_under_host_mount() -> None:
    host = Starlette(routes=[Mount("/demo", app=create_app())])
    with TestClient(host) as client:
        body = client.get("/demo/privacy").text
        assert 'href="/demo/privacy"' in body
        assert 'href="/demo/assets/app.' in body
