"""Render deterministic, typed URL helpers from the canonical route endpoints."""

from __future__ import annotations

import keyword
from dataclasses import dataclass, field, replace
from pathlib import PurePosixPath

from pyganini._generation import GeneratedArtifact, GenerationError
from pyganini._route_graph import (
    Endpoint,
    RouteGraph,
    RouteNode,
    SourcePosition,
    iter_endpoints,
)


@dataclass(slots=True)
class _MutableChild:
    member: str
    segment: str
    parameter: str | None
    node: _MutableNode


@dataclass(slots=True)
class _MutableNode:
    path: str
    owner_key: str | None = None
    evidence: Endpoint | None = None
    endpoint: Endpoint | None = None
    static: dict[str, _MutableChild] = field(default_factory=dict[str, _MutableChild])
    dynamic: _MutableChild | None = None
    conflicts: dict[tuple[str, str | None, str], _MutableChild] = field(
        default_factory=dict[tuple[str, str | None, str], _MutableChild]
    )


@dataclass(frozen=True, slots=True)
class _DestinationPlan:
    name: str
    member: str
    source_path: str
    target_path: str
    target_parameters: tuple[str, ...]
    trail_key: str | None


@dataclass(frozen=True, slots=True)
class _PlannedChild:
    member: str
    segment: str
    parameter: str | None
    node: _PlannedNode


@dataclass(frozen=True, slots=True)
class _PlannedNode:
    path: str
    owner_key: str | None
    has_endpoint: bool
    static: tuple[_PlannedChild, ...]
    dynamic: _PlannedChild | None
    destinations: tuple[_DestinationPlan, ...] = ()
    trail_keys: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class _Issue:
    source: SourcePosition
    path: str
    expression: str
    message: str
    key: tuple[str, str]
    details: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _BoundPlan:
    owner_path: str
    owner_key: str
    owner_node: _PlannedNode
    tree: _PlannedNode
    endpoints: tuple[Endpoint, ...]


@dataclass(frozen=True, slots=True)
class _MountPlan:
    mount: str
    bindings: tuple[_BoundPlan, ...]


@dataclass(frozen=True, slots=True)
class _URLHelperPlan:
    root: _PlannedNode
    mounts: tuple[_MountPlan, ...]
    catalog: _CatalogNode
    expressions: tuple[tuple[str, str], ...]
    navigation: bool = False


@dataclass(slots=True)
class _CatalogNode:
    children: dict[str, _CatalogNode] = field(
        default_factory=lambda: dict[str, _CatalogNode]()
    )
    plan: _MountPlan | None = None


def _mount_plan_details(plan: _MountPlan) -> tuple[str, ...]:
    return (
        "evidence phase: url-interface",
        *(
            detail
            for binding in plan.bindings
            for endpoint in binding.endpoints
            for detail in (
                f"live owner: {binding.owner_key}",
                f"mount identity: {plan.mount}",
                f"mounted source: {endpoint.source.path.as_posix()}",
                f"selector: {endpoint.source_path}",
                f"final path: {endpoint.path}",
            )
        ),
    )


def _mount_endpoint_details(endpoint: Endpoint) -> tuple[str, ...]:
    if endpoint.mount is None:
        return ()
    return (
        "evidence phase: url-interface",
        f"live owner: {(endpoint.owner or endpoint.source).path.as_posix()}",
        f"mount identity: {endpoint.mount}",
        f"mounted source: {endpoint.source.path.as_posix()}",
        f"selector: {endpoint.source_path}",
        f"final path: {endpoint.path}",
    )


def _destination_receiver(arguments: tuple[str, ...]) -> str:
    """Choose a destination method receiver absent from target arguments."""
    if "self" not in arguments:
        return "self"
    if "instance" not in arguments:
        return "instance"
    index = 0
    while True:
        receiver = f"receiver_{index}"
        if receiver not in arguments:
            return receiver
        index += 1


def _source_display(source: SourcePosition) -> str:
    return f"{source.path}:{source.line}:{source.column}"


def _endpoint_key(
    endpoint: Endpoint,
) -> tuple[str, int, int, str, str, tuple[str, ...], str, str, str]:
    return (
        endpoint.source.path.as_posix(),
        endpoint.source.line,
        endpoint.source.column,
        endpoint.path,
        endpoint.kind,
        endpoint.methods,
        endpoint.handler.module,
        endpoint.handler.symbol,
        endpoint.handler.binding,
    )


def _issue_order(issue: _Issue) -> tuple[str, int, int, str, str, str]:
    return (
        issue.source.path.as_posix(),
        issue.source.line,
        issue.source.column,
        issue.path,
        issue.expression,
        issue.message,
    )


def _add_issue(issues: list[_Issue], issue: _Issue) -> None:
    for index, previous in enumerate(issues):
        if previous.key != issue.key:
            continue
        if _issue_order(issue) < _issue_order(previous):
            issues[index] = issue
        return
    issues.append(issue)


def _append_path(parent: str, segment: str) -> str:
    if parent == "/":
        return "/" + segment
    return parent + "/" + segment


def _owner_anchor(graph: RouteGraph, owner: SourcePosition) -> RouteNode:
    candidates = tuple(
        node
        for node in graph.nodes
        if node.mount is None
        and (
            node.owner == owner
            or PurePosixPath(node.source_directory.as_posix(), "route.py") == owner.path
        )
    )
    if len(candidates) != 1:
        raise GenerationError(
            "PYGANINI016",
            "url-interface",
            owner.path.as_posix(),
            f"live owner {owner.path.as_posix()!r} must have exactly one URL node",
        )
    return candidates[0]


def _member(segment: str) -> tuple[str, str | None]:
    if segment.startswith("{") and segment.endswith("}"):
        parameter = segment[1:-1]
        return f"by_{parameter}", parameter
    return segment.replace("-", "_"), None


def _collision_message(
    *,
    current: Endpoint,
    previous: Endpoint,
    expression: str,
) -> str:
    owners = sorted(
        (
            (current.path, _source_display(current.source)),
            (previous.path, _source_display(previous.source)),
        ),
        key=lambda item: (item[0], item[1]),
    )
    return (
        f"URL paths {owners[0][0]!r} and {owners[1][0]!r} both map to "
        f"{expression!r} (owners {owners[0][1]} and {owners[1][1]})"
    )


def _member_collision(
    *,
    current: Endpoint,
    previous: Endpoint,
    expression: str,
    issues: list[_Issue],
) -> None:
    representative = min((current, previous), key=_endpoint_key)
    _add_issue(
        issues,
        _Issue(
            representative.source,
            representative.path,
            expression,
            _collision_message(
                current=current, previous=previous, expression=expression
            ),
            ("member-collision", expression),
            _mount_endpoint_details(representative),
        ),
    )


def _new_child(
    *,
    member: str,
    segment: str,
    parameter: str | None,
    path: str,
    endpoint: Endpoint,
) -> _MutableChild:
    node = _MutableNode(path=path, evidence=endpoint)
    return _MutableChild(member, segment, parameter, node)


def _previous_endpoint(node: _MutableNode, fallback: Endpoint) -> Endpoint:
    return node.evidence or fallback


def _deduplicated_endpoints(graph: RouteGraph) -> tuple[Endpoint, ...]:
    representatives: dict[str, Endpoint] = {}
    for endpoint in tuple(iter_endpoints(graph)):
        previous = representatives.get(endpoint.path)
        if previous is None or _endpoint_key(endpoint) < _endpoint_key(previous):
            representatives[endpoint.path] = endpoint
    return tuple(sorted(representatives.values(), key=_endpoint_key))


def _child_node(
    *,
    parent: _MutableNode,
    parent_expression: str,
    endpoint: Endpoint,
    segment: str,
    path: str,
    issues: list[_Issue],
) -> tuple[_MutableNode, str]:
    member, parameter = _member(segment)
    expression = f"{parent_expression}.{member}"

    if parameter is None:
        if keyword.iskeyword(member):
            _add_issue(
                issues,
                _Issue(
                    endpoint.source,
                    endpoint.path,
                    expression,
                    f"URL helper segment {segment!r} for {endpoint.path!r} "
                    "is a Python keyword",
                    ("keyword", expression),
                    _mount_endpoint_details(endpoint),
                ),
            )
        if member == "path":
            _add_issue(
                issues,
                _Issue(
                    endpoint.source,
                    endpoint.path,
                    expression,
                    f"URL helper segment 'path' for {endpoint.path!r} "
                    f"collides with reserved member 'path' at "
                    f"{parent_expression!r}",
                    ("reserved:path", expression),
                    _mount_endpoint_details(endpoint),
                ),
            )
        if parent_expression == "urls" and member in {"root", "with_base_path"}:
            _add_issue(
                issues,
                _Issue(
                    endpoint.source,
                    endpoint.path,
                    expression,
                    f"URL helper segment {segment!r} for {endpoint.path!r} "
                    f"collides with reserved member {member!r} at 'urls'",
                    (f"reserved:{member}", expression),
                    _mount_endpoint_details(endpoint),
                ),
            )

        static_conflict_key: tuple[str, str | None, str] = (
            member,
            parameter,
            segment,
        )
        conflict = parent.conflicts.get(static_conflict_key)
        if conflict is not None:
            return conflict.node, expression

        existing = parent.static.get(member)
        dynamic = parent.dynamic
        if existing is not None and existing.segment == segment:
            if dynamic is not None and dynamic.member == member:
                _member_collision(
                    current=endpoint,
                    previous=_previous_endpoint(dynamic.node, endpoint),
                    expression=expression,
                    issues=issues,
                )
            return existing.node, expression
        if existing is not None:
            _member_collision(
                current=endpoint,
                previous=_previous_endpoint(existing.node, endpoint),
                expression=expression,
                issues=issues,
            )
            child = _new_child(
                member=member,
                segment=segment,
                parameter=None,
                path=path,
                endpoint=endpoint,
            )
            parent.conflicts[static_conflict_key] = child
            return child.node, expression
        if dynamic is not None and dynamic.member == member:
            _member_collision(
                current=endpoint,
                previous=_previous_endpoint(dynamic.node, endpoint),
                expression=expression,
                issues=issues,
            )
            child = _new_child(
                member=member,
                segment=segment,
                parameter=None,
                path=path,
                endpoint=endpoint,
            )
            parent.conflicts[static_conflict_key] = child
            return child.node, expression
        child = _new_child(
            member=member,
            segment=segment,
            parameter=None,
            path=path,
            endpoint=endpoint,
        )
        parent.static[member] = child
        return child.node, expression

    if keyword.iskeyword(parameter):
        _add_issue(
            issues,
            _Issue(
                endpoint.source,
                endpoint.path,
                expression,
                f"URL dynamic parameter {parameter!r} for {endpoint.path!r} "
                "is a Python keyword",
                ("keyword-parameter", expression),
                _mount_endpoint_details(endpoint),
            ),
        )

    dynamic_conflict_key: tuple[str, str | None, str] = (
        member,
        parameter,
        segment,
    )
    conflict = parent.conflicts.get(dynamic_conflict_key)
    if conflict is not None:
        return conflict.node, expression

    existing = parent.static.get(member)
    dynamic = parent.dynamic
    if dynamic is not None and dynamic.parameter == parameter:
        if existing is not None:
            _member_collision(
                current=endpoint,
                previous=_previous_endpoint(existing.node, endpoint),
                expression=expression,
                issues=issues,
            )
        return dynamic.node, expression
    if existing is not None:
        _member_collision(
            current=endpoint,
            previous=_previous_endpoint(existing.node, endpoint),
            expression=expression,
            issues=issues,
        )
        child = _new_child(
            member=member,
            segment=segment,
            parameter=parameter,
            path=path,
            endpoint=endpoint,
        )
        parent.conflicts[dynamic_conflict_key] = child
        return child.node, expression
    child = _new_child(
        member=member,
        segment=segment,
        parameter=parameter,
        path=path,
        endpoint=endpoint,
    )
    parent.dynamic = child
    return child.node, expression


def _build_tree(graph: RouteGraph) -> _PlannedNode:
    root = _MutableNode("/")
    issues: list[_Issue] = []
    for endpoint in _deduplicated_endpoints(graph):
        node = root
        node.evidence = node.evidence or endpoint
        expression = "urls"
        if endpoint.path == "/":
            node.endpoint = node.endpoint or endpoint
        else:
            for segment in endpoint.path[1:].split("/"):
                child_path = _append_path(node.path, segment)
                node, expression = _child_node(
                    parent=node,
                    parent_expression=expression,
                    endpoint=endpoint,
                    segment=segment,
                    path=child_path,
                    issues=issues,
                )
                node.evidence = node.evidence or endpoint
            node.endpoint = node.endpoint or endpoint
    for mount_owner in graph.mount_owners:
        owner_key = mount_owner.owner.path
        owner_path = _owner_anchor(graph, mount_owner.owner).route_path
        current = root
        if owner_path == "/":
            current.owner_key = owner_key.as_posix()
            continue
        for segment in owner_path[1:].split("/"):
            member, parameter = _member(segment)
            child = (
                current.dynamic if parameter is not None else current.static.get(member)
            )
            if child is None:
                raise GenerationError(
                    "PYGANINI016",
                    "url-interface",
                    owner_path,
                    f"owner URL node {owner_path!r} is absent from the live URL tree",
                )
            current = child.node
        current.owner_key = owner_key.as_posix()
    if issues:
        ordered = sorted(
            issues,
            key=lambda issue: (
                issue.source.path.as_posix(),
                issue.source.line,
                issue.source.column,
                issue.path,
                issue.message,
            ),
        )
        first = ordered[0]
        raise GenerationError(
            "PYGANINI016",
            "url-interface",
            _source_display(first.source),
            first.message,
            details=(
                *first.details,
                *(
                    detail
                    for issue in ordered[1:]
                    for detail in (
                        f"{_source_display(issue.source)}: {issue.message}",
                        *issue.details,
                    )
                ),
            ),
        )
    return _freeze(root)


def _find_planned_node(root: _PlannedNode, path: str) -> _PlannedNode:
    if path == "/":
        return root
    current = root
    for segment in path[1:].split("/"):
        member, parameter = _member(segment)
        child = (
            current.dynamic
            if parameter is not None
            else next(
                (item for item in current.static if item.member == member),
                None,
            )
        )
        if child is None:
            raise GenerationError(
                "PYGANINI016",
                "url-interface",
                path,
                f"owner URL node {path!r} is absent from the live URL tree",
            )
        current = child.node
    return current


def _helper_expression(root: _PlannedNode, path: str) -> str:
    if path == "/":
        if not root.has_endpoint:
            raise GenerationError(
                "PYGANINI016",
                "url-interface",
                path,
                "root URL node is absent from the live URL tree",
            )
        return "urls.root.path"

    current = root
    expression = "urls"
    for segment in path[1:].split("/"):
        member, parameter = _member(segment)
        child = (
            current.dynamic
            if parameter is not None
            else next(
                (item for item in current.static if item.member == member),
                None,
            )
        )
        if child is None:
            raise GenerationError(
                "PYGANINI016",
                "url-interface",
                path,
                f"URL helper node {path!r} is absent from the live URL tree",
            )
        if parameter is None:
            expression += f".{member}"
        else:
            expression += f".{member}({parameter})"
        current = child.node
    if not current.has_endpoint:
        raise GenerationError(
            "PYGANINI016",
            "url-interface",
            path,
            f"URL helper node {path!r} has no endpoint in the live URL tree",
        )
    return expression + ".path"


def _relative_bound_tree(
    endpoints: tuple[Endpoint, ...],
    owner_path: str,
) -> _PlannedNode:
    root = _MutableNode("/")
    issues: list[_Issue] = []
    for endpoint in endpoints:
        relative = endpoint.path
        if owner_path != "/":
            relative = endpoint.path.removeprefix(owner_path) or "/"
        relative_endpoint = replace(
            endpoint,
            path=relative,
            node_path=relative,
        )
        current = root
        current.evidence = current.evidence or relative_endpoint
        expression = "mount_urls"
        if relative == "/":
            current.endpoint = current.endpoint or relative_endpoint
        else:
            for segment in relative[1:].split("/"):
                child_path = _append_path(current.path, segment)
                current, expression = _child_node(
                    parent=current,
                    parent_expression=expression,
                    endpoint=relative_endpoint,
                    segment=segment,
                    path=child_path,
                    issues=issues,
                )
                current.evidence = current.evidence or relative_endpoint
            current.endpoint = current.endpoint or relative_endpoint
    if issues:
        ordered = sorted(issues, key=_issue_order)
        first = ordered[0]
        raise GenerationError(
            "PYGANINI016",
            "url-interface",
            _source_display(first.source),
            first.message,
            details=(
                *first.details,
                *(
                    detail
                    for issue in ordered[1:]
                    for detail in (
                        f"{_source_display(issue.source)}: {issue.message}",
                        *issue.details,
                    )
                ),
            ),
        )
    return _freeze(root)


def _mount_plans(
    graph: RouteGraph,
    root: _PlannedNode,
) -> tuple[_MountPlan, ...]:
    endpoints = tuple(iter_endpoints(graph))
    grouped: dict[str, list[_BoundPlan]] = {}
    for mount_owner in graph.mount_owners:
        owner_path = _owner_anchor(graph, mount_owner.owner).route_path
        selected = tuple(
            endpoint
            for endpoint in endpoints
            if endpoint.mount == mount_owner.mount
            and endpoint.owner == mount_owner.owner
        )
        tree = _relative_bound_tree(selected, owner_path)
        grouped.setdefault(mount_owner.mount, []).append(
            _BoundPlan(
                owner_path,
                mount_owner.owner.path.as_posix(),
                _find_planned_node(root, owner_path),
                tree,
                selected,
            )
        )
    return tuple(
        _MountPlan(mount, tuple(values))
        for mount, values in sorted(grouped.items(), key=lambda item: item[0])
    )


def _render_bound_tree(
    tree: _PlannedNode,
    names: dict[int, str],
) -> list[str]:
    lines: list[str] = []
    for node in _flatten(tree):
        lines.extend(
            [
                "",
                "",
                "@_dataclass(frozen=True, slots=True)",
                f"class {names[id(node)]}:",
                "    _base_path: str",
                "    _local_path: str",
            ]
        )
        if node.has_endpoint:
            lines.extend(
                [
                    "",
                    "    @property",
                    "    def path(self) -> str:",
                    "        return self._base_path + (self._local_path or '/')",
                ]
            )
        for child in node.static:
            lines.extend(
                [
                    "",
                    "    @property",
                    f"    def {child.member}(self) -> {names[id(child.node)]}:",
                    f"        return {names[id(child.node)]}(",
                    "            self._base_path,",
                    f"            self._local_path + {('/' + child.segment)!a},",
                    "        )",
                ]
            )
        if node.dynamic is not None:
            parameter = node.dynamic.parameter
            assert parameter is not None
            receiver = "instance" if parameter == "self" else "self"
            lines.extend(
                [
                    "",
                    f"    def {node.dynamic.member}({receiver}, {parameter}: str) -> "
                    f"{names[id(node.dynamic.node)]}:",
                    f'        encoded = _quote_segment("parameter {parameter!r}", '
                    f"{parameter})",
                    f"        return {names[id(node.dynamic.node)]}(",
                    f"            {receiver}._base_path,",
                    f'            {receiver}._local_path + "/" + encoded,',
                    "        )",
                ]
            )
    return lines


def _catalog_tree(plans: tuple[_MountPlan, ...]) -> _CatalogNode:
    root = _CatalogNode()
    reserved = {"bind", "path", "root", "with_base_path"}
    for plan in plans:
        current = root
        components = plan.mount.split("/")
        for component in components:
            if keyword.iskeyword(component) or component in reserved:
                owner = plan.bindings[0].owner_key
                raise GenerationError(
                    "PYGANINI016",
                    "url-interface",
                    owner,
                    f"mounted source identity component {component!r} for "
                    f"{plan.mount!r} collides with a reserved URL catalog member",
                    details=_mount_plan_details(plan),
                )
            if current.plan is not None:
                owner = current.plan.bindings[0].owner_key
                raise GenerationError(
                    "PYGANINI016",
                    "url-interface",
                    owner,
                    f"mounted source identities {current.plan.mount!r} and "
                    f"{plan.mount!r} cannot share a URL catalog member",
                    details=(
                        *_mount_plan_details(current.plan),
                        *_mount_plan_details(plan),
                    ),
                )
            current = current.children.setdefault(component, _CatalogNode())
        if current.plan is not None or current.children:
            raise GenerationError(
                "PYGANINI016",
                "url-interface",
                plan.bindings[0].owner_key,
                f"mounted source identities {plan.mount!r} and an existing "
                "URL catalog member collide",
                details=_mount_plan_details(plan),
            )
        current.plan = plan
    return root


def _url_helper_projection(graph: RouteGraph) -> _URLHelperPlan:
    """Build the one transient URL-helper plan shared by generation and inspection."""
    root, navigation = _navigation_metadata(graph, _build_tree(graph))
    mounts = _mount_plans(graph, root)
    catalog = _catalog_tree(mounts)
    expressions = tuple(
        sorted(
            (
                endpoint.path,
                _helper_expression(root, endpoint.path),
            )
            for endpoint in _deduplicated_endpoints(graph)
        )
    )
    return _URLHelperPlan(root, mounts, catalog, expressions, navigation)


def _render_catalog(
    node: _CatalogNode,
    names: dict[int, str],
    bound_names: dict[int, str],
    *,
    prefix: str,
    lines: list[str],
) -> str:
    if node.plan is not None:
        plan = node.plan
        leaf_name = f"_MountCatalog{prefix}"
        lines.extend(
            [
                "",
                "",
                "@_dataclass(frozen=True, slots=True)",
                f"class {leaf_name}:",
            ]
        )
        if len(plan.bindings) == 1:
            binding = plan.bindings[0]
            owner_name = names[id(binding.owner_node)]
            bound_name = bound_names[id(binding.tree)]
            lines.extend(
                [
                    "",
                    f"    def bind(self, owner: {owner_name}) -> {bound_name}:",
                    "        owner_key = getattr(owner, '_owner_key', None)",
                ]
            )
        else:
            for binding in plan.bindings:
                owner_name = names[id(binding.owner_node)]
                bound_name = bound_names[id(binding.tree)]
                lines.extend(
                    [
                        "",
                        "    @_overload",
                        f"    def bind(self, owner: {owner_name}) -> {bound_name}:",
                        "        ...",
                    ]
                )
            lines.extend(
                [
                    "",
                    "    def bind(self, owner: object) -> object:",
                    "        owner_key = getattr(owner, '_owner_key', None)",
                ]
            )
        for binding in plan.bindings:
            bound_name = bound_names[id(binding.tree)]
            invalid_owner_message = (
                f"owner is not a generated live URL node for mount {plan.mount}"
            )
            lines.extend(
                [
                    f"        if owner_key == {binding.owner_key!a}:",
                    "            base_path = getattr(owner, '_base_path', None)",
                    "            local_path = getattr(owner, '_local_path', None)",
                    "            if not isinstance(base_path, str) or not isinstance(",
                    "                local_path, str",
                    "            ):",
                    "                raise ValueError(",
                    f"                    {invalid_owner_message!a}",
                    "                )",
                    f"            return {bound_name}(base_path, local_path)",
                ]
            )
        lines.extend(
            [
                "        raise ValueError(",
                f"            {f'owner is not a live owner of mount {plan.mount}'!a}",
                "        )",
            ]
        )
        return leaf_name

    class_name = f"_MountCatalog{prefix}"
    children: list[tuple[str, str]] = []
    for index, (component, child) in enumerate(sorted(node.children.items())):
        child_name = _render_catalog(
            child,
            names,
            bound_names,
            prefix=f"{prefix}_{index}",
            lines=lines,
        )
        children.append((component, child_name))
    lines.extend(
        [
            "",
            "",
            "@_dataclass(frozen=True, slots=True)",
            f"class {class_name}:",
        ]
    )
    for component, child_name in children:
        lines.extend(
            [
                "",
                "    @property",
                f"    def {component}(self) -> {child_name}:",
                f"        return {child_name}()",
            ]
        )
    if not children:
        lines.append("    pass")
    return class_name


def _freeze(node: _MutableNode) -> _PlannedNode:
    static = tuple(
        _PlannedChild(
            child.member,
            child.segment,
            child.parameter,
            _freeze(child.node),
        )
        for child in sorted(
            node.static.values(), key=lambda item: (item.member, item.segment)
        )
    )
    dynamic = node.dynamic
    planned_dynamic = (
        None
        if dynamic is None
        else _PlannedChild(
            dynamic.member,
            dynamic.segment,
            dynamic.parameter,
            _freeze(dynamic.node),
        )
    )
    return _PlannedNode(
        node.path,
        node.owner_key,
        node.endpoint is not None,
        static,
        planned_dynamic,
    )


def _navigation_metadata(
    graph: RouteGraph,
    root: _PlannedNode,
) -> tuple[_PlannedNode, bool]:
    destinations_by_source: dict[str, list[_DestinationPlan]] = {}
    keys_by_target: dict[str, set[str]] = {}
    for node in graph.nodes:
        declaration = node.declaration
        if declaration is None:
            continue
        for destination in declaration.destinations:
            target_parameters = tuple(
                segment[1:-1]
                for segment in destination.target_path[1:].split("/")
                if segment.startswith("{") and segment.endswith("}")
            )
            member = destination.name.replace("-", "_")
            if not member.isidentifier() or keyword.iskeyword(member):
                raise GenerationError(
                    "PYGANINI016",
                    "url-interface",
                    destination.source.path.as_posix(),
                    f"destination name {destination.name!r} becomes invalid "
                    f"Python member {member!r}",
                )
            destinations_by_source.setdefault(node.route_path, []).append(
                _DestinationPlan(
                    destination.name,
                    member,
                    node.route_path,
                    destination.target_path,
                    target_parameters,
                    destination.trail_key,
                )
            )
            if destination.trail_key is not None:
                keys_by_target.setdefault(destination.target_path, set()).add(
                    destination.trail_key
                )
    navigation = bool(destinations_by_source or keys_by_target)

    def annotate(node: _PlannedNode) -> _PlannedNode:
        static = tuple(
            replace(child, node=annotate(child.node)) for child in node.static
        )
        dynamic = (
            None
            if node.dynamic is None
            else replace(node.dynamic, node=annotate(node.dynamic.node))
        )
        destinations = tuple(
            sorted(
                destinations_by_source.get(node.path, ()),
                key=lambda item: (item.target_path, item.trail_key or "", item.member),
            )
        )
        trail_keys = tuple(
            (key, key.replace("-", "_"))
            for key in sorted(keys_by_target.get(node.path, ()))
        )
        for key, member in trail_keys:
            if not member.isidentifier() or keyword.iskeyword(member):
                raise GenerationError(
                    "PYGANINI016",
                    "url-interface",
                    node.path,
                    f"trail key {key!r} becomes invalid Python member {member!r}",
                )
        return replace(
            node,
            static=static,
            dynamic=dynamic,
            destinations=destinations,
            trail_keys=trail_keys,
        )

    annotated = annotate(root)
    for planned_node in _flatten(annotated):
        static_members = {child.member for child in planned_node.static}
        if "route_pattern" in static_members:
            raise GenerationError(
                "PYGANINI016",
                "url-interface",
                planned_node.path,
                "URL helper member 'route_pattern' is reserved by navigation",
            )
        if planned_node.destinations and "destinations" in static_members:
            raise GenerationError(
                "PYGANINI016",
                "url-interface",
                planned_node.path,
                "URL helper member 'destinations' collides with generated destinations",
            )
        if planned_node.trail_keys and "trail_keys" in static_members:
            raise GenerationError(
                "PYGANINI016",
                "url-interface",
                planned_node.path,
                "URL helper member 'trail_keys' collides with generated trail keys",
            )
    return annotated, navigation


def _flatten(node: _PlannedNode) -> tuple[_PlannedNode, ...]:
    values = [node]
    for child in node.static:
        values.extend(_flatten(child.node))
    if node.dynamic is not None:
        values.extend(_flatten(node.dynamic.node))
    return tuple(values)


def _render_navigation(plan: _URLHelperPlan) -> bytes:
    root = plan.root
    nodes = _flatten(root)
    names = {id(node): f"_URLNode{index}" for index, node in enumerate(nodes)}
    target_names = {id(node): f"_URLTarget{index}" for index, node in enumerate(nodes)}
    unbound_target_names = {
        id(node): f"_URLUnboundTarget{index}" for index, node in enumerate(nodes)
    }
    dynamic_parameters = {
        id(child.node): child.parameter
        for node in nodes
        if node.dynamic is not None
        for child in (node.dynamic,)
    }
    destination_values: dict[tuple[str, str], str] = {}
    destination_index = 0
    for node in nodes:
        for destination in node.destinations:
            destination_values[(node.path, destination.member)] = (
                f"_Destination{destination_index}"
            )
            destination_index += 1
    destination_collections = {
        node.path: f"_Destinations{index}"
        for index, node in enumerate(nodes)
        if node.destinations
    }
    trail_key_collections = {
        node.path: f"_TrailKeys{index}"
        for index, node in enumerate(nodes)
        if node.trail_keys
    }

    lines = [
        "# Code generated by pyganini; DO NOT EDIT.",
        "# pyright: reportPrivateUsage=false, reportUnusedClass=false",
        '"""Generated Pyganini URL helper interface."""',
        "",
        "from __future__ import annotations",
        "",
        "from dataclasses import dataclass as _dataclass",
        *(
            ("from typing import overload as _overload",)
            if any(len(mount.bindings) > 1 for mount in plan.mounts)
            else ()
        ),
        "from urllib.parse import quote as _quote",
        "",
        "from pyganini import Navigation as _Navigation",
        "from pyganini._navigation import _navigation_href",
        "from pyganini._url_binding import quote_segment as _quote_segment",
        "",
        '__all__ = ("mount_urls", "urls")',
        "",
        "def _normalize_base_path(base_path: object) -> str:",
        "    if not isinstance(base_path, str):",
        '        raise TypeError("base_path must be str")',
        '    if base_path in {"", "/"}:',
        '        return ""',
        '    if all(character == "/" for character in base_path):',
        '        raise ValueError("base_path must not contain empty path segments")',
        '    normalized = base_path if base_path.startswith("/") else "/" + base_path',
        '    normalized = normalized.rstrip("/")',
        '    segments = normalized[1:].split("/")',
        '    if any(segment == "" for segment in segments):',
        '        raise ValueError("base_path must not contain empty path segments")',
        "    quoted = tuple(",
        '        _quote_segment(f"base_path segment {index}", segment)',
        "        for index, segment in enumerate(segments, start=1)",
        "    )",
        '    return "/" + "/".join(quoted)',
        "",
        "def _add_trail_key(path: str, key: str) -> str:",
        (
            '    return path + ("&" if "?" in path else "?") + '
            '"_pyganini_nav_trail_key=" + _quote(key, safe="")'
        ),
        "",
        "@_dataclass(frozen=True, slots=True)",
        "class _URLRootPath:",
        "    _base_path: str",
        "    _owner_key: str | None",
        "",
        "    @property",
        "    def path(self) -> str:",
        '        return self._base_path + "/"',
        "",
        "    @property",
        "    def route_pattern(self) -> str:",
        '        return "/"',
    ]

    def destination_path(
        destination: _DestinationPlan,
        arguments: tuple[str, ...],
        receiver: str = "self",
    ) -> str:
        if destination.target_path == "/":
            expression = f'{receiver}._base_path + "/"'
        else:
            parts = destination.target_path[1:].split("/")
            fragments: list[str] = [f"{receiver}._base_path"]
            argument_index = 0
            for part in parts:
                if part.startswith("{"):
                    fragments.append(
                        '"/" + _quote_segment('
                        f'"parameter {arguments[argument_index]!s}", '
                        f"{arguments[argument_index]})"
                    )
                    argument_index += 1
                else:
                    fragments.append(f'"/{part}"')
            expression = " + ".join(fragments)
        if destination.trail_key is not None:
            expression = f"_add_trail_key({expression}, {destination.trail_key!a})"
        return expression

    for node_index, node in enumerate(nodes):
        lines.extend(
            [
                "",
                "",
                "@_dataclass(frozen=True, slots=True)",
                f"class {names[id(node)]}:",
                "    _base_path: str",
                "    _local_path: str",
                "    _owner_key: str | None",
                "",
                "    @property",
                "    def route_pattern(self) -> str:",
                f"        return {node.path!a}",
            ]
        )
        if node_index == 0:
            lines.extend(
                [
                    "",
                    (
                        f"    def with_base_path(self, base_path: str) -> "
                        f"{names[id(root)]}:"
                    ),
                    '        """Return this surface bound to a decoded path prefix."""',
                    (
                        f"        return {names[id(root)]}("
                        f'_normalize_base_path(base_path), "", self._owner_key)'
                    ),
                ]
            )
        if node_index == 0 and node.has_endpoint:
            lines.extend(
                [
                    "",
                    "    @property",
                    "    def root(self) -> _URLRootPath:",
                    "        return _URLRootPath(self._base_path, self._owner_key)",
                ]
            )
        if node_index != 0 and node.has_endpoint:
            lines.extend(
                [
                    "",
                    "    @property",
                    "    def path(self) -> str:",
                    "        return self._base_path + self._local_path",
                ]
            )
        if node.path in destination_collections:
            collection = destination_collections[node.path]
            lines.extend(
                [
                    "",
                    "    @property",
                    f"    def destinations(self) -> {collection}:",
                    f"        return {collection}(self._base_path)",
                ]
            )
        if node.path in trail_key_collections:
            collection = trail_key_collections[node.path]
            lines.extend(
                [
                    "",
                    "    @property",
                    f"    def trail_keys(self) -> {collection}:",
                    f"        return {collection}()",
                ]
            )
        for child in node.static:
            lines.extend(
                [
                    "",
                    "    @property",
                    f"    def {child.member}(self) -> {names[id(child.node)]}:",
                    f"        return {names[id(child.node)]}(",
                    "            self._base_path,",
                    f"            self._local_path + {('/' + child.segment)!a},",
                    f"            {child.node.owner_key!a},",
                    "        )",
                ]
            )
        if node.dynamic is not None:
            child = node.dynamic
            parameter = child.parameter
            assert parameter is not None
            lines.extend(
                [
                    "",
                    "    @property",
                    f"    def {child.member}(self) -> {target_names[id(child.node)]}:",
                    f"        return {target_names[id(child.node)]}(",
                    "            self._base_path,",
                    "            self._local_path,",
                    f"            {child.node.owner_key!a},",
                    "        )",
                ]
            )

    for node in nodes:
        lines.extend(
            [
                "",
                "",
                "@_dataclass(frozen=True, slots=True)",
                f"class {target_names[id(node)]}:",
                "    _base_path: str",
                "    _local_path: str",
                "    _owner_key: str | None",
                "",
                "    @property",
                "    def route_pattern(self) -> str:",
                f"        return {node.path!a}",
            ]
        )
        parameter = dynamic_parameters.get(id(node))
        if parameter is not None:
            receiver = "instance" if parameter == "self" else "self"
            lines.extend(
                [
                    "",
                    f"    def __call__({receiver}, {parameter}: str) -> "
                    f"{names[id(node)]}:",
                    (
                        f'        encoded = _quote_segment("parameter {parameter!r}", '
                        f"{parameter})"
                    ),
                    f"        return {names[id(node)]}(",
                    f"            {receiver}._base_path,",
                    f'            {receiver}._local_path + "/" + encoded,',
                    f"            {receiver}._owner_key,",
                    "        )",
                ]
            )
        if node.path in trail_key_collections:
            collection = trail_key_collections[node.path]
            lines.extend(
                [
                    "",
                    "    @property",
                    f"    def trail_keys(self) -> {collection}:",
                    f"        return {collection}()",
                ]
            )
        for child in node.static:
            lines.extend(
                [
                    "",
                    "    @property",
                    f"    def {child.member}(self) -> "
                    f"{unbound_target_names[id(child.node)]}:",
                    f"        return {unbound_target_names[id(child.node)]}(",
                    "            self._base_path,",
                    f"            self._local_path + {('/' + child.segment)!a},",
                    f"            {child.node.owner_key!a},",
                    "        )",
                ]
            )
        if node.dynamic is not None:
            child = node.dynamic
            lines.extend(
                [
                    "",
                    "    @property",
                    f"    def {child.member}(self) -> "
                    f"{unbound_target_names[id(child.node)]}:",
                    f"        return {unbound_target_names[id(child.node)]}(",
                    "            self._base_path,",
                    "            self._local_path,",
                    f"            {child.node.owner_key!a},",
                    "        )",
                ]
            )
        if not node.static and node.dynamic is None and parameter is None:
            lines.append("    pass")

    for node in nodes:
        lines.extend(
            [
                "",
                "",
                "@_dataclass(frozen=True, slots=True)",
                f"class {unbound_target_names[id(node)]}:",
                "    _base_path: str",
                "    _local_path: str",
                "    _owner_key: str | None",
                "",
                "    @property",
                "    def route_pattern(self) -> str:",
                f"        return {node.path!a}",
            ]
        )
        if node.path in trail_key_collections:
            collection = trail_key_collections[node.path]
            lines.extend(
                [
                    "",
                    "    @property",
                    f"    def trail_keys(self) -> {collection}:",
                    f"        return {collection}()",
                ]
            )
        for child in node.static:
            lines.extend(
                [
                    "",
                    "    @property",
                    f"    def {child.member}(self) -> "
                    f"{unbound_target_names[id(child.node)]}:",
                    f"        return {unbound_target_names[id(child.node)]}(",
                    "            self._base_path,",
                    f"            self._local_path + {('/' + child.segment)!a},",
                    f"            {child.node.owner_key!a},",
                    "        )",
                ]
            )
        if node.dynamic is not None:
            child = node.dynamic
            lines.extend(
                [
                    "",
                    "    @property",
                    f"    def {child.member}(self) -> "
                    f"{unbound_target_names[id(child.node)]}:",
                    f"        return {unbound_target_names[id(child.node)]}(",
                    "            self._base_path,",
                    "            self._local_path,",
                    f"            {child.node.owner_key!a},",
                    "        )",
                ]
            )

    for node in nodes:
        for destination in node.destinations:
            value_name = destination_values[(node.path, destination.member)]
            lines.extend(
                [
                    "",
                    "",
                    "@_dataclass(frozen=True, slots=True)",
                    f"class {value_name}:",
                    "    href: str",
                ]
            )
            if destination.trail_key is not None:
                lines.extend(
                    [
                        "",
                        (
                            "    def navigation_href("
                            "self, navigation: _Navigation) -> str:"
                        ),
                        "        return _navigation_href(navigation, self.href)",
                    ]
                )

    for node in nodes:
        if node.destinations:
            collection = destination_collections[node.path]
            lines.extend(
                [
                    "",
                    "",
                    "@_dataclass(frozen=True, slots=True)",
                    f"class {collection}:",
                    "    _base_path: str",
                ]
            )
            for destination in node.destinations:
                value_name = destination_values[(node.path, destination.member)]
                if destination.target_parameters:
                    arguments = destination.target_parameters
                    receiver = _destination_receiver(arguments)
                    target_expression = destination_path(
                        destination, arguments, receiver
                    )
                    lines.extend(
                        [
                            "",
                            f"    def {destination.member}({receiver}, "
                            + ", ".join(f"{argument}: str" for argument in arguments)
                            + f") -> {value_name}:",
                            f"        return {value_name}(",
                            f"            {target_expression},",
                            "        )",
                        ]
                    )
                else:
                    lines.extend(
                        [
                            "",
                            "    @property",
                            f"    def {destination.member}(self) -> {value_name}:",
                            (
                                f"        return {value_name}("
                                f"{destination_path(destination, ())})"
                            ),
                        ]
                    )

    for node in nodes:
        if node.trail_keys:
            collection = trail_key_collections[node.path]
            lines.extend(
                [
                    "",
                    "",
                    "@_dataclass(frozen=True, slots=True)",
                    f"class {collection}:",
                ]
            )
            for key, member in node.trail_keys:
                lines.extend(["", f"    {member}: str = {key!a}"])

    lines.extend(
        [
            "",
            "",
            f'urls: {names[id(root)]} = {names[id(root)]}("", "", {root.owner_key!a})',
        ]
    )
    bound_names: dict[int, str] = {}
    bound_lines: list[str] = []
    bound_index = 0
    for mount_plan in plan.mounts:
        for binding in mount_plan.bindings:
            bound_nodes = _flatten(binding.tree)
            bound_node_names = {
                id(node): f"_MountBound{bound_index}Node{index}"
                for index, node in enumerate(bound_nodes)
            }
            bound_names[id(binding.tree)] = bound_node_names[id(binding.tree)]
            bound_lines.extend(_render_bound_tree(binding.tree, bound_node_names))
            bound_index += 1
    lines.extend(bound_lines)
    catalog_name = _render_catalog(
        plan.catalog,
        names,
        bound_names,
        prefix="Root",
        lines=lines,
    )
    lines.extend(["", "", f"mount_urls: {catalog_name} = {catalog_name}()"])
    return ("\n".join(lines) + "\n").encode("ascii")


def _render(plan: _URLHelperPlan) -> bytes:
    if plan.navigation:
        return _render_navigation(plan)
    root = plan.root
    plans = plan.mounts
    nodes = _flatten(root)
    names = {id(node): f"_URLNode{index}" for index, node in enumerate(nodes)}
    root_name = names[id(root)]
    bound_names: dict[int, str] = {}
    bound_lines: list[str] = []
    bound_index = 0
    for mount_plan in plans:
        for binding in mount_plan.bindings:
            bound_nodes = _flatten(binding.tree)
            bound_node_names = {
                id(node): f"_MountBound{bound_index}Node{index}"
                for index, node in enumerate(bound_nodes)
            }
            bound_names[id(binding.tree)] = bound_node_names[id(binding.tree)]
            bound_lines.extend(_render_bound_tree(binding.tree, bound_node_names))
            bound_index += 1
    catalog = plan.catalog
    lines = [
        "# Code generated by pyganini; DO NOT EDIT.",
        '"""Generated Pyganini URL helper interface."""',
        "",
        "from __future__ import annotations",
        "",
        "from dataclasses import dataclass as _dataclass",
        *(
            ("from typing import overload as _overload",)
            if any(len(mount.bindings) > 1 for mount in plans)
            else ()
        ),
        "from urllib.parse import quote as _quote",
        "",
        '__all__ = ("mount_urls", "urls")',
        "",
        "def _quote_segment(label: str, value: object) -> str:",
        "    if not isinstance(value, str):",
        '        raise TypeError(f"{label} must be str")',
        '    if value == "":',
        '        raise ValueError(f"{label} must not be empty")',
        '    if value in {".", ".."}:',
        "        raise ValueError(f\"{label} must not be '.' or '..'\")",
        '    if "/" in value or chr(92) in value:',
        "        raise ValueError(",
        "            f\"{label} must not contain '/' or '\" + chr(92) + \"'\"",
        "        )",
        "    if any(",
        "        ord(character) < 32 or ord(character) == 127",
        "        for character in value",
        "    ):",
        "        raise ValueError(",
        '            f"{label} must not contain ASCII control characters"',
        "        )",
        "    try:",
        '        value.encode("utf-8")',
        "    except UnicodeEncodeError as error:",
        "        raise ValueError(",
        '            f"{label} must contain valid Unicode text"',
        "        ) from error",
        '    return _quote(value, safe="")',
        "",
        "def _normalize_base_path(base_path: object) -> str:",
        "    if not isinstance(base_path, str):",
        '        raise TypeError("base_path must be str")',
        '    if base_path in {"", "/"}:',
        '        return ""',
        '    if all(character == "/" for character in base_path):',
        '        raise ValueError("base_path must not contain empty path segments")',
        '    normalized = base_path if base_path.startswith("/") else "/" + base_path',
        '    normalized = normalized.rstrip("/")',
        '    segments = normalized[1:].split("/")',
        '    if any(segment == "" for segment in segments):',
        '        raise ValueError("base_path must not contain empty path segments")',
        "    quoted = tuple(",
        '        _quote_segment(f"base_path segment {index}", segment)',
        "        for index, segment in enumerate(segments, start=1)",
        "    )",
        '    return "/" + "/".join(quoted)',
        "",
        "@_dataclass(frozen=True, slots=True)",
        "class _URLRootPath:",
        "    _base_path: str",
        "    _owner_key: str | None",
        "",
        "    @property",
        "    def path(self) -> str:",
        '        return self._base_path + "/"',
    ]

    for node_index, node in enumerate(nodes):
        lines.extend(
            [
                "",
                "",
                "@_dataclass(frozen=True, slots=True)",
                f"class {names[id(node)]}:",
                "    _base_path: str",
                "    _local_path: str",
                "    _owner_key: str | None",
            ]
        )
        if node_index == 0:
            lines.extend(
                [
                    "",
                    f"    def with_base_path(self, base_path: str) -> {root_name}:",
                    '        """Return this surface bound to a decoded path prefix."""',
                    f'        return {root_name}(_normalize_base_path(base_path), "", '
                    "self._owner_key)",
                ]
            )
        if node_index == 0 and node.has_endpoint:
            lines.extend(
                [
                    "",
                    "    @property",
                    "    def root(self) -> _URLRootPath:",
                    "        return _URLRootPath(self._base_path, self._owner_key)",
                ]
            )
        if node_index != 0 and node.has_endpoint:
            lines.extend(
                [
                    "",
                    "    @property",
                    "    def path(self) -> str:",
                    "        return self._base_path + self._local_path",
                ]
            )
        for child in node.static:
            lines.extend(
                [
                    "",
                    "    @property",
                    f"    def {child.member}(self) -> {names[id(child.node)]}:",
                    f"        return {names[id(child.node)]}(",
                    "            self._base_path,",
                    f"            self._local_path + {('/' + child.segment)!a},",
                    f"            {child.node.owner_key!a},",
                    "        )",
                ]
            )
        if node.dynamic is not None:
            child = node.dynamic
            parameter = child.parameter
            assert parameter is not None
            receiver = "instance" if parameter == "self" else "self"
            lines.extend(
                [
                    "",
                    f"    def {child.member}({receiver}, {parameter}: str) -> "
                    f"{names[id(child.node)]}:",
                    f'        encoded = _quote_segment("parameter {parameter!r}", '
                    f"{parameter})",
                    f"        return {names[id(child.node)]}(",
                    f"            {receiver}._base_path,",
                    f'            {receiver}._local_path + "/" + encoded,',
                    f"            {child.node.owner_key!a},",
                    "        )",
                ]
            )

    lines.extend(
        [
            "",
            "",
            f'urls: {root_name} = {root_name}("", "", {root.owner_key!a})',
        ]
    )
    lines.extend(bound_lines)
    catalog_name = _render_catalog(
        catalog,
        names,
        bound_names,
        prefix="Root",
        lines=lines,
    )
    lines.extend(
        [
            "",
            "",
            f"mount_urls: {catalog_name} = {catalog_name}()",
        ]
    )
    return ("\n".join(lines) + "\n").encode("ascii")


def url_plan(graph: RouteGraph) -> tuple[GeneratedArtifact, ...]:
    """Return the generated typed URL-interface artifact for one route graph."""
    plan = _url_helper_projection(graph)
    return (
        GeneratedArtifact(
            PurePosixPath("app/_pyganini/urls.py"),
            _render(plan),
        ),
    )
