from starlette.testclient import TestClient

from app.main import create_app


def test_content_pages_receive_explicit_application_shell() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/privacy")
        assert response.status_code == 200
        assert 'data-layout="root"' in response.text
        assert "Pyganini Directory" in response.text
        assert "HTML authored by the application team." in response.text
        assert client.get("/privacy/part-one").status_code == 200
        assert client.post("/privacy").status_code == 404
