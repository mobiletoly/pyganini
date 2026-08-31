from pyganini import mount_route, route_mount
from starlette.requests import Request

from app._pyganini.urls import mount_urls, urls
from app.mounts.reports.handlers import (
    PeriodOption,
    ReportKit,
    ReportRow,
    ReportURLs,
)
from app.shell import root_path


def create_user_reports(request: Request) -> ReportKit:
    """Supply personal report data to the shared source."""
    app_urls = urls.with_base_path(root_path(request))
    owner_urls = mount_urls.reports.bind(app_urls.user.reports)
    return ReportKit(
        audience="User",
        heading="User Reports",
        description="Personal report view for the signed-in user.",
        periods=(
            PeriodOption("7d", "Last 7 days"),
            PeriodOption("30d", "Last 30 days"),
            PeriodOption("90d", "Last 90 days"),
        ),
        rows=(
            ReportRow("My tasks", "7 open", "Due this week"),
            ReportRow("My usage", "42 reports", "Last 30 days"),
        ),
        show_audit=False,
        urls=ReportURLs(
            page_url=owner_urls.path,
            table_url=owner_urls.table.path,
            audit_url=None,
        ),
    )


Route = route_mount(
    create=create_user_reports,
    mount="reports",
    routes=(mount_route("/"),),
)
