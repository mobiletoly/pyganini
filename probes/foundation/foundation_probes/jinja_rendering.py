from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from anyio.to_thread import run_sync
from jinja2 import (
    Environment,
    FileSystemLoader,
    StrictUndefined,
    Undefined,
    select_autoescape,
)
from jinja2.exceptions import TemplateError
from markupsafe import Markup

UndefinedPolicy = Literal["default", "strict"]
TEMPLATE_ROOT = Path(__file__).parent / "templates"


class RenderFailure(RuntimeError):
    pass


def create_environment(policy: UndefinedPolicy = "strict") -> Environment:
    undefined = StrictUndefined if policy == "strict" else Undefined
    return Environment(
        loader=FileSystemLoader(TEMPLATE_ROOT),
        autoescape=select_autoescape(
            enabled_extensions=("html",), default_for_string=True
        ),
        enable_async=False,
        undefined=undefined,
    )


def render_inheritance(
    environment: Environment,
    *,
    configured_layout: str,
    user_text: str,
) -> str:
    return environment.get_template("inheritance_page.html").render(
        configured_layout=configured_layout,
        user_text=user_text,
    )


def render_explicit_layouts(
    environment: Environment,
    *,
    page_context: Mapping[str, Any],
    layout_names: Sequence[str],
    metadata: Mapping[str, Any],
    layout_data: Mapping[str, Any],
) -> str:
    """Render the page, then wrap it from the nearest layout outward."""
    try:
        rendered = environment.get_template("child.html").render(**page_context)
    except TemplateError as error:
        raise RenderFailure(f"Jinja phase: template child.html: {error}") from error
    for position, layout_name in enumerate(layout_names):
        try:
            rendered = environment.get_template(layout_name).render(
                child_html=Markup(rendered),
                metadata=metadata,
                layout_data=layout_data,
            )
        except TemplateError as error:
            raise RenderFailure(
                f"Jinja phase: layout {layout_name} at inner-to-outer position "
                f"{position}: {error}"
            ) from error
    return rendered


async def render_explicit_layouts_in_thread(
    environment: Environment,
    *,
    page_context: Mapping[str, Any],
    layout_names: Sequence[str],
    metadata: Mapping[str, Any],
    layout_data: Mapping[str, Any],
) -> str:
    return await run_sync(
        lambda: render_explicit_layouts(
            environment,
            page_context=page_context,
            layout_names=layout_names,
            metadata=metadata,
            layout_data=layout_data,
        ),
        abandon_on_cancel=True,
    )
