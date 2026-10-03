import json
import subprocess
import sys
from pathlib import Path

import markdown_it
import pytest
from starlette.requests import Request

from pyganini import content


def request(
    path: str, *, raw: bytes | None = None, root: str = "", method: str = "GET"
) -> Request:
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "root_path": root,
        "headers": [],
        "query_string": b"",
    }
    if raw is not None:
        scope["raw_path"] = raw
    return Request(scope)


def page(
    root: Path,
    path: str = "privacy",
    *,
    body: str = "<b>trusted</b>\r\n",
    markdown: bool = False,
) -> Path:
    directory = root / path
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "page.json").write_text(
        json.dumps({"title": "<Privacy>", "description": "details"}), encoding="utf-8"
    )
    (directory / ("body.md" if markdown else "body.html")).write_bytes(
        body.encode("utf-8")
    )
    return directory


def test_html_live_pages_and_metadata(tmp_path: Path) -> None:
    directory = page(tmp_path)
    pages = content.new(content.Config(root=tmp_path))
    result = pages.resolve(request("/privacy"))
    assert result is not None
    assert (
        result.body == '<article class="pyganini-content"><b>trusted</b>\r\n</article>'
    )
    assert result.metadata.title == "<Privacy>"
    (directory / "body.html").write_text("updated", encoding="utf-8")
    assert "updated" in pages.resolve(request("/privacy")).body
    page(tmp_path, "privacy/part-one", body="new")
    assert "new" in pages.resolve(request("/privacy/part-one", method="HEAD")).body
    for path in (
        "/",
        "/absent",
        "/privacy/",
        "/Privacy",
        "/privacy/../privacy",
        "/privacy//x",
        "/privacy\\x",
    ):
        assert pages.resolve(request(path)) is None
    assert pages.resolve(request("/privacy", method="POST")) is None


def test_markdown_supported_features_and_document_local_anchors(tmp_path: Path) -> None:
    page(
        tmp_path,
        markdown=True,
        body=(
            "# Privacy part one\n"
            "\n"
            "# Privacy part one\n"
            "\n"
            "| A | B |\n"
            "| - | - |\n"
            "| 1 | 2 |\n"
            "\n"
            "- [x] done\n"
            "\n"
            "~~gone~~ www.example.com me@example.com\n"
            "\n"
            "[trusted](javascript:alert(1))\n"
            "\n"
            "<span>raw</span>\n"
        ),
    )
    pages = content.new(content.Config(root=tmp_path))
    for _ in range(2):
        body = pages.resolve(request("/privacy")).body
        for expected in (
            'id="privacy-part-one"',
            'id="privacy-part-one-1"',
            "<table>",
            "disabled",
            "checked",
            "<s>gone</s>",
            "http://www.example.com",
            "mailto:me@example.com",
            'href="javascript:',
            "<span>raw</span>",
        ):
            assert expected in body


@pytest.mark.parametrize(
    "path,raw,root,handled",
    [
        ("/privacy", b"/privacy", "", True),
        ("/privacy", b"/%70rivacy", "", False),
        ("/privacy", b"/other", "", False),
        ("/prefix/privacy", b"/prefix/privacy", "/prefix", True),
        ("/pre/fix/privacy", b"/pre%2Ffix/privacy", "/pre/fix", True),
        ("/pre/fix/privacy", b"/%70re%2ffix/privacy", "/pre/fix", True),
        (
            "/caf\u00e9/fix/privacy",
            b"/caf%C3%A9%2Ffix/privacy",
            "/caf\u00e9/fix",
            True,
        ),
        ("/pre/fix/privacy", b"/pre%2Ffix/%70rivacy", "/pre/fix", False),
        ("/pre/fix/privacy", b"/pre%2Ffix%2Fprivacy", "/pre/fix", False),
        ("/privacy", b"/privacy", "/prefix", True),
        ("/caf\u00e9/privacy", b"/caf%C3%A9/privacy", "/caf\u00e9", True),
        ("/prefix-extra/privacy", b"/prefix-extra/privacy", "/prefix", False),
        ("/privacy", None, "", True),
    ],
)
def test_original_url_evidence(
    tmp_path: Path, path: str, raw: bytes | None, root: str, handled: bool
) -> None:
    page(tmp_path)
    pages = content.new(content.Config(root=tmp_path))
    assert (pages.resolve(request(path, raw=raw, root=root)) is not None) is handled


def test_missing_linkifier_fails_at_content_import(tmp_path: Path) -> None:
    isolated = tmp_path / "site"
    isolated.mkdir()
    dependencies = Path(markdown_it.__file__).parent.parent
    for entry in dependencies.iterdir():
        if entry.name != "linkify_it":
            (isolated / entry.name).symlink_to(
                entry, target_is_directory=entry.is_dir()
            )
    source = Path(__file__).resolve().parents[1] / "src"
    script = """import importlib.util, sys
sys.path[:0] = sys.argv[1:]
assert importlib.util.find_spec('markdown_it') is not None
assert importlib.util.find_spec('mdit_py_plugins') is not None
assert importlib.util.find_spec('linkify_it') is None
try:
    import pyganini.content
except ImportError as error:
    assert 'pyganini[content]' in str(error), str(error)
    assert isinstance(error.__cause__, ModuleNotFoundError)
    assert error.__cause__.name == 'linkify_it'
else:
    raise AssertionError('content import must reject a missing linkifier')
"""
    result = subprocess.run(
        [sys.executable, "-B", "-I", "-S", "-c", script, str(source), str(isolated)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "metadata",
    [
        '{"title":"x","title":"y"}',
        '{"title":"x","other":1}',
        '{"title":null}',
        '{"title":" "}',
        '{"title":"x","description":null}',
        "[]",
        '{"title":"x"} {}',
    ],
)
def test_invalid_live_metadata_is_terminal_and_repairable(
    tmp_path: Path, metadata: str
) -> None:
    directory = page(tmp_path)
    pages = content.new(content.Config(root=tmp_path))
    (directory / "page.json").write_text(metadata, encoding="utf-8")
    with pytest.raises(content.ContentError) as invalid:
        pages.resolve(request("/privacy"))
    assert invalid.value.path == "privacy/page.json"
    assert str(tmp_path) not in str(invalid.value)
    assert metadata not in str(invalid.value)
    page(tmp_path, body="repaired")
    assert "repaired" in pages.resolve(request("/privacy")).body


def test_check_rejects_incomplete_entries_and_links_even_unrecognized(
    tmp_path: Path,
) -> None:
    directory = page(tmp_path)
    (directory / "body.md").write_text("duplicate", encoding="utf-8")
    with pytest.raises(content.ContentError):
        content.check(tmp_path)
    (directory / "body.md").unlink()
    (directory / "ignored.txt").symlink_to(directory / "body.html")
    with pytest.raises(content.ContentError) as invalid:
        content.check(tmp_path)
    assert invalid.value.path == "privacy/ignored.txt"


def test_byte_limits_are_inclusive_and_html_is_not_normalized(tmp_path: Path) -> None:
    directory = page(tmp_path, body="x" * (512 * 1024))
    content.check(tmp_path)
    (directory / "body.html").write_bytes(b"x" * (512 * 1024 + 1))
    with pytest.raises(content.ContentError) as invalid:
        content.check(tmp_path)
    assert invalid.value.path == "privacy/body.html"


def test_containers_decline_and_root_page_is_invalid(tmp_path: Path) -> None:
    page(tmp_path, "section/privacy")
    pages = content.new(content.Config(root=tmp_path))
    assert pages.resolve(request("/section")) is None
    (tmp_path / "page.json").write_text('{"title":"root"}', encoding="utf-8")
    with pytest.raises(content.ContentError):
        content.check(tmp_path)


def test_utf8_blank_metadata_and_special_files(tmp_path: Path) -> None:
    directory = page(tmp_path)
    for name, value in [
        ("page.json", b"\xff"),
        ("body.html", b"\xff"),
        ("body.html", b" \r\n\t"),
    ]:
        (directory / name).write_bytes(value)
        with pytest.raises(content.ContentError) as invalid:
            content.check(tmp_path)
        assert invalid.value.path == "privacy/" + name
        page(tmp_path)
    import os

    os.mkfifo(directory / "special")
    with pytest.raises(content.ContentError) as invalid:
        content.check(tmp_path)
    assert invalid.value.path == "privacy/special"


def test_metadata_byte_limit_and_rendered_markdown_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = page(tmp_path)
    metadata = '{"title":"x"}'
    (directory / "page.json").write_bytes(
        metadata.encode() + b" " * (16 * 1024 - len(metadata))
    )
    content.check(tmp_path)
    with (directory / "page.json").open("ab") as output:
        output.write(b" ")
    with pytest.raises(content.ContentError):
        content.check(tmp_path)
    (directory / "body.html").unlink()
    page(tmp_path, markdown=True, body="# Markdown")
    # A small source can expand beyond the output bound; prove the writer guard.
    monkeypatch.setattr(
        content._TrustedMarkdown,
        "render",
        lambda self, source: "\u00e9" * (1024 * 1024 + 1),
    )
    with pytest.raises(content.ContentError) as invalid:
        content.check(tmp_path)
    assert invalid.value.rule == "rendered Markdown exceeds 2097152 bytes"


def test_requested_page_does_not_walk_unrelated_descendants(tmp_path: Path) -> None:
    page(tmp_path)
    pages = content.new(content.Config(root=tmp_path))
    broken = tmp_path / "unrelated"
    broken.mkdir()
    (broken / "body.html").write_text("incomplete", encoding="utf-8")
    assert pages.resolve(request("/privacy")) is not None
    with pytest.raises(content.ContentError):
        content.check(tmp_path)


def test_package_resources_are_application_owned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib
    import importlib.resources

    package = tmp_path / "data_pages"
    package.mkdir()
    (package / "__init__.py").touch()
    page(package / "content", "privacy", body="packaged")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    with importlib.resources.as_file(
        importlib.resources.files("data_pages").joinpath("content")
    ) as root:
        pages = content.new(content.Config(root=root))
        assert "packaged" in pages.resolve(request("/privacy")).body


def test_deep_metadata_is_a_content_error(tmp_path: Path) -> None:
    directory = page(tmp_path)
    (directory / "page.json").write_text(
        '{"title":' + "[" * 1500 + "0" + "]" * 1500 + "}", encoding="ascii"
    )
    with pytest.raises(content.ContentError) as invalid:
        content.check(tmp_path)
    assert invalid.value.path == "privacy/page.json"
