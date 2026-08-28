# pyright: reportPrivateUsage=false

"""Inspect direct HTMX request references in graph-selected Jinja source."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Literal
from urllib.parse import urlsplit

from jinja2 import Environment, TemplateError, nodes

from pyganini import _route_graph
from pyganini._inspection import InspectionError, _validate_explain_authority
from pyganini._paths import ProjectPaths
from pyganini._route_graph import (
    Endpoint,
    RouteGraph,
    SourcePosition,
    TemplateSource,
    iter_endpoints,
)
from pyganini._url_generation import _URLHelperPlan

type _ReferenceStatus = Literal[
    "resolved", "unmatched", "dynamic", "external", "invalid"
]
type _ReferenceMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
type _HelperShape = tuple[tuple[Literal["attribute", "call"], str], ...]

_ATTRIBUTE_METHODS: dict[str, _ReferenceMethod] = {
    "hx-get": "GET",
    "data-hx-get": "GET",
    "hx-post": "POST",
    "data-hx-post": "POST",
    "hx-put": "PUT",
    "data-hx-put": "PUT",
    "hx-patch": "PATCH",
    "data-hx-patch": "PATCH",
    "hx-delete": "DELETE",
    "data-hx-delete": "DELETE",
}
_CONTROL_DELIMITER_ENDS = {
    "block_begin": "block_end",
    "comment_begin": "comment_end",
    "line_statement_begin": "line_statement_end",
    "raw_begin": "raw_end",
}
_CONTROL_DELIMITER_BEGINS = {
    end: begin for begin, end in _CONTROL_DELIMITER_ENDS.items()
}
_CONTROL_TOKEN_TYPES = frozenset((*_CONTROL_DELIMITER_ENDS, *_CONTROL_DELIMITER_BEGINS))
_ASCII_WHITESPACE = " \t\n\r\v\f"
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


@dataclass(frozen=True, slots=True)
class _ReferenceMatch:
    path: str
    kind: Literal["page", "fragment", "action"]
    methods: tuple[str, ...]
    source: SourcePosition
    owner: SourcePosition
    mount: str | None
    source_path: str | None
    helper: str


@dataclass(frozen=True, slots=True)
class _TemplateReferenceRow:
    """One private, normalized direct HTMX template-reference occurrence."""

    status: _ReferenceStatus
    method: _ReferenceMethod
    route: str | None
    attribute: str
    source: SourcePosition
    value: str
    match: _ReferenceMatch | None


@dataclass(frozen=True, slots=True)
class _ExpressionBlock:
    original: str
    expression: str
    newline_count: int


@dataclass(frozen=True, slots=True)
class _MaskedTemplate:
    text: str
    expressions: dict[str, _ExpressionBlock]


@dataclass(frozen=True, slots=True)
class _AttributeOccurrence:
    attribute: str
    method: _ReferenceMethod
    line: int
    value: str


@dataclass(frozen=True, slots=True)
class _ChainStep:
    kind: Literal["attribute", "call"]
    name: str
    call: nodes.Call | None = None


@dataclass(frozen=True, slots=True)
class _HelperAnalysis:
    shape: _HelperShape | None
    invalid_arguments: bool


@dataclass(frozen=True, slots=True)
class _ReferenceIndexes:
    endpoints_by_method_path: dict[tuple[str, str], tuple[Endpoint, ...]]
    endpoints_by_path: dict[str, tuple[Endpoint, ...]]
    helper_by_path: dict[str, str]
    paths_by_helper_shape: dict[_HelperShape, tuple[str, ...]]


class _HTMXAttributeParser(HTMLParser):
    """Collect only supported start-tag request attributes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.occurrences: list[_AttributeOccurrence] = []

    def _handle_attributes(self, attrs: list[tuple[str, str | None]]) -> None:
        line, _ = self.getpos()
        for name, value in attrs:
            method = _ATTRIBUTE_METHODS.get(name)
            if method is not None:
                self.occurrences.append(
                    _AttributeOccurrence(name, method, line, value or "")
                )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del tag
        self._handle_attributes(attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del tag
        self._handle_attributes(attrs)


def _mask_text(value: str) -> str:
    return "".join("\n" if character == "\n" else " " for character in value)


def _append_aligned(pieces: list[str], current_line: int, line: int, value: str) -> int:
    if line < current_line:
        raise InspectionError(
            f"Jinja token line moved backward from {current_line} to {line}"
        )
    if line > current_line:
        pieces.append("\n" * (line - current_line))
        current_line = line
    pieces.append(value)
    return current_line + value.count("\n")


def _variable_line_span(tokens: tuple[tuple[int, str, str], ...]) -> int:
    first_line = tokens[0][0]
    current_line = first_line
    for line, _, value in tokens:
        if line < current_line:
            raise InspectionError(
                "Jinja variable token line moved backward from "
                f"{current_line} to {line}"
            )
        if line > current_line:
            current_line = line
        current_line += value.count("\n")
    return max(0, current_line - first_line)


def _sentinel(source: str, index: int) -> tuple[str, int]:
    candidate_index = index
    normalized_source = unescape(source)
    while True:
        candidate = f"__PYGANINI_REF_{candidate_index}__"
        if candidate not in source and candidate not in normalized_source:
            return candidate, candidate_index + 1
        candidate_index += 1


def _validate_control_delimiters(
    tokens: tuple[tuple[int, str, str], ...],
) -> None:
    stack: list[tuple[str, int]] = []
    for line, token_type, _ in tokens:
        expected_end = _CONTROL_DELIMITER_ENDS.get(token_type)
        if expected_end is not None:
            stack.append((token_type, line))
            continue
        expected_begin = _CONTROL_DELIMITER_BEGINS.get(token_type)
        if expected_begin is None:
            continue
        if not stack:
            raise InspectionError(
                f"Jinja {token_type} appeared without {expected_begin}"
            )
        active_begin, active_line = stack.pop()
        if active_begin != expected_begin:
            raise InspectionError(
                f"Jinja {token_type} at line {line} closes "
                f"{active_begin} opened at line {active_line}"
            )
    if stack:
        active_begin, active_line = stack[-1]
        raise InspectionError(
            f"Jinja {active_begin} at line {active_line} is not closed"
        )


def _mask_jinja(source: str, environment: Environment | None = None) -> _MaskedTemplate:
    """Build the source-aligned HTML projection from public Jinja tokens."""
    if environment is None:
        environment = Environment()
    tokens = tuple(environment.lex(source))
    _validate_control_delimiters(tokens)
    pieces: list[str] = []
    expressions: dict[str, _ExpressionBlock] = {}
    current_line = 1
    sentinel_index = 0
    index = 0
    while index < len(tokens):
        token = tokens[index]
        line, token_type, value = token
        if token_type == "data":
            current_line = _append_aligned(pieces, current_line, line, value)
            index += 1
            continue
        if token_type == "variable_end":
            raise InspectionError("Jinja variable end appeared without a begin")
        if token_type == "variable_begin":
            end = index + 1
            while end < len(tokens) and tokens[end][1] != "variable_end":
                if tokens[end][1] == "variable_begin":
                    raise InspectionError("nested Jinja variable block")
                end += 1
            if end >= len(tokens):
                raise InspectionError("Jinja variable block is not closed")
            variable_tokens = tokens[index : end + 1]
            sentinel, sentinel_index = _sentinel(source, sentinel_index)
            original = "".join(item[2] for item in variable_tokens)
            expression = "".join(item[2] for item in variable_tokens[1:-1])
            newline_count = original.count("\n")
            expressions[sentinel] = _ExpressionBlock(
                original, expression, newline_count
            )
            current_line = _append_aligned(pieces, current_line, line, sentinel)
            span = _variable_line_span(variable_tokens)
            if span:
                pieces.append("\n" * span)
                current_line += span
            index = end + 1
            continue
        if token_type in _CONTROL_TOKEN_TYPES or token_type not in {
            "data",
            "variable_begin",
            "variable_end",
        }:
            current_line = _append_aligned(
                pieces,
                current_line,
                line,
                _mask_text(value),
            )
            index += 1
            continue
        raise InspectionError(f"unsupported Jinja token transition {token_type!r}")
    return _MaskedTemplate("".join(pieces), expressions)


def _graph_templates(
    graph: RouteGraph,
) -> Iterator[tuple[TemplateSource, str | None]]:
    for node in graph.nodes:
        mount = node.mount
        if node.layout is not None:
            yield node.layout.template, mount
        for layout in node.layouts:
            yield layout.template, mount
        declaration = node.declaration
        if declaration is None:
            continue
        if declaration.page_template is not None:
            yield declaration.page_template, mount
        for fragment in declaration.fragments:
            if fragment.template is not None:
                yield fragment.template, mount
        for action in declaration.actions:
            if action.template is not None:
                yield action.template, mount
    for endpoint in iter_endpoints(graph):
        if endpoint.template is not None:
            yield endpoint.template, endpoint.mount


def _scan_roots(graph: RouteGraph) -> tuple[PurePosixPath, ...]:
    roots: set[PurePosixPath] = set()
    for template, mount in _graph_templates(graph):
        source_parts = template.source.path.parts
        if source_parts[:2] == ("app", "routes"):
            roots.add(PurePosixPath("app", "routes"))
        if mount is not None and source_parts[:2] == ("app", "mounts"):
            roots.add(PurePosixPath("app", "mounts", *mount.split("/")))
        if template.template_root is not None:
            roots.add(PurePosixPath("app", *template.template_root.split("/")))

    selected: list[PurePosixPath] = []
    for candidate in sorted(roots, key=lambda path: path.as_posix()):
        if any(
            candidate.parts[: len(parent.parts)] == parent.parts for parent in selected
        ):
            continue
        selected.append(candidate)
    return tuple(selected)


def _walk_template_directory(
    directory: _route_graph._RouteDirectory,
    relative: PurePosixPath,
    files: list[tuple[PurePosixPath, str]],
) -> None:
    failure: BaseException | None = None
    try:
        try:
            entries = directory.entries()
        except OSError as error:
            raise InspectionError(
                f"cannot read selected template directory {relative}: {error}"
            ) from error
        for name in entries:
            entry = relative / name
            try:
                kind = directory.entry_kind(name)
            except OSError as error:
                raise InspectionError(
                    f"cannot inspect selected template entry {entry}: {error}"
                ) from error
            if name.endswith(".jinja"):
                if kind is not _route_graph._RouteEntryKind.REGULAR:
                    raise InspectionError(
                        f"selected .jinja entry is not a regular file: {entry}"
                    )
                try:
                    content = directory.read_regular(name)
                except OSError as error:
                    raise InspectionError(
                        f"cannot read selected .jinja file {entry}: {error}"
                    ) from error
                try:
                    text = content.decode("utf-8")
                except UnicodeDecodeError as error:
                    raise InspectionError(
                        f"selected .jinja file is not valid UTF-8: {entry}: {error}"
                    ) from error
                files.append((entry, text))
                continue
            if kind is _route_graph._RouteEntryKind.SYMLINK:
                continue
            if kind is not _route_graph._RouteEntryKind.DIRECTORY:
                continue
            try:
                child = directory.open_child(name)
            except OSError as error:
                raise InspectionError(
                    f"cannot access selected template directory {entry}: {error}"
                ) from error
            _walk_template_directory(child, entry, files)
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            directory.close()
        except BaseException as close_error:
            if failure is None:
                raise InspectionError(
                    f"cannot close selected template directory {relative}: "
                    f"{close_error}"
                ) from close_error
            failure.add_note(
                f"additionally failed to close selected template directory "
                f"{relative}: {close_error}"
            )


def _read_template_files(
    paths: ProjectPaths, roots: tuple[PurePosixPath, ...]
) -> tuple[tuple[PurePosixPath, str], ...]:
    files: list[tuple[PurePosixPath, str]] = []
    for relative in roots:
        absolute_root = paths.root.joinpath(*relative.parts)
        try:
            directory = _route_graph._open_route_root(absolute_root)
        except OSError as error:
            raise InspectionError(
                f"cannot access selected template root {relative}: {error}"
            ) from error
        _walk_template_directory(directory, relative, files)
    unique: dict[PurePosixPath, str] = {}
    for path, source in files:
        unique.setdefault(path, source)
    return tuple(sorted(unique.items(), key=lambda item: item[0].as_posix()))


def _parse_isolated_expression(
    environment: Environment, expression: str
) -> nodes.Expr | None:
    try:
        tree = environment.parse("{{ " + expression + " }}")
    except TemplateError:
        return None
    if len(tree.body) != 1 or not isinstance(tree.body[0], nodes.Output):
        return None
    output = tree.body[0]
    if len(output.nodes) != 1:
        return None
    return output.nodes[0]


def _chain_steps(node: nodes.Expr) -> tuple[_ChainStep, ...] | None:
    if isinstance(node, nodes.Name):
        return (_ChainStep("attribute", node.name),)
    if isinstance(node, nodes.Getattr):
        base = _chain_steps(node.node)
        if base is None:
            return None
        return (*base, _ChainStep("attribute", node.attr))
    if isinstance(node, nodes.Call):
        base = _chain_steps(node.node)
        if not base or base[-1].kind != "attribute":
            return None
        return (
            *base[:-1],
            _ChainStep("call", base[-1].name, node),
        )
    return None


def _valid_dynamic_call(call: nodes.Call, parameter: str) -> bool:
    if call.dyn_args is not None or call.dyn_kwargs is not None:
        return False
    if len(call.args) == 1 and not call.kwargs:
        return True
    return not call.args and len(call.kwargs) == 1 and call.kwargs[0].key == parameter


def _helper_analysis(node: nodes.Expr) -> _HelperAnalysis | None:
    steps = _chain_steps(node)
    if (
        steps is None
        or not steps
        or steps[0].kind != "attribute"
        or steps[0].name != "urls"
        or steps[-1] != _ChainStep("attribute", "path")
    ):
        return None
    shape: list[tuple[Literal["attribute", "call"], str]] = []
    for step in steps[1:]:
        if step.kind == "attribute":
            shape.append(("attribute", step.name))
            continue
        if not step.name.startswith("by_") or len(step.name) == 3:
            return _HelperAnalysis(None, False)
        assert step.call is not None
        shape.append(("call", step.name))
        if not _valid_dynamic_call(step.call, step.name[3:]):
            return _HelperAnalysis(tuple(shape), True)
    return _HelperAnalysis(tuple(shape), False)


def _canonical_shapes(
    environment: Environment, plan: _URLHelperPlan
) -> tuple[dict[str, str], dict[_HelperShape, tuple[str, ...]]]:
    helper_by_path: dict[str, str] = {}
    paths: dict[_HelperShape, list[str]] = {}
    for path, expression in plan.expressions:
        node = _parse_isolated_expression(environment, expression)
        if node is None:
            raise InspectionError(
                f"canonical URL helper expression cannot be parsed: {expression}"
            )
        analysis = _helper_analysis(node)
        if analysis is None or analysis.shape is None or analysis.invalid_arguments:
            raise InspectionError(
                f"canonical URL helper expression has unsupported shape: {expression}"
            )
        helper_by_path[path] = expression
        paths.setdefault(analysis.shape, []).append(path)
    return helper_by_path, {
        shape: tuple(sorted(values)) for shape, values in paths.items()
    }


def _endpoint_indexes(
    graph: RouteGraph,
) -> tuple[
    dict[tuple[str, str], tuple[Endpoint, ...]],
    dict[str, tuple[Endpoint, ...]],
]:
    by_method_path: dict[tuple[str, str], list[Endpoint]] = {}
    by_path: dict[str, list[Endpoint]] = {}
    for endpoint in iter_endpoints(graph):
        by_path.setdefault(endpoint.path, []).append(endpoint)
        for method in endpoint.methods:
            by_method_path.setdefault((method, endpoint.path), []).append(endpoint)
    return (
        {key: tuple(value) for key, value in by_method_path.items()},
        {key: tuple(value) for key, value in by_path.items()},
    )


def _indexes(
    graph: RouteGraph, plan: _URLHelperPlan, environment: Environment
) -> _ReferenceIndexes:
    helper_by_path, paths_by_shape = _canonical_shapes(environment, plan)
    by_method_path, by_path = _endpoint_indexes(graph)
    return _ReferenceIndexes(
        by_method_path,
        by_path,
        helper_by_path,
        paths_by_shape,
    )


def _match(endpoint: Endpoint, helper: str) -> _ReferenceMatch:
    return _ReferenceMatch(
        endpoint.path,
        endpoint.kind,
        endpoint.methods,
        endpoint.source,
        endpoint.owner or endpoint.source,
        endpoint.mount,
        endpoint.source_path,
        helper,
    )


def _resolve_path(
    path: str,
    method: _ReferenceMethod,
    indexes: _ReferenceIndexes,
    *,
    unmatched_route: str,
) -> tuple[_ReferenceStatus, str | None, _ReferenceMatch | None]:
    candidates = indexes.endpoints_by_method_path.get((method, path), ())
    if len(candidates) > 1:
        raise InspectionError(
            f"reference path {path!r} reconciles to multiple {method} endpoints"
        )
    if candidates:
        helper = indexes.helper_by_path.get(path)
        if helper is None:
            raise InspectionError(f"resolved endpoint has no canonical helper: {path}")
        return "resolved", path, _match(candidates[0], helper)
    return "unmatched", unmatched_route, None


def _path_without_suffix(value: str) -> str:
    positions = [
        position for marker in ("?", "#") if (position := value.find(marker)) >= 0
    ]
    return value[: min(positions)] if positions else value


def _valid_scheme(value: str) -> bool:
    return (
        bool(value)
        and (("A" <= value[0] <= "Z") or ("a" <= value[0] <= "z"))
        and all(
            ("A" <= character <= "Z")
            or ("a" <= character <= "z")
            or ("0" <= character <= "9")
            or character in "+-."
            for character in value[1:]
        )
    )


def _valid_percent_escapes(value: str) -> bool:
    return all(
        index + 2 < len(value)
        and value[index + 1] in _HEX_DIGITS
        and value[index + 2] in _HEX_DIGITS
        for index, character in enumerate(value)
        if character == "%"
    )


def _has_ascii_control_or_whitespace(value: str) -> bool:
    return any(ord(character) <= 0x20 or ord(character) == 0x7F for character in value)


def _resolve_literal(
    value: str,
    method: _ReferenceMethod,
    indexes: _ReferenceIndexes,
) -> tuple[_ReferenceStatus, str | None, _ReferenceMatch | None]:
    if not value or _has_ascii_control_or_whitespace(value):
        return "invalid", None, None
    if not _valid_percent_escapes(value):
        return "invalid", None, None
    if value.startswith("//"):
        try:
            parsed = urlsplit(value)
            _validate_explain_authority(parsed.netloc)
            _ = parsed.hostname
            _ = parsed.port
        except ValueError:
            return "invalid", None, None
        if not parsed.netloc:
            return "invalid", None, None
        return "external", None, None
    separator = value.find("://")
    if separator > 0 and _valid_scheme(value[:separator]):
        try:
            parsed = urlsplit(value)
            _validate_explain_authority(parsed.netloc)
            _ = parsed.hostname
            _ = parsed.port
        except ValueError:
            return "invalid", None, None
        if not parsed.netloc:
            return "invalid", None, None
        return "external", None, None
    if not value.startswith("/") or value.startswith("//"):
        return "invalid", None, None
    path = _path_without_suffix(value)
    if not path:
        return "invalid", None, None
    return _resolve_path(path, method, indexes, unmatched_route=path)


def _restore_value(value: str, expressions: dict[str, _ExpressionBlock]) -> str:
    restored = _remove_expression_padding(value, expressions)
    for sentinel, block in expressions.items():
        restored = restored.replace(sentinel, block.original)
    return restored


def _remove_expression_padding(
    value: str, expressions: dict[str, _ExpressionBlock]
) -> str:
    normalized = value
    for sentinel, block in expressions.items():
        normalized = normalized.replace(
            sentinel + ("\n" * block.newline_count), sentinel
        )
    return normalized


def _candidate_expression(
    value: str, expressions: dict[str, _ExpressionBlock]
) -> tuple[_ExpressionBlock, str] | None:
    value = _remove_expression_padding(value, expressions)
    found = [sentinel for sentinel in expressions if sentinel in value]
    if len(found) != 1:
        return None
    sentinel = found[0]
    if value.count(sentinel) != 1 or not value.startswith(sentinel):
        return None
    suffix = value[len(sentinel) :]
    if suffix and not suffix.startswith(("?", "#")):
        return None
    return expressions[sentinel], suffix


def _resolve_value(
    value: str,
    method: _ReferenceMethod,
    masked: _MaskedTemplate,
    indexes: _ReferenceIndexes,
    environment: Environment,
) -> tuple[_ReferenceStatus, str | None, _ReferenceMatch | None]:
    candidate = _candidate_expression(value, masked.expressions)
    if candidate is None:
        if any(sentinel in value for sentinel in masked.expressions):
            return "dynamic", None, None
        return _resolve_literal(value, method, indexes)

    block, suffix = candidate
    expression = _parse_isolated_expression(environment, block.expression)
    if expression is None:
        return "dynamic", None, None
    if isinstance(expression, nodes.Const):
        if not isinstance(expression.value, str):
            return "dynamic", None, None
        return _resolve_literal(expression.value + suffix, method, indexes)
    analysis = _helper_analysis(expression)
    if analysis is None:
        return "dynamic", None, None
    if analysis.invalid_arguments:
        return "invalid", None, None
    if analysis.shape is None:
        return "dynamic", None, None
    paths = indexes.paths_by_helper_shape.get(analysis.shape, ())
    if not paths:
        return "dynamic", None, None
    if len(paths) != 1:
        raise InspectionError(
            f"helper shape reconciles to multiple canonical paths: {analysis.shape}"
        )
    path = paths[0]
    return _resolve_path(path, method, indexes, unmatched_route=path)


def _rows_for_file(
    path: PurePosixPath,
    source: str,
    indexes: _ReferenceIndexes,
    environment: Environment,
) -> tuple[_TemplateReferenceRow, ...]:
    try:
        masked = _mask_jinja(source, environment)
    except (InspectionError, TemplateError) as error:
        raise InspectionError(
            f"Jinja lexical analysis failed for {path}: {error}"
        ) from error
    parser = _HTMXAttributeParser()
    try:
        parser.feed(masked.text)
        parser.close()
    except Exception as error:
        raise InspectionError(f"HTMLParser failed for {path}: {error}") from error
    rows: list[_TemplateReferenceRow] = []
    for occurrence in parser.occurrences:
        try:
            status, route, match = _resolve_value(
                occurrence.value,
                occurrence.method,
                masked,
                indexes,
                environment,
            )
        except Exception as error:
            raise InspectionError(
                f"reference resolution failed for {path}: {error}"
            ) from error
        rows.append(
            _TemplateReferenceRow(
                status,
                occurrence.method,
                route,
                occurrence.attribute,
                SourcePosition(path, occurrence.line, 1),
                _restore_value(occurrence.value, masked.expressions),
                match,
            )
        )
    return tuple(rows)


def _row_sort_key(row: _TemplateReferenceRow) -> tuple[object, ...]:
    return (
        row.source.path.as_posix(),
        row.source.line,
        row.source.column,
        row.attribute,
        row.method,
        row.value,
        row.status,
        row.route or "",
    )


def inspect_template_references(
    paths: ProjectPaths,
    graph: RouteGraph,
    helper_plan: _URLHelperPlan,
) -> tuple[_TemplateReferenceRow, ...]:
    """Scan graph-selected source and return one deterministic row tuple."""
    roots = _scan_roots(graph)
    environment = Environment()
    indexes = _indexes(graph, helper_plan, environment)
    files = _read_template_files(paths, roots)
    rows = [
        row
        for path, source in files
        for row in _rows_for_file(path, source, indexes, environment)
    ]
    return tuple(sorted(rows, key=_row_sort_key))


def _position_json(position: SourcePosition) -> dict[str, object]:
    return {
        "path": position.path.as_posix(),
        "line": position.line,
        "column": position.column,
    }


def _match_json(match: _ReferenceMatch) -> dict[str, object]:
    return {
        "path": match.path,
        "kind": match.kind,
        "methods": list(match.methods),
        "source": _position_json(match.source),
        "owner": _position_json(match.owner),
        "mount": match.mount,
        "source_path": match.source_path,
        "helper": match.helper,
    }


def render_reference_json(rows: tuple[_TemplateReferenceRow, ...]) -> bytes:
    """Render the stable ``pyganini.refs.v1`` JSON payload."""
    references: list[dict[str, object]] = []
    for row in rows:
        references.append(
            {
                "status": row.status,
                "method": row.method,
                "route": row.route,
                "kind": None if row.match is None else row.match.kind,
                "attribute": row.attribute,
                "source": _position_json(row.source),
                "value": row.value,
                "matched": None if row.match is None else _match_json(row.match),
            }
        )
    payload: dict[str, object] = {
        "schema": "pyganini.refs.v1",
        "references": references,
    }
    return (json.dumps(payload, ensure_ascii=True, indent=2) + "\n").encode("utf-8")


def _display_value(value: str) -> str:
    if not value or any(
        ord(character) > 0x7F
        or character in _ASCII_WHITESPACE
        or ord(character) < 0x20
        or ord(character) == 0x7F
        for character in value
    ):
        return json.dumps(value, ensure_ascii=True)
    return value


def _display_values(row: _TemplateReferenceRow) -> tuple[str, ...]:
    return (
        row.status,
        row.method,
        _display_value(row.route) if row.route is not None else "-",
        row.match.kind if row.match is not None else "-",
        row.attribute,
        _display_value(f"{row.source.path.as_posix()}:{row.source.line}:1"),
        _display_value(row.value),
    )


_TEXT_HEADER = (
    "STATUS",
    "METHOD",
    "ROUTE",
    "KIND",
    "ATTRIBUTE",
    "SOURCE",
    "VALUE",
)


def render_reference_text(rows: tuple[_TemplateReferenceRow, ...]) -> bytes:
    """Render the stable ASCII reference table."""
    values = [_TEXT_HEADER, *(_display_values(row) for row in rows)]
    widths = tuple(
        max(len(row[index]) for row in values) for index in range(len(_TEXT_HEADER))
    )
    lines = [
        "  ".join(
            value.ljust(widths[index]) if index < len(widths) - 1 else value
            for index, value in enumerate(row)
        )
        for row in values
    ]
    try:
        return ("\n".join(lines) + "\n").encode("ascii")
    except UnicodeEncodeError as error:
        raise InspectionError(f"reference table is not ASCII: {error}") from error


def render_reference_payload(
    rows: tuple[_TemplateReferenceRow, ...], *, json_output: bool
) -> bytes:
    """Render one complete text or JSON reference payload."""
    return render_reference_json(rows) if json_output else render_reference_text(rows)
