# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnnecessaryIsInstance=false

"""Request-scoped, application-rendered navigation values."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from starlette.requests import Request

from pyganini._url_binding import bind_external_pattern, normalize_base_path

_KEY = re.compile(r"^[a-z][a-z0-9_]*$", re.ASCII)
_DESTINATION_NAME = re.compile(r"^[a-z][a-z0-9_-]*$", re.ASCII)
_TRAIL_KEY = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$", re.ASCII)
_NAV_SCOPE_KEY = "_pyganini_navigation"
_MAX_RETURN_LENGTH = 2048
type NavigationFact = tuple[str | None, str | None, str, bool]


@dataclass(frozen=True, slots=True)
class RouteNav:
    """Declare one static label or one application-data label key."""

    label: str | None = None
    key: str | None = None

    def __post_init__(self) -> None:
        if (self.label is None) == (self.key is None):
            raise ValueError("RouteNav requires exactly one of label or key")
        if self.label is not None:
            if not isinstance(self.label, str):
                raise TypeError("RouteNav label must be a string or None")
            label = self.label.strip()
            if not label:
                raise ValueError("RouteNav label must not be empty")
            object.__setattr__(self, "label", label)
        if self.key is not None:
            if not isinstance(self.key, str):
                raise TypeError("RouteNav key must be a string or None")
            if not self.key.isascii() or _KEY.fullmatch(self.key) is None:
                raise ValueError(
                    "RouteNav key must match ^[a-z][a-z0-9_]*$ using ASCII"
                )


@runtime_checkable
class RouteTarget(Protocol):
    """A generated target identifying one canonical route pattern."""

    @property
    def route_pattern(self) -> str:
        """Return the target's canonical route pattern."""
        ...


@dataclass(frozen=True, slots=True)
class Destination:
    """Declare a typed source-to-target navigation edge."""

    name: str
    target: RouteTarget
    trail_key: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise TypeError("destination name must be a string")
        if not self.name.isascii() or _DESTINATION_NAME.fullmatch(self.name) is None:
            raise ValueError(
                "destination name must match ^[a-z][a-z0-9_-]*$ using ASCII"
            )
        if not isinstance(self.target, RouteTarget):
            raise TypeError("destination target must be a generated RouteTarget")
        if not isinstance(self.target.route_pattern, str):
            raise TypeError("destination target route_pattern must be a string")
        if self.trail_key is not None:
            if not isinstance(self.trail_key, str):
                raise TypeError("destination trail_key must be a string or None")
            if (
                not self.trail_key.isascii()
                or _TRAIL_KEY.fullmatch(self.trail_key) is None
            ):
                raise ValueError(
                    "destination trail_key must match the lowercase ASCII "
                    "trail-key grammar"
                )


def to(
    name: str,
    target: RouteTarget,
    *,
    trail_key: str | None = None,
) -> Destination:
    """Declare one destination from the owning route."""
    return Destination(name, target, trail_key)


@dataclass(frozen=True, slots=True)
class NavTrailStep:
    """One application-rendered navigation trail step."""

    label: str
    href: str = ""
    current: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.label, str):
            raise TypeError("navigation label must be a string")
        if not self.label.strip():
            raise ValueError("navigation label must not be empty")
        if not isinstance(self.href, str):
            raise TypeError("navigation href must be a string")
        if not isinstance(self.current, bool):
            raise TypeError("navigation current must be bool")
        if self.current and self.href:
            raise ValueError("current navigation steps must not have an href")
        if not self.current and not self.href.strip():
            raise ValueError("linked navigation steps require an href")


type NavTrail = tuple[NavTrailStep, ...]


@dataclass(frozen=True, slots=True)
class NavigationBack:
    """The nearest preceding linked navigation step."""

    href: str = ""
    label: str = ""
    ok: bool = False


@dataclass(frozen=True, slots=True)
class NavigationCurrent:
    """The current navigation step and its canonical href."""

    href: str = ""
    label: str = ""
    ok: bool = False


@dataclass(frozen=True, slots=True)
class Navigation:
    """Immutable navigation data explicitly passed to application templates."""

    trail: NavTrail = ()
    back: NavigationBack = NavigationBack()
    current: NavigationCurrent = NavigationCurrent()
    _return_to: str | None = field(default=None, repr=False, compare=False, init=False)


def _label_value(label: object) -> str | None:
    if not isinstance(label, str) or not label.strip():
        return None
    return label


def nav_step(label: str, href: str) -> NavTrailStep:
    """Create a linked navigation trail step."""
    if not isinstance(href, str):
        raise TypeError("navigation href must be a string")
    if not href.strip():
        raise ValueError("navigation href must not be empty")
    return NavTrailStep(label, href, False)


def current_nav_step(label: str) -> NavTrailStep:
    """Create a current navigation trail step."""
    return NavTrailStep(label, "", True)


@dataclass(slots=True)
class _Resolution:
    label: str
    href: str


@dataclass(frozen=True, slots=True)
class _CanonicalStep:
    label: str | None
    key: str | None
    href: str
    current: bool


@dataclass(slots=True)
class _NavigationState:
    steps: tuple[_CanonicalStep, ...]
    accepted_key: str | None = None
    return_to: str | None = None
    back_override: str | None = None
    resolutions: dict[str, _Resolution] = field(
        default_factory=lambda: dict[str, _Resolution]()
    )


def _validate_trail(trail: NavTrail) -> NavTrail:
    if not isinstance(trail, tuple):
        raise TypeError("navigation trail must be a tuple")
    current_count = 0
    current_index = -1
    for index, item in enumerate(trail):
        if not isinstance(item, NavTrailStep):
            raise TypeError("navigation trail must contain NavTrailStep values")
        if item.current:
            current_count += 1
            current_index = index
    if current_count > 1:
        raise ValueError("navigation trail must contain at most one current step")
    if current_index >= 0 and current_index != len(trail) - 1:
        raise ValueError("current navigation step must be the final trail item")
    if current_index >= 0 and any(
        not item.current for item in trail[current_index + 1 :]
    ):
        raise ValueError("linked navigation step cannot follow the current step")
    return trail


def _navigation_for_trail(
    trail: NavTrail,
    *,
    current_href: str = "",
    back_override: str | None = None,
    return_to: str | None = None,
) -> Navigation:
    _validate_trail(trail)
    current_index = next(
        (index for index, item in enumerate(trail) if item.current),
        len(trail),
    )
    back = NavigationBack()
    for item in reversed(trail[:current_index]):
        if not item.current and item.href:
            back = NavigationBack(item.href, item.label, True)
            break
    if back_override is not None and back.ok:
        back = NavigationBack(back_override, back.label, True)
    current = NavigationCurrent()
    if current_index < len(trail):
        item = trail[current_index]
        current = NavigationCurrent(current_href or item.href, item.label, True)
    value = Navigation(trail, back, current)
    if return_to is not None:
        object.__setattr__(value, "_return_to", return_to)
    return value


class RequestNav:
    """Request-local navigation resolver shared by creators and handlers."""

    __slots__ = ("_state",)

    def __init__(self, state: _NavigationState | None = None) -> None:
        self._state = state

    def trail_key(self) -> str | None:
        """Return the accepted alternate trail key, if any."""
        return None if self._state is None else self._state.accepted_key

    def resolve(self, key: str, label: str) -> None:
        """Resolve a dynamic label and restore its canonical href."""
        self.resolve_href(key, label, "")

    def resolve_href(self, key: str, label: str, href: str) -> None:
        """Resolve a dynamic label with an optional app-owned href override."""
        state = self._state
        if state is None or not isinstance(key, str) or not key:
            return
        resolved_label = _label_value(label)
        if resolved_label is None or not isinstance(href, str):
            return
        for step in state.steps:
            if step.key == key:
                state.resolutions[key] = _Resolution(
                    resolved_label,
                    href if href else step.href,
                )
                return

    def trail(self) -> NavTrail:
        """Return the currently resolved canonical trail."""
        state = self._state
        if state is None:
            return ()
        values: list[NavTrailStep] = []
        for step in state.steps:
            resolution = None if step.key is None else state.resolutions.get(step.key)
            label = step.label if step.key is None else None
            href = step.href
            if resolution is not None:
                label = resolution.label
                href = resolution.href
            if label is None:
                continue
            if step.current:
                values.append(current_nav_step(label))
            elif href:
                values.append(nav_step(label, href))
        return tuple(values)

    def navigation(self) -> Navigation:
        """Return immutable navigation for the canonical resolved trail."""
        state = self._state
        if state is None:
            return Navigation()
        trail = self.trail()
        current_href = next(
            (
                step.href
                for step in state.steps
                if step.current
                and (
                    step.label is not None
                    or (step.key is not None and step.key in state.resolutions)
                )
            ),
            "",
        )
        return _navigation_for_trail(
            trail,
            current_href=current_href,
            back_override=state.back_override,
            return_to=state.return_to,
        )

    def navigation_with_trail(self, trail: NavTrail) -> Navigation:
        """Return immutable navigation for an explicit application trail."""
        state = self._state
        return _navigation_for_trail(
            _validate_trail(trail),
            back_override=None if state is None else state.back_override,
            return_to=None if state is None else state.return_to,
        )


def nav(request: Request | None) -> RequestNav:
    """Return the private request navigation facade, or an inert facade."""
    if request is None:
        return RequestNav()
    state = request.scope.get(_NAV_SCOPE_KEY)
    return RequestNav(state if isinstance(state, _NavigationState) else None)


def _navigation_href(navigation: Navigation, href: str) -> str:
    """Append the private bounded return value to one generated destination."""
    if not isinstance(navigation, Navigation) or not isinstance(href, str):
        return href
    if not navigation._return_to:
        return href
    separator = "&" if "?" in href else "?"
    return (
        href
        + separator
        + "_pyganini_return_to="
        + quote(navigation._return_to, safe="")
    )


def _canonical_query(items: Sequence[tuple[str, str]]) -> str:
    return urlencode(sorted(items, key=lambda item: item[0]))


def _strict_percent_decode(value: str) -> str | None:
    decoded = bytearray()
    index = 0
    while index < len(value):
        character = value[index]
        if character == "%":
            if index + 2 >= len(value):
                return None
            first = value[index + 1]
            second = value[index + 2]
            if first not in "0123456789abcdefABCDEF" or second not in (
                "0123456789abcdefABCDEF"
            ):
                return None
            decoded.append(int(first + second, 16))
            index += 3
            continue
        try:
            decoded.extend(character.encode("utf-8"))
        except UnicodeError:
            return None
        index += 1
    try:
        return decoded.decode("utf-8", "strict")
    except UnicodeError:
        return None


def _safe_return_to(value: str, *, base_path: str = "") -> str | None:
    if (
        not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        return None
    candidate = value
    external_base_path = ""
    if base_path:
        if not (value == base_path or value.startswith(base_path + "/")):
            return None
        external_base_path = normalize_base_path(base_path)
        candidate = external_base_path + value[len(base_path) :]
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return None
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.fragment
        or not parsed.path.startswith("/")
    ):
        return None
    decoded_query = _strict_percent_decode(parsed.query)
    if decoded_query is None:
        return None
    if any(
        ord(character) < 0x20 or ord(character) == 0x7F for character in decoded_query
    ):
        return None
    external_path = parsed.path
    if base_path:
        if not (
            parsed.path == external_base_path
            or parsed.path.startswith(external_base_path + "/")
        ):
            return None
        suffix = parsed.path[len(external_base_path) :]
        decoded_suffix = _strict_percent_decode(suffix)
        if decoded_suffix is None or "\\" in decoded_suffix:
            return None
        if any(
            ord(character) < 0x20 or ord(character) == 0x7F
            for character in decoded_suffix
        ):
            return None
        if any(
            segment in {".", ".."}
            for candidate in (suffix, decoded_suffix)
            for segment in candidate.split("/")
        ):
            return None
    else:
        decoded_path = _strict_percent_decode(parsed.path)
        if decoded_path is None:
            return None
        if (
            not decoded_path.startswith("/")
            or decoded_path.startswith("//")
            or "\\" in decoded_path
            or any(
                ord(character) < 0x20 or ord(character) == 0x7F
                for character in decoded_path
            )
        ):
            return None
    try:
        items = [
            (key, item)
            for key, item in parse_qsl(
                parsed.query,
                keep_blank_values=True,
                errors="strict",
            )
            if key != "_pyganini_return_to"
        ]
    except (UnicodeError, ValueError):
        return None
    query = _canonical_query(items)
    result = urlunsplit(("", "", external_path, query, ""))
    if len(result) > _MAX_RETURN_LENGTH:
        return None
    return result


def _request_query_items(request: Request) -> list[tuple[str, str]]:
    raw_query = request.scope.get("query_string", b"")
    if not isinstance(raw_query, bytes):
        return []
    try:
        query = raw_query.decode("ascii", "strict")
        return parse_qsl(query, keep_blank_values=True, errors="strict")
    except (UnicodeError, ValueError):
        return []


def _prepare_navigation(
    request: Request,
    *,
    facts: tuple[NavigationFact, ...],
    accepted_keys: tuple[str, ...] = (),
) -> None:
    """Install immutable generated navigation facts in the private ASGI scope."""
    if not facts and not accepted_keys:
        return
    root_path = request.scope.get("root_path", "")
    base_path = normalize_base_path(root_path)
    decoded_base_path = _strict_percent_decode(base_path)
    if decoded_base_path is None:
        raise ValueError("normalized base_path must contain valid Unicode text")
    items = _request_query_items(request)
    selected_values = [
        value for key, value in items if key == "_pyganini_nav_trail_key"
    ]
    selected = (
        selected_values[0]
        if len(selected_values) == 1
        and _TRAIL_KEY.fullmatch(selected_values[0]) is not None
        and selected_values[0] in accepted_keys
        else None
    )
    return_to: str | None = None
    if selected is not None:
        return_values = [value for key, value in items if key == "_pyganini_return_to"]
        if len(return_values) == 1:
            return_to = _safe_return_to(
                return_values[0],
                base_path=decoded_base_path,
            )
    captured_return_to: str | None = None
    if request.method in {"GET", "HEAD"}:
        capture_items = [item for item in items if item[0] != "_pyganini_return_to"]
        path = request.scope.get("path", "")
        if not isinstance(path, str) or not path.startswith("/"):
            path = "/"
        captured = path
        query = _canonical_query(capture_items)
        if query:
            captured += "?" + query
        if len(captured) <= _MAX_RETURN_LENGTH:
            captured_return_to = captured
    bound = tuple(
        _CanonicalStep(
            label,
            key,
            bind_external_pattern(
                pattern,
                request.path_params,
                base_path=root_path,
            ),
            current,
        )
        for label, key, pattern, current in facts
    )
    state = _NavigationState(
        bound,
        selected,
        captured_return_to,
        return_to,
    )
    request.scope[_NAV_SCOPE_KEY] = state


__all__ = (
    "Destination",
    "NavTrail",
    "NavTrailStep",
    "Navigation",
    "NavigationBack",
    "NavigationCurrent",
    "RequestNav",
    "RouteNav",
    "RouteTarget",
    "current_nav_step",
    "nav",
    "nav_step",
    "to",
)
