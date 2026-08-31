from app._pyganini.urls import mount_urls, urls

from .client import ExampleClient


def test_home_links_to_both_live_owners(client: ExampleClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert 'data-page="home"' in response.text
    assert 'href="/admin/reports"' in response.text
    assert 'href="/user/reports"' in response.text


def test_admin_owner_renders_shared_page_with_bound_urls(
    client: ExampleClient,
) -> None:
    response = client.get("/admin/reports")

    assert response.status_code == 200
    assert 'data-layout="root"' in response.text
    assert 'data-layout="mounted-reports"' in response.text
    assert 'data-audience="Admin"' in response.text
    assert 'hx-get="/admin/reports/table"' in response.text
    assert 'href="/admin/reports/audit"' in response.text
    assert "$128,400" in response.text


def test_user_owner_renders_shared_page_without_admin_child(
    client: ExampleClient,
) -> None:
    response = client.get("/user/reports")

    assert response.status_code == 200
    assert 'data-audience="User"' in response.text
    assert 'hx-get="/user/reports/table"' in response.text
    assert "/user/reports/audit" not in response.text
    assert "Admin report tools" not in response.text
    assert "42 reports" in response.text


def test_only_admin_owner_selects_the_audit_child(client: ExampleClient) -> None:
    admin = client.get("/admin/reports/audit")
    user = client.get("/user/reports/audit")

    assert admin.status_code == 200
    assert 'data-page="audit"' in admin.text
    assert 'href="/admin/reports"' in admin.text
    assert user.status_code == 404


def test_fragment_uses_one_known_period_and_omits_layouts(
    client: ExampleClient,
) -> None:
    response = client.get("/admin/reports/table?period=7d")

    assert response.status_code == 200
    assert 'data-fragment="report-table"' in response.text
    assert 'data-period="7d"' in response.text
    assert 'data-layout="root"' not in response.text
    assert 'data-layout="mounted-reports"' not in response.text


def test_fragment_defaults_for_unknown_or_repeated_periods(
    client: ExampleClient,
) -> None:
    unknown = client.get("/user/reports/table?period=year")
    repeated = client.get("/user/reports/table?period=7d&period=90d")

    assert 'data-period="30d"' in unknown.text
    assert 'data-period="30d"' in repeated.text


def test_generated_mount_urls_reflect_each_owner_selection() -> None:
    admin = mount_urls.reports.bind(urls.admin.reports)
    user = mount_urls.reports.bind(urls.user.reports)

    assert admin.path == "/admin/reports"
    assert admin.table.path == "/admin/reports/table"
    assert admin.audit.path == "/admin/reports/audit"
    assert user.path == "/user/reports"
    assert user.table.path == "/user/reports/table"
    assert not hasattr(user, "audit")
