"""Public render values and Pyganini's synchronous Jinja rendering contract."""

from __future__ import annotations

import functools
import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Literal, cast

from anyio.to_thread import run_sync as _run_sync
from jinja2 import (
    BaseLoader,
    Environment,
    PackageLoader,
    StrictUndefined,
    select_autoescape,
)
from markupsafe import Markup
from starlette.responses import HTMLResponse, Response

_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_RESERVED_HEADERS = frozenset(
    {"content-length", "content-type", "location", "transfer-encoding"}
)

type TemplateDeclarationEvidence = tuple[str, int, int]
type TemplateEvidence = tuple[
    str,
    str,
    int,
    int,
    str | None,
    TemplateDeclarationEvidence | None,
]
type LayoutEvidence = tuple[str, int, int, str, TemplateEvidence]
type InspectionMarkerEvidence = tuple[str, str, str, str, str, str, str, str, str]
type EmbeddedFragmentEvidence = tuple[str, InspectionMarkerEvidence]


class TemplateInspectionMode(StrEnum):
    """Select optional development-time Jinja render-unit inspection."""

    OFF = "off"
    COMMENTS = "comments"
    OVERLAY = "overlay"


_MARKER_LITERAL_BYTES = frozenset(
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/:._~{}"
)


def _marker_encode(value: str) -> str:
    return "".join(
        chr(byte) if byte in _MARKER_LITERAL_BYTES else f"%{byte:02X}"
        for byte in value.encode("utf-8")
    )


def _marker_id(evidence: InspectionMarkerEvidence, label: str | None) -> str:
    digest = hashlib.sha256()
    values = evidence if label is None else (*evidence, label)
    for value in values:
        raw = value.encode("utf-8")
        digest.update(str(len(raw)).encode("ascii"))
        digest.update(b":")
        digest.update(raw)
    return "u" + digest.hexdigest()


def _marker_wrap(
    content: str,
    evidence: InspectionMarkerEvidence,
    *,
    label: str | None = None,
) -> Markup:
    kind, surface, route, template, source, declaration, owner, handler, mount = (
        evidence
    )
    identifier = _marker_id(evidence, label)
    fields = [
        ("kind", kind),
        ("surface", surface),
        ("route", route),
        ("template", template),
        ("source", source),
        ("declaration", declaration),
        ("owner", owner),
        ("handler", handler),
        ("mount", mount),
    ]
    if label is not None:
        fields.append(("label", label))
    metadata = " ".join(f"{name}={_marker_encode(value)}" for name, value in fields)
    return Markup(
        f"<!--pyganini:start id={identifier} {metadata}-->"
        f"{content}"
        f"<!--pyganini:end id={identifier}-->"
    )


@dataclass(frozen=True, slots=True)
class _InspectionNamespace:
    mode: TemplateInspectionMode
    marker: InspectionMarkerEvidence | None
    embedded_fragments: Mapping[str, InspectionMarkerEvidence]

    def component(self, label: object, *, caller: object) -> Markup:
        if not isinstance(label, str):
            raise TypeError("component label must be a string")
        normalized = label.strip()
        if not normalized:
            raise ValueError("component label must contain a non-whitespace character")
        if not callable(caller):
            raise TypeError("component call block must provide a caller")
        rendered = str(cast(Callable[[], object], caller)())
        if self.mode is TemplateInspectionMode.OFF or self.marker is None:
            return Markup(rendered)
        marker: InspectionMarkerEvidence = (
            "component",
            "component",
            *self.marker[2:],
        )
        return _marker_wrap(rendered, marker, label=normalized)

    def fragment(self, path: object, *, caller: object) -> Markup:
        if not isinstance(path, str):
            raise TypeError("embedded fragment path must be a string")
        marker = self.embedded_fragments.get(path)
        if marker is None:
            raise ValueError(
                f"embedded fragment path is not available from this render unit: {path}"
            )
        if not callable(caller):
            raise TypeError("embedded fragment call block must provide a caller")
        rendered = str(cast(Callable[[], object], caller)())
        if self.mode is TemplateInspectionMode.OFF:
            return Markup(rendered)
        return _marker_wrap(rendered, marker)


class RenderFailure(RuntimeError):
    """A private rendering failure converted into a dispatch diagnostic."""

    def __init__(
        self,
        phase: Literal["render-configuration", "render-template"],
        message: str,
        *,
        details: Sequence[str] = (),
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.phase: Literal["render-configuration", "render-template"] = phase
        self.message = message
        self.details = tuple(sorted(details))
        if cause is not None:
            self.__cause__ = cause


def _mapping_copy(
    value: object,
    *,
    field_name: str,
    string_values: bool = False,
) -> MappingProxyType[str, object] | MappingProxyType[str, str]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    copied = dict(cast(Mapping[object, object], value))
    if not all(isinstance(key, str) for key in copied):
        raise TypeError(f"{field_name} keys must be strings")
    if string_values and not all(isinstance(item, str) for item in copied.values()):
        raise TypeError(f"{field_name} values must be strings")
    return MappingProxyType(cast(dict[str, object], copied))


def _validate_status(status_code: object) -> int:
    if not isinstance(status_code, int) or isinstance(status_code, bool):
        raise TypeError("status_code must be an int")
    if (200 <= status_code <= 299 and status_code not in {204, 205}) or (
        400 <= status_code <= 599
    ):
        return status_code
    raise ValueError(
        "status_code must be 200 through 299 except 204 and 205, or 400 through 599"
    )


def _validate_headers(value: object) -> MappingProxyType[str, str]:
    copied = cast(
        MappingProxyType[str, str],
        _mapping_copy(value, field_name="header", string_values=True),
    )
    folded: set[str] = set()
    for name, header_value in copied.items():
        if not name.isascii() or _HEADER_NAME.fullmatch(name) is None:
            raise ValueError("header name must be a non-empty ASCII HTTP token")
        normalized = name.lower()
        if normalized in folded:
            raise ValueError(
                "header names must be unique after case-insensitive folding"
            )
        folded.add(normalized)
        if normalized in _RESERVED_HEADERS:
            raise ValueError(f"header name {name!r} is reserved for rendered responses")
        try:
            header_value.encode("latin-1")
        except UnicodeEncodeError as error:
            raise ValueError("header value must be encodable as Latin-1") from error
        if any(
            code != 9 and (code < 32 or code == 127) for code in map(ord, header_value)
        ):
            raise ValueError("header value contains a forbidden control character")
    return copied


@dataclass(frozen=True, slots=True)
class PageMetadata:
    """Metadata supplied unchanged to every selected page layout."""

    title: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        if not isinstance(cast(object, self.title), str):
            raise TypeError("title must be a string")
        if not isinstance(cast(object, self.description), str):
            raise TypeError("description must be a string")


def _empty_object_mapping() -> Mapping[str, object]:
    return {}


def _empty_headers() -> Mapping[str, str]:
    return {}


@dataclass(frozen=True, slots=True)
class Page:
    """An immutable request to render a page and its selected layouts."""

    context: Mapping[str, object] = field(default_factory=_empty_object_mapping)
    metadata: PageMetadata = field(default_factory=PageMetadata)
    layout: Mapping[str, object] = field(default_factory=_empty_object_mapping)
    status_code: int = 200
    headers: Mapping[str, str] = field(default_factory=_empty_headers)

    def __post_init__(self) -> None:
        if not isinstance(cast(object, self.metadata), PageMetadata):
            raise TypeError("metadata must be a PageMetadata")
        object.__setattr__(
            self, "context", _mapping_copy(self.context, field_name="context")
        )
        object.__setattr__(
            self, "layout", _mapping_copy(self.layout, field_name="layout")
        )
        object.__setattr__(self, "status_code", _validate_status(self.status_code))
        object.__setattr__(self, "headers", _validate_headers(self.headers))


@dataclass(frozen=True, slots=True)
class FragmentResponse:
    """An immutable request to render one fragment without page layouts."""

    context: Mapping[str, object] = field(default_factory=_empty_object_mapping)
    status_code: int = 200
    headers: Mapping[str, str] = field(default_factory=_empty_headers)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "context", _mapping_copy(self.context, field_name="context")
        )
        object.__setattr__(self, "status_code", _validate_status(self.status_code))
        object.__setattr__(self, "headers", _validate_headers(self.headers))


type RouteResponse = Page | FragmentResponse | Response
type PageRouteResponse = Page | Response
type FragmentRouteResponse = FragmentResponse | Response


def create_environment(*, loader: BaseLoader | None = None) -> Environment:
    """Create Pyganini's strict, autoescaped, synchronous Jinja environment."""
    selected_loader = (
        PackageLoader("app", package_path="") if loader is None else loader
    )
    return Environment(
        loader=selected_loader,
        autoescape=select_autoescape(
            enabled_extensions=("html", "jinja"),
            default_for_string=True,
            default=False,
        ),
        undefined=StrictUndefined,
        enable_async=False,
    )


def validate_environment(
    environment: object,
    *,
    template_names: tuple[str, ...],
) -> Environment:
    """Validate a generated router's application-supplied environment."""
    if not isinstance(environment, Environment):
        raise RenderFailure(
            "render-configuration", "environment must be a Jinja Environment"
        )
    if environment.is_async:
        raise RenderFailure(
            "render-configuration", "Jinja environment must have async mode disabled"
        )
    try:
        strict = issubclass(environment.undefined, StrictUndefined)
    except TypeError as error:
        raise RenderFailure(
            "render-configuration",
            "Jinja environment must use StrictUndefined or a subclass",
            cause=error,
        ) from error
    if not strict:
        raise RenderFailure(
            "render-configuration",
            "Jinja environment must use StrictUndefined or a subclass",
        )
    if environment.loader is None:
        raise RenderFailure(
            "render-configuration", "Jinja environment must have a loader"
        )
    try:
        autoescape = environment.autoescape
        disabled = tuple(
            name
            for name in template_names
            if not bool(autoescape(name) if callable(autoescape) else autoescape)
        )
    except Exception as error:
        raise RenderFailure(
            "render-configuration",
            "Jinja autoescape selection failed for a generated template",
            cause=error,
        ) from error
    if disabled:
        raise RenderFailure(
            "render-configuration",
            "Jinja environment must autoescape every generated template",
            details=tuple(f"template: {name}" for name in disabled),
        )
    return environment


@dataclass(frozen=True, slots=True)
class _TemplateStageFailure(Exception):
    message: str
    details: tuple[str, ...]
    cause: Exception


def _render_template(
    environment: Environment,
    template: TemplateEvidence,
    context: Mapping[str, object],
    *,
    details: tuple[str, ...] = (),
    inspection: _InspectionNamespace,
) -> str:
    environment_name, source, line, column, template_root, declaration = template
    declaration_details: tuple[str, ...] = ()
    if declaration is not None:
        declaration_path, declaration_line, declaration_column = declaration
        declaration_details = (
            f"template declaration: "
            f"{declaration_path}:{declaration_line}:{declaration_column}",
        )
    try:
        if "pyganini_inspection" in context:
            raise ValueError("Jinja template context reserves pyganini_inspection")
        return environment.get_template(environment_name).render(
            {**context, "pyganini_inspection": inspection}
        )
    except Exception as error:
        raise _TemplateStageFailure(
            "Jinja template rendering failed",
            (
                *details,
                *declaration_details,
                f"template root: {template_root or '<none>'}",
                f"template: {environment_name}",
                f"template source: {source}:{line}:{column}",
            ),
            error,
        ) from error


def _render_page(
    environment: Environment,
    context: Mapping[str, object],
    metadata: PageMetadata,
    layout: Mapping[str, object],
    template: TemplateEvidence,
    layouts: tuple[LayoutEvidence, ...],
    *,
    mode: TemplateInspectionMode,
    marker: InspectionMarkerEvidence | None,
    layout_markers: tuple[InspectionMarkerEvidence, ...],
    embedded_fragments: tuple[EmbeddedFragmentEvidence, ...],
) -> str:
    chain = " -> ".join(
        f"{route_prefix} ({marker}:{line}:{column})"
        for marker, line, column, route_prefix, _ in layouts
    )
    chain_detail = f"selected layout chain: {chain or '<none>'}"
    child = _render_template(
        environment,
        template,
        context,
        details=(chain_detail,),
        inspection=_InspectionNamespace(mode, marker, dict(embedded_fragments)),
    )
    if mode is not TemplateInspectionMode.OFF and marker is not None:
        child = str(_marker_wrap(child, marker))
    total = len(layouts)
    for reverse_index, layout_evidence in enumerate(reversed(layouts), start=1):
        marker_path, marker_line, marker_column, route_prefix, layout_template = (
            layout_evidence
        )
        position = total - reverse_index + 1
        layout_marker = layout_markers[position - 1] if layout_markers else None
        child = _render_template(
            environment,
            layout_template,
            {"child": Markup(child), "metadata": metadata, "layout": layout},
            details=(
                chain_detail,
                f"layout chain position: {position} of {total}",
                f"layout marker: {marker_path}:{marker_line}:{marker_column}",
                f"layout route prefix: {route_prefix}",
            ),
            inspection=_InspectionNamespace(
                mode, layout_marker, dict(embedded_fragments)
            ),
        )
        if mode is not TemplateInspectionMode.OFF:
            assert layout_marker is not None
            child = str(_marker_wrap(child, layout_marker))
    return child


def _render_response_sync(
    environment: Environment,
    result: Page | FragmentResponse,
    template: TemplateEvidence,
    layouts: tuple[LayoutEvidence, ...],
    template_inspection: object,
    marker: InspectionMarkerEvidence | None,
    layout_markers: tuple[InspectionMarkerEvidence, ...],
    embedded_fragments: tuple[EmbeddedFragmentEvidence, ...],
) -> tuple[str, int, dict[str, str]]:
    if not isinstance(template_inspection, TemplateInspectionMode):
        raise TypeError("template_inspection must be a TemplateInspectionMode")
    if template_inspection is not TemplateInspectionMode.OFF and len(
        layout_markers
    ) != len(layouts):
        raise ValueError("layout inspection facts disagree with selected layouts")
    if isinstance(result, Page):
        if not isinstance(cast(object, result.metadata), PageMetadata):
            raise TypeError("metadata must be a PageMetadata")
        metadata = PageMetadata(
            title=result.metadata.title,
            description=result.metadata.description,
        )
        context = cast(
            Mapping[str, object], _mapping_copy(result.context, field_name="context")
        )
        layout = cast(
            Mapping[str, object], _mapping_copy(result.layout, field_name="layout")
        )
        status_code = _validate_status(result.status_code)
        headers = dict(_validate_headers(result.headers))
        content = _render_page(
            environment,
            context,
            metadata,
            layout,
            template,
            layouts,
            mode=template_inspection,
            marker=marker,
            layout_markers=layout_markers,
            embedded_fragments=embedded_fragments,
        )
    else:
        context = cast(
            Mapping[str, object], _mapping_copy(result.context, field_name="context")
        )
        status_code = _validate_status(result.status_code)
        headers = dict(_validate_headers(result.headers))
        content = _render_template(
            environment,
            template,
            context,
            inspection=_InspectionNamespace(
                template_inspection, marker, dict(embedded_fragments)
            ),
        )
        if template_inspection is not TemplateInspectionMode.OFF and marker is not None:
            content = str(_marker_wrap(content, marker))
    return content, status_code, headers


async def render_response(
    *,
    environment: Environment,
    result: Page | FragmentResponse,
    template: TemplateEvidence,
    layouts: tuple[LayoutEvidence, ...],
    template_inspection: TemplateInspectionMode = TemplateInspectionMode.OFF,
    marker: InspectionMarkerEvidence | None = None,
    layout_markers: tuple[InspectionMarkerEvidence, ...] = (),
    embedded_fragments: tuple[EmbeddedFragmentEvidence, ...] = (),
) -> HTMLResponse:
    """Render a validated Pyganini value in one cancellable AnyIO worker call."""
    call = functools.partial(
        _render_response_sync,
        environment,
        result,
        template,
        layouts,
        template_inspection,
        marker,
        layout_markers,
        embedded_fragments,
    )
    try:
        content, status_code, headers = await _run_sync(call, abandon_on_cancel=True)
    except _TemplateStageFailure as error:
        failure = RenderFailure(
            "render-template",
            error.message,
            details=error.details,
            cause=error.cause,
        )
        raise failure from error.cause
    return HTMLResponse(content, status_code=status_code, headers=headers)
