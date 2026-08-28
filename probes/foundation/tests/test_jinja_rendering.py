import threading
from collections.abc import MutableMapping
from typing import cast

import pytest
from jinja2 import DictLoader

from foundation_probes.jinja_rendering import (
    RenderFailure,
    create_environment,
    render_explicit_layouts,
    render_explicit_layouts_in_thread,
    render_inheritance,
)


def _context(**changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "title": "Profile",
        "user_text": "<script>alert(1)</script>",
        "app_markup": "<strong>application</strong>",
    }
    values.update(changes)
    return values


def test_environment_is_sync_autoescaped_and_strict_by_default() -> None:
    environment = create_environment()
    assert environment.is_async is False
    rendered = environment.from_string("{{ value }}").render(value="<b>x</b>")
    assert rendered == "&lt;b&gt;x&lt;/b&gt;"


def test_fragment_template_escapes_user_data() -> None:
    rendered = (
        create_environment()
        .get_template("fragment.html")
        .render(user_text="<script>fragment</script>")
    )
    assert rendered == '<div id="fragment">&lt;script&gt;fragment&lt;/script&gt;</div>'


def test_inheritance_uses_configured_template_name_and_escapes_user_data() -> None:
    rendered = render_inheritance(
        create_environment(),
        configured_layout="inheritance_base.html",
        user_text="<em>unsafe</em>",
    )
    assert '<body data-layout="inheritance">' in rendered
    assert "&lt;em&gt;unsafe&lt;/em&gt;" in rendered


def test_explicit_layouts_escape_application_values_but_not_rendered_child() -> None:
    rendered = render_explicit_layouts(
        create_environment(),
        page_context=_context(),
        layout_names=("layout_inner.html", "layout_outer.html"),
        metadata={"title": "Account <one>"},
        layout_data={"theme": "light", "nav": "Home <next>"},
    )
    assert rendered.index('data-layout="outer"') < rendered.index('data-layout="inner"')
    assert rendered.count("<main>") == 1
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "&lt;strong&gt;application&lt;/strong&gt;" in rendered
    assert "Account &lt;one&gt;" in rendered
    assert "Home &lt;next&gt;" in rendered
    assert "fallback" in rendered


def test_only_framework_rendered_child_is_marked_safe() -> None:
    rendered = render_explicit_layouts(
        create_environment(),
        page_context=_context(app_markup="<i>still escaped</i>"),
        layout_names=("layout_inner.html",),
        metadata={"title": "Profile"},
        layout_data={"theme": "light", "nav": "Home"},
    )
    assert "&lt;i&gt;still escaped&lt;/i&gt;" in rendered
    assert "<main>" in rendered


def test_strict_undefined_localizes_missing_required_page_value() -> None:
    context = _context()
    del context["title"]
    with pytest.raises(RenderFailure, match=r"Jinja phase: template child\.html"):
        render_explicit_layouts(
            create_environment(),
            page_context=context,
            layout_names=(),
            metadata={},
            layout_data={},
        )


def test_default_undefined_was_compared_but_hides_required_value() -> None:
    context = _context()
    del context["title"]
    rendered = render_explicit_layouts(
        create_environment("default"),
        page_context=context,
        layout_names=(),
        metadata={},
        layout_data={},
    )
    assert "<h1></h1>" in rendered


@pytest.mark.anyio
async def test_sync_jinja_rendering_runs_outside_event_loop_thread() -> None:
    environment = create_environment()
    loop_thread = threading.get_ident()
    globals_map = cast("MutableMapping[str, object]", environment.globals)
    globals_map["render_thread"] = threading.get_ident
    environment.loader = DictLoader({"child.html": "{{ render_thread() }}"})
    rendered = await render_explicit_layouts_in_thread(
        environment,
        page_context={},
        layout_names=(),
        metadata={},
        layout_data={},
    )
    assert int(rendered) != loop_thread


@pytest.mark.anyio
async def test_render_exception_crosses_worker_boundary_with_cause() -> None:
    with pytest.raises(RenderFailure) as captured:
        await render_explicit_layouts_in_thread(
            create_environment(),
            page_context={},
            layout_names=(),
            metadata={},
            layout_data={},
        )
    assert captured.value.__cause__ is not None
