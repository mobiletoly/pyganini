# pyright: reportPrivateUsage=false, reportUnusedFunction=false

"""Build Pyganini's immutable route graph without importing application code."""

from __future__ import annotations

import ast
import io
import os
import re
import stat
import tokenize
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Literal, NoReturn, Protocol

from pyganini._declarations import (
    _normalize_action_method,
    _normalize_local_path,
    _normalize_mount_identity,
    _normalize_mount_route_path,
    _normalize_template,
    _normalize_template_root,
)
from pyganini._navigation import RouteNav
from pyganini._paths import ProjectPaths
from pyganini.request_data import BodyCapture, FormCapture, capture_body, capture_form

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
_PRIVATE = re.compile(r"^_[a-z][a-z0-9_]*$")
_CONSTRUCTORS = frozenset(
    {
        "action",
        "fragment_route",
        "kit_action",
        "kit_fragment_route",
        "mount_route",
        "route",
        "route_mount",
        "route_kit",
        "RouteNav",
        "RouteMeta",
        "to",
    }
)
_ACTION_RANK = {"POST": 0, "PUT": 1, "PATCH": 2, "DELETE": 3}
_DESTINATION_NAME = re.compile(r"^[a-z][a-z0-9_-]*$", re.ASCII)
_TRAIL_KEY = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$", re.ASCII)
_IS_WINDOWS = os.name == "nt"

_GENERIC_READ = 0x80000000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000


@dataclass(frozen=True, slots=True)
class SourcePosition:
    path: PurePosixPath
    line: int = field(compare=False)
    column: int = field(compare=False)


@dataclass(frozen=True, slots=True)
class HandlerReference:
    module: str
    symbol: str
    binding: str
    source: SourcePosition


@dataclass(frozen=True, slots=True)
class TemplateSource:
    """A validated template file and its declaration evidence."""

    source: SourcePosition
    environment_name: str
    template_root: str | None = None
    declaration: SourcePosition | None = None


@dataclass(frozen=True, slots=True)
class FragmentSurface:
    path: str
    handler: HandlerReference
    source: SourcePosition
    template: TemplateSource | None


@dataclass(frozen=True, slots=True)
class ActionSurface:
    method: Literal["POST", "PUT", "PATCH", "DELETE"]
    path: str
    handler: HandlerReference
    source: SourcePosition
    template: TemplateSource | None
    request_data: BodyCapture | FormCapture | None = None
    request_data_source: SourcePosition | None = None


@dataclass(frozen=True, slots=True)
class RouteNavSource:
    value: RouteNav
    source: SourcePosition


@dataclass(frozen=True, slots=True)
class DestinationSource:
    name: str
    target_path: str
    trail_key: str | None
    source: SourcePosition
    target_selector: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RouteLabelSource:
    key: str
    value: str
    source: SourcePosition


@dataclass(frozen=True, slots=True)
class RouteMetadataSource:
    name: str | None
    name_source: SourcePosition | None
    title: str | None
    title_source: SourcePosition | None
    labels: tuple[RouteLabelSource, ...]
    meta_source: SourcePosition | None


@dataclass(frozen=True, slots=True)
class MountRouteSelection:
    path: str
    nav: RouteNavSource | None
    destinations: tuple[DestinationSource, ...]
    source: SourcePosition


@dataclass(frozen=True, slots=True)
class NormalizedRoute:
    page: HandlerReference | None
    page_template: TemplateSource | None
    fragments: tuple[FragmentSurface, ...]
    actions: tuple[ActionSurface, ...]
    kit: KitRouteBinding | None = None
    mount: MountRouteBinding | None = None
    nav: RouteNavSource | None = None
    destinations: tuple[DestinationSource, ...] = ()
    error_page_template: TemplateSource | None = None
    error_fragment_template: TemplateSource | None = None
    metadata: RouteMetadataSource | None = None


@dataclass(frozen=True, slots=True)
class KitRouteBinding:
    creator: HandlerReference | None
    template_root: str | None


@dataclass(frozen=True, slots=True)
class MountRouteBinding:
    """Static evidence for one live mounted-source owner declaration."""

    creator: HandlerReference
    mount: str
    routes: tuple[str, ...] | None
    selections: tuple[MountRouteSelection, ...] = ()


@dataclass(frozen=True, slots=True)
class LayoutSource:
    source: SourcePosition
    route_prefix: str
    template: TemplateSource


@dataclass(frozen=True, slots=True, eq=False)
class MiddlewareEntrySource:
    source: SourcePosition

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MiddlewareEntrySource):
            return NotImplemented
        return (
            self.source.path,
            self.source.line,
            self.source.column,
        ) == (
            other.source.path,
            other.source.line,
            other.source.column,
        )

    def __hash__(self) -> int:
        return hash((self.source.path, self.source.line, self.source.column))


@dataclass(frozen=True, slots=True, eq=False)
class MiddlewareSource:
    source: SourcePosition
    route_prefix: str
    entries: tuple[MiddlewareEntrySource, ...]

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MiddlewareSource):
            return NotImplemented
        return (
            self.source.path,
            self.source.line,
            self.source.column,
            self.route_prefix,
            self.entries,
        ) == (
            other.source.path,
            other.source.line,
            other.source.column,
            other.route_prefix,
            other.entries,
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.source.path,
                self.source.line,
                self.source.column,
                self.route_prefix,
                self.entries,
            )
        )


@dataclass(frozen=True, slots=True)
class RouteNode:
    source_directory: PurePosixPath
    module: str
    route_path: str
    parameters: tuple[str, ...]
    declaration: NormalizedRoute | None
    layout: LayoutSource | None
    owner: SourcePosition | None = None
    source: SourcePosition | None = None
    mount: str | None = None
    source_path: str | None = None
    layouts: tuple[LayoutSource, ...] = ()
    source_nav: RouteNavSource | None = None
    source_destinations: tuple[DestinationSource, ...] = ()
    middleware: MiddlewareSource | None = None
    middleware_chain: tuple[MiddlewareSource, ...] = ()
    error_page_template: TemplateSource | None = None
    error_fragment_template: TemplateSource | None = None


@dataclass(frozen=True, slots=True)
class MountOwner:
    """One selected live owner and its referenced source identity."""

    owner: SourcePosition
    mount: str
    selected_routes: tuple[str, ...] | None
    selections: tuple[MountRouteSelection, ...] = ()


@dataclass(frozen=True, slots=True)
class MountedRouteBinding:
    """One selected source declaration expanded below a live owner."""

    owner: SourcePosition
    mount: str
    source_route: SourcePosition
    source_path: str
    final_path: str


@dataclass(frozen=True, slots=True)
class MountedRouteCandidate:
    """One owner-specific mounted source declaration and selection result."""

    owner: SourcePosition
    mount: str
    source_route: SourcePosition
    source_path: str
    final_path: str
    declaration: NormalizedRoute
    included: bool


@dataclass(frozen=True, slots=True)
class RouteGraph:
    nodes: tuple[RouteNode, ...]
    mount_owners: tuple[MountOwner, ...] = ()
    mounted_bindings: tuple[MountedRouteBinding, ...] = ()
    mounted_candidates: tuple[MountedRouteCandidate, ...] = ()


@dataclass(frozen=True, slots=True)
class Endpoint:
    kind: Literal["page", "fragment", "action"]
    methods: tuple[str, ...]
    path: str
    parameters: tuple[str, ...]
    handler: HandlerReference
    source: SourcePosition
    template: TemplateSource | None
    creator: HandlerReference | None = None
    handler_source: SourcePosition | None = None
    owner: SourcePosition | None = None
    mount: str | None = None
    source_path: str | None = None
    node_path: str | None = None
    request_data: BodyCapture | FormCapture | None = None
    request_data_source: SourcePosition | None = None


@dataclass(frozen=True, slots=True)
class RouteDiagnostic:
    code: Literal["PYGANINI009", "PYGANINI010", "PYGANINI011"]
    phase: Literal["route-filesystem", "route-declaration", "route-collision"]
    path: PurePosixPath
    message: str
    line: int | None = None
    column: int | None = None
    field: str | None = None
    owners: tuple[SourcePosition, ...] = ()
    mount: str | None = None
    source_path: str | None = None
    final_path: str | None = None
    method: str | None = None

    def render(self) -> str:
        """Render the stable CLI diagnostic form."""
        location = self.path.as_posix()
        if self.line is not None and self.column is not None:
            location += f":{self.line}:{self.column}"
        field = f"{self.field}: " if self.field is not None else ""
        return f"{location}: {self.code} {self.phase}: {field}{self.message}"


class RouteGraphError(ValueError):
    """One or more localized static route-graph diagnostics."""

    def __init__(self, diagnostics: Sequence[RouteDiagnostic]) -> None:
        self.diagnostics = tuple(sorted(diagnostics, key=_diagnostic_key))
        super().__init__(f"route graph has {len(self.diagnostics)} diagnostic(s)")


_METHOD_ORDER = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE")


@dataclass(frozen=True, slots=True)
class _PathGroup:
    path: str
    parameters: tuple[str, ...]
    endpoints: tuple[Endpoint, ...]


class _DeclarationFailure(ValueError):
    def __init__(self, node: ast.AST, field: str, message: str) -> None:
        self.node = node
        self.field = field
        self.message = message
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class _ImportBinding:
    module: str
    symbol: str | None


@dataclass(frozen=True, slots=True)
class _BindingEvent:
    name: str
    node: ast.AST
    kind: str
    direct: bool


@dataclass(frozen=True, slots=True)
class _ParserState:
    handlers: dict[str, _ImportBinding]
    local_functions: set[str]
    invalid: dict[str, str]
    constructors: set[str]
    capture_constructors: set[str]

    def copy(self) -> _ParserState:
        return _ParserState(
            handlers=dict(self.handlers),
            local_functions=set(self.local_functions),
            invalid=dict(self.invalid),
            constructors=set(self.constructors),
            capture_constructors=set(self.capture_constructors),
        )


def _diagnostic_key(
    diagnostic: RouteDiagnostic,
) -> tuple[
    str,
    tuple[str, ...],
    str,
    str,
    str,
    str,
    str,
    int,
    int,
    str,
    str,
]:
    owners = tuple(
        owner.path.as_posix()
        for owner in sorted(
            diagnostic.owners,
            key=lambda owner: (
                owner.path.as_posix(),
                owner.line,
                owner.column,
            ),
        )
    ) or (diagnostic.path.as_posix(),)
    return (
        diagnostic.code,
        owners,
        diagnostic.mount or "",
        diagnostic.source_path or diagnostic.path.as_posix(),
        diagnostic.final_path or "",
        diagnostic.method or "",
        diagnostic.path.as_posix(),
        diagnostic.line or 0,
        diagnostic.column or 0,
        diagnostic.field or "",
        diagnostic.message,
    )


def _position(path: PurePosixPath, node: ast.AST) -> SourcePosition:
    return SourcePosition(
        path=path,
        line=getattr(node, "lineno", 1),
        column=getattr(node, "col_offset", 0) + 1,
    )


def _declaration_diagnostic(
    path: PurePosixPath,
    node: ast.AST,
    field: str,
    message: str,
) -> RouteDiagnostic:
    position = _position(path, node)
    return RouteDiagnostic(
        "PYGANINI010",
        "route-declaration",
        path,
        message,
        line=position.line,
        column=position.column,
        field=field,
    )


def _collision_diagnostic(
    source: SourcePosition,
    field: str,
    message: str,
) -> RouteDiagnostic:
    return RouteDiagnostic(
        "PYGANINI011",
        "route-collision",
        source.path,
        message,
        line=source.line,
        column=source.column,
        field=field,
    )


def _source_label(source: SourcePosition) -> str:
    return f"{source.path}:{source.line}:{source.column}"


def _groups(endpoints: Sequence[Endpoint]) -> tuple[_PathGroup, ...]:
    grouped: dict[str, list[Endpoint]] = {}
    parameters: dict[str, tuple[str, ...]] = {}
    for endpoint in endpoints:
        previous = parameters.setdefault(endpoint.path, endpoint.parameters)
        if previous != endpoint.parameters:
            raise ValueError(
                f"path {endpoint.path!r} has inconsistent parameter evidence"
            )
        grouped.setdefault(endpoint.path, []).append(endpoint)
    return tuple(
        _PathGroup(path, parameters[path], tuple(values))
        for path, values in grouped.items()
    )


def _method_endpoints(group: _PathGroup) -> dict[str, Endpoint]:
    method_endpoints: dict[str, Endpoint] = {}
    for endpoint in group.endpoints:
        for method in endpoint.methods:
            method_endpoints[method] = endpoint
    return method_endpoints


def _group_methods(group: _PathGroup) -> tuple[str, ...]:
    method_endpoints = _method_endpoints(group)
    return tuple(method for method in _METHOD_ORDER if method in method_endpoints)


def _mount_evidence_message(
    message: str,
    *,
    owners: Sequence[SourcePosition],
    mount: str,
    source: str,
    selector: str,
    final_path: str,
    phase: str,
) -> str:
    owner_labels = ", ".join(
        _source_label(owner)
        for owner in sorted(
            owners,
            key=lambda owner: (
                owner.path.as_posix(),
                owner.line,
                owner.column,
            ),
        )
    )
    return (
        f"{message}; live owner: {owner_labels}; mount identity: {mount}; "
        f"mounted source: {source}; selector: {selector}; "
        f"final path: {final_path}; evidence phase: {phase}"
    )


def _with_mount_evidence(
    diagnostic: RouteDiagnostic,
    *,
    owners: Sequence[SourcePosition],
    mount: str,
    source: str,
    selector: str,
    final_path: str,
    phase: str,
    method: str | None = None,
) -> RouteDiagnostic:
    ordered_owners = tuple(
        sorted(
            owners,
            key=lambda owner: (
                owner.path.as_posix(),
                owner.line,
                owner.column,
            ),
        )
    )
    return replace(
        diagnostic,
        message=_mount_evidence_message(
            diagnostic.message,
            owners=ordered_owners,
            mount=mount,
            source=source,
            selector=selector,
            final_path=final_path,
            phase=phase,
        ),
        owners=ordered_owners,
        mount=mount,
        source_path=source,
        final_path=final_path,
        method=method,
    )


def _with_navigation_mount_evidence(
    diagnostic: RouteDiagnostic,
    node: RouteNode,
) -> RouteDiagnostic:
    if node.mount is None:
        return diagnostic
    owner = node.owner or node.source
    source = node.source or node.owner
    if owner is None or source is None:
        return diagnostic
    return _with_mount_evidence(
        diagnostic,
        owners=(owner,),
        mount=node.mount,
        source=source.path.as_posix(),
        selector=node.source_path or "/",
        final_path=node.route_path,
        phase="static route collision",
    )


def _bound_names(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Starred):
        return _bound_names(node.value)
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple(name for item in node.elts for name in _bound_names(item))
    return ()


class _NamedExpressionVisitor(ast.NodeVisitor):
    def __init__(self, *, direct: bool) -> None:
        self.direct = direct
        self.events: list[_BindingEvent] = []

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.events.extend(
            _BindingEvent(name, node, "named expression", self.direct)
            for name in _bound_names(node.target)
        )
        self.visit(node.value)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return


def _expression_events(
    node: ast.AST | None, *, direct: bool
) -> tuple[_BindingEvent, ...]:
    if node is None:
        return ()
    visitor = _NamedExpressionVisitor(direct=direct)
    visitor.visit(node)
    return tuple(visitor.events)


def _function_expression_events(
    statement: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    direct: bool,
) -> tuple[_BindingEvent, ...]:
    expressions: list[ast.AST] = [*statement.decorator_list]
    arguments = statement.args
    expressions.extend(arguments.defaults)
    expressions.extend(item for item in arguments.kw_defaults if item is not None)
    expressions.extend(
        argument.annotation
        for argument in (
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
        )
        if argument.annotation is not None
    )
    if arguments.vararg is not None and arguments.vararg.annotation is not None:
        expressions.append(arguments.vararg.annotation)
    if arguments.kwarg is not None and arguments.kwarg.annotation is not None:
        expressions.append(arguments.kwarg.annotation)
    if statement.returns is not None:
        expressions.append(statement.returns)
    expressions.extend(statement.type_params)
    return tuple(
        event
        for expression in expressions
        for event in _expression_events(expression, direct=direct)
    )


def _pattern_events(pattern: ast.pattern, *, direct: bool) -> tuple[_BindingEvent, ...]:
    events: list[_BindingEvent] = []
    if isinstance(pattern, (ast.MatchAs, ast.MatchStar)) and pattern.name is not None:
        events.append(_BindingEvent(pattern.name, pattern, "match capture", direct))
    elif isinstance(pattern, ast.MatchMapping) and pattern.rest is not None:
        events.append(_BindingEvent(pattern.rest, pattern, "match capture", direct))
    for child in ast.iter_child_nodes(pattern):
        if isinstance(child, ast.pattern):
            events.extend(_pattern_events(child, direct=direct))
    return tuple(events)


def _statement_events(
    statement: ast.stmt,
    *,
    direct: bool,
    type_checking_is_false: bool = False,
) -> tuple[_BindingEvent, ...]:
    events: list[_BindingEvent] = []
    nested = False
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
        kind = "function definition" if direct else "conditional function definition"
        events.append(_BindingEvent(statement.name, statement, kind, direct))
        events.extend(_function_expression_events(statement, direct=direct))
    elif isinstance(statement, ast.ClassDef):
        kind = "class definition" if direct else "conditional class definition"
        events.append(_BindingEvent(statement.name, statement, kind, direct))
        expressions: list[ast.AST] = [
            *statement.decorator_list,
            *statement.bases,
            *(keyword.value for keyword in statement.keywords),
            *statement.type_params,
        ]
        for expression in expressions:
            events.extend(_expression_events(expression, direct=direct))
    elif isinstance(statement, ast.ImportFrom):
        for alias in statement.names:
            if alias.name == "*":
                events.append(_BindingEvent("*", alias, "star import", direct))
            else:
                kind = "import binding" if direct else "conditional import binding"
                events.append(
                    _BindingEvent(alias.asname or alias.name, alias, kind, direct)
                )
    elif isinstance(statement, ast.Import):
        for alias in statement.names:
            kind = "import binding" if direct else "conditional import binding"
            events.append(
                _BindingEvent(
                    alias.asname or alias.name.split(".", 1)[0], alias, kind, direct
                )
            )
    elif isinstance(statement, ast.Assign):
        kind = "assignment" if direct else "conditional assignment"
        for target in statement.targets:
            events.extend(
                _BindingEvent(name, target, kind, direct)
                for name in _bound_names(target)
            )
        events.extend(_expression_events(statement.value, direct=direct))
    elif isinstance(statement, ast.AnnAssign):
        kind = "annotated binding" if direct else "conditional annotated binding"
        events.extend(
            _BindingEvent(name, statement.target, kind, direct)
            for name in _bound_names(statement.target)
        )
        events.extend(_expression_events(statement.annotation, direct=direct))
        events.extend(_expression_events(statement.value, direct=direct))
    elif isinstance(statement, ast.AugAssign):
        kind = "augmented binding" if direct else "conditional augmented binding"
        events.extend(
            _BindingEvent(name, statement.target, kind, direct)
            for name in _bound_names(statement.target)
        )
        events.extend(_expression_events(statement.value, direct=direct))
    elif isinstance(statement, (ast.For, ast.AsyncFor)):
        events.extend(
            _BindingEvent(name, statement.target, "loop target", direct)
            for name in _bound_names(statement.target)
        )
        events.extend(_expression_events(statement.iter, direct=direct))
        nested = True
    elif isinstance(statement, (ast.With, ast.AsyncWith)):
        for item in statement.items:
            events.extend(_expression_events(item.context_expr, direct=direct))
            if item.optional_vars is not None:
                events.extend(
                    _BindingEvent(name, item.optional_vars, "with target", direct)
                    for name in _bound_names(item.optional_vars)
                )
        nested = True
    elif isinstance(statement, (ast.If, ast.While)):
        events.extend(_expression_events(statement.test, direct=direct))
        nested = True
    elif isinstance(statement, (ast.Try, ast.TryStar)):
        for handler in statement.handlers:
            events.extend(_expression_events(handler.type, direct=direct))
            if handler.name is not None:
                events.append(
                    _BindingEvent(handler.name, handler, "exception target", direct)
                )
        nested = True
    elif isinstance(statement, ast.Match):
        events.extend(_expression_events(statement.subject, direct=direct))
        for case in statement.cases:
            events.extend(_pattern_events(case.pattern, direct=direct))
            events.extend(_expression_events(case.guard, direct=direct))
        nested = True
    elif isinstance(statement, ast.Delete):
        for target in statement.targets:
            events.extend(
                _BindingEvent(name, target, "delete binding", direct)
                for name in _bound_names(target)
            )
    elif isinstance(statement, ast.TypeAlias):
        events.extend(
            _BindingEvent(name, statement.name, "type alias", direct)
            for name in _bound_names(statement.name)
        )
        events.extend(_expression_events(statement.value, direct=direct))
        for type_parameter in statement.type_params:
            events.extend(_expression_events(type_parameter, direct=direct))
    elif isinstance(statement, ast.Expr):
        events.extend(_expression_events(statement.value, direct=direct))
    elif isinstance(statement, ast.Assert):
        events.extend(_expression_events(statement.test, direct=direct))
        events.extend(_expression_events(statement.msg, direct=direct))
    elif isinstance(statement, ast.Raise):
        events.extend(_expression_events(statement.exc, direct=direct))
        events.extend(_expression_events(statement.cause, direct=direct))

    if nested:
        suites: list[list[ast.stmt]] = []
        if (
            type_checking_is_false
            and isinstance(statement, ast.If)
            and isinstance(statement.test, ast.Name)
            and statement.test.id == "TYPE_CHECKING"
        ):
            suites.append(statement.orelse)
        elif isinstance(statement, (ast.For, ast.AsyncFor, ast.While, ast.If)):
            suites.extend((statement.body, statement.orelse))
        elif isinstance(statement, (ast.With, ast.AsyncWith)):
            suites.append(statement.body)
        elif isinstance(statement, (ast.Try, ast.TryStar)):
            suites.extend((statement.body, statement.orelse, statement.finalbody))
            suites.extend(handler.body for handler in statement.handlers)
        elif isinstance(statement, ast.Match):
            suites.extend(case.body for case in statement.cases)
        for suite in suites:
            for child in suite:
                events.extend(_statement_events(child, direct=False))
    return tuple(events)


def _statement_event_map(tree: ast.Module) -> dict[int, tuple[_BindingEvent, ...]]:
    events: dict[int, tuple[_BindingEvent, ...]] = {}
    type_checking_is_false = False
    for statement in tree.body:
        statement_events = _statement_events(
            statement,
            direct=True,
            type_checking_is_false=type_checking_is_false,
        )
        events[id(statement)] = statement_events

        if any(event.name == "TYPE_CHECKING" for event in statement_events):
            type_checking_is_false = False
        if isinstance(statement, ast.ImportFrom):
            for alias in statement.names:
                binding = alias.asname or alias.name
                if binding == "TYPE_CHECKING":
                    type_checking_is_false = (
                        statement.level == 0
                        and statement.module == "typing"
                        and alias.name == "TYPE_CHECKING"
                        and alias.asname is None
                    )
    return events


def _is_direct_binding(statement: ast.stmt, event: _BindingEvent) -> bool:
    if not event.direct:
        return False
    return (
        (
            isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
            and event.kind == "function definition"
        )
        or (
            isinstance(statement, (ast.Import, ast.ImportFrom))
            and event.kind == "import binding"
        )
        or (isinstance(statement, ast.Assign) and event.kind == "assignment")
        or (isinstance(statement, ast.AnnAssign) and event.kind == "annotated binding")
        or (isinstance(statement, ast.AugAssign) and event.kind == "augmented binding")
        or (isinstance(statement, ast.ClassDef) and event.kind == "class definition")
    )


def _invalidate(state: _ParserState, name: str, kind: str) -> None:
    state.handlers.pop(name, None)
    state.local_functions.discard(name)
    state.constructors.discard(name)
    state.capture_constructors.discard(name)
    state.invalid[name] = f"handler symbol {name!r} was rebound by unsupported {kind}"


def _relative_module(package: str, level: int, module: str | None) -> str:
    if level == 0:
        if module is None:
            raise ValueError("absolute import requires a module")
        return module
    parts = package.split(".")
    keep = len(parts) - (level - 1)
    if keep <= 0:
        raise ValueError("relative import escapes the application package")
    base = parts[:keep]
    if module:
        base.extend(module.split("."))
    return ".".join(base)


def _record_import_from(
    state: _ParserState,
    statement: ast.ImportFrom,
    package: str,
) -> None:
    module = _relative_module(package, statement.level, statement.module)
    for alias in statement.names:
        if alias.name == "*":
            continue
        binding = alias.asname or alias.name
        state.handlers[binding] = _ImportBinding(module, alias.name)
        state.local_functions.discard(binding)
        state.invalid.pop(binding, None)
        state.constructors.discard(binding)
        state.capture_constructors.discard(binding)
        if (
            statement.level == 0
            and statement.module == "pyganini"
            and alias.name in _CONSTRUCTORS
            and alias.asname is None
        ):
            state.constructors.add(alias.name)
        if (
            statement.level == 0
            and statement.module == "pyganini.request_data"
            and alias.name in {"capture_body", "capture_form"}
            and alias.asname is None
        ):
            state.capture_constructors.add(alias.name)


def _record_import(state: _ParserState, statement: ast.Import) -> None:
    for alias in statement.names:
        binding = alias.asname or alias.name.split(".", 1)[0]
        module = alias.name if alias.asname else binding
        state.handlers[binding] = _ImportBinding(module, None)
        state.local_functions.discard(binding)
        state.invalid.pop(binding, None)
        state.constructors.discard(binding)
        state.capture_constructors.discard(binding)


def _resolve_handler(
    node: ast.AST,
    *,
    field: str,
    path: PurePosixPath,
    route_module: str,
    state: _ParserState,
) -> HandlerReference:
    if isinstance(node, ast.Name):
        if node.id in state.invalid:
            raise _DeclarationFailure(node, field, state.invalid[node.id])
        if node.id in state.local_functions:
            return HandlerReference(
                route_module, node.id, node.id, _position(path, node)
            )
        binding = state.handlers.get(node.id)
        if binding is not None and binding.symbol is not None:
            return HandlerReference(
                binding.module,
                binding.symbol,
                node.id,
                _position(path, node),
            )
        raise _DeclarationFailure(node, field, f"missing handler symbol {node.id!r}")
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        binding = state.handlers.get(node.value.id)
        if binding is not None and binding.symbol is None:
            return HandlerReference(
                binding.module,
                node.attr,
                node.value.id,
                _position(path, node),
            )
    raise _DeclarationFailure(
        node, field, "requires a named local or imported handler reference"
    )


def _literal_string(node: ast.AST, field: str) -> str:
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        raise _DeclarationFailure(node, field, "must be a string literal")
    return node.value


def _template_literal_string(node: ast.AST, field: str, source: str) -> str:
    value = _literal_string(node, field)
    segment = ast.get_source_segment(source, node)
    if segment is None:
        raise _DeclarationFailure(node, field, "must be one direct string literal")
    tokens = tokenize.generate_tokens(io.StringIO(segment).readline)
    if sum(token.type == tokenize.STRING for token in tokens) != 1:
        raise _DeclarationFailure(
            node,
            field,
            "must be one direct string literal; concatenation is unsupported",
        )
    return value


def _metadata_string(
    node: ast.AST,
    *,
    field: Literal["name", "title"],
    path: PurePosixPath,
    source: str,
) -> tuple[str | None, SourcePosition | None]:
    if isinstance(node, ast.Constant) and node.value is None:
        return None, None
    value = _template_literal_string(node, field, source)
    if not value:
        raise _DeclarationFailure(node, field, f"{field} must not be empty")
    return value, _position(path, node)


def _metadata_labels(
    node: ast.AST,
    *,
    path: PurePosixPath,
    source: str,
) -> tuple[RouteLabelSource, ...]:
    if not isinstance(node, ast.Dict):
        raise _DeclarationFailure(node, "meta", "labels must use a literal dictionary")
    labels: list[RouteLabelSource] = []
    seen: set[str] = set()
    for key_node, value_node in zip(node.keys, node.values, strict=True):
        if key_node is None:
            raise _DeclarationFailure(
                value_node,
                "meta",
                "label mapping unpacking is unsupported",
            )
        key = _template_literal_string(key_node, "meta", source)
        value = _template_literal_string(value_node, "meta", source)
        if not key:
            raise _DeclarationFailure(key_node, "meta", "label keys must not be empty")
        if key in seen:
            raise _DeclarationFailure(key_node, "meta", "duplicate literal label key")
        seen.add(key)
        labels.append(RouteLabelSource(key, value, _position(path, key_node)))
    return tuple(sorted(labels, key=lambda label: label.key))


def _metadata_value(
    node: ast.AST,
    *,
    path: PurePosixPath,
    source: str,
    state: _ParserState,
) -> tuple[tuple[RouteLabelSource, ...], SourcePosition | None, bool]:
    if isinstance(node, ast.Constant) and node.value is None:
        return (), None, False
    if (
        not isinstance(node, ast.Call)
        or not isinstance(node.func, ast.Name)
        or node.func.id != "RouteMeta"
        or "RouteMeta" not in state.constructors
    ):
        raise _DeclarationFailure(
            node,
            "meta",
            "must use the exact imported RouteMeta(...) constructor",
        )
    if node.args:
        raise _DeclarationFailure(
            node.args[0], "meta", "positional arguments are unsupported"
        )
    labels_node: ast.expr | None = None
    for keyword in node.keywords:
        if keyword.arg is None:
            raise _DeclarationFailure(
                keyword.value,
                "meta",
                "keyword expansion is unsupported",
            )
        if keyword.arg != "labels":
            raise _DeclarationFailure(
                keyword.value,
                "meta",
                f"unknown RouteMeta field {keyword.arg!r}",
            )
        if labels_node is not None:
            raise _DeclarationFailure(
                keyword.value,
                "meta",
                "duplicate RouteMeta labels field",
            )
        labels_node = keyword.value
    labels = (
        ()
        if labels_node is None
        else _metadata_labels(labels_node, path=path, source=source)
    )
    return labels, _position(path, node), True


def _parse_route_metadata(
    fields: dict[str, ast.expr],
    *,
    path: PurePosixPath,
    source: str,
    state: _ParserState,
) -> RouteMetadataSource | None:
    name, name_source = (
        _metadata_string(fields["name"], field="name", path=path, source=source)
        if "name" in fields
        else (None, None)
    )
    title, title_source = (
        _metadata_string(fields["title"], field="title", path=path, source=source)
        if "title" in fields
        else (None, None)
    )
    labels, meta_source, meta_present = (
        _metadata_value(fields["meta"], path=path, source=source, state=state)
        if "meta" in fields
        else ((), None, False)
    )
    if name is None and title is None and not meta_present:
        return None
    return RouteMetadataSource(
        name,
        name_source,
        title,
        title_source,
        labels,
        meta_source,
    )


def _template_root_literal(
    node: ast.AST,
    *,
    field: str,
    source: str,
) -> str | None:
    if isinstance(node, ast.Constant) and node.value is None:
        return None
    try:
        return _normalize_template_root(_template_literal_string(node, field, source))
    except _DeclarationFailure:
        raise
    except (TypeError, ValueError) as error:
        raise _DeclarationFailure(node, field, str(error)) from error


def _parse_nav_value(
    node: ast.AST,
    *,
    path: PurePosixPath,
    source: str,
    state: _ParserState,
    field: str = "nav",
) -> RouteNavSource | None:
    if isinstance(node, ast.Constant) and node.value is None:
        return None
    if (
        not isinstance(node, ast.Call)
        or not isinstance(node.func, ast.Name)
        or node.func.id != "RouteNav"
        or "RouteNav" not in state.constructors
        or node.args
    ):
        raise _DeclarationFailure(
            node,
            field,
            "must use the exact imported RouteNav(...) constructor",
        )
    values: dict[str, str] = {}
    for keyword in node.keywords:
        if keyword.arg is None:
            raise _DeclarationFailure(
                keyword.value, field, "keyword expansion is unsupported"
            )
        if keyword.arg not in {"label", "key"}:
            raise _DeclarationFailure(
                keyword.value,
                field,
                f"unknown RouteNav field {keyword.arg!r}",
            )
        if keyword.arg in values:
            raise _DeclarationFailure(keyword.value, field, "duplicate RouteNav field")
        values[keyword.arg] = _template_literal_string(
            keyword.value, keyword.arg, source
        )
    if set(values) not in ({"label"}, {"key"}):
        raise _DeclarationFailure(
            node,
            field,
            "RouteNav requires exactly one literal label or key field",
        )
    try:
        value = RouteNav(**values)
    except (TypeError, ValueError) as error:
        raise _DeclarationFailure(node, field, str(error)) from error
    return RouteNavSource(value, _position(path, node))


def _target_selector(
    node: ast.AST,
    *,
    path: PurePosixPath,
    state: _ParserState,
) -> tuple[str, ...]:
    members: list[str] = []
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        members.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name) or current.id != "urls":
        raise _DeclarationFailure(
            node,
            "target",
            "must be an exact generated urls selector chain",
        )
    binding = state.handlers.get("urls")
    if (
        binding is None
        or binding.module != "app._pyganini.urls"
        or binding.symbol != "urls"
    ):
        raise _DeclarationFailure(
            node,
            "target",
            "urls must be imported unaliased from app._pyganini.urls",
        )
    if not members:
        raise _DeclarationFailure(
            node,
            "target",
            "must select a generated URL target",
        )
    members.reverse()
    if members == ["root"]:
        return ("root",)
    for member in members:
        if _IDENTIFIER.fullmatch(member) is None:
            raise _DeclarationFailure(
                node,
                "target",
                f"URL target member {member!r} is invalid",
            )
    return tuple(members)


def _selector_path(selector: tuple[str, ...]) -> str:
    if selector == ("root",):
        return "/"
    segments = [
        "{" + member[3:] + "}" if member.startswith("by_") else member.replace("_", "-")
        for member in selector
    ]
    return "/" + "/".join(segments)


def _route_selector(path: str) -> tuple[str, ...]:
    if path == "/":
        return ("root",)
    return tuple(
        "by_" + segment[1:-1]
        if segment.startswith("{") and segment.endswith("}")
        else segment.replace("-", "_")
        for segment in path[1:].split("/")
    )


def _resolve_target_selector(
    selector: tuple[str, ...], live_paths: Sequence[str]
) -> str | None:
    candidates = tuple(
        sorted({path for path in live_paths if _route_selector(path) == selector})
    )
    return candidates[0] if len(candidates) == 1 else None


def _parse_destination(
    node: ast.AST,
    *,
    path: PurePosixPath,
    source: str,
    state: _ParserState,
) -> DestinationSource:
    if (
        not isinstance(node, ast.Call)
        or not isinstance(node.func, ast.Name)
        or node.func.id != "to"
        or "to" not in state.constructors
        or len(node.args) != 2
        or any(isinstance(argument, ast.Starred) for argument in node.args)
    ):
        raise _DeclarationFailure(
            node,
            "destinations",
            "entry must use the exact imported to(name, target, ...) helper",
        )
    if any(keyword.arg is None for keyword in node.keywords):
        raise _DeclarationFailure(
            node,
            "destinations",
            "keyword expansion is unsupported",
        )
    trail_key_node: ast.expr | None = None
    for keyword in node.keywords:
        if keyword.arg != "trail_key" or trail_key_node is not None:
            raise _DeclarationFailure(
                keyword.value,
                "trail_key",
                "destination accepts only one trail_key keyword",
            )
        trail_key_node = keyword.value
    name = _template_literal_string(node.args[0], "name", source)
    if not name.isascii() or _DESTINATION_NAME.fullmatch(name) is None:
        raise _DeclarationFailure(
            node.args[0],
            "name",
            "destination name must match ^[a-z][a-z0-9_-]*$ using ASCII",
        )
    trail_key: str | None = None
    if trail_key_node is not None and not (
        isinstance(trail_key_node, ast.Constant) and trail_key_node.value is None
    ):
        trail_key = _template_literal_string(trail_key_node, "trail_key", source)
        if not trail_key.isascii() or _TRAIL_KEY.fullmatch(trail_key) is None:
            raise _DeclarationFailure(
                trail_key_node,
                "trail_key",
                "trail_key must match the lowercase ASCII trail-key grammar",
            )
    selector = _target_selector(node.args[1], path=path, state=state)
    return DestinationSource(
        name,
        _selector_path(selector),
        trail_key,
        _position(path, node),
        selector,
    )


def _parse_destinations(
    node: ast.AST | None,
    *,
    path: PurePosixPath,
    source: str,
    state: _ParserState,
    context: Literal["live", "mounted"],
) -> tuple[DestinationSource, ...]:
    if node is None:
        return ()
    if not isinstance(node, ast.Tuple):
        raise _DeclarationFailure(
            node,
            "destinations",
            "destinations must use a literal tuple",
        )
    values = tuple(
        _parse_destination(item, path=path, source=source, state=state)
        for item in node.elts
    )
    names = [item.name.replace("-", "_") for item in values]
    if len(names) != len(set(names)):
        raise _DeclarationFailure(
            node,
            "destinations",
            "destination names must not collide after Python member normalization",
        )
    if context == "mounted" and values:
        raise _DeclarationFailure(
            node,
            "destinations",
            "mounted source route_kit(...) declarations must not declare destinations",
        )
    return values


def _template_source(
    node: ast.AST,
    *,
    field: str,
    path: PurePosixPath,
    source: str,
    template_root: str | None = None,
) -> TemplateSource | None:
    if isinstance(node, ast.Constant) and node.value is None:
        return None
    try:
        template = _normalize_template(_template_literal_string(node, field, source))
    except _DeclarationFailure:
        raise
    except (TypeError, ValueError) as error:
        raise _DeclarationFailure(node, field, str(error)) from error
    if template is None:
        return None
    base = (
        PurePosixPath(template_root)
        if template_root is not None
        else PurePosixPath(*path.parts[1:-1])
    )
    environment_name = (base / template).as_posix()
    return TemplateSource(
        SourcePosition(
            PurePosixPath("app") / PurePosixPath(environment_name),
            1,
            1,
        ),
        environment_name,
        template_root,
        _position(path, node),
    )


def _error_templates(
    fields: dict[str, ast.expr],
    *,
    path: PurePosixPath,
    source: str,
) -> tuple[TemplateSource | None, TemplateSource | None]:
    values: list[TemplateSource | None] = []
    for field_name in ("error_page_template", "error_fragment_template"):
        node = fields.get(field_name)
        values.append(
            None
            if node is None
            else _template_source(
                node,
                field=field_name,
                path=path,
                source=source,
            )
        )
    return values[0], values[1]


def _helper_call(
    node: ast.AST,
    *,
    helper: Literal["fragment_route", "action", "kit_fragment_route", "kit_action"],
    state: _ParserState,
) -> ast.Call:
    if (
        not isinstance(node, ast.Call)
        or not isinstance(node.func, ast.Name)
        or node.func.id != helper
        or helper not in state.constructors
    ):
        field = "fragments" if "fragment" in helper else "actions"
        raise _DeclarationFailure(
            node, field, f"entry must use the exact imported {helper}(...) helper"
        )
    expected = 2 if "fragment" in helper else 3
    if len(node.args) != expected or any(
        isinstance(argument, ast.Starred) for argument in node.args
    ):
        field = "fragments" if "fragment" in helper else "actions"
        raise _DeclarationFailure(
            node, field, f"{helper}(...) requires exactly {expected} arguments"
        )
    seen_template = False
    seen_request_data = False
    accepts_request_data = helper in {"action", "kit_action"}
    for keyword in node.keywords:
        if keyword.arg is None:
            raise _DeclarationFailure(
                keyword.value, "template", "keyword expansion is unsupported"
            )
        if keyword.arg != "template" and not (
            keyword.arg == "request_data" and accepts_request_data
        ):
            raise _DeclarationFailure(
                keyword.value,
                keyword.arg,
                f"unknown {helper} field {keyword.arg!r}",
            )
        if keyword.arg == "template" and seen_template:
            raise _DeclarationFailure(
                keyword.value, "template", "duplicate template field"
            )
        if keyword.arg == "template":
            seen_template = True
        elif seen_request_data:
            raise _DeclarationFailure(
                keyword.value, "request_data", "duplicate request_data field"
            )
        else:
            seen_request_data = True
    return node


def _helper_template(
    call: ast.Call,
    *,
    path: PurePosixPath,
    source: str,
    template_root: str | None = None,
) -> TemplateSource | None:
    for keyword in call.keywords:
        if keyword.arg == "template":
            return _template_source(
                keyword.value,
                field="template",
                path=path,
                source=source,
                template_root=template_root,
            )
    return None


def _literal_integer(node: ast.AST, field: str) -> int:
    if not isinstance(node, ast.Constant) or type(node.value) is not int:
        raise _DeclarationFailure(node, field, "must be an integer literal")
    return node.value


def _parse_request_data(
    call: ast.Call,
    *,
    path: PurePosixPath,
    state: _ParserState,
) -> tuple[BodyCapture | FormCapture | None, SourcePosition | None]:
    request_data_node = next(
        (keyword.value for keyword in call.keywords if keyword.arg == "request_data"),
        None,
    )
    if request_data_node is None:
        return None, None
    if (
        not isinstance(request_data_node, ast.Call)
        or not isinstance(request_data_node.func, ast.Name)
        or request_data_node.func.id not in state.capture_constructors
    ):
        raise _DeclarationFailure(
            request_data_node,
            "request_data",
            "requires an exact imported capture_body(...) or capture_form(...) call",
        )
    helper = request_data_node.func.id
    if request_data_node.args or any(
        keyword.arg is None for keyword in request_data_node.keywords
    ):
        raise _DeclarationFailure(
            request_data_node,
            "request_data",
            f"{helper}(...) requires literal keyword arguments",
        )
    expected = (
        ("max_bytes",)
        if helper == "capture_body"
        else ("max_files", "max_fields", "max_part_size", "max_upload_size")
    )
    fields: dict[str, ast.expr] = {}
    for keyword in request_data_node.keywords:
        assert keyword.arg is not None
        if keyword.arg in fields:
            raise _DeclarationFailure(
                keyword.value,
                "request_data",
                f"duplicate {helper} field {keyword.arg!r}",
            )
        if keyword.arg not in expected:
            raise _DeclarationFailure(
                keyword.value,
                "request_data",
                f"unknown {helper} field {keyword.arg!r}",
            )
        fields[keyword.arg] = keyword.value
    if set(fields) != set(expected):
        raise _DeclarationFailure(
            request_data_node,
            "request_data",
            f"{helper}(...) requires exactly {', '.join(expected)}",
        )
    values = {
        field: _literal_integer(node, "request_data") for field, node in fields.items()
    }
    try:
        capture: BodyCapture | FormCapture
        if helper == "capture_body":
            capture = capture_body(max_bytes=values["max_bytes"])
        else:
            capture = capture_form(
                max_files=values["max_files"],
                max_fields=values["max_fields"],
                max_part_size=values["max_part_size"],
                max_upload_size=values["max_upload_size"],
            )
    except (TypeError, ValueError) as error:
        raise _DeclarationFailure(
            request_data_node, "request_data", str(error)
        ) from error
    return capture, _position(path, request_data_node)


def _parse_fragment(
    node: ast.AST,
    *,
    path: PurePosixPath,
    route_module: str,
    state: _ParserState,
    source: str,
) -> FragmentSurface:
    call = _helper_call(node, helper="fragment_route", state=state)
    raw_path = _literal_string(call.args[0], "path")
    try:
        normalized = _normalize_local_path(raw_path)
    except (TypeError, ValueError) as error:
        raise _DeclarationFailure(call.args[0], "path", str(error)) from error
    handler = _resolve_handler(
        call.args[1],
        field="handler",
        path=path,
        route_module=route_module,
        state=state,
    )
    return FragmentSurface(
        normalized,
        handler,
        _position(path, call),
        _helper_template(call, path=path, source=source),
    )


def _parse_action(
    node: ast.AST,
    *,
    path: PurePosixPath,
    route_module: str,
    state: _ParserState,
    source: str,
) -> ActionSurface:
    call = _helper_call(node, helper="action", state=state)
    try:
        method = _normalize_action_method(_literal_string(call.args[0], "method"))
    except _DeclarationFailure:
        raise
    except (TypeError, ValueError) as error:
        raise _DeclarationFailure(call.args[0], "method", str(error)) from error
    try:
        normalized = _normalize_local_path(_literal_string(call.args[1], "path"))
    except _DeclarationFailure:
        raise
    except (TypeError, ValueError) as error:
        raise _DeclarationFailure(call.args[1], "path", str(error)) from error
    handler = _resolve_handler(
        call.args[2],
        field="handler",
        path=path,
        route_module=route_module,
        state=state,
    )
    request_data, request_data_source = _parse_request_data(
        call, path=path, state=state
    )
    return ActionSurface(
        method,
        normalized,
        handler,
        _position(path, call),
        _helper_template(call, path=path, source=source),
        request_data,
        request_data_source,
    )


def _parse_kit_fragment(
    node: ast.AST,
    *,
    path: PurePosixPath,
    route_module: str,
    state: _ParserState,
    source: str,
    template_root: str | None,
) -> FragmentSurface:
    call = _helper_call(node, helper="kit_fragment_route", state=state)
    raw_path = _literal_string(call.args[0], "path")
    try:
        normalized = _normalize_local_path(raw_path)
    except (TypeError, ValueError) as error:
        raise _DeclarationFailure(call.args[0], "path", str(error)) from error
    handler = _resolve_handler(
        call.args[1],
        field="handler",
        path=path,
        route_module=route_module,
        state=state,
    )
    return FragmentSurface(
        normalized,
        handler,
        _position(path, call),
        _helper_template(
            call,
            path=path,
            source=source,
            template_root=template_root,
        ),
    )


def _parse_kit_action(
    node: ast.AST,
    *,
    path: PurePosixPath,
    route_module: str,
    state: _ParserState,
    source: str,
    template_root: str | None,
) -> ActionSurface:
    call = _helper_call(node, helper="kit_action", state=state)
    try:
        method = _normalize_action_method(_literal_string(call.args[0], "method"))
    except _DeclarationFailure:
        raise
    except (TypeError, ValueError) as error:
        raise _DeclarationFailure(call.args[0], "method", str(error)) from error
    try:
        normalized = _normalize_local_path(_literal_string(call.args[1], "path"))
    except _DeclarationFailure:
        raise
    except (TypeError, ValueError) as error:
        raise _DeclarationFailure(call.args[1], "path", str(error)) from error
    handler = _resolve_handler(
        call.args[2],
        field="handler",
        path=path,
        route_module=route_module,
        state=state,
    )
    request_data, request_data_source = _parse_request_data(
        call, path=path, state=state
    )
    return ActionSurface(
        method,
        normalized,
        handler,
        _position(path, call),
        _helper_template(
            call,
            path=path,
            source=source,
            template_root=template_root,
        ),
        request_data,
        request_data_source,
    )


def _parse_route_call(
    call: ast.Call,
    *,
    path: PurePosixPath,
    route_module: str,
    state: _ParserState,
    diagnostics: list[RouteDiagnostic],
    source: str,
    context: Literal["live", "mounted"] = "live",
) -> NormalizedRoute | None:
    if not isinstance(call.func, ast.Name) or call.func.id not in {
        "route",
        "route_kit",
        "route_mount",
    }:
        diagnostics.append(
            _declaration_diagnostic(
                path,
                call.func,
                "Route",
                "requires the exact route(...), route_kit(...), or "
                "route_mount(...) constructor",
            )
        )
        return None
    if call.func.id not in state.constructors:
        diagnostics.append(
            _declaration_diagnostic(
                path,
                call.func,
                "imports",
                f"{call.func.id} must be imported unaliased from pyganini before Route",
            )
        )
        return None
    if call.args:
        diagnostics.append(
            _declaration_diagnostic(
                path, call.args[0], "Route", "positional route fields are unsupported"
            )
        )
        return None

    error_keywords = tuple(
        keyword
        for keyword in call.keywords
        if keyword.arg in {"error_page_template", "error_fragment_template"}
    )
    if error_keywords and (
        context != "live" or path != PurePosixPath("app/routes/route.py")
    ):
        for keyword in error_keywords:
            assert keyword.arg is not None
            diagnostics.append(
                _declaration_diagnostic(
                    path,
                    keyword.value,
                    keyword.arg,
                    "error templates may be declared only by app/routes/route.py",
                )
            )
        return None

    if call.func.id == "route_mount":
        return _parse_mount_route_call(
            call,
            path=path,
            route_module=route_module,
            state=state,
            diagnostics=diagnostics,
            source=source,
            context=context,
        )

    if call.func.id == "route_kit":
        return _parse_kit_route_call(
            call,
            path=path,
            route_module=route_module,
            state=state,
            diagnostics=diagnostics,
            source=source,
            context=context,
        )

    if context == "mounted":
        diagnostics.append(
            _declaration_diagnostic(
                path,
                call.func,
                "Route",
                "mounted route files must use the exact route_kit(...) constructor",
            )
        )
        return None

    fields: dict[str, ast.expr] = {}
    for keyword in call.keywords:
        if keyword.arg is None:
            diagnostics.append(
                _declaration_diagnostic(
                    path,
                    keyword.value,
                    "Route",
                    "keyword expansion is unsupported",
                )
            )
            return None
        if keyword.arg in fields:
            diagnostics.append(
                _declaration_diagnostic(
                    path, keyword.value, keyword.arg, "duplicate route field"
                )
            )
            return None
        if keyword.arg not in {
            "page",
            "template",
            "fragments",
            "actions",
            "nav",
            "destinations",
            "error_page_template",
            "error_fragment_template",
            "name",
            "title",
            "meta",
        }:
            diagnostics.append(
                _declaration_diagnostic(
                    path,
                    keyword.value,
                    "Route",
                    f"unknown route field {keyword.arg!r}",
                )
            )
            return None
        fields[keyword.arg] = keyword.value

    page: HandlerReference | None = None
    page_node = fields.get("page")
    if page_node is not None and not (
        isinstance(page_node, ast.Constant) and page_node.value is None
    ):
        try:
            page = _resolve_handler(
                page_node,
                field="page",
                path=path,
                route_module=route_module,
                state=state,
            )
        except _DeclarationFailure as error:
            diagnostics.append(
                _declaration_diagnostic(path, error.node, error.field, error.message)
            )
            return None

    page_template: TemplateSource | None = None
    template_node = fields.get("template")
    if template_node is not None:
        try:
            page_template = _template_source(
                template_node,
                field="template",
                path=path,
                source=source,
            )
        except _DeclarationFailure as error:
            diagnostics.append(
                _declaration_diagnostic(path, error.node, error.field, error.message)
            )
            return None
    if page is None and page_template is not None:
        diagnostics.append(
            _declaration_diagnostic(
                path,
                template_node if template_node is not None else call,
                "template",
                "page template requires a page handler",
            )
        )
        return None

    fragments: list[FragmentSurface] = []
    fragments_node = fields.get("fragments")
    if fragments_node is not None:
        if not isinstance(fragments_node, ast.Tuple):
            diagnostics.append(
                _declaration_diagnostic(
                    path,
                    fragments_node,
                    "fragments",
                    "fragments must use a literal tuple",
                )
            )
            return None
        for item in fragments_node.elts:
            try:
                fragments.append(
                    _parse_fragment(
                        item,
                        path=path,
                        route_module=route_module,
                        state=state,
                        source=source,
                    )
                )
            except _DeclarationFailure as error:
                diagnostics.append(
                    _declaration_diagnostic(
                        path, error.node, error.field, error.message
                    )
                )
                return None

    actions: list[ActionSurface] = []
    actions_node = fields.get("actions")
    if actions_node is not None:
        if not isinstance(actions_node, ast.Tuple):
            diagnostics.append(
                _declaration_diagnostic(
                    path,
                    actions_node,
                    "actions",
                    "actions must use a literal tuple",
                )
            )
            return None
        for item in actions_node.elts:
            try:
                actions.append(
                    _parse_action(
                        item,
                        path=path,
                        route_module=route_module,
                        state=state,
                        source=source,
                    )
                )
            except _DeclarationFailure as error:
                diagnostics.append(
                    _declaration_diagnostic(
                        path, error.node, error.field, error.message
                    )
                )
                return None

    try:
        nav = (
            _parse_nav_value(
                fields["nav"],
                path=path,
                source=source,
                state=state,
            )
            if "nav" in fields
            else None
        )
        destinations = _parse_destinations(
            fields.get("destinations"),
            path=path,
            source=source,
            state=state,
            context=context,
        )
        error_page_template, error_fragment_template = _error_templates(
            fields,
            path=path,
            source=source,
        )
        metadata = _parse_route_metadata(
            fields,
            path=path,
            source=source,
            state=state,
        )
    except _DeclarationFailure as error:
        diagnostics.append(
            _declaration_diagnostic(path, error.node, error.field, error.message)
        )
        return None

    if page is None and not fragments and not actions and metadata is not None:
        diagnostics.append(
            _declaration_diagnostic(
                path,
                call,
                "Route",
                "route metadata requires a page, fragment, or action",
            )
        )
        return None
    if (
        page is None
        and not fragments
        and not actions
        and error_page_template is None
        and error_fragment_template is None
    ):
        diagnostics.append(
            _declaration_diagnostic(
                path, call, "Route", "route must declare a page, fragment, or action"
            )
        )
        return None
    index_fragment = next(
        (fragment for fragment in fragments if fragment.path == "/"), None
    )
    if page is not None and index_fragment is not None:
        diagnostics.append(
            _declaration_diagnostic(
                path,
                call,
                "fragments",
                "route cannot declare both a page and an index fragment",
            )
        )
        return None

    fragment_seen: dict[str, FragmentSurface] = {}
    for fragment_surface in fragments:
        previous_fragment = fragment_seen.get(fragment_surface.path)
        if previous_fragment is not None:
            diagnostics.append(
                _collision_diagnostic(
                    fragment_surface.source,
                    "fragments",
                    f"normalized fragment path {fragment_surface.path!r} is owned "
                    f"by {_source_label(previous_fragment.source)} and "
                    f"{_source_label(fragment_surface.source)}",
                )
            )
        else:
            fragment_seen[fragment_surface.path] = fragment_surface

    action_seen: dict[tuple[str, str], ActionSurface] = {}
    for action_surface in actions:
        key = (action_surface.method, action_surface.path)
        previous_action = action_seen.get(key)
        if previous_action is not None:
            diagnostics.append(
                _collision_diagnostic(
                    action_surface.source,
                    "actions",
                    f"normalized action {action_surface.method} "
                    f"{action_surface.path} is owned by "
                    f"{_source_label(previous_action.source)} and "
                    f"{_source_label(action_surface.source)}",
                )
            )
        else:
            action_seen[key] = action_surface
    if any(
        diagnostic.path == path and diagnostic.code == "PYGANINI011"
        for diagnostic in diagnostics
    ):
        return None

    fragments.sort(
        key=lambda item: (
            item.path != "/",
            item.path,
            item.handler.module,
            item.handler.symbol,
        )
    )
    actions.sort(
        key=lambda item: (
            item.path,
            _ACTION_RANK[item.method],
            item.handler.module,
            item.handler.symbol,
        )
    )
    return NormalizedRoute(
        page,
        page_template,
        tuple(fragments),
        tuple(actions),
        nav=nav,
        destinations=destinations,
        error_page_template=error_page_template,
        error_fragment_template=error_fragment_template,
        metadata=metadata,
    )


def _parse_mount_route_call(
    call: ast.Call,
    *,
    path: PurePosixPath,
    route_module: str,
    state: _ParserState,
    diagnostics: list[RouteDiagnostic],
    source: str,
    context: Literal["live", "mounted"],
) -> NormalizedRoute | None:
    if context == "mounted":
        diagnostics.append(
            _declaration_diagnostic(
                path,
                call.func,
                "Route",
                "route_mount(...) is only supported below app/routes",
            )
        )
        return None
    if call.args:
        diagnostics.append(
            _declaration_diagnostic(
                path,
                call.args[0],
                "Route",
                "positional route_mount fields are unsupported",
            )
        )
        return None
    fields: dict[str, ast.expr] = {}
    for keyword in call.keywords:
        if keyword.arg is None:
            diagnostics.append(
                _declaration_diagnostic(
                    path,
                    keyword.value,
                    "Route",
                    "keyword expansion is unsupported",
                )
            )
            return None
        if keyword.arg in fields:
            diagnostics.append(
                _declaration_diagnostic(
                    path, keyword.value, keyword.arg, "duplicate route field"
                )
            )
            return None
        if keyword.arg not in {
            "create",
            "mount",
            "routes",
            "error_page_template",
            "error_fragment_template",
        }:
            diagnostics.append(
                _declaration_diagnostic(
                    path,
                    keyword.value,
                    "Route",
                    f"unknown route_mount field {keyword.arg!r}",
                )
            )
            return None
        fields[keyword.arg] = keyword.value

    creator_node = fields.get("create")
    mount_node = fields.get("mount")
    if creator_node is None:
        diagnostics.append(
            _declaration_diagnostic(
                path, call, "create", "route_mount requires a create handler"
            )
        )
        return None
    if mount_node is None:
        diagnostics.append(
            _declaration_diagnostic(
                path, call, "mount", "route_mount requires a mount identity"
            )
        )
        return None
    try:
        creator = _resolve_handler(
            creator_node,
            field="create",
            path=path,
            route_module=route_module,
            state=state,
        )
        mount = _normalize_mount_identity(
            _template_literal_string(mount_node, "mount", source)
        )
    except _DeclarationFailure as error:
        diagnostics.append(
            _declaration_diagnostic(path, error.node, error.field, error.message)
        )
        return None
    except (TypeError, ValueError) as error:
        diagnostics.append(
            _declaration_diagnostic(path, mount_node, "mount", str(error))
        )
        return None

    routes_node = fields.get("routes")
    routes: tuple[str, ...] | None = None
    if routes_node is not None and not (
        isinstance(routes_node, ast.Constant) and routes_node.value is None
    ):
        if not isinstance(routes_node, ast.Tuple):
            diagnostics.append(
                _declaration_diagnostic(
                    path,
                    routes_node,
                    "routes",
                    "routes must use a literal tuple of mount_route(...) calls",
                )
            )
            return None
        if not routes_node.elts:
            diagnostics.append(
                _declaration_diagnostic(
                    path, routes_node, "routes", "routes must not be empty"
                )
            )
            return None
        selected: list[str] = []
        selections: list[MountRouteSelection] = []
        for item in routes_node.elts:
            if (
                not isinstance(item, ast.Call)
                or not isinstance(item.func, ast.Name)
                or item.func.id != "mount_route"
                or "mount_route" not in state.constructors
                or len(item.args) != 1
                or any(isinstance(argument, ast.Starred) for argument in item.args)
            ):
                diagnostics.append(
                    _declaration_diagnostic(
                        path,
                        item,
                        "routes",
                        "routes entries must use the exact mount_route("
                        "<string literal>) helper",
                    )
                )
                return None
            selection_fields: dict[str, ast.expr] = {}
            for keyword in item.keywords:
                if keyword.arg is None:
                    diagnostics.append(
                        _declaration_diagnostic(
                            path,
                            keyword.value,
                            "routes",
                            "keyword expansion is unsupported",
                        )
                    )
                    return None
                if keyword.arg in selection_fields or keyword.arg not in {
                    "nav",
                    "destinations",
                }:
                    diagnostics.append(
                        _declaration_diagnostic(
                            path,
                            keyword.value,
                            keyword.arg or "routes",
                            f"unknown mount_route field {keyword.arg!r}",
                        )
                    )
                    return None
                selection_fields[keyword.arg] = keyword.value
            try:
                selected_path = _normalize_mount_route_path(
                    _template_literal_string(item.args[0], "path", source)
                )
                nav = (
                    _parse_nav_value(
                        selection_fields["nav"],
                        path=path,
                        source=source,
                        state=state,
                        field="nav",
                    )
                    if "nav" in selection_fields
                    else None
                )
                destinations = _parse_destinations(
                    selection_fields.get("destinations"),
                    path=path,
                    source=source,
                    state=state,
                    context="live",
                )
            except _DeclarationFailure as error:
                diagnostics.append(
                    _declaration_diagnostic(
                        path, error.node, error.field, error.message
                    )
                )
                return None
            except (TypeError, ValueError) as error:
                diagnostics.append(
                    _declaration_diagnostic(path, item.args[0], "path", str(error))
                )
                return None
            if selected_path in selected:
                diagnostics.append(
                    _declaration_diagnostic(
                        path,
                        item,
                        "routes",
                        f"routes contains duplicate route pattern: {selected_path}",
                    )
                )
                return None
            selected.append(selected_path)
            selections.append(
                MountRouteSelection(
                    selected_path,
                    nav,
                    destinations,
                    _position(path, item),
                )
            )
        routes = tuple(selected)
    else:
        selections = []

    try:
        error_page_template, error_fragment_template = _error_templates(
            fields,
            path=path,
            source=source,
        )
    except _DeclarationFailure as error:
        diagnostics.append(
            _declaration_diagnostic(path, error.node, error.field, error.message)
        )
        return None

    return NormalizedRoute(
        None,
        None,
        (),
        (),
        mount=MountRouteBinding(creator, mount, routes, tuple(selections)),
        error_page_template=error_page_template,
        error_fragment_template=error_fragment_template,
    )


def _parse_kit_route_call(
    call: ast.Call,
    *,
    path: PurePosixPath,
    route_module: str,
    state: _ParserState,
    diagnostics: list[RouteDiagnostic],
    source: str,
    context: Literal["live", "mounted"] = "live",
) -> NormalizedRoute | None:
    fields: dict[str, ast.expr] = {}
    for keyword in call.keywords:
        if keyword.arg is None:
            diagnostics.append(
                _declaration_diagnostic(
                    path,
                    keyword.value,
                    "Route",
                    "keyword expansion is unsupported",
                )
            )
            return None
        if keyword.arg in fields:
            diagnostics.append(
                _declaration_diagnostic(
                    path, keyword.value, keyword.arg, "duplicate route field"
                )
            )
            return None
        if keyword.arg not in {
            "create",
            "template_root",
            "page",
            "template",
            "fragments",
            "actions",
            "nav",
            "destinations",
            "error_page_template",
            "error_fragment_template",
            "name",
            "title",
            "meta",
        }:
            diagnostics.append(
                _declaration_diagnostic(
                    path,
                    keyword.value,
                    "Route",
                    f"unknown route_kit field {keyword.arg!r}",
                )
            )
            return None
        fields[keyword.arg] = keyword.value

    creator: HandlerReference | None = None
    creator_node = fields.get("create")
    if context == "mounted":
        if creator_node is not None:
            diagnostics.append(
                _declaration_diagnostic(
                    path,
                    creator_node,
                    "create",
                    "mounted route_kit(...) must omit create",
                )
            )
            return None
    else:
        if creator_node is None:
            diagnostics.append(
                _declaration_diagnostic(
                    path, call, "create", "route_kit requires a create handler"
                )
            )
            return None
        try:
            creator = _resolve_handler(
                creator_node,
                field="create",
                path=path,
                route_module=route_module,
                state=state,
            )
        except _DeclarationFailure as error:
            diagnostics.append(
                _declaration_diagnostic(path, error.node, error.field, error.message)
            )
            return None

    template_root: str | None = None
    template_root_node = fields.get("template_root")
    if context == "mounted" and template_root_node is not None:
        diagnostics.append(
            _declaration_diagnostic(
                path,
                template_root_node,
                "template_root",
                "mounted route_kit(...) must omit template_root",
            )
        )
        return None
    if template_root_node is not None:
        try:
            template_root = _template_root_literal(
                template_root_node,
                field="template_root",
                source=source,
            )
        except _DeclarationFailure as error:
            diagnostics.append(
                _declaration_diagnostic(path, error.node, error.field, error.message)
            )
            return None

    page: HandlerReference | None = None
    page_node = fields.get("page")
    if page_node is not None and not (
        isinstance(page_node, ast.Constant) and page_node.value is None
    ):
        try:
            page = _resolve_handler(
                page_node,
                field="page",
                path=path,
                route_module=route_module,
                state=state,
            )
        except _DeclarationFailure as error:
            diagnostics.append(
                _declaration_diagnostic(path, error.node, error.field, error.message)
            )
            return None

    page_template: TemplateSource | None = None
    template_node = fields.get("template")
    if template_node is not None:
        try:
            page_template = _template_source(
                template_node,
                field="template",
                path=path,
                source=source,
                template_root=template_root,
            )
        except _DeclarationFailure as error:
            diagnostics.append(
                _declaration_diagnostic(path, error.node, error.field, error.message)
            )
            return None
    if page is None and page_template is not None:
        diagnostics.append(
            _declaration_diagnostic(
                path,
                template_node if template_node is not None else call,
                "template",
                "page template requires a page handler",
            )
        )
        return None

    fragments: list[FragmentSurface] = []
    fragments_node = fields.get("fragments")
    if fragments_node is not None:
        if not isinstance(fragments_node, ast.Tuple):
            diagnostics.append(
                _declaration_diagnostic(
                    path,
                    fragments_node,
                    "fragments",
                    "fragments must use a literal tuple",
                )
            )
            return None
        for item in fragments_node.elts:
            try:
                fragments.append(
                    _parse_kit_fragment(
                        item,
                        path=path,
                        route_module=route_module,
                        state=state,
                        source=source,
                        template_root=template_root,
                    )
                )
            except _DeclarationFailure as error:
                diagnostics.append(
                    _declaration_diagnostic(
                        path, error.node, error.field, error.message
                    )
                )
                return None

    actions: list[ActionSurface] = []
    actions_node = fields.get("actions")
    if actions_node is not None:
        if not isinstance(actions_node, ast.Tuple):
            diagnostics.append(
                _declaration_diagnostic(
                    path,
                    actions_node,
                    "actions",
                    "actions must use a literal tuple",
                )
            )
            return None
        for item in actions_node.elts:
            try:
                actions.append(
                    _parse_kit_action(
                        item,
                        path=path,
                        route_module=route_module,
                        state=state,
                        source=source,
                        template_root=template_root,
                    )
                )
            except _DeclarationFailure as error:
                diagnostics.append(
                    _declaration_diagnostic(
                        path, error.node, error.field, error.message
                    )
                )
                return None

    try:
        nav = (
            _parse_nav_value(
                fields["nav"],
                path=path,
                source=source,
                state=state,
            )
            if "nav" in fields
            else None
        )
        destinations = _parse_destinations(
            fields.get("destinations"),
            path=path,
            source=source,
            state=state,
            context=context,
        )
        error_page_template, error_fragment_template = _error_templates(
            fields,
            path=path,
            source=source,
        )
        metadata = _parse_route_metadata(
            fields,
            path=path,
            source=source,
            state=state,
        )
    except _DeclarationFailure as error:
        diagnostics.append(
            _declaration_diagnostic(path, error.node, error.field, error.message)
        )
        return None

    if page is None and not fragments and not actions and metadata is not None:
        diagnostics.append(
            _declaration_diagnostic(
                path,
                call,
                "Route",
                "route metadata requires a page, fragment, or action",
            )
        )
        return None
    if page is None and not fragments and not actions:
        diagnostics.append(
            _declaration_diagnostic(
                path, call, "Route", "route must declare a page, fragment, or action"
            )
        )
        return None
    index_fragment = next(
        (fragment for fragment in fragments if fragment.path == "/"), None
    )
    if page is not None and index_fragment is not None:
        diagnostics.append(
            _declaration_diagnostic(
                path,
                call,
                "fragments",
                "route cannot declare both a page and an index fragment",
            )
        )
        return None

    fragment_seen: dict[str, FragmentSurface] = {}
    for fragment_surface in fragments:
        previous_fragment = fragment_seen.get(fragment_surface.path)
        if previous_fragment is not None:
            diagnostics.append(
                _collision_diagnostic(
                    fragment_surface.source,
                    "fragments",
                    f"normalized fragment path {fragment_surface.path!r} is owned "
                    f"by {_source_label(previous_fragment.source)} and "
                    f"{_source_label(fragment_surface.source)}",
                )
            )
        else:
            fragment_seen[fragment_surface.path] = fragment_surface

    action_seen: dict[tuple[str, str], ActionSurface] = {}
    for action_surface in actions:
        key = (action_surface.method, action_surface.path)
        previous_action = action_seen.get(key)
        if previous_action is not None:
            diagnostics.append(
                _collision_diagnostic(
                    action_surface.source,
                    "actions",
                    f"normalized action {action_surface.method} "
                    f"{action_surface.path} is owned by "
                    f"{_source_label(previous_action.source)} and "
                    f"{_source_label(action_surface.source)}",
                )
            )
        else:
            action_seen[key] = action_surface
    if any(
        diagnostic.path == path and diagnostic.code == "PYGANINI011"
        for diagnostic in diagnostics
    ):
        return None

    has_template = (
        page_template is not None
        or any(value.template is not None for value in fragments)
        or any(value.template is not None for value in actions)
    )
    if context == "live" and has_template and template_root is None:
        diagnostics.append(
            _declaration_diagnostic(
                path,
                template_node if template_node is not None else call,
                "template_root",
                "kit templates require a template_root",
            )
        )
        return None
    if not has_template and template_root is not None:
        diagnostics.append(
            _declaration_diagnostic(
                path,
                template_root_node if template_root_node is not None else call,
                "template_root",
                "template_root requires a declared kit template",
            )
        )
        return None

    fragments.sort(
        key=lambda item: (
            item.path != "/",
            item.path,
            item.handler.module,
            item.handler.symbol,
        )
    )
    actions.sort(
        key=lambda item: (
            item.path,
            _ACTION_RANK[item.method],
            item.handler.module,
            item.handler.symbol,
        )
    )
    return NormalizedRoute(
        page,
        page_template,
        tuple(fragments),
        tuple(actions),
        KitRouteBinding(creator, template_root),
        nav=nav,
        destinations=destinations,
        error_page_template=error_page_template,
        error_fragment_template=error_fragment_template,
        metadata=metadata,
    )


def _parse_route_module(
    tree: ast.Module,
    *,
    source: str,
    path: PurePosixPath,
    route_module: str,
    diagnostics: list[RouteDiagnostic],
    context: Literal["live", "mounted"] = "live",
) -> NormalizedRoute | None:
    events = _statement_event_map(tree)
    for statement_events in events.values():
        for event in statement_events:
            if event.kind == "star import":
                diagnostics.append(
                    _declaration_diagnostic(
                        path,
                        event.node,
                        "imports",
                        "star import bindings are not statically enumerable",
                    )
                )
                return None
            if event.name == "Route" and not (
                event.direct and event.kind == "assignment"
            ):
                diagnostics.append(
                    _declaration_diagnostic(
                        path,
                        event.node,
                        "Route",
                        f"{event.kind} is unsupported; one direct assignment "
                        "is required",
                    )
                )
                return None

    state = _ParserState({}, set(), {}, set(), set())
    declaration: tuple[ast.Call, _ParserState] | None = None
    for statement in tree.body:
        statement_events = events[id(statement)]
        for event in statement_events:
            if not _is_direct_binding(statement, event):
                _invalidate(state, event.name, event.kind)

        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            state.handlers.pop(statement.name, None)
            state.invalid.pop(statement.name, None)
            state.constructors.discard(statement.name)
            state.capture_constructors.discard(statement.name)
            state.local_functions.add(statement.name)
        elif isinstance(statement, ast.ImportFrom):
            try:
                _record_import_from(state, statement, route_module.rsplit(".", 1)[0])
            except ValueError as error:
                diagnostics.append(
                    _declaration_diagnostic(path, statement, "imports", str(error))
                )
                return None
        elif isinstance(statement, ast.Import):
            _record_import(state, statement)
        elif isinstance(statement, ast.Assign):
            names = tuple(
                name for target in statement.targets for name in _bound_names(target)
            )
            if "Route" in names:
                if not (
                    len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name)
                    and statement.targets[0].id == "Route"
                ):
                    diagnostics.append(
                        _declaration_diagnostic(
                            path,
                            statement,
                            "Route",
                            "one direct unannotated assignment is required",
                        )
                    )
                    return None
                if declaration is not None:
                    diagnostics.append(
                        _declaration_diagnostic(
                            path,
                            statement,
                            "Route",
                            "multiple Route bindings are unsupported",
                        )
                    )
                    return None
                if not isinstance(statement.value, ast.Call):
                    diagnostics.append(
                        _declaration_diagnostic(
                            path,
                            statement.value,
                            "Route",
                            "Route must use the route(...) or route_kit(...) "
                            "constructor",
                        )
                    )
                    return None
                declaration = (statement.value, state.copy())
            else:
                for name in names:
                    _invalidate(state, name, "assignment")
        elif isinstance(statement, ast.AnnAssign):
            for name in _bound_names(statement.target):
                _invalidate(state, name, "annotated binding")
        elif isinstance(statement, ast.AugAssign):
            for name in _bound_names(statement.target):
                _invalidate(state, name, "augmented binding")
        elif isinstance(statement, ast.ClassDef):
            _invalidate(state, statement.name, "class definition")

    if declaration is None:
        diagnostics.append(
            _declaration_diagnostic(path, tree, "Route", "missing Route declaration")
        )
        return None
    call, declaration_state = declaration
    diagnostic_start = len(diagnostics)
    parsed = _parse_route_call(
        call,
        path=path,
        route_module=route_module,
        state=declaration_state,
        diagnostics=diagnostics,
        source=source,
        context=context,
    )
    if (
        context == "live"
        and isinstance(call.func, ast.Name)
        and call.func.id == "route_mount"
    ):
        raw_mount = "<invalid>"
        raw_selector = "<declaration>"
        for keyword in call.keywords:
            if keyword.arg == "mount" and isinstance(keyword.value, ast.Constant):
                raw_mount = repr(keyword.value.value)
            elif keyword.arg == "routes":
                raw_selector = (
                    ast.get_source_segment(source, keyword.value) or "<invalid>"
                )
        owner = SourcePosition(
            path,
            getattr(call, "lineno", 1),
            getattr(call, "col_offset", 0) + 1,
        )
        for index in range(diagnostic_start, len(diagnostics)):
            diagnostic = diagnostics[index]
            diagnostics[index] = _with_mount_evidence(
                diagnostic,
                owners=(owner,),
                mount=raw_mount,
                source="<unresolved>",
                selector=raw_selector,
                final_path="<unresolved>",
                phase="static route declaration",
            )
    return parsed


class _RouteEntryKind(Enum):
    REGULAR = "regular file"
    DIRECTORY = "directory"
    SYMLINK = "symlink or reparse point"
    OTHER = "non-regular filesystem entry"


def _route_entry_kind(info: os.stat_result) -> _RouteEntryKind:
    if getattr(info, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT:
        return _RouteEntryKind.SYMLINK
    if stat.S_ISREG(info.st_mode):
        return _RouteEntryKind.REGULAR
    if stat.S_ISDIR(info.st_mode):
        return _RouteEntryKind.DIRECTORY
    if stat.S_ISLNK(info.st_mode):
        return _RouteEntryKind.SYMLINK
    return _RouteEntryKind.OTHER


class _RouteDirectory(Protocol):
    path: Path

    def entries(self) -> list[str]: ...

    def entry_kind(self, name: str) -> _RouteEntryKind: ...

    def open_child(self, name: str) -> _RouteDirectory: ...

    def read_regular(self, name: str) -> bytes: ...

    def close(self) -> None: ...


class _PosixRouteDirectory:
    def __init__(self, path: Path, descriptor: int) -> None:
        self.path = path
        self._descriptor = descriptor

    @classmethod
    def open(cls, path: Path) -> _PosixRouteDirectory:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        return cls(path, os.open(path, flags))

    def entries(self) -> list[str]:
        return sorted(os.listdir(self._descriptor))

    def entry_kind(self, name: str) -> _RouteEntryKind:
        info = os.stat(name, dir_fd=self._descriptor, follow_symlinks=False)
        return _route_entry_kind(info)

    def open_child(self, name: str) -> _PosixRouteDirectory:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptor = os.open(name, flags, dir_fd=self._descriptor)
        return _PosixRouteDirectory(self.path / name, descriptor)

    def read_regular(self, name: str) -> bytes:
        flags = (
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        )
        descriptor = os.open(name, flags, dir_fd=self._descriptor)
        try:
            if _route_entry_kind(os.fstat(descriptor)) is not _RouteEntryKind.REGULAR:
                raise OSError("convention path must be a regular file")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                return stream.read()
        finally:
            os.close(descriptor)

    def close(self) -> None:
        os.close(self._descriptor)


class _Win32RouteApiProtocol(Protocol):
    def open_directory(self, path: Path) -> Any: ...

    def read_regular(self, path: Path) -> bytes: ...

    def close(self, handle: Any) -> None: ...


class _Win32RouteApi:
    def __init__(self) -> None:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        ctypes_module: Any = ctypes
        self._ctypes = ctypes_module
        self._kernel32 = ctypes_module.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateFileW.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        self._kernel32.CreateFileW.restype = wintypes.HANDLE
        self._kernel32.GetFileAttributesW.argtypes = (wintypes.LPCWSTR,)
        self._kernel32.GetFileAttributesW.restype = wintypes.DWORD
        self._kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._msvcrt: Any = msvcrt

    def _invalid(self, handle: Any) -> bool:
        return handle in (None, -1, self._ctypes.c_void_p(-1).value)

    def _close_after_failure(self, handle: Any, error: BaseException) -> NoReturn:
        try:
            self.close(handle)
        except OSError as close_error:
            if isinstance(error, OSError):
                raise OSError(
                    f"{error}; additionally failed to close route handle: {close_error}"
                ) from error
            error.add_note(f"additionally failed to close route handle: {close_error}")
        raise error

    def _open(self, path: Path, *, directory: bool) -> Any:
        flags = _FILE_FLAG_OPEN_REPARSE_POINT
        if directory:
            flags |= _FILE_FLAG_BACKUP_SEMANTICS
        handle = self._kernel32.CreateFileW(
            str(path),
            0 if directory else _GENERIC_READ,
            _FILE_SHARE_READ | _FILE_SHARE_WRITE,
            None,
            _OPEN_EXISTING,
            flags,
            None,
        )
        if self._invalid(handle):
            raise self._ctypes.WinError(self._ctypes.get_last_error())
        attributes = self._kernel32.GetFileAttributesW(str(path))
        if attributes == _INVALID_FILE_ATTRIBUTES:
            error = self._ctypes.WinError(self._ctypes.get_last_error())
            self._close_after_failure(handle, error)
        if attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
            self._close_after_failure(handle, OSError("route path is a reparse point"))
        if directory != bool(attributes & _FILE_ATTRIBUTE_DIRECTORY):
            expected = "directory" if directory else "regular file"
            self._close_after_failure(
                handle, OSError(f"route path must be a {expected}")
            )
        return handle

    def open_directory(self, path: Path) -> Any:
        return self._open(path, directory=True)

    def read_regular(self, path: Path) -> bytes:
        handle = self._open(path, directory=False)
        try:
            descriptor = self._msvcrt.open_osfhandle(int(handle), os.O_RDONLY)
        except BaseException as error:
            self._close_after_failure(handle, error)
        try:
            if _route_entry_kind(os.fstat(descriptor)) is not _RouteEntryKind.REGULAR:
                raise OSError("convention path must be a regular file")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                return stream.read()
        finally:
            os.close(descriptor)

    def close(self, handle: Any) -> None:
        if not self._kernel32.CloseHandle(handle):
            raise self._ctypes.WinError(self._ctypes.get_last_error())


class _WindowsRouteDirectory:
    def __init__(
        self,
        path: Path,
        handle: Any,
        api: _Win32RouteApiProtocol,
    ) -> None:
        self.path = path
        self._handle = handle
        self._api = api

    @classmethod
    def open(
        cls,
        path: Path,
        api: _Win32RouteApiProtocol,
    ) -> _WindowsRouteDirectory:
        return cls(path, api.open_directory(path), api)

    def entries(self) -> list[str]:
        return sorted(os.listdir(self.path))

    def entry_kind(self, name: str) -> _RouteEntryKind:
        return _route_entry_kind((self.path / name).lstat())

    def open_child(self, name: str) -> _WindowsRouteDirectory:
        return _WindowsRouteDirectory.open(self.path / name, self._api)

    def read_regular(self, name: str) -> bytes:
        return self._api.read_regular(self.path / name)

    def close(self) -> None:
        self._api.close(self._handle)


def _open_route_root(path: Path) -> _RouteDirectory:
    if _IS_WINDOWS:
        return _WindowsRouteDirectory.open(path, _Win32RouteApi())
    return _PosixRouteDirectory.open(path)


def _app_relative(paths: ProjectPaths, path: Path) -> PurePosixPath:
    return PurePosixPath(path.relative_to(paths.root).as_posix())


def _filesystem_diagnostic(
    paths: ProjectPaths, path: Path, message: str
) -> RouteDiagnostic:
    return RouteDiagnostic(
        "PYGANINI009",
        "route-filesystem",
        _app_relative(paths, path),
        message,
    )


def _read_convention(
    paths: ProjectPaths,
    directory: _RouteDirectory,
    path: Path,
    diagnostics: list[RouteDiagnostic],
    *,
    field: str | None = None,
) -> tuple[PurePosixPath, ast.Module, str] | None:
    relative = _app_relative(paths, path)
    try:
        kind = directory.entry_kind(path.name)
        if kind is _RouteEntryKind.SYMLINK:
            diagnostics.append(
                _filesystem_diagnostic(
                    paths, path, "convention file must not be a symlink"
                )
            )
            return None
        if kind is not _RouteEntryKind.REGULAR:
            diagnostics.append(
                _filesystem_diagnostic(
                    paths, path, "convention path must be a regular file"
                )
            )
            return None
    except OSError as error:
        diagnostics.append(
            _filesystem_diagnostic(
                paths, path, f"cannot inspect convention file: {error}"
            )
        )
        return None
    try:
        content = directory.read_regular(path.name)
    except OSError as error:
        diagnostics.append(
            _filesystem_diagnostic(paths, path, f"cannot read convention file: {error}")
        )
        return None
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        diagnostics.append(
            _filesystem_diagnostic(
                paths, path, f"convention file is not valid UTF-8: {error}"
            )
        )
        return None
    try:
        return relative, ast.parse(text, filename=relative.as_posix()), text
    except SyntaxError as error:
        diagnostics.append(
            RouteDiagnostic(
                "PYGANINI010",
                "route-declaration",
                relative,
                "invalid Python syntax",
                line=error.lineno,
                column=error.offset,
                field=field or ("Route" if path.name == "route.py" else None),
            )
        )
        return None


def _parse_middleware_module(
    tree: ast.Module,
    *,
    path: PurePosixPath,
    route_prefix: str,
    diagnostics: list[RouteDiagnostic],
) -> MiddlewareSource | None:
    events = _statement_event_map(tree)
    binding: ast.Assign | ast.AnnAssign | None = None
    for statement in tree.body:
        for event in events[id(statement)]:
            if event.name != "MIDDLEWARE":
                continue
            candidate: ast.Assign | ast.AnnAssign | None = None
            if (
                isinstance(statement, ast.Assign)
                and event.direct
                and event.kind == "assignment"
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
                and statement.targets[0].id == "MIDDLEWARE"
            ) or (
                isinstance(statement, ast.AnnAssign)
                and event.direct
                and event.kind == "annotated binding"
                and isinstance(statement.target, ast.Name)
                and statement.target.id == "MIDDLEWARE"
            ):
                candidate = statement
            if candidate is None:
                diagnostics.append(
                    _declaration_diagnostic(
                        path,
                        event.node,
                        "MIDDLEWARE",
                        f"{event.kind} is unsupported; one direct MIDDLEWARE "
                        "assignment is required",
                    )
                )
                return None
            if binding is not None:
                diagnostics.append(
                    _declaration_diagnostic(
                        path,
                        event.node,
                        "MIDDLEWARE",
                        "multiple MIDDLEWARE bindings are unsupported",
                    )
                )
                return None
            binding = candidate

    if binding is None:
        diagnostics.append(
            _declaration_diagnostic(
                path,
                tree,
                "MIDDLEWARE",
                "missing direct MIDDLEWARE binding",
            )
        )
        return None

    value = binding.value
    if not isinstance(value, ast.Tuple):
        diagnostics.append(
            _declaration_diagnostic(
                path,
                value or binding,
                "MIDDLEWARE",
                "MIDDLEWARE must be a non-empty tuple literal",
            )
        )
        return None
    if not value.elts:
        diagnostics.append(
            _declaration_diagnostic(
                path,
                value,
                "MIDDLEWARE",
                "MIDDLEWARE must be a non-empty tuple literal",
            )
        )
        return None
    entries: list[MiddlewareEntrySource] = []
    for item in value.elts:
        if isinstance(item, ast.Starred):
            diagnostics.append(
                _declaration_diagnostic(
                    path,
                    item,
                    "MIDDLEWARE",
                    "MIDDLEWARE tuple entries must not use star expansion",
                )
            )
            return None
        entries.append(MiddlewareEntrySource(_position(path, item)))
    if isinstance(binding, ast.AnnAssign):
        target = binding.target
    else:
        assert isinstance(binding, ast.Assign)
        assert isinstance(binding.targets[0], ast.Name)
        target = binding.targets[0]
    return MiddlewareSource(
        _position(path, target),
        route_prefix,
        tuple(entries),
    )


def _read_template(
    paths: ProjectPaths,
    directory: _RouteDirectory,
    path: Path,
    diagnostics: list[RouteDiagnostic],
) -> PurePosixPath | None:
    relative = _app_relative(paths, path)
    try:
        kind = directory.entry_kind(path.name)
        if kind is _RouteEntryKind.SYMLINK:
            diagnostics.append(
                _filesystem_diagnostic(
                    paths, path, "template file must not be a symlink"
                )
            )
            return None
        if kind is not _RouteEntryKind.REGULAR:
            diagnostics.append(
                _filesystem_diagnostic(
                    paths, path, "template path must be a regular file"
                )
            )
            return None
    except OSError as error:
        diagnostics.append(
            _filesystem_diagnostic(
                paths, path, f"cannot inspect required template file: {error}"
            )
        )
        return None
    try:
        content = directory.read_regular(path.name)
    except OSError as error:
        diagnostics.append(
            _filesystem_diagnostic(paths, path, f"cannot read template file: {error}")
        )
        return None
    try:
        content.decode("utf-8")
    except UnicodeDecodeError as error:
        diagnostics.append(
            _filesystem_diagnostic(
                paths, path, f"template file is not valid UTF-8: {error}"
            )
        )
        return None
    return relative


def _route_path(segments: tuple[str, ...]) -> str:
    return "/" if not segments else "/" + "/".join(segments)


def _environment_name(path: PurePosixPath) -> str:
    return PurePosixPath(*path.parts[1:]).as_posix()


def _declared_templates(declaration: NormalizedRoute) -> tuple[TemplateSource, ...]:
    templates = [
        template
        for template in (
            declaration.page_template,
            *(fragment.template for fragment in declaration.fragments),
            *(action.template for action in declaration.actions),
            declaration.error_page_template,
            declaration.error_fragment_template,
        )
        if template is not None
    ]
    return tuple(templates)


def _join_local(route_path: str, local_path: str) -> str:
    if local_path == "/":
        return route_path
    if route_path == "/":
        return local_path
    return route_path + local_path


def _join_route(base: str, child: str) -> str:
    if child == "/":
        return base
    if base == "/":
        return child
    return base + child


def _route_patterns_overlap(first: str, second: str) -> bool:
    first_segments = () if first == "/" else tuple(first[1:].split("/"))
    second_segments = () if second == "/" else tuple(second[1:].split("/"))
    if len(first_segments) != len(second_segments):
        return False
    dynamic = False
    for left, right in zip(first_segments, second_segments, strict=True):
        left_dynamic = left.startswith("{") and left.endswith("}")
        right_dynamic = right.startswith("{") and right.endswith("}")
        if left_dynamic and right_dynamic:
            dynamic = True
            continue
        if left_dynamic or right_dynamic or left != right:
            return False
    return dynamic


def _endpoint_collision_evidence(endpoint: Endpoint, method: str) -> str:
    owner = "<none>" if endpoint.owner is None else endpoint.owner.path.as_posix()
    source = endpoint.source.path.as_posix()
    mounted = "<live>" if endpoint.mount is None else endpoint.mount
    source_route = endpoint.source_path or endpoint.node_path or "/"
    return (
        f"{method} {endpoint.path} ({endpoint.kind}) owner {owner}, mount "
        f"{mounted}, source route {source_route!r}, declaration {source}, "
        "evidence phase: static route collision"
    )


def _with_endpoint_collision_sort_evidence(
    diagnostic: RouteDiagnostic,
    endpoints: Sequence[Endpoint],
    method: str,
) -> RouteDiagnostic:
    mounted = tuple(endpoint for endpoint in endpoints if endpoint.mount is not None)
    if not mounted:
        return diagnostic
    owners = tuple(
        sorted(
            {endpoint.owner for endpoint in endpoints if endpoint.owner is not None},
            key=lambda owner: (
                owner.path.as_posix(),
                owner.line,
                owner.column,
            ),
        )
    )
    return replace(
        diagnostic,
        owners=owners,
        mount=", ".join(
            sorted({endpoint.mount for endpoint in mounted if endpoint.mount})
        ),
        source_path=", ".join(
            sorted({endpoint.source.path.as_posix() for endpoint in mounted})
        ),
        final_path=", ".join(sorted({endpoint.path for endpoint in endpoints})),
        method=method,
    )


def iter_endpoints(graph: RouteGraph) -> Iterator[Endpoint]:
    """Derive canonical endpoints from the graph's normalized facts."""
    for node in graph.nodes:
        declaration = node.declaration
        if declaration is None:
            continue
        creator = None if declaration.kit is None else declaration.kit.creator
        source = node.source
        owner = node.owner
        if declaration.page is not None:
            yield Endpoint(
                "page",
                ("GET", "HEAD"),
                node.route_path,
                node.parameters,
                declaration.page,
                source or declaration.page.source,
                declaration.page_template,
                creator,
                handler_source=declaration.page.source,
                owner=owner or source or declaration.page.source,
                mount=node.mount,
                source_path=node.source_path,
                node_path=node.route_path,
            )
        for fragment in declaration.fragments:
            yield Endpoint(
                "fragment",
                ("GET", "HEAD"),
                _join_local(node.route_path, fragment.path),
                node.parameters,
                fragment.handler,
                source or fragment.source,
                fragment.template,
                creator,
                handler_source=fragment.source,
                owner=owner or source or fragment.source,
                mount=node.mount,
                source_path=node.source_path,
                node_path=node.route_path,
            )
        for action in declaration.actions:
            yield Endpoint(
                "action",
                (action.method,),
                _join_local(node.route_path, action.path),
                node.parameters,
                action.handler,
                source or action.source,
                action.template,
                creator,
                handler_source=action.source,
                owner=owner or source or action.source,
                mount=node.mount,
                source_path=node.source_path,
                node_path=node.route_path,
                request_data=action.request_data,
                request_data_source=action.request_data_source,
            )


def _selected_layouts(
    graph: RouteGraph, endpoint: Endpoint
) -> tuple[LayoutSource, ...]:
    """Return the canonical outer-to-inner layout chain for an endpoint."""
    for node in graph.nodes:
        if (
            node.route_path == endpoint.node_path
            and node.source == endpoint.source
            and node.mount == endpoint.mount
        ):
            if node.layouts:
                return node.layouts
            if node.mount is not None:
                return ()
            owner = endpoint.source.path.parent
            return tuple(
                node.layout
                for node in graph.nodes
                if node.layout is not None
                and owner.parts[: len(node.source_directory.parts)]
                == node.source_directory.parts
            )
    raise ValueError(f"endpoint source is absent from graph: {endpoint.source.path!r}")


type ErrorRenderFacts = tuple[
    TemplateSource | None,
    TemplateSource | None,
    tuple[LayoutSource, ...],
]


def _root_error_render_facts(graph: RouteGraph) -> ErrorRenderFacts:
    """Return the canonical live-root error templates and layout chain."""
    root = next(
        (
            node
            for node in graph.nodes
            if node.source_directory == PurePosixPath("app/routes")
            and node.mount is None
            and node.owner is not None
            and node.owner.path == PurePosixPath("app/routes/route.py")
        ),
        None,
    )
    if root is None:
        return None, None, ()
    return (
        root.error_page_template,
        root.error_fragment_template,
        root.layouts,
    )


def _endpoint_node(graph: RouteGraph, endpoint: Endpoint) -> RouteNode:
    for node in graph.nodes:
        if (
            node.route_path == endpoint.node_path
            and node.source == endpoint.source
            and node.mount == endpoint.mount
        ):
            return node
    raise ValueError(f"endpoint source is absent from graph: {endpoint.source.path!r}")


def _middleware_signature(
    chain: tuple[MiddlewareSource, ...],
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            marker.source.path.as_posix(),
            marker.source.line,
            marker.source.column,
            marker.route_prefix,
            tuple(
                (
                    entry.source.path.as_posix(),
                    entry.source.line,
                    entry.source.column,
                )
                for entry in marker.entries
            ),
        )
        for marker in chain
    )


def _middleware_chain_label(chain: tuple[MiddlewareSource, ...]) -> str:
    if not chain:
        return "<none>"
    return " -> ".join(
        "{}:{}:{} prefix={!r} entries=[{}]".format(
            marker.source.path,
            marker.source.line,
            marker.source.column,
            marker.route_prefix,
            ", ".join(
                f"{entry.source.line}:{entry.source.column}" for entry in marker.entries
            ),
        )
        for marker in chain
    )


def _middleware_endpoint_label(endpoint: Endpoint, method: str) -> str:
    owner = endpoint.owner or endpoint.source
    mount = endpoint.mount or "<live>"
    source = endpoint.source.path.as_posix()
    selector = endpoint.source_path or "<live>"
    return (
        f"{method} {endpoint.kind}; live owner: {_source_label(owner)}; "
        f"mount identity: {mount}; mounted source: {source}; "
        f"selector: {selector}"
    )


def _middleware_chain_difference(
    first: tuple[MiddlewareSource, ...], second: tuple[MiddlewareSource, ...]
) -> str:
    first_signature = _middleware_signature(first)
    second_signature = _middleware_signature(second)
    for index in range(max(len(first_signature), len(second_signature))):
        left = first_signature[index] if index < len(first_signature) else None
        right = second_signature[index] if index < len(second_signature) else None
        if left != right:
            return f"first differing marker index {index}: {left!r} versus {right!r}"
    return "middleware chain differs"


@dataclass(frozen=True, slots=True)
class _Child:
    name: str
    browser_segment: str
    parameter: str | None
    path: Path


@dataclass(frozen=True, slots=True)
class _MountedSourceTree:
    mount: str
    nodes: tuple[RouteNode, ...]
    valid: bool


class _GraphBuilder:
    def __init__(self, paths: ProjectPaths) -> None:
        self.paths = paths
        self.nodes: list[RouteNode] = []
        self.diagnostics: list[RouteDiagnostic] = []
        self._validated_shared_roots: set[str] = set()
        self._invalid_shared_roots: set[str] = set()
        self._validated_shared_templates: set[str] = set()
        self._mounted_sources: dict[str, _MountedSourceTree] = {}
        self.mount_owners: list[MountOwner] = []
        self.mounted_bindings: list[MountedRouteBinding] = []
        self.mounted_candidates: list[MountedRouteCandidate] = []

    def build(self) -> RouteGraph:
        directories: list[_RouteDirectory] = []
        try:
            root_directory = _open_route_root(self.paths.root)
            directories.append(root_directory)
            app_directory = root_directory.open_child("app")
            directories.append(app_directory)
            routes_directory = app_directory.open_child("routes")
            directories.append(routes_directory)
        except OSError as error:
            self.diagnostics.append(
                _filesystem_diagnostic(
                    self.paths,
                    self.paths.routes,
                    f"cannot access route directory: {error}",
                )
            )
        else:
            self._scan(
                routes_directory,
                self.paths.routes,
                (),
                (),
                (),
                (),
                app_directory=app_directory,
                nodes=self.nodes,
                context="live",
                source_base=PurePosixPath("app/routes"),
                module_parts=("app", "routes"),
            )
        finally:
            for directory in reversed(directories):
                self._close_directory(directory)
        self._set_live_layouts()
        self._set_live_middleware_chains()
        self._expand_mounts()
        self._sort_nodes()
        self._resolve_navigation_targets()
        graph = RouteGraph(
            tuple(self.nodes),
            tuple(self.mount_owners),
            tuple(self.mounted_bindings),
            tuple(
                sorted(
                    self.mounted_candidates,
                    key=lambda candidate: (
                        candidate.mount,
                        candidate.owner.path.as_posix(),
                        candidate.owner.line,
                        candidate.owner.column,
                        candidate.source_path,
                        candidate.source_route.path.as_posix(),
                    ),
                )
            ),
        )
        self._validate_endpoints(graph)
        if self.diagnostics:
            raise RouteGraphError(self.diagnostics)
        return graph

    @staticmethod
    def _path_contains(parent: PurePosixPath, child: PurePosixPath) -> bool:
        return child.parts[: len(parent.parts)] == parent.parts

    def _layout_chain(
        self,
        nodes: Sequence[RouteNode],
        target: RouteNode,
    ) -> tuple[LayoutSource, ...]:
        layouts: list[LayoutSource] = [
            node.layout
            for node in nodes
            if node.layout is not None
            and self._path_contains(node.source_directory, target.source_directory)
        ]
        return tuple(
            sorted(
                layouts,
                key=lambda layout: (
                    len(layout.route_prefix.strip("/").split("/"))
                    if layout.route_prefix != "/"
                    else 0,
                    layout.source.path.as_posix(),
                ),
            )
        )

    def _set_live_layouts(self) -> None:
        original = tuple(self.nodes)
        self.nodes = [
            replace(node, layouts=self._layout_chain(original, node))
            for node in original
        ]

    def _middleware_chain(
        self,
        nodes: Sequence[RouteNode],
        target: RouteNode,
    ) -> tuple[MiddlewareSource, ...]:
        markers = [
            node.middleware
            for node in nodes
            if node.middleware is not None
            and self._path_contains(node.source_directory, target.source_directory)
        ]
        return tuple(
            sorted(
                (marker for marker in markers),
                key=lambda marker: (
                    len(marker.route_prefix.strip("/").split("/"))
                    if marker.route_prefix != "/"
                    else 0,
                    marker.source.path.as_posix(),
                ),
            )
        )

    def _set_live_middleware_chains(self) -> None:
        original = tuple(self.nodes)
        self.nodes = [
            replace(node, middleware_chain=self._middleware_chain(original, node))
            for node in original
        ]

    def _sort_nodes(self) -> None:
        self.nodes.sort(
            key=lambda node: (
                node.route_path,
                node.source_directory.as_posix(),
                "" if node.source is None else node.source.path.as_posix(),
            )
        )

    def _resolve_navigation_targets(self) -> None:
        live_paths = tuple(
            node.route_path for node in self.nodes if node.declaration is not None
        )

        def resolve_destination(destination: DestinationSource) -> DestinationSource:
            if not destination.target_selector:
                return destination
            resolved = _resolve_target_selector(destination.target_selector, live_paths)
            if resolved is None:
                return destination
            return replace(destination, target_path=resolved)

        resolved_nodes: list[RouteNode] = []
        for node in self.nodes:
            declaration = node.declaration
            if declaration is None or not declaration.destinations:
                resolved_nodes.append(node)
                continue
            resolved_nodes.append(
                replace(
                    node,
                    declaration=replace(
                        declaration,
                        destinations=tuple(
                            resolve_destination(destination)
                            for destination in declaration.destinations
                        ),
                    ),
                )
            )
        self.nodes = resolved_nodes
        self.mount_owners = [
            replace(
                owner,
                selections=tuple(
                    replace(
                        selection,
                        destinations=tuple(
                            resolve_destination(destination)
                            for destination in selection.destinations
                        ),
                    )
                    for selection in owner.selections
                ),
            )
            for owner in self.mount_owners
        ]

    def _source_package_chain(
        self, mount: str
    ) -> tuple[_RouteDirectory, list[_RouteDirectory], Path] | None:
        directories: list[_RouteDirectory] = []
        completed = False
        try:
            root_directory = _open_route_root(self.paths.root)
            directories.append(root_directory)
            app_directory = root_directory.open_child("app")
            directories.append(app_directory)
            mounts_directory = app_directory.open_child("mounts")
            directories.append(mounts_directory)
            current = mounts_directory
            current_path = self.paths.app / "mounts"
            if not self._validate_package(
                current,
                current_path,
                missing_message=(
                    "mounted source root requires a contained regular __init__.py"
                ),
                read_marker=True,
                read_message="cannot read mounted source package marker",
            ):
                return None
            for component in mount.split("/"):
                component_path = current_path / component
                try:
                    kind = current.entry_kind(component)
                    if kind is not _RouteEntryKind.DIRECTORY:
                        self.diagnostics.append(
                            _filesystem_diagnostic(
                                self.paths,
                                component_path,
                                "mounted source path must be a regular directory",
                            )
                        )
                        return None
                    child = current.open_child(component)
                except OSError as error:
                    self.diagnostics.append(
                        _filesystem_diagnostic(
                            self.paths,
                            component_path,
                            f"cannot access mounted source directory: {error}",
                        )
                    )
                    return None
                directories.append(child)
                current = child
                current_path = component_path
                if not self._validate_package(
                    current,
                    current_path,
                    missing_message=(
                        "mounted source directory requires a contained regular "
                        "__init__.py"
                    ),
                    read_marker=True,
                    read_message="cannot read mounted source package marker",
                ):
                    return None
            completed = True
            return current, directories, current_path
        except OSError as error:
            self.diagnostics.append(
                _filesystem_diagnostic(
                    self.paths,
                    self.paths.app / "mounts" / PurePosixPath(mount),
                    f"cannot access mounted source root: {error}",
                )
            )
            return None
        finally:
            if not completed:
                for directory in reversed(directories):
                    self._close_directory(directory)

    def _scan_mounted_source(self, mount: str) -> _MountedSourceTree:
        cached = self._mounted_sources.get(mount)
        if cached is not None:
            return cached
        start = len(self.diagnostics)
        source_nodes: list[RouteNode] = []
        package = self._source_package_chain(mount)
        if package is None:
            result = _MountedSourceTree(mount, (), False)
            self._mounted_sources[mount] = result
            return result
        source_directory, directories, source_path = package
        app_directory = directories[1]
        try:
            mount_parts = tuple(mount.split("/"))
            self._scan(
                source_directory,
                source_path,
                (),
                (),
                (),
                (),
                app_directory=app_directory,
                nodes=source_nodes,
                context="mounted",
                source_base=PurePosixPath("app/mounts", *mount_parts),
                module_parts=("app", "mounts", *mount_parts),
            )
        finally:
            for directory in reversed(directories):
                self._close_directory(directory)

        if not any(node.declaration is not None for node in source_nodes):
            self.diagnostics.append(
                RouteDiagnostic(
                    "PYGANINI010",
                    "route-declaration",
                    PurePosixPath("app/mounts", *mount.split("/")),
                    "mounted source tree must contain at least one route declaration",
                    field="Route",
                )
            )
        source_graph = RouteGraph(tuple(source_nodes))
        self._validate_endpoints(source_graph)
        valid = len(self.diagnostics) == start
        result = _MountedSourceTree(mount, tuple(source_nodes), valid)
        self._mounted_sources[mount] = result
        return result

    def _select_mounted_nodes(
        self,
        owner: RouteNode,
        binding: MountRouteBinding,
        source: _MountedSourceTree,
    ) -> tuple[RouteNode, ...] | None:
        declarations = {
            node.route_path: node
            for node in source.nodes
            if node.declaration is not None
        }
        if binding.routes is None:
            return tuple(node for node in source.nodes if node.declaration is not None)
        owner_position = (
            owner.source
            or owner.owner
            or SourcePosition(owner.source_directory / "route.py", 1, 1)
        )
        selected: list[RouteNode] = []
        missing = False
        for path in binding.routes:
            node = declarations.get(path)
            if node is None:
                self.diagnostics.append(
                    _with_mount_evidence(
                        RouteDiagnostic(
                            "PYGANINI010",
                            "route-declaration",
                            owner_position.path,
                            f"routes references missing mounted route: {path}",
                            line=owner_position.line,
                            column=owner_position.column,
                            field="routes",
                        ),
                        owners=(owner_position,),
                        mount=binding.mount,
                        source=f"app/mounts/{binding.mount}/<missing route.py>",
                        selector=path,
                        final_path=_join_route(owner.route_path, path),
                        phase="static route selection",
                    )
                )
                missing = True
                continue
            selected.append(node)
        if missing:
            return None
        selected.sort(
            key=lambda node: (node.route_path, node.source_directory.as_posix())
        )
        return tuple(selected)

    def _expand_mounts(self) -> None:
        original = tuple(self.nodes)
        owners_by_mount: dict[str, list[SourcePosition]] = {}
        for candidate in original:
            candidate_declaration = candidate.declaration
            candidate_mount = (
                None if candidate_declaration is None else candidate_declaration.mount
            )
            if candidate_mount is None:
                continue
            candidate_owner = (
                candidate.owner
                or candidate.source
                or SourcePosition(candidate.source_directory / "route.py", 1, 1)
            )
            owners_by_mount.setdefault(candidate_mount.mount, []).append(
                candidate_owner
            )
        expanded: list[RouteNode] = []
        for owner in original:
            declaration = owner.declaration
            mount_binding = None if declaration is None else declaration.mount
            if mount_binding is None:
                expanded.append(owner)
                continue

            owner_position = (
                owner.owner
                or owner.source
                or SourcePosition(owner.source_directory / "route.py", 1, 1)
            )
            self.mount_owners.append(
                MountOwner(
                    owner_position,
                    mount_binding.mount,
                    mount_binding.routes,
                    mount_binding.selections,
                )
            )
            expanded.append(replace(owner, declaration=None))
            diagnostic_start = len(self.diagnostics)
            source = self._scan_mounted_source(mount_binding.mount)
            for index in range(diagnostic_start, len(self.diagnostics)):
                diagnostic = self.diagnostics[index]
                if diagnostic.path.parts[:2] != ("app", "mounts"):
                    continue
                self.diagnostics[index] = _with_mount_evidence(
                    diagnostic,
                    owners=tuple(owners_by_mount[mount_binding.mount]),
                    mount=mount_binding.mount,
                    source=diagnostic.path.as_posix(),
                    selector="<source validation>",
                    final_path="<not expanded>",
                    phase=f"static {diagnostic.phase}",
                )
            if not source.valid:
                continue
            selected = self._select_mounted_nodes(owner, mount_binding, source)
            if selected is None:
                continue
            selected_paths = {node.route_path for node in selected}
            for source_node in source.nodes:
                source_declaration = source_node.declaration
                if source_declaration is None:
                    continue
                source_position = (
                    source_node.source or source_node.owner or owner_position
                )
                self.mounted_candidates.append(
                    MountedRouteCandidate(
                        owner_position,
                        mount_binding.mount,
                        source_position,
                        source_node.route_path,
                        _join_route(owner.route_path, source_node.route_path),
                        source_declaration,
                        source_node.route_path in selected_paths,
                    )
                )
            live_layouts = self._layout_chain(original, owner)
            for source_node in selected:
                source_declaration = source_node.declaration
                if source_declaration is None:
                    continue
                child_parameters = (*owner.parameters, *source_node.parameters)
                repeated = next(
                    (
                        parameter
                        for parameter in source_node.parameters
                        if parameter in owner.parameters
                    ),
                    None,
                )
                final_path = _join_route(owner.route_path, source_node.route_path)
                if repeated is not None:
                    source_position = (
                        source_node.source or source_node.owner or owner_position
                    )
                    self.diagnostics.append(
                        _with_mount_evidence(
                            _collision_diagnostic(
                                source_position,
                                "parameters",
                                f"dynamic parameter {repeated!r} repeats a live "
                                f"owner parameter at {_source_label(owner_position)}",
                            ),
                            owners=(owner_position,),
                            mount=mount_binding.mount,
                            source=source_position.path.as_posix(),
                            selector=source_node.route_path,
                            final_path=final_path,
                            phase="static route collision",
                        )
                    )
                    continue
                self.mounted_bindings.append(
                    MountedRouteBinding(
                        owner_position,
                        mount_binding.mount,
                        source_node.source or source_node.owner or owner_position,
                        source_node.route_path,
                        final_path,
                    )
                )
                final_declaration = replace(
                    source_declaration,
                    kit=KitRouteBinding(mount_binding.creator, None),
                    mount=None,
                    nav=(
                        next(
                            (
                                selection.nav
                                for selection in mount_binding.selections
                                if selection.path == source_node.route_path
                            ),
                            None,
                        )
                        or source_declaration.nav
                    ),
                    destinations=next(
                        (
                            selection.destinations
                            for selection in mount_binding.selections
                            if selection.path == source_node.route_path
                        ),
                        (),
                    ),
                )
                mounted_layouts = source_node.layouts or self._layout_chain(
                    source.nodes, source_node
                )
                expanded.append(
                    RouteNode(
                        owner.source_directory,
                        owner.module,
                        final_path,
                        child_parameters,
                        final_declaration,
                        source_node.layout,
                        owner=owner_position,
                        source=source_node.source or source_node.owner,
                        mount=mount_binding.mount,
                        source_path=source_node.route_path,
                        layouts=(*live_layouts, *mounted_layouts),
                        source_nav=source_declaration.nav,
                        source_destinations=source_declaration.destinations,
                        middleware_chain=owner.middleware_chain,
                    )
                )
        self.nodes = expanded

    def _close_directory(self, directory: _RouteDirectory) -> None:
        try:
            directory.close()
        except OSError as error:
            self.diagnostics.append(
                _filesystem_diagnostic(
                    self.paths,
                    directory.path,
                    f"cannot close route directory: {error}",
                )
            )

    def _validate_package(
        self,
        route_directory: _RouteDirectory,
        directory: Path,
        *,
        missing_message: str = (
            "live route directory requires a contained regular __init__.py"
        ),
        read_marker: bool = False,
        read_message: str = "cannot read route package marker",
    ) -> bool:
        marker = directory / "__init__.py"
        try:
            kind = route_directory.entry_kind(marker.name)
        except PermissionError as error:
            self.diagnostics.append(
                _filesystem_diagnostic(
                    self.paths,
                    directory,
                    f"cannot access route directory: {error}",
                )
            )
            return False
        except FileNotFoundError:
            self.diagnostics.append(
                _filesystem_diagnostic(
                    self.paths,
                    marker,
                    missing_message,
                )
            )
            return False
        except OSError as error:
            self.diagnostics.append(
                _filesystem_diagnostic(
                    self.paths,
                    marker,
                    f"cannot inspect route package marker: {error}",
                )
            )
            return False
        if kind is _RouteEntryKind.SYMLINK:
            self.diagnostics.append(
                _filesystem_diagnostic(
                    self.paths, marker, "route package marker must not be a symlink"
                )
            )
            return False
        if kind is not _RouteEntryKind.REGULAR:
            self.diagnostics.append(
                _filesystem_diagnostic(
                    self.paths,
                    marker,
                    missing_message,
                )
            )
            return False
        if read_marker:
            try:
                route_directory.read_regular(marker.name)
            except OSError as error:
                self.diagnostics.append(
                    _filesystem_diagnostic(
                        self.paths,
                        marker,
                        f"{read_message}: {error}",
                    )
                )
                return False
        return True

    def _read_shared_template(
        self,
        app_directory: _RouteDirectory,
        template: TemplateSource,
    ) -> None:
        environment_path = PurePosixPath(template.environment_name)
        parts = environment_path.parts
        if len(parts) < 2:
            return
        root_name = PurePosixPath(*parts[:-1]).as_posix()
        if root_name in self._invalid_shared_roots:
            return

        if root_name not in self._validated_shared_roots:
            current = app_directory
            opened: list[_RouteDirectory] = []
            valid = True
            for index, component in enumerate(parts[:-1]):
                package_path = self.paths.app.joinpath(*parts[: index + 1])
                try:
                    kind = current.entry_kind(component)
                except OSError as error:
                    self.diagnostics.append(
                        _filesystem_diagnostic(
                            self.paths,
                            package_path,
                            "cannot inspect shared template package directory: "
                            f"{error}",
                        )
                    )
                    valid = False
                    break
                if kind is _RouteEntryKind.SYMLINK:
                    self.diagnostics.append(
                        _filesystem_diagnostic(
                            self.paths,
                            package_path,
                            "shared template package directory must not be a symlink",
                        )
                    )
                    valid = False
                    break
                if kind is not _RouteEntryKind.DIRECTORY:
                    self.diagnostics.append(
                        _filesystem_diagnostic(
                            self.paths,
                            package_path,
                            "shared template package path must be a directory",
                        )
                    )
                    valid = False
                    break
                try:
                    child = current.open_child(component)
                except OSError as error:
                    self.diagnostics.append(
                        _filesystem_diagnostic(
                            self.paths,
                            package_path,
                            f"cannot access shared template package directory: {error}",
                        )
                    )
                    valid = False
                    break
                opened.append(child)
                current = child
                if not self._validate_package(
                    current,
                    package_path,
                    missing_message=(
                        "shared template root requires a contained regular __init__.py"
                    ),
                    read_marker=True,
                    read_message="cannot read shared template package marker",
                ):
                    valid = False
                    break

            for opened_directory in reversed(opened):
                self._close_directory(opened_directory)
            if not valid:
                self._invalid_shared_roots.add(root_name)
                return
            self._validated_shared_roots.add(root_name)

        if template.environment_name in self._validated_shared_templates:
            return
        template_path = self.paths.app / PurePosixPath(template.environment_name)
        parts_without_file = parts[:-1]
        current = app_directory
        template_opened: list[_RouteDirectory] = []
        try:
            for component in parts_without_file:
                current = current.open_child(component)
                template_opened.append(current)
            _read_template(self.paths, current, template_path, self.diagnostics)
            self._validated_shared_templates.add(template.environment_name)
        except OSError as error:
            self.diagnostics.append(
                _filesystem_diagnostic(
                    self.paths,
                    template_path,
                    f"cannot access shared template package: {error}",
                )
            )
        finally:
            for opened_directory in reversed(template_opened):
                self._close_directory(opened_directory)

    def _directory_entries(
        self, route_directory: _RouteDirectory, directory: Path
    ) -> list[str] | None:
        try:
            return route_directory.entries()
        except OSError as error:
            self.diagnostics.append(
                _filesystem_diagnostic(
                    self.paths, directory, f"cannot read route directory: {error}"
                )
            )
            return None

    def _children(
        self,
        route_directory: _RouteDirectory,
        directory: Path,
        entries: Sequence[str],
        route_path: str,
    ) -> list[_Child]:
        children: list[_Child] = []
        for name in entries:
            if name in {"route.py", "layout.py"}:
                continue
            if name == "__pycache__" or _PRIVATE.fullmatch(name):
                continue
            entry = directory / name
            try:
                kind = route_directory.entry_kind(name)
            except OSError as error:
                self.diagnostics.append(
                    _filesystem_diagnostic(
                        self.paths, entry, f"cannot inspect route entry: {error}"
                    )
                )
                continue
            is_symlink = kind is _RouteEntryKind.SYMLINK
            valid_static = not name.startswith("by_") and bool(
                _IDENTIFIER.fullmatch(name)
            )
            valid_dynamic = name.startswith("by_") and bool(
                _IDENTIFIER.fullmatch(name[3:])
            )
            if kind is not _RouteEntryKind.DIRECTORY and not (
                is_symlink and (valid_static or valid_dynamic)
            ):
                continue
            if name.startswith("by_"):
                parameter = name[3:]
                if not _IDENTIFIER.fullmatch(parameter):
                    self.diagnostics.append(
                        _filesystem_diagnostic(
                            self.paths,
                            entry,
                            "dynamic route directory must use by_<param> with a "
                            "lowercase ASCII identifier",
                        )
                    )
                    continue
                browser = "{" + parameter + "}"
            elif _IDENTIFIER.fullmatch(name):
                parameter = None
                browser = name.replace("_", "-")
            else:
                self.diagnostics.append(
                    _filesystem_diagnostic(
                        self.paths,
                        entry,
                        "static route directory must use a lowercase ASCII "
                        "Python identifier",
                    )
                )
                continue
            if is_symlink:
                self.diagnostics.append(
                    _filesystem_diagnostic(
                        self.paths, entry, "live route directory must not be a symlink"
                    )
                )
                continue
            children.append(_Child(name, browser, parameter, entry))

        dynamic = [child for child in children if child.parameter is not None]
        if len(dynamic) > 1:
            first = dynamic[0]
            for other in dynamic[1:]:
                path = _app_relative(self.paths, other.path)
                first_path = _app_relative(self.paths, first.path)
                self.diagnostics.append(
                    RouteDiagnostic(
                        "PYGANINI011",
                        "route-collision",
                        path,
                        f"dynamic siblings at source directories {first_path} "
                        f"({first.parameter!r}) and {path} ({other.parameter!r}) "
                        f"have shared parent route {route_path!r}",
                    )
                )
        static = sorted(
            (child for child in children if child.parameter is None),
            key=lambda child: (child.browser_segment, child.name),
        )
        return [*static, *sorted(dynamic, key=lambda child: child.name)]

    def _scan(
        self,
        route_directory: _RouteDirectory,
        directory: Path,
        parts: tuple[str, ...],
        segments: tuple[str, ...],
        parameters: tuple[str, ...],
        parameter_sources: tuple[PurePosixPath, ...],
        *,
        app_directory: _RouteDirectory,
        nodes: list[RouteNode],
        context: Literal["live", "mounted"],
        source_base: PurePosixPath,
        module_parts: tuple[str, ...],
    ) -> None:
        entries = self._directory_entries(route_directory, directory)
        if entries is None:
            return
        if context == "mounted" and "middleware.py" in entries:
            self.diagnostics.append(
                _filesystem_diagnostic(
                    self.paths,
                    directory / "middleware.py",
                    "middleware.py is not supported in a referenced mounted source",
                )
            )
        if not self._validate_package(
            route_directory,
            directory,
            missing_message=(
                "mounted source directory requires a contained regular __init__.py"
                if context == "mounted"
                else "live route directory requires a contained regular __init__.py"
            ),
            read_marker=context == "mounted",
            read_message="cannot read mounted source package marker",
        ):
            return
        route_path = _route_path(segments)
        module = ".".join((*module_parts, *parts))
        declaration: NormalizedRoute | None = None
        route_file = directory / "route.py"
        if route_file.name in entries:
            parsed = _read_convention(
                self.paths, route_directory, route_file, self.diagnostics
            )
            if parsed is not None:
                relative, tree, source = parsed
                declaration = _parse_route_module(
                    tree,
                    source=source,
                    path=relative,
                    route_module=module + ".route",
                    diagnostics=self.diagnostics,
                    context=context,
                )
                if declaration is not None:
                    validated: set[str] = set()
                    for template in _declared_templates(declaration):
                        if template.environment_name in validated:
                            continue
                        validated.add(template.environment_name)
                        if (
                            declaration.kit is None
                            or declaration.kit.template_root is None
                        ):
                            _read_template(
                                self.paths,
                                route_directory,
                                directory
                                / PurePosixPath(template.environment_name).name,
                                self.diagnostics,
                            )
                        else:
                            self._read_shared_template(app_directory, template)

        middleware: MiddlewareSource | None = None
        if context == "live" and "middleware.py" in entries:
            middleware_file = directory / "middleware.py"
            parsed = _read_convention(
                self.paths,
                route_directory,
                middleware_file,
                self.diagnostics,
                field="MIDDLEWARE",
            )
            if parsed is not None:
                relative, tree, _ = parsed
                middleware = _parse_middleware_module(
                    tree,
                    path=relative,
                    route_prefix=route_path,
                    diagnostics=self.diagnostics,
                )

        layout: LayoutSource | None = None
        layout_file = directory / "layout.py"
        if layout_file.name in entries:
            parsed = _read_convention(
                self.paths, route_directory, layout_file, self.diagnostics
            )
            template_relative = _read_template(
                self.paths,
                route_directory,
                directory / "layout.jinja",
                self.diagnostics,
            )
            if parsed is not None and template_relative is not None:
                relative, _, _ = parsed
                layout = LayoutSource(
                    SourcePosition(relative, 1, 1),
                    route_path,
                    TemplateSource(
                        SourcePosition(template_relative, 1, 1),
                        _environment_name(template_relative),
                    ),
                )

        route_file_source = SourcePosition(
            _app_relative(self.paths, route_file),
            1,
            1,
        )
        nodes.append(
            RouteNode(
                source_base.joinpath(*parts),
                module,
                route_path,
                parameters,
                declaration,
                layout,
                owner=route_file_source,
                source=route_file_source,
                middleware=middleware,
                error_page_template=(
                    None if declaration is None else declaration.error_page_template
                ),
                error_fragment_template=(
                    None if declaration is None else declaration.error_fragment_template
                ),
            )
        )

        for child in self._children(route_directory, directory, entries, route_path):
            child_parameters = parameters
            child_parameter_sources = parameter_sources
            if child.parameter is not None:
                if child.parameter in parameters:
                    previous_source = parameter_sources[
                        parameters.index(child.parameter)
                    ]
                    self.diagnostics.append(
                        RouteDiagnostic(
                            "PYGANINI011",
                            "route-collision",
                            _app_relative(self.paths, child.path),
                            f"dynamic parameter {child.parameter!r} repeats an "
                            f"ancestor from {previous_source} at "
                            f"{_app_relative(self.paths, child.path)} under "
                            f"route {route_path}",
                        )
                    )
                child_parameters = (*parameters, child.parameter)
                child_parameter_sources = (
                    *parameter_sources,
                    _app_relative(self.paths, child.path),
                )
            try:
                child_directory = route_directory.open_child(child.name)
            except OSError as error:
                operation = "read" if isinstance(error, PermissionError) else "access"
                self.diagnostics.append(
                    _filesystem_diagnostic(
                        self.paths,
                        child.path,
                        f"cannot {operation} route directory: {error}",
                    )
                )
                continue
            try:
                self._scan(
                    child_directory,
                    child.path,
                    (*parts, child.name),
                    (*segments, child.browser_segment),
                    child_parameters,
                    child_parameter_sources,
                    app_directory=app_directory,
                    nodes=nodes,
                    context=context,
                    source_base=source_base,
                    module_parts=module_parts,
                )
            finally:
                self._close_directory(child_directory)

    def _validate_middleware(self, graph: RouteGraph) -> None:
        endpoints = tuple(iter_endpoints(graph))
        for group in _groups(endpoints):
            method_endpoints = _method_endpoints(group)
            if not method_endpoints:
                continue
            first_method = next(
                method for method in _METHOD_ORDER if method in method_endpoints
            )
            first_endpoint = method_endpoints[first_method]
            first_chain = _endpoint_node(graph, first_endpoint).middleware_chain
            first_signature = _middleware_signature(first_chain)
            for method in _METHOD_ORDER:
                endpoint = method_endpoints.get(method)
                if endpoint is None or method == first_method:
                    continue
                chain = _endpoint_node(graph, endpoint).middleware_chain
                if _middleware_signature(chain) == first_signature:
                    continue
                first_label = _middleware_endpoint_label(first_endpoint, first_method)
                endpoint_label = _middleware_endpoint_label(endpoint, method)
                message = (
                    f"normalized path: {group.path}; incompatible middleware "
                    f"chains; {first_label}; "
                    f"chain: {_middleware_chain_label(first_chain)}; "
                    f"{endpoint_label}; "
                    f"chain: {_middleware_chain_label(chain)}; "
                    f"{_middleware_chain_difference(first_chain, chain)}"
                )
                diagnostic = _collision_diagnostic(
                    endpoint.source, "middleware", message
                )
                self.diagnostics.append(
                    replace(
                        diagnostic,
                        owners=tuple(
                            sorted(
                                {
                                    first_endpoint.owner or first_endpoint.source,
                                    endpoint.owner or endpoint.source,
                                },
                                key=lambda owner: (
                                    owner.path.as_posix(),
                                    owner.line,
                                    owner.column,
                                ),
                            )
                        ),
                        method=method,
                    )
                )

    def _validate_endpoints(self, graph: RouteGraph) -> None:
        self._validate_middleware(graph)
        self._validate_navigation(graph)
        seen: dict[tuple[str, str], Endpoint] = {}
        patterns: dict[str, list[Endpoint]] = {}
        for endpoint in iter_endpoints(graph):
            for method in endpoint.methods:
                key = (method, endpoint.path)
                previous = seen.get(key)
                if previous is not None:
                    previous_evidence = _endpoint_collision_evidence(previous, method)
                    endpoint_evidence = _endpoint_collision_evidence(endpoint, method)
                    self.diagnostics.append(
                        _with_endpoint_collision_sort_evidence(
                            _collision_diagnostic(
                                endpoint.source,
                                "path",
                                f"{method} {endpoint.path} is owned by "
                                f"{previous_evidence} and {endpoint_evidence}",
                            ),
                            (previous, endpoint),
                            method,
                        )
                    )
                else:
                    seen[key] = endpoint
                previous_patterns = patterns.setdefault(method, [])
                for previous_pattern in previous_patterns:
                    if (
                        previous_pattern.path != endpoint.path
                        and _route_patterns_overlap(
                            previous_pattern.path, endpoint.path
                        )
                    ):
                        previous_evidence = _endpoint_collision_evidence(
                            previous_pattern, method
                        )
                        endpoint_evidence = _endpoint_collision_evidence(
                            endpoint, method
                        )
                        self.diagnostics.append(
                            _with_endpoint_collision_sort_evidence(
                                _collision_diagnostic(
                                    endpoint.source,
                                    "path",
                                    f"{previous_evidence} overlaps {endpoint_evidence}",
                                ),
                                (previous_pattern, endpoint),
                                method,
                            )
                        )
                previous_patterns.append(endpoint)

    def _validate_navigation(self, graph: RouteGraph) -> None:
        live_nodes = tuple(node for node in graph.nodes if node.declaration is not None)
        live_paths = {node.route_path for node in live_nodes}
        for node in live_nodes:
            declaration = node.declaration
            assert declaration is not None
            for destination in declaration.destinations:
                if destination.target_path not in live_paths:
                    trail_key = (
                        ""
                        if destination.trail_key is None
                        else f" trail_key={destination.trail_key!r}"
                    )
                    self.diagnostics.append(
                        _with_navigation_mount_evidence(
                            _collision_diagnostic(
                                destination.source,
                                "destinations",
                                f"destination {destination.name!r}{trail_key} "
                                "targets absent "
                                f"live route {destination.target_path!r}; source route "
                                f"{node.route_path!r}",
                            ),
                            node,
                        )
                    )
        for node in live_nodes:
            ancestors = tuple(
                candidate
                for candidate in live_nodes
                if candidate.route_path == "/"
                or candidate.route_path == node.route_path
                or (
                    candidate.route_path != "/"
                    and node.route_path.startswith(candidate.route_path + "/")
                )
            )
            keys: dict[str, tuple[RouteNavSource, RouteNode]] = {}
            for candidate in sorted(
                ancestors,
                key=lambda item: (
                    len(item.route_path.strip("/").split("/"))
                    if item.route_path != "/"
                    else 0,
                    item.route_path,
                ),
            ):
                candidate_declaration = candidate.declaration
                if candidate_declaration is None or candidate_declaration.nav is None:
                    continue
                nav = candidate_declaration.nav
                if nav.value.key is None:
                    continue
                previous = keys.get(nav.value.key)
                if previous is not None:
                    previous_nav, previous_node = previous
                    diagnostic = _collision_diagnostic(
                        nav.source,
                        "nav",
                        f"dynamic navigation key {nav.value.key!r} is repeated "
                        "in canonical trail at "
                        f"{_source_label(previous_nav.source)} and "
                        f"{_source_label(nav.source)}",
                    )
                    self.diagnostics.append(
                        _with_navigation_mount_evidence(
                            diagnostic,
                            candidate if candidate.mount is not None else previous_node,
                        )
                    )
                else:
                    keys[nav.value.key] = (nav, candidate)


def build_route_graph(paths: ProjectPaths) -> RouteGraph:
    """Scan, normalize, and validate the application's static route graph."""
    return _GraphBuilder(paths).build()
