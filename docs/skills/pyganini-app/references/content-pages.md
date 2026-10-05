# Trusted Content Pages

Use this for first-party HTML/Markdown pages outside the route source tree.
Authors must be trusted like template authors. Pyganini preserves raw HTML and
does not sanitize bodies. Public uploads and untrusted content are unsupported.

## Optional dependency and files

Enable the `content` extra on the app's existing Pyganini dependency, preserving
its version policy. For the [setup example](project-setup.md), use
`pyganini[content]==0.2.0`, then update the lock and environment normally. Do not
import `pyganini.content` unless this feature is being used.

Keep content outside `app/`, for example:

```text
content/
  guides/
    getting-started/
      page.json
      body.md
```

The directory names determine literal content paths; this example owns
`/guides/getting-started`. Each page has JSON metadata containing a non-empty `title`
and optional `description`, plus exactly one `body.md` or `body.html`. A directory
without page files groups children. The content root cannot represent `/` or
contain page files; keep the home route explicit.

## Explicit miss integration

Construct the resolver with an ordinary application-owned `Path`:

```python
from pathlib import Path

from pyganini import content

pages = content.new(content.Config(root=Path("content")))
```

Select the actual app root rather than relying on an unknown server working
directory. Pass `pages.resolve`, or an app wrapper that adds required layout
values, to generated `create_router(additional_page_source=...)`. Preserve the
host's middleware, static mounts, lifespan, inspection, and error options.
The sync resolver's filesystem work is offloaded by generated dispatch.

The optional `AdditionalPageSource` may be sync or async and returns
`AdditionalPage`, a concrete Starlette response, or `None`. It runs only after
an ordinary route miss for GET/HEAD; matched routes and 405 are terminal. Source
pages use original live static layout/middleware ancestry. Dynamic route and
mounted-source ancestry do not create content ownership. Supply needed
`AdditionalPage.layout` values explicitly; `dataclasses.replace` can add them
without mutating the resolved page.

## Rendering and lifetime

Bodies are completed trusted HTML, not Jinja templates. Content renders in
`<article class="pyganini-content">`; the app supplies styling, images, and asset
delivery. GFM includes tables, task lists, strikethrough, autolinks, raw HTML, and
per-document heading IDs. Inspect punctuation-heavy heading IDs before linking;
do not promise byte-identical Goldmark slugs or a parser plugin API.

Content paths have no generated URL helpers, navigation entries, or route-list
rows. Author body links with the intended public prefix; Pyganini does not
rewrite them. Use generated helpers for declared endpoints and explicit
application values for content links.

External metadata/body files are read on each GET/HEAD. Valid new pages and
repairs appear without generation or server restart. Multi-file saves are not
transactional; invalid entries raise `ContentError` until repaired. Use the
app's error policy instead of concealing errors with a cached last-good result.
`content.check(root)` validates current content without claiming HTML safety.

For packaged resources, hold the application's
`importlib.resources.as_file(...)` extraction context for the entire server
lifetime. Immutable packaged data still needs normal build/restart. The built-in
resolver is not a hostile mutable-filesystem confinement mechanism, remote
storage interface, cache, or asset server.
