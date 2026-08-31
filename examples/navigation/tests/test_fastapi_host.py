from fastapi import FastAPI
from starlette.staticfiles import StaticFiles
from starlette.testclient import TestClient

from app._pyganini.asgi import create_router
from app.main import ASSET_DIRECTORY
from assets import pyganini_assets_gen as assets

from .client import as_example_client


def test_fastapi_mount_preserves_navigation_destinations_and_back() -> None:
    host = FastAPI()
    host.mount("/directory/assets", StaticFiles(directory=ASSET_DIRECTORY))
    host.mount("/directory", create_router())

    with TestClient(host) as raw_client:
        client = as_example_client(raw_client)
        source = client.get(
            "/directory/main/hq/teams/hq-team/analytics?risk=high&page=2"
        )
        destination = (
            "/directory/main/hq/teams/hq-team/analytics/customers/contoso/report?"
            "_pyganini_nav_trail_key=hq-analytics&"
            "_pyganini_return_to=%2Fdirectory%2Fmain%2Fhq%2Fteams%2Fhq-team%2F"
            "analytics%3Fpage%3D2%26risk%3Dhigh"
        )
        assert source.status_code == 200
        assert f'href="{destination.replace("&", "&amp;")}"' in source.text
        assert f'href="{assets.path("app.css", base_path="/directory")}"' in source.text

        report = client.get(destination)
        assert report.status_code == 200
        assert 'href="/directory/main/hq">HQ</a>' in report.text
        assert (
            'href="/directory/main/hq/teams/hq-team/analytics?page=2&amp;'
            'risk=high">Back to Contoso Retail</a>' in report.text
        )
        detailed = client.get(
            "/directory/main/regional/offices/sea/teams/regional-team/customers/"
            "northwind/report/detailed"
        )
        assert detailed.status_code == 200
        assert 'href="/directory/main/regional/offices/sea">Seattle</a>' in (
            detailed.text
        )
        assert '<span aria-current="page">Detailed</span>' in detailed.text
