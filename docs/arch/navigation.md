# Navigation Architecture

Navigation is a request-local projection of the one live `RouteGraph`. It
does not add a route registry, destination graph, matcher, persisted manifest,
request context, client state, or generated product.

## Ownership

`_navigation.py` owns the public immutable values, request facade, resolution
mapping, trail validation, Back derivation, and bounded return handling. It
reads one private ASGI scope slot installed by generated dispatch. That one
slot contains immutable step facts, the accepted key, bounded return values,
and the private resolution mapping; there is no second return-value scope slot.
It does not import route declarations, graph construction, generated application
modules, Jinja, or application code.

`_navigation.py` owns frozen `RouteNav` and `Destination` values. `_declarations.py`
owns route declaration fields, mounted selection fields, and constructor
validation that carries those values. `_route_graph.py` parses exact literal
declarations without imports and
retains source-positioned `RouteNavSource` and `DestinationSource` facts on
normalized route nodes. A destination keeps its unbound generated member
selector until the final graph resolves that selector against canonical live
URL paths, so a static `by-id` member is not reconstructed as a dynamic
`{id}` path. Mounted source defaults remain source facts; live selection
overrides and destinations become effective final-node facts.
Static route display metadata is retained beside these facts but has no
navigation meaning. Inspection may display metadata and effective navigation
together; metadata never creates a trail, destination, label, key, or policy.

The final graph validates destination target existence, dynamic-key uniqueness
in canonical ancestry, mounted source destination exclusion, and effective
ownership. Generated import validation compares runtime route values and
mounted selections with the captured graph evidence.

## Canonical projection

For an endpoint, dispatch walks live root-to-owner route ancestry. It includes
only effective non-`None` navigation declarations. A local fragment or action
does not add a trail level. The exact owner declaration is current only when it
has navigation; an un-navigated owner does not promote an ancestor.

Generated dispatch stores method-specific immutable label/key/pattern/current
facts and accepted inbound trail keys in generated source. After Starlette path
matching and parameter-name validation, `_prepare_navigation()` normalizes the
trusted decoded ASGI `root_path` through the generated URL base-path contract.
It binds graph-local patterns and matched parameters, then prefixes the bound
path. Mounted-source rebasing has already selected the final live-owner
pattern. `_url_binding.py` owns the pure normalization, composition, and
segment quoting. Navigation preparation performs no I/O,
rendering, filesystem access, event-loop creation, or worker-limit mutation.

Dynamic labels remain unresolved until application code calls `resolve()` or
`resolve_href()`. A returned `Navigation` is newly constructed and detached
from later resolution calls. A custom tuple from `navigation_with_trail()` is
validated independently and never changes the canonical request trail.

## Generated URL projection

Navigation-bearing URL plans adapt dynamic members to immutable callable target
objects. The existing `urls.users.by_id(value).path` call remains valid, while
the uncalled target exposes `route_pattern`, unbound descendants, accepted
`trail_keys`, and typed source `destinations` where the graph requires them.
Destination values expose `.href`; only a destination with a declared trail
key exposes `.navigation_href(navigation)`. Plain paths and mounted source
helpers stay query-free. The generated module imports the shared private URL
segment function; no second quoting implementation or path formatter is
created. Navigation-free plans use the pre-navigation renderer byte-for-byte.

Generated navigation members are checked against reserved URL members and
destination/trail-key collections before artifact writing. Destination and
trail-key members that normalize to Python keywords fail as localized
`PYGANINI016 url-interface` errors. A dynamic target whose parameter is `self`
uses a non-conflicting generated receiver name while preserving the existing
call syntax. Deterministic target, destination, key, and source ordering is
derived from graph path and source facts.

## Query and return boundary

The two reserved keys are `_pyganini_nav_trail_key` and `_pyganini_return_to`.
Accepted trail keys derive only from live inbound destination declarations.
Dispatch ignores missing, repeated, malformed, unknown, and undeclared values.

For GET and HEAD, the request target captured for a later destination return
uses the complete ASGI `scope["path"]` once and never adds `root_path`. It
excludes nested return values and sorts keys
in ASCII order, preserves repeated-value order, and is bounded at 2048
characters. An inbound return value is considered only with one accepted key;
it must be a bounded local path with no scheme, authority, fragment, nested
return value, backslash, control character, or unsafe URL form. A valid value
must also stay inside a non-empty effective prefix on a decoded segment
boundary. The containment owner rejects literal or one-level percent-decoded
dot segments in the untrusted suffix, without reinterpreting literal percent
text in the already-decoded trusted prefix. It replaces that decoded prefix
with the normalized external prefix before structural URL parsing, so trusted
prefix characters such as literal percent, `?`, and `#` are percent-quoted
rather than interpreted as URL delimiters. A valid value replaces only the
nearest semantic Back href. No return stack is created and no arbitrary
request query is forwarded to a target.

## Rendering boundary

Pyganini never places navigation in Jinja implicitly. Handlers explicitly put a
`Navigation` value in `Page.context`, `FragmentResponse.context`, or another
application-owned mapping. Templates own breadcrumb, menu, Back, HTMX, and
fallback HTML. Application composition and the ASGI server remain responsible
for supplying `root_path`. `resolve_href()` and custom trails remain
application-owned and receive no automatic prefixing.
