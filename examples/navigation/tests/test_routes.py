import pytest

from app._pyganini.urls import mount_urls, urls

from .client import ExampleClient

LIVE_PATHS = (
    "/",
    "/about",
    "/main",
    "/main/hq",
    "/main/hq/teams/hq-team",
    "/main/hq/teams/hq-team/analytics",
    "/main/hq/teams/hq-team/analytics/customers/contoso/report",
    "/main/hq/teams/hq-team/customers/contoso",
    "/main/hq/teams/hq-team/customers/contoso/report",
    "/main/hq/teams/hq-team/customers/contoso/report/brief",
    "/main/hq/teams/hq-team/customers/contoso/report/detailed",
    "/main/regional",
    "/main/regional/offices/sea",
    "/main/regional/offices/sea/teams/regional-team",
    "/main/regional/offices/sea/teams/regional-team/analytics",
    "/main/regional/offices/sea/teams/regional-team/analytics/customers/northwind/report",
    "/main/regional/offices/sea/teams/regional-team/customers/northwind",
    "/main/regional/offices/sea/teams/regional-team/customers/northwind/report",
    "/main/regional/offices/sea/teams/regional-team/customers/northwind/report/brief",
    "/main/regional/offices/sea/teams/regional-team/customers/northwind/report/detailed",
    "/main/reports/contoso",
)


@pytest.mark.parametrize("path", LIVE_PATHS)
def test_every_documented_path_supports_get_and_head(
    client: ExampleClient, path: str
) -> None:
    response = client.get(path)
    head = client.head(path)

    assert response.status_code == 200
    assert head.status_code == 200
    assert head.content == b""
    assert head.headers["content-length"] == str(len(response.content))


def test_hq_customer_resolves_dynamic_canonical_trail(client: ExampleClient) -> None:
    response = client.get("/main/hq/teams/hq-team/customers/contoso")

    assert response.status_code == 200
    labels = ("Home", "Main", "HQ", "HQ Team", "Contoso Retail")
    assert all(label in response.text for label in labels)
    assert '<span aria-current="page">Contoso Retail</span>' in response.text
    assert 'href="/main/hq/teams/hq-team">HQ Team</a>' in response.text


def test_regional_customer_resolves_office_team_and_customer(
    client: ExampleClient,
) -> None:
    response = client.get(
        "/main/regional/offices/sea/teams/regional-team/customers/northwind"
    )

    assert response.status_code == 200
    labels = (
        "Home",
        "Main",
        "Regional",
        "Seattle",
        "Regional Team",
        "Northwind Supply",
    )
    assert all(label in response.text for label in labels)
    assert '<span aria-current="page">Northwind Supply</span>' in response.text


@pytest.mark.parametrize(
    "path",
    (
        "/main/hq/teams/missing",
        "/main/hq/teams/regional-team",
        "/main/hq/teams/hq-team/customers/northwind",
        "/main/hq/teams/hq-team/analytics/customers/northwind/report",
        "/main/regional/offices/missing",
        "/main/regional/offices/sea/teams/hq-team",
        "/main/regional/offices/sea/teams/regional-team/customers/contoso",
        "/main/regional/offices/sea/teams/regional-team/analytics/customers/contoso/report",
        "/main/reports/missing",
    ),
)
def test_unknown_and_wrong_owner_records_return_404(
    client: ExampleClient, path: str
) -> None:
    assert client.get(path).status_code == 404


def test_customer_report_mount_keeps_outer_and_inner_layouts(
    client: ExampleClient,
) -> None:
    response = client.get(
        "/main/regional/offices/sea/teams/regional-team/customers/northwind/report/detailed"
    )

    assert response.status_code == 200
    assert response.text.index('data-layout="root"') < response.text.index(
        'data-layout="mounted-customer-report"'
    )
    assert '<span aria-current="page">Detailed</span>' in response.text
    assert 'href="/main/regional/offices/sea/teams/regional-team/customers/' in (
        response.text
    )


def test_filtered_hq_analytics_destination_preserves_safe_return(
    client: ExampleClient,
) -> None:
    source = client.get("/main/hq/teams/hq-team/analytics?risk=high&page=2")
    destination = (
        "/main/hq/teams/hq-team/analytics/customers/contoso/report?"
        "_pyganini_nav_trail_key=hq-analytics&"
        "_pyganini_return_to=%2Fmain%2Fhq%2Fteams%2Fhq-team%2Fanalytics%3F"
        "page%3D2%26risk%3Dhigh"
    )

    assert f'href="{destination.replace("&", "&amp;")}"' in source.text
    report = client.get(destination)
    assert report.status_code == 200
    assert '<span aria-current="page">Report</span>' in report.text
    assert 'href="/main/hq/teams/hq-team/analytics">Analytics</a>' in report.text
    assert (
        'href="/main/hq/teams/hq-team/analytics?page=2&amp;risk=high">'
        "Back to Contoso Retail</a>" in report.text
    )
    assert "Regional" not in report.text


def test_regional_analytics_destination_has_no_hq_label(
    client: ExampleClient,
) -> None:
    destination = (
        "/main/regional/offices/sea/teams/regional-team/analytics/customers/"
        "northwind/report?_pyganini_nav_trail_key=regional-analytics"
    )
    report = client.get(destination)

    assert report.status_code == 200
    assert "Seattle" in report.text
    assert "Regional Team" in report.text
    assert "Northwind Supply" in report.text
    assert ">HQ<" not in report.text


def test_analytics_report_uses_only_live_owner_customer_data(
    client: ExampleClient,
) -> None:
    report = client.get(
        "/main/regional/offices/sea/teams/regional-team/analytics/customers/"
        "northwind/report?risk=high"
    )

    assert report.status_code == 404


@pytest.mark.parametrize(
    "query",
    (
        "",
        "?_pyganini_nav_trail_key=unknown",
        (
            "?_pyganini_nav_trail_key=regional-analytics&"
            "_pyganini_nav_trail_key=regional-analytics"
        ),
    ),
)
def test_analytics_report_invalid_trail_key_uses_canonical_navigation(
    client: ExampleClient,
    query: str,
) -> None:
    report = client.get(
        "/main/regional/offices/sea/teams/regional-team/analytics/customers/"
        f"northwind/report{query}"
    )

    assert report.status_code == 200
    assert (
        'href="/main/regional/offices/sea/teams/regional-team/customers/'
        'northwind">Northwind Supply</a>' not in report.text
    )


@pytest.mark.parametrize(
    ("source", "trail", "expected_label"),
    (
        (
            "/main/hq/teams/hq-team/customers/contoso",
            "hq-customer",
            "Contoso Retail",
        ),
        (
            "/main/regional/offices/sea/teams/regional-team/customers/northwind",
            "regional-customer",
            "Northwind Supply",
        ),
    ),
)
def test_shared_report_destination_reconstructs_entry_trail(
    client: ExampleClient,
    source: str,
    trail: str,
    expected_label: str,
) -> None:
    source_response = client.get(source)
    marker = f"_pyganini_nav_trail_key={trail}"
    assert marker in source_response.text
    customer_identifier = source.rsplit("/", 1)[-1]
    report = client.get(f"/main/reports/{customer_identifier}?{marker}")

    assert report.status_code == 200
    assert f'data-trail="{trail}"' in report.text
    assert expected_label in report.text
    assert '<span aria-current="page">Report</span>' in report.text


def test_unsafe_or_nested_return_does_not_replace_semantic_back(
    client: ExampleClient,
) -> None:
    base = (
        "/main/hq/teams/hq-team/analytics/customers/contoso/report?"
        "_pyganini_nav_trail_key=hq-analytics&"
    )
    unsafe = client.get(base + "_pyganini_return_to=https%3A%2F%2Fevil.example")
    nested = client.get(
        base + "_pyganini_return_to=%2Fmain%2Fhq&" + "_pyganini_return_to=%2Fmain"
    )

    canonical_back = (
        'href="/main/hq/teams/hq-team/customers/contoso">Back to Contoso Retail</a>'
    )
    assert canonical_back in unsafe.text
    assert canonical_back in nested.text
    assert "evil.example" not in unsafe.text


def test_plain_generated_and_mount_paths_are_query_free() -> None:
    hq_customer = urls.main.hq.teams.by_team_id("hq-team").customers.by_customer_id(
        "contoso"
    )
    report = mount_urls.customer_report.bind(hq_customer.report)
    analytics = mount_urls.analytics.bind(
        urls.main.hq.teams.by_team_id("hq-team").analytics
    )

    assert hq_customer.path.endswith("/customers/contoso")
    assert report.path.endswith("/customers/contoso/report")
    assert report.brief.path.endswith("/customers/contoso/report/brief")
    assert analytics.path.endswith("/teams/hq-team/analytics")
    assert all(
        "?" not in path
        for path in (
            hq_customer.path,
            report.path,
            report.brief.path,
            analytics.path,
        )
    )
