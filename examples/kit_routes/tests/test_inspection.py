import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]


def _inventory(*arguments: str) -> list[dict[str, Any]]:
    result = subprocess.run(
        [sys.executable, "-m", "pyganini", "routes", "list", "--json", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = cast(dict[str, Any], json.loads(result.stdout))
    assert payload["schema"] == "pyganini.routes.v1"
    return cast(list[dict[str, Any]], payload["routes"])


def test_route_inventory_reports_the_exact_live_surface() -> None:
    rows = _inventory()

    assert {(row["path"], row["kind"]) for row in rows if row["kind"] != "layout"} == {
        ("/", "page"),
        ("/admin/reports", "page"),
        ("/admin/reports/table", "fragment"),
        ("/admin/reports/audit", "page"),
        ("/user/reports", "page"),
        ("/user/reports/table", "fragment"),
    }
    mounted = [row for row in rows if row["mount"] == "reports"]
    assert {
        (row["owner"]["path"], row["source"]["path"])
        for row in mounted
        if row["kind"] == "page" and row["source_path"] == "/"
    } == {
        (
            "app/routes/admin/reports/route.py",
            "app/mounts/reports/route.py",
        ),
        (
            "app/routes/user/reports/route.py",
            "app/mounts/reports/route.py",
        ),
    }


def test_mount_inventory_exposes_the_excluded_user_audit_row() -> None:
    rows = _inventory("--mount", "reports")
    excluded = [row for row in rows if row["selection"] == "excluded"]

    assert len(excluded) == 1
    assert excluded[0]["path"] == "/user/reports/audit"
    assert excluded[0]["kind"] == "route"
    assert excluded[0]["owner"]["path"] == "app/routes/user/reports/route.py"
    assert excluded[0]["source"]["path"] == "app/mounts/reports/audit/route.py"
    assert excluded[0]["declaration"]["implementation"] is None
