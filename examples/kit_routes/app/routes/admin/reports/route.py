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


def create_admin_reports(request: Request) -> ReportKit:
    """Supply organization-wide report data to the shared source."""
    app_urls = urls.with_base_path(root_path(request))
    owner_urls = mount_urls.reports.bind(app_urls.admin.reports)
    return ReportKit(
        audience="Admin",
        heading="Admin Reports",
        description="Operational view across all teams.",
        periods=(
            PeriodOption("7d", "Last 7 days"),
            PeriodOption("30d", "Last 30 days"),
            PeriodOption("90d", "Last 90 days"),
        ),
        rows=(
            ReportRow("Revenue", "$128,400", "All teams"),
            ReportRow("Churn risk", "4 accounts", "Needs follow-up"),
        ),
        show_audit=True,
        urls=ReportURLs(
            page_url=owner_urls.path,
            table_url=owner_urls.table.path,
            audit_url=owner_urls.audit.path,
        ),
    )


Route = route_mount(
    create=create_admin_reports,
    mount="reports",
    routes=(mount_route("/"), mount_route("/audit")),
)
