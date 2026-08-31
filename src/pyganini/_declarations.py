"""Typed declaration values used by application route source."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, cast, overload

from starlette.requests import Request

from pyganini._navigation import Destination, RouteNav
from pyganini._render import (
    FragmentRouteResponse,
    PageRouteResponse,
    RouteResponse,
)
from pyganini.request_data import Body, BodyCapture, Form, FormCapture

_TEMPLATE_NAME = re.compile(r"^[a-z][a-z0-9_]*\.jinja$")
_TEMPLATE_ROOT_COMPONENT = re.compile(r"^[a-z][a-z0-9_]*$")
_MOUNT_COMPONENT = re.compile(r"^[a-z][a-z0-9_]*$")
_MOUNT_STATIC_SEGMENT = re.compile(r"^[a-z][a-z0-9-]*$")
_MOUNT_PARAMETER_SEGMENT = re.compile(r"^\{[a-z][a-z0-9_]*\}$")

type _KitCreator[K] = Callable[[Request], K | Awaitable[K]]
type _KitPageHandler[K] = Callable[
    [K, Request], PageRouteResponse | Awaitable[PageRouteResponse]
]
type _KitFragmentHandler[K] = Callable[
    [K, Request], FragmentRouteResponse | Awaitable[FragmentRouteResponse]
]
type _KitActionHandler[K] = Callable[
    [K, Request], RouteResponse | Awaitable[RouteResponse]
]
type _ActionHandler = Callable[[Request], RouteResponse | Awaitable[RouteResponse]]
type _BodyActionHandler = Callable[
    [Request, Body], RouteResponse | Awaitable[RouteResponse]
]
type _FormActionHandler = Callable[
    [Request, Form], RouteResponse | Awaitable[RouteResponse]
]
type _KitBodyActionHandler[K] = Callable[
    [K, Request, Body], RouteResponse | Awaitable[RouteResponse]
]
type _KitFormActionHandler[K] = Callable[
    [K, Request, Form], RouteResponse | Awaitable[RouteResponse]
]


def _empty_route_labels() -> Mapping[str, str]:
    return MappingProxyType({})


def _copy_route_labels(value: object) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise TypeError("labels must be a mapping")
    copied: dict[str, str] = {}
    for key, item in cast(Mapping[object, object], value).items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise TypeError("label keys and values must be strings")
        if not key:
            raise ValueError("label keys must not be empty")
        copied[key] = item
    return MappingProxyType(dict(sorted(copied.items())))


@dataclass(frozen=True, slots=True)
class RouteMeta:
    """Opaque display labels attached to one route declaration."""

    labels: Mapping[str, str] = field(default_factory=_empty_route_labels)

    def __post_init__(self) -> None:
        object.__setattr__(self, "labels", _copy_route_labels(self.labels))


@dataclass(frozen=True, slots=True)
class FragmentRouteDef:
    """A route-local fragment declaration."""

    path: str
    handler: Callable[..., object]
    template: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _normalize_local_path(self.path))
        object.__setattr__(self, "template", _normalize_template(self.template))


@dataclass(frozen=True, slots=True, init=False)
class ActionDef:
    """A route-local action declaration."""

    method: Literal["POST", "PUT", "PATCH", "DELETE"]
    path: str
    handler: _ActionHandler | _BodyActionHandler | _FormActionHandler
    template: str | None = None
    request_data: BodyCapture | FormCapture | None = None

    @overload
    def __init__(
        self,
        method: Literal["POST", "PUT", "PATCH", "DELETE"],
        path: str,
        handler: _ActionHandler,
        template: str | None = None,
        request_data: None = None,
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["POST", "PUT", "PATCH", "DELETE"],
        path: str,
        handler: _BodyActionHandler,
        *,
        template: str | None = None,
        request_data: BodyCapture,
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["POST", "PUT", "PATCH", "DELETE"],
        path: str,
        handler: _BodyActionHandler,
        template: str | None,
        request_data: BodyCapture,
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["POST", "PUT", "PATCH", "DELETE"],
        path: str,
        handler: _FormActionHandler,
        *,
        template: str | None = None,
        request_data: FormCapture,
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["POST", "PUT", "PATCH", "DELETE"],
        path: str,
        handler: _FormActionHandler,
        template: str | None,
        request_data: FormCapture,
    ) -> None: ...

    def __init__(
        self,
        method: Literal["POST", "PUT", "PATCH", "DELETE"],
        path: str,
        handler: _ActionHandler | _BodyActionHandler | _FormActionHandler,
        template: str | None = None,
        request_data: BodyCapture | FormCapture | None = None,
    ) -> None:
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "handler", handler)
        object.__setattr__(self, "template", template)
        object.__setattr__(self, "request_data", request_data)
        self.__post_init__()

    def __post_init__(self) -> None:
        object.__setattr__(self, "method", _normalize_action_method(self.method))
        object.__setattr__(self, "path", _normalize_local_path(self.path))
        object.__setattr__(self, "template", _normalize_template(self.template))
        object.__setattr__(
            self, "request_data", _normalize_request_data(self.request_data)
        )


@dataclass(frozen=True, slots=True)
class KitFragmentRouteDef[K]:
    """A shared-kit fragment declaration owned by one live route."""

    path: str
    handler: _KitFragmentHandler[K]
    template: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _normalize_local_path(self.path))
        object.__setattr__(self, "template", _normalize_template(self.template))


@dataclass(frozen=True, slots=True, init=False)
class KitActionDef[K]:
    """A shared-kit action declaration owned by one live route."""

    method: Literal["POST", "PUT", "PATCH", "DELETE"]
    path: str
    handler: _KitActionHandler[K] | _KitBodyActionHandler[K] | _KitFormActionHandler[K]
    template: str | None = None
    request_data: BodyCapture | FormCapture | None = None

    @overload
    def __init__(
        self,
        method: Literal["POST", "PUT", "PATCH", "DELETE"],
        path: str,
        handler: _KitActionHandler[K],
        template: str | None = None,
        request_data: None = None,
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["POST", "PUT", "PATCH", "DELETE"],
        path: str,
        handler: _KitBodyActionHandler[K],
        *,
        template: str | None = None,
        request_data: BodyCapture,
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["POST", "PUT", "PATCH", "DELETE"],
        path: str,
        handler: _KitBodyActionHandler[K],
        template: str | None,
        request_data: BodyCapture,
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["POST", "PUT", "PATCH", "DELETE"],
        path: str,
        handler: _KitFormActionHandler[K],
        *,
        template: str | None = None,
        request_data: FormCapture,
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["POST", "PUT", "PATCH", "DELETE"],
        path: str,
        handler: _KitFormActionHandler[K],
        template: str | None,
        request_data: FormCapture,
    ) -> None: ...

    def __init__(
        self,
        method: Literal["POST", "PUT", "PATCH", "DELETE"],
        path: str,
        handler: (
            _KitActionHandler[K] | _KitBodyActionHandler[K] | _KitFormActionHandler[K]
        ),
        template: str | None = None,
        request_data: BodyCapture | FormCapture | None = None,
    ) -> None:
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "handler", handler)
        object.__setattr__(self, "template", template)
        object.__setattr__(self, "request_data", request_data)
        self.__post_init__()

    def __post_init__(self) -> None:
        object.__setattr__(self, "method", _normalize_action_method(self.method))
        object.__setattr__(self, "path", _normalize_local_path(self.path))
        object.__setattr__(self, "template", _normalize_template(self.template))
        object.__setattr__(
            self, "request_data", _normalize_request_data(self.request_data)
        )


@dataclass(frozen=True, slots=True)
class RouteDef:
    """The endpoint declarations owned by one route package."""

    page: Callable[..., object] | None
    page_template: str | None
    fragments: tuple[FragmentRouteDef, ...]
    actions: tuple[ActionDef, ...]
    nav: RouteNav | None = None
    destinations: tuple[Destination, ...] = ()
    error_page_template: str | None = None
    error_fragment_template: str | None = None
    name: str | None = None
    title: str | None = None
    meta: RouteMeta | None = None

    def __post_init__(self) -> None:
        fragments = _validate_fragments(self.fragments)
        actions = _validate_actions(self.actions)
        nav = _validate_nav(self.nav)
        destinations = _validate_destinations(self.destinations)
        page_template = _normalize_template(self.page_template)
        error_page_template = _normalize_template(self.error_page_template)
        error_fragment_template = _normalize_template(self.error_fragment_template)
        name = _normalize_display_string(self.name, "name")
        title = _normalize_display_string(self.title, "title")
        meta = _validate_route_meta(self.meta)
        object.__setattr__(self, "page_template", page_template)
        object.__setattr__(self, "error_page_template", error_page_template)
        object.__setattr__(self, "error_fragment_template", error_fragment_template)
        object.__setattr__(self, "nav", nav)
        object.__setattr__(self, "destinations", destinations)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "meta", meta)
        _validate_route(
            self.page,
            page_template,
            fragments,
            actions,
            error_page_template,
            error_fragment_template,
            has_metadata=name is not None or title is not None or meta is not None,
        )


@dataclass(frozen=True, slots=True)
class KitRouteDef[K]:
    """The shared-kit endpoint declarations owned by one live route."""

    create: _KitCreator[K] | None
    template_root: str | None
    page: _KitPageHandler[K] | None
    page_template: str | None
    fragments: tuple[KitFragmentRouteDef[K], ...]
    actions: tuple[KitActionDef[K], ...]
    nav: RouteNav | None = None
    destinations: tuple[Destination, ...] = ()
    error_page_template: str | None = None
    error_fragment_template: str | None = None
    name: str | None = None
    title: str | None = None
    meta: RouteMeta | None = None

    def __post_init__(self) -> None:
        fragments = cast(
            tuple[KitFragmentRouteDef[K], ...], _validate_kit_fragments(self.fragments)
        )
        actions = cast(tuple[KitActionDef[K], ...], _validate_kit_actions(self.actions))
        nav = _validate_nav(self.nav)
        destinations = _validate_destinations(self.destinations)
        template_root = _normalize_template_root(self.template_root)
        page_template = _normalize_template(self.page_template)
        error_page_template = _normalize_template(self.error_page_template)
        error_fragment_template = _normalize_template(self.error_fragment_template)
        name = _normalize_display_string(self.name, "name")
        title = _normalize_display_string(self.title, "title")
        meta = _validate_route_meta(self.meta)
        object.__setattr__(self, "template_root", template_root)
        object.__setattr__(self, "page_template", page_template)
        object.__setattr__(self, "error_page_template", error_page_template)
        object.__setattr__(self, "error_fragment_template", error_fragment_template)
        object.__setattr__(self, "nav", nav)
        object.__setattr__(self, "destinations", destinations)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "meta", meta)
        _validate_kit_route(
            self.page,
            page_template,
            fragments,
            actions,
            template_root,
        )


@dataclass(frozen=True, slots=True)
class MountRoute:
    """One source-relative declaration selected by a mounted route owner."""

    path: str
    nav: RouteNav | None = None
    destinations: tuple[Destination, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _normalize_mount_route_path(self.path))
        object.__setattr__(self, "nav", _validate_nav(self.nav))
        object.__setattr__(
            self, "destinations", _validate_destinations(self.destinations)
        )


@dataclass(frozen=True, slots=True)
class KitRouteMount[K]:
    """A live owner that expands one reusable mounted route subtree."""

    create: _KitCreator[K]
    mount: str
    routes: tuple[MountRoute, ...] | None = None
    error_page_template: str | None = None
    error_fragment_template: str | None = None

    def __post_init__(self) -> None:
        mount = _normalize_mount_identity(self.mount)
        routes = _validate_mount_routes(self.routes)
        error_page_template = _normalize_template(self.error_page_template)
        error_fragment_template = _normalize_template(self.error_fragment_template)
        object.__setattr__(self, "mount", mount)
        object.__setattr__(self, "routes", routes)
        object.__setattr__(self, "error_page_template", error_page_template)
        object.__setattr__(self, "error_fragment_template", error_fragment_template)


def _normalize_template(template: object) -> str | None:
    if template is None:
        return None
    if not isinstance(template, str):
        raise TypeError("template must be a string or None")
    if not template.isascii() or _TEMPLATE_NAME.fullmatch(template) is None:
        raise ValueError("template must match ^[a-z][a-z0-9_]*\\.jinja$ using ASCII")
    return template


def _normalize_display_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string or None")
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    return value


def _validate_route_meta(value: object) -> RouteMeta | None:
    if value is None:
        return None
    if not isinstance(value, RouteMeta):
        raise TypeError("meta must be a RouteMeta value or None")
    return value


def _normalize_request_data(
    value: object,
) -> BodyCapture | FormCapture | None:
    if value is None:
        return None
    if not isinstance(value, (BodyCapture, FormCapture)):
        raise TypeError("request_data must be a BodyCapture, FormCapture, or None")
    return value


def _normalize_template_root(template_root: object) -> str | None:
    if template_root is None:
        return None
    if not isinstance(template_root, str):
        raise TypeError("template_root must be a string or None")
    if not template_root.isascii():
        raise ValueError("template_root must use ASCII")
    components = template_root.split("/")
    if not components or any(
        _TEMPLATE_ROOT_COMPONENT.fullmatch(component) is None
        for component in components
    ):
        raise ValueError(
            "template_root must use lowercase ASCII package components separated by '/'"
        )
    if components[0] in {"routes", "_pyganini"}:
        raise ValueError("template_root must not start with routes or _pyganini")
    if any(component.startswith("_") for component in components):
        raise ValueError("template_root components must not be private")
    return template_root


def _normalize_mount_identity(mount: object) -> str:
    if not isinstance(mount, str):
        raise TypeError("mount must be a string")
    if not mount or not mount.isascii():
        raise ValueError("mount must use non-empty ASCII package components")
    components = mount.split("/")
    if any(
        component in {"", ".", ".."}
        or component.startswith("_")
        or _MOUNT_COMPONENT.fullmatch(component) is None
        for component in components
    ):
        raise ValueError(
            "mount must use lowercase ASCII identifier components separated by '/'"
        )
    return mount


def _normalize_mount_route_path(path: object) -> str:
    if not isinstance(path, str):
        raise TypeError("mount route path must be a string")
    if path == "/":
        return path
    if (
        not path
        or not path.isascii()
        or not path.startswith("/")
        or path.endswith("/")
        or "//" in path
        or "\\" in path
        or "%" in path
        or "?" in path
        or "#" in path
    ):
        raise ValueError("mount route path must be a canonical ASCII route pattern")
    segments = path[1:].split("/")
    if any(
        _MOUNT_PARAMETER_SEGMENT.fullmatch(segment) is None
        and _MOUNT_STATIC_SEGMENT.fullmatch(segment) is None
        for segment in segments
    ):
        raise ValueError(
            "mount route path segments must use lowercase static names or {parameter}"
        )
    return path


def _validate_mount_routes(value: object) -> tuple[MountRoute, ...] | None:
    if value is None:
        return None
    if not isinstance(value, tuple):
        raise TypeError("routes must be a tuple of MountRoute values or None")
    items = cast(tuple[object, ...], value)
    if not items:
        raise ValueError("routes must not be empty")
    if not all(isinstance(item, MountRoute) for item in items):
        raise TypeError("routes must contain only MountRoute values")
    routes = cast(tuple[MountRoute, ...], items)
    paths = [route.path for route in routes]
    if len(paths) != len(set(paths)):
        raise ValueError("routes must not contain duplicate mount route paths")
    return routes


def _normalize_local_path(path: object) -> str:
    if not isinstance(path, str):
        raise TypeError("route-local path must be a string")
    if path == "/":
        return path
    if not path:
        raise ValueError("route-local path must not be empty")
    if not path.isascii():
        raise ValueError("route-local path must use ASCII")
    if not path.startswith("/"):
        raise ValueError("route-local path must start with '/'")
    if path.endswith("/"):
        raise ValueError("route-local path must not have a trailing slash")
    segment = path[1:]
    if "/" in segment:
        raise ValueError("route-local path must contain one segment")
    if not segment[0].islower() or not segment[0].isascii():
        raise ValueError("route-local segment must start with a lowercase ASCII letter")
    if any(
        not (
            character.isascii()
            and (character.islower() or character.isdigit() or character in "_-")
        )
        for character in segment
    ):
        raise ValueError(
            "route-local segment must use lowercase ASCII letters, digits, "
            "underscores, or hyphens"
        )
    return "/" + segment.replace("_", "-")


def _normalize_action_method(
    method: object,
) -> Literal["POST", "PUT", "PATCH", "DELETE"]:
    if not isinstance(method, str):
        raise TypeError("action method must be a string")
    if method == "POST":
        return "POST"
    if method == "PUT":
        return "PUT"
    if method == "PATCH":
        return "PATCH"
    if method == "DELETE":
        return "DELETE"
    raise ValueError("action method must be POST, PUT, PATCH, or DELETE")


def _validate_fragments(value: object) -> tuple[FragmentRouteDef, ...]:
    if not isinstance(value, tuple):
        raise TypeError("fragments must be a tuple of FragmentRouteDef values")
    items = cast(tuple[object, ...], value)
    if not all(isinstance(item, FragmentRouteDef) for item in items):
        raise TypeError("fragments must contain only FragmentRouteDef values")
    return cast(tuple[FragmentRouteDef, ...], items)


def _validate_nav(value: object) -> RouteNav | None:
    if value is None:
        return None
    if not isinstance(value, RouteNav):
        raise TypeError("nav must be a RouteNav value or None")
    return value


def _validate_destinations(value: object) -> tuple[Destination, ...]:
    if not isinstance(value, tuple):
        raise TypeError("destinations must be a tuple of Destination values")
    items = cast(tuple[object, ...], value)
    if not all(isinstance(item, Destination) for item in items):
        raise TypeError("destinations must contain only Destination values")
    destinations = cast(tuple[Destination, ...], items)
    names = [item.name.replace("-", "_") for item in destinations]
    if len(names) != len(set(names)):
        raise ValueError("destinations must not contain duplicate names")
    return destinations


def _validate_actions(value: object) -> tuple[ActionDef, ...]:
    if not isinstance(value, tuple):
        raise TypeError("actions must be a tuple of ActionDef values")
    items = cast(tuple[object, ...], value)
    if not all(isinstance(item, ActionDef) for item in items):
        raise TypeError("actions must contain only ActionDef values")
    return cast(tuple[ActionDef, ...], items)


def _validate_kit_fragments(
    value: object,
) -> tuple[KitFragmentRouteDef[object], ...]:
    if not isinstance(value, tuple):
        raise TypeError("fragments must be a tuple of KitFragmentRouteDef values")
    items = cast(tuple[object, ...], value)
    if not all(isinstance(item, KitFragmentRouteDef) for item in items):
        raise TypeError("fragments must contain only KitFragmentRouteDef values")
    return cast(tuple[KitFragmentRouteDef[object], ...], items)


def _validate_kit_actions(value: object) -> tuple[KitActionDef[object], ...]:
    if not isinstance(value, tuple):
        raise TypeError("actions must be a tuple of KitActionDef values")
    items = cast(tuple[object, ...], value)
    if not all(isinstance(item, KitActionDef) for item in items):
        raise TypeError("actions must contain only KitActionDef values")
    return cast(tuple[KitActionDef[object], ...], items)


def _validate_route(
    page: Callable[..., object] | None,
    page_template: str | None,
    fragments: tuple[FragmentRouteDef, ...],
    actions: tuple[ActionDef, ...],
    error_page_template: str | None,
    error_fragment_template: str | None,
    *,
    has_metadata: bool = False,
) -> None:
    if page is None and page_template is not None:
        raise ValueError("page template requires a page handler")
    if page is None and not fragments and not actions and has_metadata:
        raise ValueError("route metadata requires a page, fragment, or action")
    if (
        page is None
        and not fragments
        and not actions
        and error_page_template is None
        and error_fragment_template is None
    ):
        raise ValueError("route must declare a page, fragment, or action")
    if page is not None and any(value.path == "/" for value in fragments):
        raise ValueError("route cannot declare both a page and an index fragment")

    fragment_paths = [value.path for value in fragments]
    if len(fragment_paths) != len(set(fragment_paths)):
        raise ValueError("route has duplicate normalized fragment paths")
    action_keys = [(value.method, value.path) for value in actions]
    if len(action_keys) != len(set(action_keys)):
        raise ValueError("route has duplicate action method and path pairs")


def _validate_kit_route[K](
    page: _KitPageHandler[K] | None,
    page_template: str | None,
    fragments: tuple[KitFragmentRouteDef[K], ...],
    actions: tuple[KitActionDef[K], ...],
    template_root: str | None,
) -> None:
    if page is None and page_template is not None:
        raise ValueError("page template requires a page handler")
    if page is None and not fragments and not actions:
        raise ValueError("route must declare a page, fragment, or action")
    if page is not None and any(value.path == "/" for value in fragments):
        raise ValueError("route cannot declare both a page and an index fragment")

    fragment_paths = [value.path for value in fragments]
    if len(fragment_paths) != len(set(fragment_paths)):
        raise ValueError("route has duplicate normalized fragment paths")
    action_keys = [(value.method, value.path) for value in actions]
    if len(action_keys) != len(set(action_keys)):
        raise ValueError("route has duplicate action method and path pairs")

    has_template = (
        page_template is not None
        or any(value.template is not None for value in fragments)
        or any(value.template is not None for value in actions)
    )
    if not has_template and template_root is not None:
        raise ValueError("template_root requires a declared kit template")


def fragment_route(
    path: str,
    handler: Callable[..., object],
    *,
    template: str | None = None,
) -> FragmentRouteDef:
    """Declare a fragment at one normalized route-local path."""
    return FragmentRouteDef(
        path=_normalize_local_path(path),
        handler=handler,
        template=_normalize_template(template),
    )


@overload
def action(
    method: Literal["POST", "PUT", "PATCH", "DELETE"],
    path: str,
    handler: _ActionHandler,
    *,
    template: str | None = None,
    request_data: None = None,
) -> ActionDef: ...


@overload
def action(
    method: Literal["POST", "PUT", "PATCH", "DELETE"],
    path: str,
    handler: _BodyActionHandler,
    *,
    template: str | None = None,
    request_data: BodyCapture,
) -> ActionDef: ...


@overload
def action(
    method: Literal["POST", "PUT", "PATCH", "DELETE"],
    path: str,
    handler: _FormActionHandler,
    *,
    template: str | None = None,
    request_data: FormCapture,
) -> ActionDef: ...


def action(
    method: Literal["POST", "PUT", "PATCH", "DELETE"],
    path: str,
    handler: _ActionHandler | _BodyActionHandler | _FormActionHandler,
    *,
    template: str | None = None,
    request_data: BodyCapture | FormCapture | None = None,
) -> ActionDef:
    """Declare an action at one normalized route-local path."""
    normalized_method = _normalize_action_method(method)
    normalized_path = _normalize_local_path(path)
    normalized_template = _normalize_template(template)
    normalized_request_data = _normalize_request_data(request_data)
    if normalized_request_data is None:
        return ActionDef(
            method=normalized_method,
            path=normalized_path,
            handler=cast(_ActionHandler, handler),
            template=normalized_template,
            request_data=None,
        )
    if isinstance(normalized_request_data, BodyCapture):
        return ActionDef(
            method=normalized_method,
            path=normalized_path,
            handler=cast(_BodyActionHandler, handler),
            template=normalized_template,
            request_data=normalized_request_data,
        )
    return ActionDef(
        method=normalized_method,
        path=normalized_path,
        handler=cast(_FormActionHandler, handler),
        template=normalized_template,
        request_data=normalized_request_data,
    )


def kit_fragment_route[K](
    path: str,
    handler: _KitFragmentHandler[K],
    *,
    template: str | None = None,
) -> KitFragmentRouteDef[K]:
    """Declare one shared-kit fragment at one normalized route-local path."""
    return KitFragmentRouteDef(
        path=_normalize_local_path(path),
        handler=handler,
        template=_normalize_template(template),
    )


@overload
def kit_action[K](
    method: Literal["POST", "PUT", "PATCH", "DELETE"],
    path: str,
    handler: _KitActionHandler[K],
    *,
    template: str | None = None,
    request_data: None = None,
) -> KitActionDef[K]: ...


@overload
def kit_action[K](
    method: Literal["POST", "PUT", "PATCH", "DELETE"],
    path: str,
    handler: _KitBodyActionHandler[K],
    *,
    template: str | None = None,
    request_data: BodyCapture,
) -> KitActionDef[K]: ...


@overload
def kit_action[K](
    method: Literal["POST", "PUT", "PATCH", "DELETE"],
    path: str,
    handler: _KitFormActionHandler[K],
    *,
    template: str | None = None,
    request_data: FormCapture,
) -> KitActionDef[K]: ...


def kit_action[K](
    method: Literal["POST", "PUT", "PATCH", "DELETE"],
    path: str,
    handler: (
        _KitActionHandler[K] | _KitBodyActionHandler[K] | _KitFormActionHandler[K]
    ),
    *,
    template: str | None = None,
    request_data: BodyCapture | FormCapture | None = None,
) -> KitActionDef[K]:
    """Declare one shared-kit action at one normalized route-local path."""
    normalized_method = _normalize_action_method(method)
    normalized_path = _normalize_local_path(path)
    normalized_template = _normalize_template(template)
    normalized_request_data = _normalize_request_data(request_data)
    if normalized_request_data is None:
        return KitActionDef(
            method=normalized_method,
            path=normalized_path,
            handler=cast(_KitActionHandler[K], handler),
            template=normalized_template,
            request_data=None,
        )
    if isinstance(normalized_request_data, BodyCapture):
        return KitActionDef(
            method=normalized_method,
            path=normalized_path,
            handler=cast(_KitBodyActionHandler[K], handler),
            template=normalized_template,
            request_data=normalized_request_data,
        )
    return KitActionDef(
        method=normalized_method,
        path=normalized_path,
        handler=cast(_KitFormActionHandler[K], handler),
        template=normalized_template,
        request_data=normalized_request_data,
    )


def route(
    *,
    page: Callable[..., object] | None = None,
    template: str | None = None,
    fragments: tuple[FragmentRouteDef, ...] = (),
    actions: tuple[ActionDef, ...] = (),
    nav: RouteNav | None = None,
    destinations: tuple[Destination, ...] = (),
    error_page_template: str | None = None,
    error_fragment_template: str | None = None,
    name: str | None = None,
    title: str | None = None,
    meta: RouteMeta | None = None,
) -> RouteDef:
    """Declare the endpoint surface owned by one route package."""
    fragments = _validate_fragments(fragments)
    actions = _validate_actions(actions)
    return RouteDef(
        page=page,
        page_template=_normalize_template(template),
        fragments=fragments,
        actions=actions,
        nav=_validate_nav(nav),
        destinations=_validate_destinations(destinations),
        error_page_template=_normalize_template(error_page_template),
        error_fragment_template=_normalize_template(error_fragment_template),
        name=_normalize_display_string(name, "name"),
        title=_normalize_display_string(title, "title"),
        meta=_validate_route_meta(meta),
    )


def route_kit[K](
    *,
    create: _KitCreator[K] | None = None,
    template_root: str | None = None,
    page: _KitPageHandler[K] | None = None,
    template: str | None = None,
    fragments: tuple[KitFragmentRouteDef[K], ...] = (),
    actions: tuple[KitActionDef[K], ...] = (),
    nav: RouteNav | None = None,
    destinations: tuple[Destination, ...] = (),
    error_page_template: str | None = None,
    error_fragment_template: str | None = None,
    name: str | None = None,
    title: str | None = None,
    meta: RouteMeta | None = None,
) -> KitRouteDef[K]:
    """Declare a shared-kit endpoint surface owned by one live route."""
    validated_fragments = cast(
        tuple[KitFragmentRouteDef[K], ...], _validate_kit_fragments(fragments)
    )
    validated_actions = cast(
        tuple[KitActionDef[K], ...], _validate_kit_actions(actions)
    )
    return KitRouteDef(
        create=create,
        template_root=_normalize_template_root(template_root),
        page=page,
        page_template=_normalize_template(template),
        fragments=validated_fragments,
        actions=validated_actions,
        nav=_validate_nav(nav),
        destinations=_validate_destinations(destinations),
        error_page_template=_normalize_template(error_page_template),
        error_fragment_template=_normalize_template(error_fragment_template),
        name=_normalize_display_string(name, "name"),
        title=_normalize_display_string(title, "title"),
        meta=_validate_route_meta(meta),
    )


def mount_route(
    path: str,
    *,
    nav: RouteNav | None = None,
    destinations: tuple[Destination, ...] = (),
) -> MountRoute:
    """Select one canonical source-relative route declaration."""
    return MountRoute(
        _normalize_mount_route_path(path),
        _validate_nav(nav),
        _validate_destinations(destinations),
    )


def route_mount[K](
    *,
    create: _KitCreator[K],
    mount: str,
    routes: tuple[MountRoute, ...] | None = None,
    error_page_template: str | None = None,
    error_fragment_template: str | None = None,
) -> KitRouteMount[K]:
    """Declare a live owner for one reusable mounted route subtree."""
    return KitRouteMount(
        create=create,
        mount=mount,
        routes=routes,
        error_page_template=error_page_template,
        error_fragment_template=error_fragment_template,
    )
