# Navigation

Pyganini supplies request-local navigation values for application-rendered
breadcrumbs and semantic Back links. Pyganini does not render navigation HTML,
manage browser history, read `Referer`, or install a Jinja global. Handlers
resolve application data and pass the resulting values explicitly to page or
fragment context.

## Route declarations

Declare one static label or one application-data key on a live route:

```python
from pyganini import RouteNav, route

Route = route(page=page, template="page.jinja", nav=RouteNav(label="Home"))
```

Dynamic labels use a lowercase key. A handler resolves that key after loading
application data:

```python
from pyganini import RouteNav, nav, route

Route = route(page=page, template="page.jinja", nav=RouteNav(key="contact"))


def page(request):
    contact = repository.contact_by_id(request.path_params["id"])
    request_navigation = nav(request)
    request_navigation.resolve("contact", contact.name)
    return Page(
        context={"navigation": request_navigation.navigation(), "contact": contact}
    )
```

`RouteNav(label=...)` strips surrounding whitespace and requires a non-empty
label. `RouteNav(key=...)` accepts only ASCII `^[a-z][a-z0-9_]*$`. A route's
page, fragment, and actions share its one canonical navigation contribution;
local fragment and action suffixes do not add trail levels.

## Resolved trails

Use `nav(request)` only with the current Starlette `Request`. It returns an
inert facade for `None` or a request not prepared by generated Pyganini dispatch.
The facade exposes `trail_key()`, `resolve()`, `resolve_href()`, `trail()`,
`navigation()`, and `navigation_with_trail()`.

Static route labels resolve immediately. Dynamic steps appear only after a
handler supplies a non-empty label. Pyganini binds framework-derived canonical
hrefs to the trusted decoded ASGI `request.scope["root_path"]`. The current
step is marked current and has no trail href; its browser-visible canonical
href remains available as `navigation.current.href`.

```jinja
<nav aria-label="Breadcrumb">
  <ol>
    {% for step in navigation.trail %}
    <li>
      {% if step.current %}
      <span aria-current="page">{{ step.label }}</span>
      {% else %}
      <a href="{{ step.href }}">{{ step.label }}</a>
      {% endif %}
    </li>
    {% endfor %}
  </ol>
</nav>
```

`resolve_href(key, label, href)` uses a non-empty application-owned href
exactly as supplied. `resolve(key, label)` restores the canonical href.
Unknown keys, inert facades, empty keys, and blank labels are ignored. Repeated
accepted calls use the last value.

`navigation_with_trail()` accepts an explicit tuple of `NavTrailStep` values.
It permits at most one current step, and a current step must be last. Use
`nav_step(label, href)` and `current_nav_step(label)` to create steps.
Pyganini does not prefix or normalize custom trail hrefs.

## Host prefixes

Canonical trail, current, and Back hrefs automatically use the effective ASGI
prefix. Starlette and FastAPI compose an application mount and a server-supplied
proxy prefix in the same scope value:

| Hosting case | Effective `root_path` | Canonical current example |
| --- | --- | --- |
| root | `""` | `/users/42` |
| `/directory` mount | `/directory` | `/directory/users/42` |
| `/proxy` server prefix | `/proxy` | `/proxy/users/42` |
| combined | `/proxy/directory` | `/proxy/directory/users/42` |

Applications bind generated URL and asset helpers from the same decoded scope
value. Pyganini does not read `Forwarded`, `X-Forwarded-Prefix`, or another proxy
header. Host or server configuration must supply `root_path`.

## Back

`navigation.back` is the nearest preceding linked step in the selected trail.
It is semantic application navigation, not browser history:

```jinja
{% if navigation.back.ok %}
<a href="{{ navigation.back.href }}">Back to {{ navigation.back.label }}</a>
{% endif %}
```

The application chooses any fallback when `ok` is false. `navigation.current`
describes the resolved current step and its canonical href.

## Destinations and alternate trails

Destinations are declared on the live source route and target the generated URL
surface without string paths:

```python
from app._pyganini.urls import urls
from pyganini import to

Route = route(
    page=page,
    destinations=(to("contact-detail", urls.users.by_id, trail_key="from-contacts"),),
)
```

The target must be an exact unbound `urls` selector chain. Generated source
nodes expose typed destination values:

```python
destination = urls.users.destinations.contact_detail("42")
href = destination.href
returning_href = destination.navigation_href(navigation)
```

`.href` is the target path plus the accepted
`_pyganini_nav_trail_key` when the destination declares one. Only that keyed
destination exposes `navigation_href()`. It may append one bounded local
`_pyganini_return_to` value carried privately by `Navigation`.

The target exposes accepted trail keys as generated constants, for example
`urls.users.by_id.trail_keys.from_contacts`. Dispatch accepts a key only when
there is exactly one valid value and it is an inbound live destination key.
Invalid, repeated, malformed, unknown, and undeclared values are ignored.
Selecting a key never changes the canonical trail. The handler may branch on
`nav(request).trail_key()` and supply an explicit alternate trail with
`navigation_with_trail()`.

## Return safety and query ownership

For GET and HEAD, generated dispatch captures the complete ASGI path and
canonical query only for `navigation_href()`. It excludes nested
`_pyganini_return_to` items, sorts query keys in ASCII order, preserves repeated
value order, and bounds the result at 2048 characters. It never copies
application filters, pagination, search, or arbitrary query state to a target.

An inbound return value is honored only with one valid selected trail key. It
must be one local path beginning with one `/`, with no authority, scheme,
fragment, nested return parameter, backslash, control character, or oversized
canonical query. When `root_path` is non-empty, the decoded return path must
stay inside that prefix on a segment boundary, and its untrusted suffix must
not contain a literal or percent-encoded dot or dot-dot segment. Pyganini quotes
the trusted decoded prefix before interpreting the remaining URL structure, so
valid prefix text such as literal percent, `?`, and `#` characters is preserved
in percent-quoted external form. Invalid or outside-prefix values are ignored
without an error. A valid value replaces only `navigation.back.href` and
preserves the semantic Back label.

Plain route `.path` values and mounted URL helpers never add navigation query
state. Application-owned target query parameters must be composed explicitly
with standard-library URL tools.

## Mounted routes

Mounted source `route_kit(nav=...)` declarations provide defaults. A selected
`mount_route(nav=...)` replaces that default when non-`None`; omitted selection
navigation inherits the source value. Source declarations below `app/mounts`
cannot declare destinations. Live owners declare destination edges on their
selected `mount_route` values.

Each live owner receives rebased canonical trails, target keys, destinations,
and request-local state. Excluded source declarations remain absent. Two owners
of one source can therefore use different labels, destinations, data, layouts,
and alternate trail behavior without a second route graph.

Navigation values are ordinary application context. Fragments and actions do
not receive implicit template values or layouts; handlers pass Navigation in
their explicit `FragmentResponse.context` or `Page.context` when needed.

## Runnable example

The [Navigation example](../../examples/navigation) provides HQ and Regional
journeys through dynamic office, team, and customer labels. Its README walks
through analytics destinations with filtered Back URLs, customer-owned mounted
reports, and a shared report that selects one of two explicit alternate trails.
The example also tests the same links below a FastAPI `/directory` mount.
