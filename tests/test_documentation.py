from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

REPOSITORY = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")
GUIDE_ENTRY = re.compile(r"^- \[([^]]+)\]\(([^)]+\.md)\)(.*)$")


def _local_link_targets(path: Path) -> list[Path]:
    targets: list[Path] = []
    for raw_target in MARKDOWN_LINK.findall(path.read_text(encoding="utf-8")):
        target = raw_target.strip().strip("<>")
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        targets.append((path.parent / unquote(parsed.path)).resolve())
    return targets


def _guide_entries(path: Path) -> list[tuple[str, str, str]]:
    entries: list[tuple[str, str, str]] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        match = GUIDE_ENTRY.fullmatch(line)
        if match is None:
            continue
        title, target, first_description = match.groups()
        description_lines = [first_description]
        for continuation in lines[index + 1 :]:
            if not continuation.startswith("  "):
                break
            description_lines.append(continuation)
        description = " ".join(" ".join(description_lines).split())
        entries.append((title, Path(target).name, description))
    return entries


def test_public_onboarding_links_resolve() -> None:
    documents = (
        REPOSITORY / "README.md",
        REPOSITORY / "docs" / "user" / "getting-started.md",
    )
    missing = [
        target
        for document in documents
        for target in _local_link_targets(document)
        if not target.exists()
    ]
    assert missing == []


def test_readme_indexes_every_runnable_example() -> None:
    readme = (REPOSITORY / "README.md").read_text(encoding="utf-8")
    example_directories = {
        path.name
        for path in (REPOSITORY / "examples").iterdir()
        if path.is_dir() and not path.name.startswith(".")
    }

    assert example_directories == {
        "chat",
        "full_feature",
        "kit_routes",
        "navigation",
        "react_island",
        "svelte_island",
    }
    assert "[Chat](examples/chat)" in readme
    assert "[Kit route mounts](examples/kit_routes)" in readme
    assert "[Navigation](examples/navigation)" in readme
    assert "[Full-feature contact directory](examples/full_feature)" in readme
    assert "[React island](examples/react_island)" in readme
    assert "[Svelte island](examples/svelte_island)" in readme


def test_user_guide_indexes_match_and_cover_all_guides() -> None:
    root_entries = _guide_entries(REPOSITORY / "README.md")
    user_entries = _guide_entries(REPOSITORY / "docs" / "user" / "README.md")
    guide_files = {
        path.name
        for path in (REPOSITORY / "docs" / "user").glob("*.md")
        if path.name != "README.md"
    }

    assert root_entries == user_entries
    assert [target for _, target, _ in root_entries] == [
        "getting-started.md",
        "installation.md",
        "project-layout.md",
        "cli.md",
        "assets.md",
        "client-islands.md",
        "route-inspection.md",
        "routes.md",
        "middleware.md",
        "errors.md",
        "route-kits.md",
        "mounted-routes.md",
        "navigation.md",
        "urls.md",
        "rendering.md",
        "sse.md",
        "browser.md",
        "template-inspection.md",
        "htmx.md",
        "csrf.md",
    ]
    assert {target for _, target, _ in root_entries} == guide_files
