# Project Setup

Use this reference when adding Pyganini, creating an application, or repairing
missing app tooling. These examples target Pyganini 0.2.0, CPython 3.13 or newer,
and Python 3.14 for development. Check the existing app's installed version and
dependency policy before changing them.

Consumers may use any compliant Python installer. uv is the workflow used in
this new-app example, not a runtime dependency. Uvicorn and FastAPI are host
choices; Pyganini does not install a server or make FastAPI a core dependency.

## Create a minimal application

Create a new directory only when the user requested a new app. Inside it, create
regular packages and the files below. If adding Pyganini to an existing project,
merge the project marker and dependencies instead of replacing its metadata.

```bash
mkdir -p app/routes/users/by_user_id
touch app/__init__.py app/routes/__init__.py
touch app/routes/users/__init__.py app/routes/users/by_user_id/__init__.py
```

### `pyproject.toml`

```toml
[project]
name = "hello-pyganini"
version = "0.0.0"
requires-python = ">=3.13"
dependencies = [
    "pyganini==0.2.0",
    "starlette>=1.6.0,<1.7",
    "uvicorn>=0.52.4,<0.53",
]

[tool.pyganini]
```

The empty table is the project marker; it currently accepts no keys. The root
is selected explicitly with `--app-root`, or by searching upward from the
working directory for the nearest marker. Dependencies install normally:

```bash
uv lock
uv sync --locked --python 3.14
```

### `app/routes/route.py`

```python
from pyganini import route

from .handlers import page

Route = route(page=page, template="page.jinja")
```

### `app/routes/handlers.py`

```python
from pyganini import Page, PageMetadata
from starlette.requests import Request

from app._pyganini.urls import urls


def page(request: Request) -> Page:
    app_urls = urls.with_base_path(request.scope.get("root_path", ""))
    return Page(
        context={"user_ids": ("ada", "grace"), "urls": app_urls},
        metadata=PageMetadata(title="Pyganini users"),
    )
```

### `app/routes/page.jinja`

```html
<main>
  <h1>Users</h1>
  <ul>
    {% for user_id in user_ids %}
    <li><a href="{{ urls.users.by_user_id(user_id).path }}">{{ user_id }}</a></li>
    {% endfor %}
  </ul>
</main>
```

### `app/routes/layout.py`

```python
# This file marks ownership of the adjacent layout.jinja.
```

### `app/routes/layout.jinja`

```html
<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><title>{{ metadata.title }}</title></head>
  <body>{{ child }}</body>
</html>
```

### `app/routes/users/by_user_id/route.py`

```python
from pyganini import route

from .handlers import page

Route = route(page=page, template="page.jinja")
```

### `app/routes/users/by_user_id/handlers.py`

```python
from pyganini import Page, PageMetadata
from starlette.requests import Request

from app._pyganini.urls import urls


def page(request: Request) -> Page:
    user_id = request.path_params["user_id"]
    app_urls = urls.with_base_path(request.scope.get("root_path", ""))
    return Page(
        context={"user_id": user_id, "home_url": app_urls.root.path},
        metadata=PageMetadata(title=f"User {user_id}"),
    )
```

### `app/routes/users/by_user_id/page.jinja`

```html
<main>
  <h1>User {{ user_id }}</h1>
  <a href="{{ home_url }}">Home</a>
</main>
```

## Generate before importing the host

Generation parses declarations without importing their handlers, so a handler
can refer to the URL module that is about to be generated. Run generation before
importing the server or running type checkers that need generated modules:

```bash
uv run --locked pyganini generate
uv run --locked pyganini check
uv run --locked pyganini routes list
uv run --locked pyganini routes explain /users/ada
```

Keep generated `app/_pyganini` files in version control; never edit them by hand.
There is no Pyganini application scaffolding or development-server command.

### `app/main.py`

```python
from starlette.applications import Starlette
from starlette.routing import Mount

from app._pyganini.asgi import router

app = Starlette(routes=[Mount("/", app=router)])
```

The app owns host setup, lifespan, middleware, static mounts, and server policy.
More specific static or API mounts belong before the catch-all Pyganini mount.
A FastAPI host may mount the same generated router; its API decorators,
dependencies, and OpenAPI remain host-owned.

```bash
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Visit `/` and `/users/ada`; both render through the root layout. Stop the server
after verification. If dependencies cannot be installed, report the actual
failure rather than cloning framework source into the app. Continue with
[Routes](routes.md) or [HTMX fragments and actions](htmx-fragments-actions.md).
