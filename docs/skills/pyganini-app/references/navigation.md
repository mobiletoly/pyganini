# Navigation

Read this for breadcrumbs, semantic Back links, destination edges, or alternate
trails. Pyganini supplies ordinary request-local values, not navigation HTML,
browser history, Referer inference, sessions, or Jinja globals.

Declare `nav=RouteNav(label="Users")` for a static label, or
`nav=RouteNav(key="user")` for an application-resolved label. A route's page,
fragments, and actions share this contribution. Bind the handler before `Route`.
After loading application data in the handler:

```python
from pyganini import nav

request_navigation = nav(request)
request_navigation.resolve("user", user.name)
navigation = request_navigation.navigation()
# Pass navigation explicitly in Page.context or FragmentResponse.context.
```

Unresolved dynamic steps do not appear. `resolve_href(key, label, href)` uses an
application-owned href verbatim; `resolve` restores the canonical one.
Framework-derived links already use trusted ASGI `root_path`. Generated URL and
asset helpers still need explicit prefix binding.

```jinja
<nav aria-label="Breadcrumb">
  {% for step in navigation.trail %}
    {% if step.current %}<span aria-current="page">{{ step.label }}</span>
    {% else %}<a href="{{ step.href }}">{{ step.label }}</a>{% endif %}
  {% endfor %}
</nav>
{% if navigation.back.ok %}
<a href="{{ navigation.back.href }}">Back to {{ navigation.back.label }}</a>
{% endif %}
```

Back is the nearest prior linked trail step. Choose a fallback in application
code if none exists. An inert `nav(None)` or unprepared request has no live trail.

## Destinations and alternate trails

Live declarations can use a literal tuple of `to(...)` edges targeting exact,
unbound generated `urls` selectors:

```python
from app._pyganini.urls import urls
from pyganini import to

# In the source route declaration:
# destinations=(to("user-detail", urls.users.by_user_id,
#                  trail_key="from-users"),)
```

An edge owned by `users` exposes
`urls.users.destinations.user_detail("42").href`. A keyed edge also exposes
`navigation_href(navigation)` for a bounded validated return link. Its target
exposes `urls.users.by_user_id.trail_keys.from_users`. Handlers may branch on
`nav(request).trail_key()` and use `navigation_with_trail(...)` with `nav_step`
and `current_nav_step`; the current step must be unique and last.

Do not manually synthesize `_pyganini_nav_trail_key` or `_pyganini_return_to`
parameters or treat arbitrary query state as inherited navigation. Ordinary
`.path` and mounted helpers remain query-free. The application owns filters
and pagination. Return destinations must remain local and within the effective
mount prefix; invalid/repeated keys or return values are ignored.

Mounted source navigation is a default. A live selected `mount_route(nav=...)`
can replace it and declare owner destinations. Mounted sources cannot declare
destination edges. See [Shared kit routes](shared-kit-routes.md).
