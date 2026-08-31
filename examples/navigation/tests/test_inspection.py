import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from .test_routes import LIVE_PATHS

ROOT = Path(__file__).resolve().parents[1]


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pyganini", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def _inventory(*arguments: str) -> list[dict[str, Any]]:
    payload = cast(
        dict[str, Any],
        json.loads(_run("routes", "list", "--json", *arguments).stdout),
    )
    assert payload["schema"] == "pyganini.routes.v1"
    return cast(list[dict[str, Any]], payload["routes"])


def test_inspection_reports_exact_live_surface_and_navigation_facts() -> None:
    rows = _inventory()
    pages = [row for row in rows if row["kind"] == "page"]

    assert {row["path"] for row in pages} == {
        path.replace("hq-team", "{team_id}")
        .replace("sea", "{office_id}")
        .replace("regional-team", "{team_id}")
        .replace("contoso", "{customer_id}")
        .replace("northwind", "{customer_id}")
        for path in LIVE_PATHS
    }
    assert all(row["methods"] == ["GET", "HEAD"] for row in pages)
    shared_report = next(
        row for row in pages if row["path"] == "/main/reports/{customer_id}"
    )
    assert shared_report["declaration"]["trail_keys"] == [
        "hq-customer",
        "regional-customer",
    ]


def test_mount_inspection_keeps_source_and_owner_evidence() -> None:
    analytics = _inventory("--mount", "analytics")
    reports = _inventory("--mount", "customer_report")

    assert {row["owner"]["path"] for row in analytics if row["kind"] == "page"} == {
        "app/routes/main/hq/teams/by_team_id/analytics/route.py",
        "app/routes/main/regional/offices/by_office_id/teams/by_team_id/analytics/route.py",
    }
    assert {row["source"]["path"] for row in analytics if row["kind"] == "page"} == {
        "app/mounts/analytics/route.py",
        "app/mounts/analytics/customers/by_customer_id/report/route.py",
    }
    assert {row["source"]["path"] for row in reports if row["kind"] == "page"} == {
        "app/mounts/customer_report/route.py",
        "app/mounts/customer_report/brief/route.py",
        "app/mounts/customer_report/detailed/route.py",
    }


def test_generation_is_repeatable() -> None:
    generated = tuple(
        path
        for root in (ROOT / "app" / "_pyganini", ROOT / "assets")
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    before = {path: path.read_bytes() for path in generated}

    _run("generate")

    assert {path: path.read_bytes() for path in generated} == before
