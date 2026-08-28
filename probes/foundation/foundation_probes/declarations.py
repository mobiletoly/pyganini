import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class DeclarationDiagnostic(ValueError):
    def __init__(
        self,
        *,
        source: Path,
        node: ast.AST,
        field: str,
        reason: str,
    ) -> None:
        self.source = source
        self.line = getattr(node, "lineno", 1)
        self.column = getattr(node, "col_offset", 0) + 1
        self.field = field
        self.reason = reason
        super().__init__(
            f"AST phase: {source}:{self.line}:{self.column}: field {field}: {reason}"
        )


@dataclass(frozen=True, slots=True, order=True)
class HandlerReference:
    module: str | None
    symbol: str


@dataclass(frozen=True, slots=True)
class NormalizedDeclaration:
    path: str
    parameters: tuple[str, ...]
    page: HandlerReference
    fragments: tuple[HandlerReference, ...]
    actions: tuple[HandlerReference, ...]
    metadata: tuple[tuple[str, str], ...]

    def stable_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class ImportBinding:
    module: str
    symbol: str | None


@dataclass(frozen=True, slots=True)
class BindingEvent:
    name: str
    node: ast.AST
    kind: str
    direct: bool


def _diagnostic(
    source: Path,
    node: ast.AST,
    field: str,
    reason: str,
) -> DeclarationDiagnostic:
    return DeclarationDiagnostic(
        source=source,
        node=node,
        field=field,
        reason=reason,
    )


def _literal(
    source: Path,
    node: ast.AST,
    field: str,
    expected: type[Any] | tuple[type[Any], ...],
) -> Any:
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError) as error:
        raise _diagnostic(
            source,
            node,
            field,
            "requires literal data; calls and computed values are unsupported",
        ) from error
    if not isinstance(value, expected):
        expected_name = (
            expected.__name__
            if isinstance(expected, type)
            else " or ".join(item.__name__ for item in expected)
        )
        raise _diagnostic(source, node, field, f"requires {expected_name} literal")
    return value


def _handler(
    source: Path,
    node: ast.AST,
    field: str,
    imports: dict[str, ImportBinding],
    local_symbols: set[str],
    invalid_bindings: dict[str, str],
) -> HandlerReference:
    if isinstance(node, ast.Name):
        if node.id in invalid_bindings:
            raise _diagnostic(source, node, field, invalid_bindings[node.id])
        if node.id in imports:
            binding = imports[node.id]
            if binding.symbol is None:
                raise _diagnostic(
                    source, node, field, "module reference needs a symbol"
                )
            return HandlerReference(binding.module, binding.symbol)
        if node.id in local_symbols:
            return HandlerReference(None, node.id)
        raise _diagnostic(source, node, field, f"missing handler symbol {node.id!r}")
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        attribute_binding = imports.get(node.value.id)
        if attribute_binding is not None and attribute_binding.symbol is None:
            return HandlerReference(attribute_binding.module, node.attr)
    raise _diagnostic(
        source,
        node,
        field,
        "requires a named local or imported handler reference",
    )


def _handler_tuple(
    source: Path,
    node: ast.AST,
    field: str,
    imports: dict[str, ImportBinding],
    local_symbols: set[str],
    invalid_bindings: dict[str, str],
) -> tuple[HandlerReference, ...]:
    if not isinstance(node, (ast.Tuple, ast.List)):
        raise _diagnostic(source, node, field, "requires a literal handler sequence")
    return tuple(
        _handler(
            source,
            item,
            field,
            imports,
            local_symbols,
            invalid_bindings,
        )
        for item in node.elts
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
        self.events: list[BindingEvent] = []

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.events.extend(
            BindingEvent(name, node, "named expression", self.direct)
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
) -> tuple[BindingEvent, ...]:
    if node is None:
        return ()
    visitor = _NamedExpressionVisitor(direct=direct)
    visitor.visit(node)
    return tuple(visitor.events)


def _function_expression_events(
    statement: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    direct: bool,
) -> tuple[BindingEvent, ...]:
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


def _pattern_events(pattern: ast.pattern, *, direct: bool) -> tuple[BindingEvent, ...]:
    events: list[BindingEvent] = []
    if isinstance(pattern, (ast.MatchAs, ast.MatchStar)) and pattern.name is not None:
        events.append(BindingEvent(pattern.name, pattern, "match capture", direct))
    elif isinstance(pattern, ast.MatchMapping) and pattern.rest is not None:
        events.append(BindingEvent(pattern.rest, pattern, "match capture", direct))
    for child in ast.iter_child_nodes(pattern):
        if isinstance(child, ast.pattern):
            events.extend(_pattern_events(child, direct=direct))
    return tuple(events)


def _statement_events(statement: ast.stmt, *, direct: bool) -> tuple[BindingEvent, ...]:
    events: list[BindingEvent] = []
    nested = False
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
        kind = "function definition" if direct else "conditional function definition"
        events.append(BindingEvent(statement.name, statement, kind, direct))
        events.extend(_function_expression_events(statement, direct=direct))
    elif isinstance(statement, ast.ClassDef):
        kind = "class definition" if direct else "conditional class definition"
        events.append(BindingEvent(statement.name, statement, kind, direct))
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
                events.append(BindingEvent("*", alias, "star import", direct))
            else:
                name = alias.asname or alias.name
                kind = "import binding" if direct else "conditional import binding"
                events.append(BindingEvent(name, alias, kind, direct))
    elif isinstance(statement, ast.Import):
        for alias in statement.names:
            name = alias.asname or alias.name.split(".", 1)[0]
            kind = "import binding" if direct else "conditional import binding"
            events.append(BindingEvent(name, alias, kind, direct))
    elif isinstance(statement, ast.Assign):
        kind = "assignment" if direct else "conditional assignment"
        for target in statement.targets:
            events.extend(
                BindingEvent(name, target, kind, direct)
                for name in _bound_names(target)
            )
        events.extend(_expression_events(statement.value, direct=direct))
    elif isinstance(statement, ast.AnnAssign):
        kind = "annotated binding" if direct else "conditional annotated binding"
        events.extend(
            BindingEvent(name, statement.target, kind, direct)
            for name in _bound_names(statement.target)
        )
        events.extend(_expression_events(statement.annotation, direct=direct))
        events.extend(_expression_events(statement.value, direct=direct))
    elif isinstance(statement, ast.AugAssign):
        kind = "augmented binding" if direct else "conditional augmented binding"
        events.extend(
            BindingEvent(name, statement.target, kind, direct)
            for name in _bound_names(statement.target)
        )
        events.extend(_expression_events(statement.value, direct=direct))
    elif isinstance(statement, (ast.For, ast.AsyncFor)):
        events.extend(
            BindingEvent(name, statement.target, "loop target", direct)
            for name in _bound_names(statement.target)
        )
        events.extend(_expression_events(statement.iter, direct=direct))
        nested = True
    elif isinstance(statement, (ast.With, ast.AsyncWith)):
        for item in statement.items:
            events.extend(_expression_events(item.context_expr, direct=direct))
            if item.optional_vars is not None:
                events.extend(
                    BindingEvent(name, item.optional_vars, "with target", direct)
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
                    BindingEvent(handler.name, handler, "exception target", direct)
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
                BindingEvent(name, target, "delete binding", direct)
                for name in _bound_names(target)
            )
    elif isinstance(statement, ast.TypeAlias):
        events.extend(
            BindingEvent(name, statement.name, "type alias", direct)
            for name in _bound_names(statement.name)
        )
        events.extend(_expression_events(statement.value, direct=direct))
        for type_param in statement.type_params:
            events.extend(_expression_events(type_param, direct=direct))
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
            isinstance(statement, ast.If)
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


def _is_directly_handled(statement: ast.stmt, event: BindingEvent) -> bool:
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
    )


def _invalidate_event(
    event: BindingEvent,
    imports: dict[str, ImportBinding],
    local_symbols: set[str],
    invalid_bindings: dict[str, str],
) -> None:
    imports.pop(event.name, None)
    local_symbols.discard(event.name)
    invalid_bindings[event.name] = (
        f"handler symbol {event.name!r} was rebound by unsupported {event.kind}"
    )


def _invalidate_bindings(
    names: tuple[str, ...],
    imports: dict[str, ImportBinding],
    local_symbols: set[str],
    invalid_bindings: dict[str, str],
) -> None:
    for name in names:
        imports.pop(name, None)
        local_symbols.discard(name)
        invalid_bindings[name] = (
            f"handler symbol {name!r} was rebound by unsupported assignment"
        )


def parse_declaration(source: Path) -> NormalizedDeclaration:
    text = source.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(source))
    imports: dict[str, ImportBinding] = {}
    local_symbols: set[str] = set()
    invalid_bindings: dict[str, str] = {}
    declaration: ast.Call | None = None
    declaration_imports: dict[str, ImportBinding] = {}
    declaration_local_symbols: set[str] = set()
    declaration_invalid_bindings: dict[str, str] = {}

    statement_events = {
        id(statement): _statement_events(statement, direct=True)
        for statement in tree.body
    }
    for events in statement_events.values():
        for event in events:
            if event.kind == "star import":
                raise _diagnostic(
                    source,
                    event.node,
                    "imports",
                    "star import bindings are not statically enumerable",
                )
            if event.name == "ROUTE" and not (
                event.direct
                and event.kind
                in {"assignment", "annotated binding", "augmented binding"}
            ):
                raise _diagnostic(
                    source,
                    event.node,
                    "ROUTE",
                    f"{event.kind} is unsupported; a single direct module "
                    "assignment is required",
                )

    for statement in tree.body:
        events = statement_events[id(statement)]
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if statement.decorator_list:
                raise _diagnostic(
                    source,
                    statement.decorator_list[0],
                    "registration",
                    "decorator-driven route registration is unsupported",
                )
            imports.pop(statement.name, None)
            invalid_bindings.pop(statement.name, None)
            local_symbols.add(statement.name)
        elif isinstance(statement, ast.ImportFrom):
            module = "." * statement.level + (statement.module or "")
            for alias in statement.names:
                bound_name = alias.asname or alias.name
                local_symbols.discard(bound_name)
                invalid_bindings.pop(bound_name, None)
                imports[bound_name] = ImportBinding(module, alias.name)
        elif isinstance(statement, ast.Import):
            for alias in statement.names:
                bound_name = alias.asname or alias.name.split(".", 1)[0]
                module = alias.name if alias.asname else bound_name
                local_symbols.discard(bound_name)
                invalid_bindings.pop(bound_name, None)
                imports[bound_name] = ImportBinding(module, None)
        elif isinstance(statement, ast.Assign):
            names = tuple(
                name for target in statement.targets for name in _bound_names(target)
            )
            if "ROUTE" not in names:
                _invalidate_bindings(
                    names,
                    imports,
                    local_symbols,
                    invalid_bindings,
                )
            else:
                if not (
                    len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name)
                    and statement.targets[0].id == "ROUTE"
                ):
                    raise _diagnostic(
                        source,
                        statement,
                        "ROUTE",
                        "a single direct assignment is required",
                    )
                if declaration is not None:
                    raise _diagnostic(
                        source,
                        statement,
                        "ROUTE",
                        "multiple declarations are unsupported",
                    )
                if (
                    not isinstance(statement.value, ast.Call)
                    or not isinstance(
                        statement.value.func,
                        ast.Name,
                    )
                    or statement.value.func.id != "route"
                ):
                    raise _diagnostic(
                        source,
                        statement.value,
                        "ROUTE",
                        "requires the probe route constructor",
                    )
                declaration = statement.value
                declaration_imports = dict(imports)
                declaration_local_symbols = set(local_symbols)
                declaration_invalid_bindings = dict(invalid_bindings)
        elif isinstance(statement, ast.AnnAssign):
            names = _bound_names(statement.target)
            if "ROUTE" in names:
                raise _diagnostic(
                    source,
                    statement,
                    "ROUTE",
                    "annotated binding is unsupported",
                )
            _invalidate_bindings(
                names,
                imports,
                local_symbols,
                invalid_bindings,
            )
        elif isinstance(statement, ast.AugAssign):
            names = _bound_names(statement.target)
            if "ROUTE" in names:
                raise _diagnostic(
                    source,
                    statement,
                    "ROUTE",
                    "augmented binding is unsupported",
                )
            _invalidate_bindings(
                names,
                imports,
                local_symbols,
                invalid_bindings,
            )

        if declaration is None:
            for event in events:
                if not _is_directly_handled(statement, event):
                    _invalidate_event(
                        event,
                        imports,
                        local_symbols,
                        invalid_bindings,
                    )

    if declaration is None:
        raise _diagnostic(source, tree, "ROUTE", "missing declaration")
    if declaration.args:
        raise _diagnostic(
            source, declaration.args[0], "ROUTE", "positional fields unsupported"
        )
    fields: dict[str, ast.expr] = {}
    for keyword in declaration.keywords:
        if keyword.arg is None:
            raise _diagnostic(
                source,
                keyword.value,
                "ROUTE",
                "keyword expansion is unsupported",
            )
        if keyword.arg in fields:
            raise _diagnostic(
                source,
                keyword.value,
                keyword.arg,
                "duplicate declaration field",
            )
        fields[keyword.arg] = keyword.value
    required = {"path", "page"}
    missing = required - fields.keys()
    if missing:
        raise _diagnostic(
            source, declaration, sorted(missing)[0], "missing required field"
        )
    unknown = fields.keys() - {
        "path",
        "parameters",
        "page",
        "fragments",
        "actions",
        "metadata",
    }
    if unknown:
        name = sorted(unknown)[0]
        raise _diagnostic(source, fields[name], name, "unknown declaration field")

    path = _literal(source, fields["path"], "path", str)
    parameters_value = _literal(
        source,
        fields.get("parameters", ast.Tuple(elts=[])),
        "parameters",
        (tuple, list),
    )
    if not all(isinstance(item, str) for item in parameters_value):
        raise _diagnostic(
            source, fields["parameters"], "parameters", "requires strings"
        )
    metadata_value = _literal(
        source,
        fields.get("metadata", ast.Dict(keys=[], values=[])),
        "metadata",
        dict,
    )
    if not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in metadata_value.items()
    ):
        raise _diagnostic(
            source, fields["metadata"], "metadata", "requires string pairs"
        )

    empty = ast.Tuple(elts=[])
    return NormalizedDeclaration(
        path=path,
        parameters=tuple(parameters_value),
        page=_handler(
            source,
            fields["page"],
            "page",
            declaration_imports,
            declaration_local_symbols,
            declaration_invalid_bindings,
        ),
        fragments=_handler_tuple(
            source,
            fields.get("fragments", empty),
            "fragments",
            declaration_imports,
            declaration_local_symbols,
            declaration_invalid_bindings,
        ),
        actions=_handler_tuple(
            source,
            fields.get("actions", empty),
            "actions",
            declaration_imports,
            declaration_local_symbols,
            declaration_invalid_bindings,
        ),
        metadata=tuple(sorted(metadata_value.items())),
    )
