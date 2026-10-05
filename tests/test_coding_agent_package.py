from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from test_documentation import _local_link_targets

REPOSITORY = Path(__file__).resolve().parents[1]
SKILL = REPOSITORY / "docs" / "skills" / "pyganini-app"
EXAMPLE_FILE = re.compile(
    r"^### `([^`]+)`\n\n```(?:python|html|toml)\n(.*?)^```\n",
    re.MULTILINE | re.DOTALL,
)


def _copy_skill(root: Path) -> Path:
    return Path(shutil.copytree(SKILL, root / SKILL.name))


def _write_example(reference: Path, root: Path) -> None:
    files = EXAMPLE_FILE.findall(reference.read_text(encoding="ascii"))
    assert files, f"No application files in {reference.name}"
    for relative, source in files:
        path = root / relative
        assert path.resolve().is_relative_to(root.resolve())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="ascii")
        if path.suffix == ".py":
            for package in path.parents:
                if package == root:
                    break
                (package / "__init__.py").touch()


def _run(root: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    # Refactors must not import stale bytecode, even on coarse-mtime filesystems.
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, *arguments],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def _cli(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return _run(root, ["-m", "pyganini", *arguments])


def _succeeded(result: subprocess.CompletedProcess[str]) -> str:
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_distribution_metadata_selects_the_canonical_package() -> None:
    marketplace = json.loads(
        (REPOSITORY / ".claude-plugin" / "marketplace.json").read_text()
    )
    plugin = json.loads((SKILL / ".claude-plugin" / "plugin.json").read_text())
    assert marketplace["name"] == "pyganini"
    assert len(marketplace["plugins"]) == 1
    entry = marketplace["plugins"][0]
    assert entry["name"] == plugin["name"] == SKILL.name == "pyganini-app"
    assert plugin["version"] == "0.1.0"
    assert entry["source"] == {
        "source": "git-subdir",
        "url": "mobiletoly/pyganini",
        "path": SKILL.relative_to(REPOSITORY).as_posix(),
    }
    source = REPOSITORY / entry["source"]["path"]
    assert (source / "SKILL.md").is_file()
    assert (source / "agents" / "openai.yaml").is_file()
    assert not (source / "skills").exists()
    assert "skills" not in plugin  # Root single-skill discovery.
    frontmatter = (source / "SKILL.md").read_text().split("---", 2)[1]
    assert re.search(r"^name: pyganini-app$", frontmatter, re.MULTILINE)
    guide = (REPOSITORY / "docs" / "user" / "coding-agents.md").read_text()
    assert (
        "$skill-installer install https://github.com/"
        f"{entry['source']['url']}/tree/main/{entry['source']['path']}"
    ) in guide
    assert f"claude plugin install {entry['name']}@{marketplace['name']}" in guide


def test_copied_skill_references_resolve_without_framework_docs(tmp_path: Path) -> None:
    copied = _copy_skill(tmp_path)
    documents = set(copied.rglob("*.md"))
    pending = [copied / "SKILL.md"]
    visited: set[Path] = set()
    while pending:
        document = pending.pop()
        if document in visited:
            continue
        visited.add(document)
        for target in _local_link_targets(document):
            assert target.is_relative_to(copied), (document, target)
            assert target.is_file(), (document, target)
            if target.suffix == ".md":
                pending.append(target)
    assert visited == documents
    for file in copied.rglob("*"):
        if file.is_file():
            file.read_text(encoding="ascii")


def test_documented_app_generation_requests_and_route_refactor(tmp_path: Path) -> None:
    copied = _copy_skill(tmp_path)
    app_root = tmp_path / "application"
    app_root.mkdir()
    _write_example(copied / "references" / "project-setup.md", app_root)
    _succeeded(_cli(app_root, "generate"))
    _succeeded(_cli(app_root, "check"))
    listing = _succeeded(_cli(app_root, "routes", "list", "--json"))
    assert "/users/{user_id}" in listing
    explained = _succeeded(_cli(app_root, "routes", "explain", "/users/ada"))
    assert "user_id" in explained and "ada" in explained
    _succeeded(
        _run(
            app_root,
            [
                "-c",
                "from starlette.testclient import TestClient\n"
                "from app.main import app\n"
                "from app._pyganini.urls import urls\n"
                "with TestClient(app) as client:\n"
                "    home = client.get('/')\n"
                "    assert home.status_code == 200\n"
                "    assert '<!doctype html>' in home.text\n"
                "    assert 'href=\"/users/ada\"' in home.text\n"
                "    path = urls.users.by_user_id('ada').path\n"
                "    detail = client.get(path)\n"
                "    assert detail.status_code == 200\n"
                "    assert '<h1>User ada</h1>' in detail.text\n"
                "    assert '<!doctype html>' in detail.text\n",
            ],
        )
    )

    routes = app_root / "app" / "routes"
    (routes / "users").rename(routes / "people")
    handler = routes / "handlers.py"
    handler.write_text(handler.read_text().replace("urls.users", "urls.people"))
    template = routes / "page.jinja"
    template.write_text(template.read_text().replace("urls.users", "urls.people"))
    before = {
        path.name: path.read_bytes()
        for path in (app_root / "app" / "_pyganini").iterdir()
    }
    stale = _cli(app_root, "check")
    assert stale.returncode == 1, stale.stdout + stale.stderr
    assert {
        path.name: path.read_bytes()
        for path in (app_root / "app" / "_pyganini").iterdir()
    } == before
    _succeeded(_cli(app_root, "generate"))
    _succeeded(_cli(app_root, "check"))
    listing = _succeeded(_cli(app_root, "routes", "list", "--json"))
    assert "/people/{user_id}" in listing
    assert "/users/{user_id}" not in listing
    _succeeded(
        _run(
            app_root,
            [
                "-c",
                "from starlette.testclient import TestClient\n"
                "from app.main import app\n"
                "from app._pyganini.urls import urls\n"
                "assert not hasattr(urls, 'users')\n"
                "assert urls.people.by_user_id('ada').path == '/people/ada'\n"
                "with TestClient(app) as client:\n"
                "    assert 'href=\"/people/ada\"' in client.get('/').text\n"
                "    assert client.get('/people/ada').status_code == 200\n"
                "    assert client.get('/users/ada').status_code == 404\n",
            ],
        )
    )


def test_documented_htmx_action_returns_a_layout_free_fragment(tmp_path: Path) -> None:
    copied = _copy_skill(tmp_path)
    app_root = tmp_path / "application"
    app_root.mkdir()
    for reference in ("project-setup.md", "htmx-fragments-actions.md"):
        _write_example(copied / "references" / reference, app_root)
    _succeeded(_cli(app_root, "generate"))
    _succeeded(_cli(app_root, "check"))
    _succeeded(
        _run(
            app_root,
            [
                "-c",
                "from starlette.testclient import TestClient\n"
                "from app.main import app\n"
                "with TestClient(app) as client:\n"
                "    page = client.get('/')\n"
                "    assert page.status_code == 200\n"
                "    assert '<!doctype html>' in page.text\n"
                "    assert 'hx-post=\"/submit\"' in page.text\n"
                "    assert 'hx-target=\"#result\"' in page.text\n"
                "    result = client.post('/submit', data={'name': '<Ada>'}, "
                "headers={'HX-Request': 'true'})\n"
                "    assert result.status_code == 200\n"
                "    assert '<section id=\"result\">' in result.text\n"
                "    assert 'Hello &lt;Ada&gt;' in result.text\n"
                "    assert '<!doctype html>' not in result.text\n"
                "    assert result.headers['HX-Trigger'] == 'name:accepted'\n"
                "    invalid = client.post('/submit', data={'name': ''})\n"
                "    assert invalid.status_code == 422\n"
                "    assert 'Name is required.' in invalid.text\n"
                "    assert '<!doctype html>' not in invalid.text\n",
            ],
        )
    )
