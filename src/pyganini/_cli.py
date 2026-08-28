# pyright: reportPrivateUsage=false

"""Command-line coordination for project selection and generated state."""

import argparse
import sys
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path

from pyganini._assets import (
    AssetError,
    AssetResult,
    check_assets,
    check_prepared_assets,
    clean_assets,
    close_asset_plan,
    prepare_assets,
    prepare_enabled_assets,
    render_asset_list,
    write_assets,
)
from pyganini._config import ConfigError
from pyganini._declarations import _normalize_mount_identity
from pyganini._dispatch_generation import dispatch_plan
from pyganini._generation import (
    GenerationError,
    bootstrap_plan,
    check_generated_state,
    generate,
)
from pyganini._inspection import (
    InspectionError,
    _normalize_explain_method,
    _parse_explain_target,
    _render_explain,
    _render_explain_negative,
    _render_unit_payload,
    _render_unit_rows,
    _select_explain_route,
    filter_mount,
    inventory_rows,
    render_layout_map,
    render_payload,
)
from pyganini._paths import PathError, select_project_paths
from pyganini._route_graph import RouteGraphError, build_route_graph
from pyganini._template_references import (
    inspect_template_references,
    render_reference_payload,
)
from pyganini._url_generation import _url_helper_projection, url_plan


def _mount_argument(value: str) -> str:
    try:
        return _normalize_mount_identity(value)
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _explain_target_argument(value: str) -> tuple[str, str]:
    try:
        return _parse_explain_target(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _explain_method_argument(value: str) -> str:
    try:
        return _normalize_explain_method(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyganini",
        description=(
            "Validate app/routes and generate or check Pyganini-owned files under "
            "app/_pyganini, or manage final browser-ready assets under assets/. "
            "Application code must not edit Pyganini-owned products."
        ),
        epilog=(
            "generate writes app/_pyganini/.pyganini-root, app/_pyganini/__init__.py, "
            "app/_pyganini/asgi.py, and app/_pyganini/urls.py; check performs no "
            "application writes; asset commands read or write assets/build, "
            "assets/dist, "
            "assets/.pyganini/assets.json, and assets/pyganini_assets_gen.py; "
            "routes list reads the accepted source route "
            "graph without reading or writing generated state; routes layouts "
            "reads the same source graph without URL-helper validation; routes "
            "refs inventories direct HTMX request attributes in graph-selected "
            "Jinja source; routes render-units reports declared template-backed "
            "render capability without loading templates. "
            "Success returns 0, project "
            "or generated-state failures return 1, and usage errors return 2."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('pyganini')}",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("generate", "write current Pyganini-owned generated files"),
        ("check", "check generated files without writing"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument(
            "--app-root",
            type=Path,
            metavar="PATH",
            help="use this exact application root instead of searching from cwd",
        )
    assets = commands.add_parser(
        "assets",
        help="project final build files into fingerprinted browser assets",
        allow_abbrev=False,
    )
    asset_commands = assets.add_subparsers(dest="assets_command", required=True)
    for name, help_text in (
        ("dist", "write fingerprinted asset files and generated lookup state"),
        ("check", "check fingerprinted asset files without writing"),
        ("clean", "remove stale state-owned asset files"),
    ):
        asset_command = asset_commands.add_parser(
            name,
            help=help_text,
            allow_abbrev=False,
        )
        asset_command.add_argument(
            "--app-root",
            type=Path,
            metavar="PATH",
            help="use this exact application root instead of searching from cwd",
        )
    asset_list = asset_commands.add_parser(
        "list",
        help="list final build assets from memory",
        allow_abbrev=False,
    )
    asset_list.add_argument(
        "--app-root",
        type=Path,
        metavar="PATH",
        help="use this exact application root instead of searching from cwd",
    )
    asset_list.add_argument(
        "--json",
        action="store_true",
        help="write the pyganini.assets.v1 JSON schema",
    )
    routes = commands.add_parser(
        "routes",
        help="inspect the static route graph",
        allow_abbrev=False,
    )
    route_commands = routes.add_subparsers(dest="routes_command", required=True)
    list_command = route_commands.add_parser(
        "list",
        help="list canonical routes and static graph evidence",
        allow_abbrev=False,
    )
    list_command.add_argument(
        "--app-root",
        type=Path,
        metavar="PATH",
        help="use this exact application root instead of searching from cwd",
    )
    list_command.add_argument(
        "--mount",
        type=_mount_argument,
        metavar="MOUNT",
        help="show included and excluded rows for this mounted source identity",
    )
    list_command.add_argument(
        "--json",
        action="store_true",
        help="write the pyganini.routes.v1 JSON schema",
    )
    layouts_command = route_commands.add_parser(
        "layouts",
        help="show the source route layout map",
        allow_abbrev=False,
    )
    layouts_command.add_argument(
        "--app-root",
        type=Path,
        metavar="PATH",
        help="use this exact application root instead of searching from cwd",
    )
    explain_command = route_commands.add_parser(
        "explain",
        help="explain one URL path and method against the route graph",
        allow_abbrev=False,
    )
    explain_command.add_argument(
        "--app-root",
        type=Path,
        metavar="PATH",
        help="use this exact application root instead of searching from cwd",
    )
    explain_command.add_argument(
        "--method",
        type=_explain_method_argument,
        default="GET",
        metavar="METHOD",
        help="normalize and explain this HTTP method (default: GET)",
    )
    explain_command.add_argument("target", type=_explain_target_argument)
    refs_command = route_commands.add_parser(
        "refs",
        help="inventory direct HTMX request attributes in Jinja source",
        allow_abbrev=False,
    )
    refs_command.add_argument(
        "--app-root",
        type=Path,
        metavar="PATH",
        help="use this exact application root instead of searching from cwd",
    )
    refs_command.add_argument(
        "--json",
        action="store_true",
        help="write the pyganini.refs.v1 JSON schema",
    )
    render_units_command = route_commands.add_parser(
        "render-units",
        help="report template-backed render units from the source graph",
        allow_abbrev=False,
    )
    render_units_command.add_argument(
        "--app-root",
        type=Path,
        metavar="PATH",
        help="use this exact application root instead of searching from cwd",
    )
    render_units_command.add_argument(
        "--json",
        action="store_true",
        help="write the pyganini.render_units.v1 JSON schema",
    )
    return parser


def _render(*, code: str, phase: str, path: object, message: str) -> str:
    return f"{path}: {code} {phase}: {message}"


def _render_generation_error(error: GenerationError) -> None:
    print(
        _render(
            code=error.code,
            phase=error.phase,
            path=error.path,
            message=error.message,
        ),
        file=sys.stderr,
    )
    for detail in error.details:
        print(f"  {detail}", file=sys.stderr)


def _render_asset_error(error: AssetError) -> None:
    print(
        _render(
            code=error.code,
            phase=error.phase,
            path=error.path,
            message=error.message,
        ),
        file=sys.stderr,
    )
    for detail in error.details:
        print(f"  {detail}", file=sys.stderr)


def _print_asset_result(result: AssetResult) -> None:
    written = result.written
    unchanged = result.unchanged
    removed = result.removed
    print(
        "Pyganini asset state: "
        f"written={len(written)} "
        f"unchanged={len(unchanged)} "
        f"removed={len(removed)}."
    )


def _run_assets(
    command: str,
    app_root: Path | None,
    json_output: bool = False,
) -> int:
    try:
        paths = select_project_paths(
            explicit=app_root,
            start=None if app_root is not None else Path.cwd(),
            validate_generated=False,
        )
        if command == "list":
            plan = prepare_assets(paths, "list")
            sys.stdout.write(render_asset_list(plan, json_output=json_output))
            return 0
        if command == "check":
            differences = check_assets(paths)
            if differences:
                for difference in differences:
                    print(
                        _render(
                            code=difference.code,
                            phase=difference.phase,
                            path=difference.path,
                            message=difference.message,
                        ),
                        file=sys.stderr,
                    )
                return 1
            print("Pyganini asset state is current.")
            return 0
        if command == "clean":
            _print_asset_result(clean_assets(prepare_assets(paths, "clean")))
            return 0
        _print_asset_result(write_assets(prepare_assets(paths, "dist")))
        return 0
    except (ConfigError, PathError) as error:
        print(
            _render(
                code=error.code,
                phase=error.phase,
                path=error.path,
                message=error.message,
            ),
            file=sys.stderr,
        )
        return 1
    except AssetError as error:
        _render_asset_error(error)
        return 1
    except Exception as error:
        _render_asset_error(
            AssetError(
                "PYGANINI022",
                "asset-write",
                "pyganini",
                f"unexpected internal failure: {error}",
            )
        )
        return 1


def _run(command: str, app_root: Path | None) -> int:
    asset_result: AssetResult | None = None
    asset_plan = None
    try:
        paths = select_project_paths(
            explicit=app_root,
            start=None if app_root is not None else Path.cwd(),
        )
        if command == "generate":
            asset_plan = prepare_enabled_assets(paths, "dist")
        route_graph = build_route_graph(paths)
        plan = (*bootstrap_plan(), *dispatch_plan(route_graph), *url_plan(route_graph))
        if command == "check":
            differences = check_generated_state(paths, plan)
            if differences:
                for difference in differences:
                    print(
                        _render(
                            code=difference.code,
                            phase=difference.phase,
                            path=difference.path,
                            message=difference.message,
                        ),
                        file=sys.stderr,
                    )
                return 1
            asset_plan = prepare_enabled_assets(paths, "check")
            if asset_plan is not None:
                asset_differences = check_prepared_assets(asset_plan)
                if asset_differences:
                    for asset_difference in asset_differences:
                        print(
                            _render(
                                code=asset_difference.code,
                                phase=asset_difference.phase,
                                path=asset_difference.path,
                                message=asset_difference.message,
                            ),
                            file=sys.stderr,
                        )
                    return 1
            print("Pyganini generated state is current.")
            if asset_plan is not None:
                print("Pyganini asset state is current.")
            return 0

        result = generate(paths, plan)
        asset_result = write_assets(asset_plan) if asset_plan is not None else None
    except (ConfigError, PathError) as error:
        print(
            _render(
                code=error.code,
                phase=error.phase,
                path=error.path,
                message=error.message,
            ),
            file=sys.stderr,
        )
        return 1
    except RouteGraphError as error:
        for diagnostic in error.diagnostics:
            print(diagnostic.render(), file=sys.stderr)
        return 1
    except AssetError as error:
        _render_asset_error(error)
        return 1
    except GenerationError as error:
        _render_generation_error(error)
        return 1
    except Exception as error:
        unexpected = GenerationError(
            "PYGANINI007",
            "generation-plan",
            "pyganini",
            f"unexpected internal failure: {error}",
        )
        _render_generation_error(unexpected)
        return 1
    finally:
        try:
            close_asset_plan(asset_plan)
        except OSError as error:
            _render_asset_error(
                AssetError(
                    "PYGANINI022",
                    "asset-write",
                    "assets",
                    f"could not close prepared asset operation: {error}",
                )
            )

    print(
        "Pyganini generated state: "
        f"written={len(result.written)} "
        f"unchanged={len(result.unchanged)} "
        f"removed={len(result.removed)}."
    )
    if asset_result is not None:
        _print_asset_result(asset_result)
    return 0


def _render_inspection_error(error: BaseException, command: str = "list") -> None:
    message = str(error) or error.__class__.__name__
    print(
        f"pyganini routes {command}: PYGANINI017 route-inspection: {message}",
        file=sys.stderr,
    )


def _run_routes_list(
    app_root: Path | None,
    mount: str | None,
    json_output: bool,
) -> int:
    try:
        paths = select_project_paths(
            explicit=app_root,
            start=None if app_root is not None else Path.cwd(),
            validate_generated=False,
        )
        route_graph = build_route_graph(paths)
    except (ConfigError, PathError) as error:
        print(
            _render(
                code=error.code,
                phase=error.phase,
                path=error.path,
                message=error.message,
            ),
            file=sys.stderr,
        )
        return 1
    except RouteGraphError as error:
        for diagnostic in error.diagnostics:
            print(diagnostic.render(), file=sys.stderr)
        return 1

    try:
        helper_plan = _url_helper_projection(route_graph)
        rows = filter_mount(
            inventory_rows(route_graph, helper_plan),
            mount,
            graph=route_graph,
        )
        payload = render_payload(
            rows,
            json_output=json_output,
            graph=route_graph,
            mount_selection=mount is not None,
        )
        text_payload = payload.decode("utf-8")
    except GenerationError as error:
        _render_generation_error(error)
        return 1
    except InspectionError as error:
        _render_inspection_error(error)
        return 1
    except Exception as error:
        _render_inspection_error(error)
        return 1

    try:
        sys.stdout.write(text_payload)
    except Exception as error:
        _render_inspection_error(error)
        return 1
    return 0


def _run_routes_layouts(app_root: Path | None) -> int:
    try:
        paths = select_project_paths(
            explicit=app_root,
            start=None if app_root is not None else Path.cwd(),
            validate_generated=False,
        )
        route_graph = build_route_graph(paths)
    except (ConfigError, PathError) as error:
        print(
            _render(
                code=error.code,
                phase=error.phase,
                path=error.path,
                message=error.message,
            ),
            file=sys.stderr,
        )
        return 1
    except RouteGraphError as error:
        for diagnostic in error.diagnostics:
            print(diagnostic.render(), file=sys.stderr)
        return 1

    try:
        payload = render_layout_map(route_graph)
        text_payload = payload.decode("ascii")
    except InspectionError as error:
        _render_inspection_error(error, "layouts")
        return 1
    except Exception as error:
        _render_inspection_error(error, "layouts")
        return 1

    try:
        sys.stdout.write(text_payload)
    except Exception as error:
        _render_inspection_error(error, "layouts")
        return 1
    return 0


def _run_routes_explain(
    app_root: Path | None,
    target: tuple[str, str],
    method: str,
) -> int:
    url_path, asgi_path = target
    try:
        paths = select_project_paths(
            explicit=app_root,
            start=None if app_root is not None else Path.cwd(),
            validate_generated=False,
        )
        route_graph = build_route_graph(paths)
    except (ConfigError, PathError) as error:
        print(
            _render(
                code=error.code,
                phase=error.phase,
                path=error.path,
                message=error.message,
            ),
            file=sys.stderr,
        )
        return 1
    except RouteGraphError as error:
        for diagnostic in error.diagnostics:
            print(diagnostic.render(), file=sys.stderr)
        return 1

    try:
        status, route, endpoint, parameters, allowed = _select_explain_route(
            route_graph,
            asgi_path,
            method,
        )
        if status == "matched":
            if endpoint is None:
                raise InspectionError("matched route explanation lacks endpoint")
            payload = _render_explain(
                route_graph,
                url_path=url_path,
                asgi_path=asgi_path,
                method=method,
                endpoint=endpoint,
                parameters=parameters,
            )
            text_payload = payload.decode("ascii")
        else:
            payload = _render_explain_negative(
                graph=route_graph,
                status=status,
                method=method,
                url_path=url_path,
                asgi_path=asgi_path,
                route=route,
                allowed=allowed,
            )
            text_payload = payload.decode("ascii")
    except InspectionError as error:
        _render_inspection_error(error, "explain")
        return 1
    except Exception as error:
        _render_inspection_error(error, "explain")
        return 1

    if status != "matched":
        try:
            sys.stderr.write(text_payload + "\n")
        except Exception as error:
            _render_inspection_error(error, "explain")
            return 1
        return 1

    try:
        sys.stdout.write(text_payload)
    except Exception as error:
        _render_inspection_error(error, "explain")
        return 1
    return 0


def _run_routes_refs(app_root: Path | None, json_output: bool) -> int:
    try:
        paths = select_project_paths(
            explicit=app_root,
            start=None if app_root is not None else Path.cwd(),
            validate_generated=False,
        )
        route_graph = build_route_graph(paths)
    except (ConfigError, PathError) as error:
        print(
            _render(
                code=error.code,
                phase=error.phase,
                path=error.path,
                message=error.message,
            ),
            file=sys.stderr,
        )
        return 1
    except RouteGraphError as error:
        for diagnostic in error.diagnostics:
            print(diagnostic.render(), file=sys.stderr)
        return 1

    try:
        helper_plan = _url_helper_projection(route_graph)
        rows = inspect_template_references(paths, route_graph, helper_plan)
        payload = render_reference_payload(rows, json_output=json_output)
        text_payload = payload.decode("utf-8")
    except GenerationError as error:
        _render_generation_error(error)
        return 1
    except InspectionError as error:
        _render_inspection_error(error, "refs")
        return 1
    except Exception as error:
        _render_inspection_error(error, "refs")
        return 1

    try:
        sys.stdout.write(text_payload)
    except Exception as error:
        _render_inspection_error(error, "refs")
        return 1
    return 0


def _run_routes_render_units(app_root: Path | None, json_output: bool) -> int:
    try:
        paths = select_project_paths(
            explicit=app_root,
            start=None if app_root is not None else Path.cwd(),
            validate_generated=False,
        )
        route_graph = build_route_graph(paths)
    except (ConfigError, PathError) as error:
        print(
            _render(
                code=error.code,
                phase=error.phase,
                path=error.path,
                message=error.message,
            ),
            file=sys.stderr,
        )
        return 1
    except RouteGraphError as error:
        for diagnostic in error.diagnostics:
            print(diagnostic.render(), file=sys.stderr)
        return 1

    try:
        rows = _render_unit_rows(route_graph)
        payload = _render_unit_payload(rows, json_output=json_output)
        text_payload = payload.decode("utf-8")
    except InspectionError as error:
        _render_inspection_error(error, "render-units")
        return 1
    except Exception as error:
        _render_inspection_error(error, "render-units")
        return 1

    try:
        sys.stdout.write(text_payload)
    except Exception as error:
        _render_inspection_error(error, "render-units")
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the installed Pyganini command and return its process exit code."""
    parser = _parser()
    try:
        arguments = parser.parse_args(argv)
    except SystemExit as error:
        return error.code if isinstance(error.code, int) else 1
    if arguments.command == "routes":
        if arguments.routes_command == "list":
            return _run_routes_list(
                arguments.app_root,
                arguments.mount,
                arguments.json,
            )
        if arguments.routes_command == "layouts":
            return _run_routes_layouts(arguments.app_root)
        if arguments.routes_command == "explain":
            return _run_routes_explain(
                arguments.app_root,
                arguments.target,
                arguments.method,
            )
        if arguments.routes_command == "refs":
            return _run_routes_refs(arguments.app_root, arguments.json)
        if arguments.routes_command == "render-units":
            return _run_routes_render_units(arguments.app_root, arguments.json)
    if arguments.command == "assets":
        return _run_assets(
            arguments.assets_command,
            arguments.app_root,
            getattr(arguments, "json", False),
        )
    return _run(arguments.command, arguments.app_root)
