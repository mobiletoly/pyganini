# Generated URL Interfaces

`pyganini generate` emits one typed URL module at `app/_pyganini/urls.py`. Import its
two public values:

```python
from app._pyganini.urls import mount_urls, urls
```

The module is generated from the same normalized route graph as dispatch. It
does not import route handlers, scan the filesystem, read a request, or
register a runtime router.

Route-kit endpoints use the same route-shaped helper surface as local
endpoints. The live owner supplies an owner-specific generated URL value in
the kit; Pyganini does not create a kit-specific URL type or infer a shared
owner's path.

## Mounted source helpers

`mount_urls` is a generated catalog of mounted source identities. Bind one
identity to the live owner's `urls` value; the owner's `route_mount(...)`
declaration already selected the exact declarations it exposes:

```python
from app._pyganini.urls import mount_urls, urls

owner_urls = urls.with_base_path(request.scope.get("root_path", ""))
directory_urls = mount_urls.contact_directory.bind(owner_urls.users)
table_path = directory_urls.table.path
create_path = directory_urls.create.path
```

The bound value preserves the owner's path prefix and exposes only the source
endpoints selected by `route_mount(...)`. Omitted declaration selection means
all source declarations. Selection is not an argument to `bind(...)`. A source
endpoint excluded by the owner declaration has no generated member and cannot
be dispatched. Binding a different owner key fails closed; the catalog never
offers one unbound all-source helper tree. Mounted identities may be nested
when the source identity contains nested packages.

## Route-shaped paths

Static segments are Python attributes. Browser hyphens become Python
underscores. A dynamic `by_<param>` route directory becomes one typed method
whose parameter has the same name:

```python
home_path: str = urls.root.path
users_path: str = urls.users.path
status_path: str = urls.status_options.path
profile_path: str = urls.users.by_user_id(user_id="42").profile.path
```

Dynamic segments bind one value at a time, so nested routes remain visible and
typed:

```python
nested_path: str = (
    urls.organizations.by_organization_id("acme").users.by_user_id("42").path
)
```

`.path` exists only on a node that owns at least one live endpoint. A namespace
that only exposes descendants has no path of its own. Pages, fragments, and
actions at one normalized path share one helper; HTTP methods are not part of
the expression. Only the root path ends in `/`.

An empty route graph still generates an importable URL module with
`with_base_path()` and no route attributes. If the graph owns `/`, its helper is
`urls.root.path`.

## Dynamic values

Dynamic values are decoded one-segment text. Pyganini rejects a non-string value,
an empty value, `.` or `..`, `/`, `\`, ASCII control characters, and text that
cannot be UTF-8 encoded. Errors identify the parameter, for example:

```text
parameter 'user_id' must not contain '/' or '\'
```

Accepted values are quoted with `urllib.parse.quote(value, safe="")`:

```text
"42"       -> 42
"a b"      -> a%20b
"a%2Fb"    -> a%252Fb
"cafe"     -> cafe
"caf\u00e9" -> caf%C3%A9
"x?y#z"    -> x%3Fy%23z
```

The source examples stay ASCII; the accented result represents a UTF-8 encoded
Unicode value. Literal percent text is quoted as input, not treated as already
escaped.

## Explicit base paths

URL values are local absolute paths. They do not contain a scheme, authority,
host, port, or proxy-header policy. Bind a decoded mount or proxy prefix
explicitly, usually from the request scope selected by application host code:

```python
app_urls = urls.with_base_path(request.scope.get("root_path", ""))
users_path = app_urls.users.path
```

`with_base_path()` returns a new immutable value with the same typed route
surface. It does not mutate `urls` or another bound value. Empty input and `/`
mean no prefix. Missing leading slashes are added, trailing slashes are
removed, repeated internal slashes that create empty segments are rejected, and
each decoded segment is validated and quoted once:

```text
""              -> ""
"/"             -> ""
"webapp"        -> "/webapp"
"/webapp/"      -> "/webapp"
"/team space"   -> "/team%20space"
"/api/v1"       -> "/api/v1"
```

Pyganini does not infer `root_path`, use a current-request global, read proxy
headers, or silently alter a template environment.

Request Navigation is different: generated dispatch already has the current
request, so it binds framework-derived canonical hrefs from the effective
`root_path` automatically. Bind URL and asset helpers explicitly from that
same value so destinations, breadcrumbs, forms, and assets share one external
path space. A proxy header without an ASGI `root_path` has no effect.

## Templates and typing

Pass the selected URL value explicitly when a template needs it. There is no
implicit Jinja global or filter:

```python
from app._pyganini.urls import urls
from pyganini import Page


def page(request):
    app_urls = urls.with_base_path(request.scope.get("root_path", ""))
    return Page(context={"urls": app_urls, "title": "Users"})
```

The template can keep the hypermedia behavior visible:

```html
<a href="{{ urls.users.path }}">Users</a>

<form method="post" action="{{ urls.users.create.path }}"
      hx-post="{{ urls.users.create.path }}"
      hx-target="#users-directory" hx-swap="outerHTML">
  <button type="submit">Create</button>
</form>
```

The generated value is explicit context; Pyganini does not generate or inject the
HTMX attributes. See [HTMX and async forms](htmx.md) for route-local forms,
fragments, actions, and request/response headers.

The generated `.py` file is both the runtime module and the static typing
surface. It has no companion `.pyi`. Mypy and Pyright can reject missing,
unknown, or wrong-typed dynamic arguments and unknown route attributes while
retaining typed child access after a binding.

The source-only [route inspection](route-inspection.md) command reports the
same live helper spelling as `HELPER` in its table or `helper` in JSON. For
example, `/users/{user_id}` is reported as
`urls.users.by_user_id(user_id).path`. Inspection derives this expression from
the transient URL projection; it does not import `app/_pyganini/urls.py`, use
`with_base_path(...)`, or expose `mount_urls` expressions.

The same inspection document describes the separate inbound `routes explain`
surface. It models Starlette's decoded ASGI path by decoding a complete URL
path once: `%2F` becomes a separator and normally prevents a single dynamic
capture, while `%252F` becomes the literal captured value `%2F`. The outbound
URL interface still rejects slash-containing dynamic values; it does not claim
to replace inbound matching or construct query strings.

## Boundaries

The plain URL interface does not construct generic query strings, merge
application query parameters, add fragments, encode forms, or generate HTMX
attributes. Navigation-bearing source nodes may expose typed `destinations`
and target nodes may expose accepted `trail_keys`; see
[Navigation](navigation.md). Plain `.path` values and mounted helpers remain
query-free.

Slash-containing dynamic values are rejected because current Pyganini dispatch uses
Starlette's decoded `scope["path"]`. Returning an escaped slash would not claim
a round trip through that inbound matcher.

Helper-only ambiguity fails closed with `PYGANINI016 url-interface` before generated
state is inspected or changed. Reserved members, Python keywords, and distinct
paths that would map to one helper expression do not receive aliases or a
second access style.
