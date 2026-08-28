# CSRF helpers

Pyganini includes an optional signed double-submit-cookie helper in `pyganini.csrf`.
It is not installed, mounted, or enforced automatically. Applications still
own the secret, middleware selection and ordering, request parsing, validation
placement, and failed-response policy.

## Configure the guard

Supply stable application-owned secret material with at least 32 bytes:

```python
import os

from pyganini import csrf

guard = csrf.Guard(secret=os.environ["CSRF_SECRET"].encode("ascii"))
application.add_middleware(csrf.TokenMiddleware, guard=guard)
```

The default cookie is `pyganini_csrf`, with path `/`, a 12-hour lifetime,
`HttpOnly`, and `SameSite=Lax`. Set `secure=True` for HTTPS. `SameSite=None`
requires `secure=True`. Cookie names, paths, lifetime, and SameSite values are
validated when the guard is constructed. `max_age` must be between 1 and
`2_147_483_647` seconds. A development-only application may explicitly use
`secrets.token_bytes(32)`; deployed applications should load a stable secret
through their own configuration and rotation process.

`cookie_path` is the URL path scope of the browser cookie. Keep `/` when the
middleware covers the whole host. If the application is mounted under a path
prefix, set the same prefix explicitly so the cookie follows that mount:

```python
guard = csrf.Guard(
    secret=os.environ["CSRF_SECRET"].encode("ascii"),
    cookie_path="/admin",
)
```

The path must start with `/`; it is a cookie scope, not a replacement for the
application's route or URL configuration.

Mount the middleware at the host when every HTTP surface should receive a
token. A route-tree middleware mount is application-owned and intentionally
narrower. The middleware only reuses a valid incoming cookie or issues a new
one. It never reads the body, rejects a request, or performs validation.

## Render visible HTML

Pass the CSRF module and request token explicitly into the Jinja context. The
module value is needed by the examples below because Pyganini does not install a
Jinja global:

```python
context = {"csrf": csrf, "csrf_token": csrf.token(request)}
```

Keep ordinary forms visible in the template:

```jinja
<input type="hidden" name="{{ csrf.FIELD_NAME }}" value="{{ csrf_token }}">
```

For HTMX requests that do not submit a form field, put the plain JSON string
on a visible inherited attribute:

```jinja
<body hx-headers='{{ csrf.headers(csrf_token) }}'>
```

Application-owned JavaScript may use visible meta markup and send the value in
`X-CSRF-Token`:

```jinja
<meta name="{{ csrf.META_NAME }}" content="{{ csrf_token }}">
```

These helpers return ordinary strings. Pyganini does not provide Jinja globals,
filters, `Markup` values, hidden-input renderers, meta-tag renderers, or a
browser runtime.

## Validate before mutation

Parse the form or JSON body using the application-selected policy, then call
the guard before changing application state:

```python
try:
    guard.validate(request, form_token)
except csrf.ValidationError:
    return Response("Forbidden", status_code=403)

# Perform the mutation only after validation succeeds.
```

`X-CSRF-Token` takes precedence over the supplied form value. GET, HEAD,
OPTIONS, and TRACE are safe; every other method is unsafe, including unknown
extension methods. Unsafe validation compares the submitted value with the
incoming cookie, not with a replacement token issued by the middleware.

Duplicate evidence never uses first- or last-value selection. More than one
`X-CSRF-Token` header or more than one configured CSRF cookie fails with
`BadTokenError`, regardless of order or whether an individual value is empty or
valid. The token middleware treats duplicate configured cookies as invalid and
issues a replacement without rejecting the request. When accepting a form
token, parse the body under application policy and require exactly one textual
field before calling `guard.validate()`:

```python
values = form.getlist(csrf.FIELD_NAME)
if len(values) != 1 or not isinstance(values[0], str):
    return Response("Forbidden", status_code=403)

guard.validate(request, values[0])
```

Applications should normally catch `csrf.ValidationError` as one forbidden
boundary and avoid exposing whether a token was missing, malformed, bad, or
expired. `csrf.token(request)` raises `TokenUnavailableError` when the
middleware was not mounted or did not provide a request token.

The helper does not solve XSS, compromised subdomains, authorization defects,
unsafe GET behavior, cookie injection, origin policy, TLS, proxy policy, or
application validation performed after mutation. Applications may choose
another CSRF library or browser policy when that better fits their threat
model.
