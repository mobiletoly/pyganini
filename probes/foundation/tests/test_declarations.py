from pathlib import Path

import pytest

from foundation_probes.declarations import DeclarationDiagnostic, parse_declaration

FIXTURES = Path(__file__).parent / "fixtures" / "declarations"


def test_literal_route_facts_and_aliases_are_extracted_without_import() -> None:
    result = parse_declaration(FIXTURES / "complete.py")
    assert result.path == "/users/{user_id}"
    assert result.parameters == ("user_id",)
    assert (result.page.module, result.page.symbol) == (None, "local_page")
    assert [(item.module, item.symbol) for item in result.fragments] == [
        ("fragments", "summary"),
        ("fragments", "details"),
    ]
    assert [(item.module, item.symbol) for item in result.actions] == [
        ("actions", "save")
    ]
    assert result.metadata == (("section", "users"), ("title", "User"))


def test_identical_input_produces_identical_normalized_data() -> None:
    first = parse_declaration(FIXTURES / "identical_a.py")
    second = parse_declaration(FIXTURES / "identical_b.py")
    assert first == second
    assert first.stable_json() == second.stable_json()


def test_relative_import_level_and_alias_are_preserved() -> None:
    result = parse_declaration(FIXTURES / "package" / "relative_import.py")
    assert (result.page.module, result.page.symbol) == (".handlers", "page")


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("shadowed_handler.py", "rebound by unsupported assignment"),
        ("forward_handler.py", "missing handler symbol"),
    ],
)
def test_handler_bindings_follow_source_order(name: str, reason: str) -> None:
    with pytest.raises(DeclarationDiagnostic, match=reason):
        parse_declaration(FIXTURES / name)


@pytest.mark.parametrize(
    ("source_text", "field", "reason"),
    [
        (
            "def page():\n    pass\n"
            "extra = {'metadata': {'section': 'users'}}\n"
            "ROUTE = route(path='/expanded', page=page, **extra)\n",
            "ROUTE",
            "keyword expansion is unsupported",
        ),
        (
            "def page():\n    pass\n"
            "ROUTE = route(path='/first', path='/second', page=page)\n",
            "path",
            "duplicate declaration field",
        ),
        (
            "def page():\n    pass\n"
            "ROUTE = route(path='/first', page=page)\n"
            "ROUTE = route(path='/second', page=page)\n",
            "ROUTE",
            "multiple declarations are unsupported",
        ),
        (
            "def page():\n    pass\n"
            "ROUTE = alias = route(path='/chained', page=page)\n",
            "ROUTE",
            "direct assignment is required",
        ),
        (
            "ROUTE, other = values\n",
            "ROUTE",
            "direct assignment is required",
        ),
        (
            "def page():\n    pass\n"
            "ROUTE: object = route(path='/annotated', page=page)\n",
            "ROUTE",
            "annotated binding is unsupported",
        ),
        (
            "def page():\n    pass\n"
            "ROUTE = route(path='/first', page=page)\n"
            "ROUTE += other\n",
            "ROUTE",
            "augmented binding is unsupported",
        ),
    ],
)
def test_route_call_and_binding_shapes_fail_closed(
    tmp_path: Path,
    source_text: str,
    field: str,
    reason: str,
) -> None:
    source = tmp_path / "route_shape.py"
    source.write_text(source_text, encoding="ascii")
    with pytest.raises(DeclarationDiagnostic) as captured:
        parse_declaration(source)
    diagnostic = captured.value
    assert diagnostic.source == source
    assert diagnostic.line > 0
    assert diagnostic.column > 0
    assert diagnostic.field == field
    assert reason in diagnostic.reason


@pytest.mark.parametrize(
    ("binding", "reason"),
    [
        ("def ROUTE():\n    pass\n", "function definition"),
        ("async def ROUTE():\n    pass\n", "function definition"),
        ("class ROUTE:\n    pass\n", "class definition"),
        ("import handlers as ROUTE\n", "import binding"),
        ("from handlers import page as ROUTE\n", "import binding"),
        ("del ROUTE\n", "delete binding"),
        ("if enabled:\n    ROUTE = other\n", "conditional assignment"),
        ("for ROUTE in values:\n    pass\n", "loop target"),
        ("with manager as ROUTE:\n    pass\n", "with target"),
        (
            "try:\n    pass\nexcept Exception as ROUTE:\n    pass\n",
            "exception target",
        ),
        ("match value:\n    case ROUTE:\n        pass\n", "match capture"),
        ("(ROUTE := other)\n", "named expression"),
        ("type ROUTE = object\n", "type alias"),
    ],
)
def test_every_other_module_route_binding_fails_closed(
    tmp_path: Path,
    binding: str,
    reason: str,
) -> None:
    source = tmp_path / "route_binding.py"
    source.write_text(
        f"def page():\n    pass\nROUTE = route(path='/accepted', page=page)\n{binding}",
        encoding="ascii",
    )
    with pytest.raises(DeclarationDiagnostic) as captured:
        parse_declaration(source)
    diagnostic = captured.value
    assert diagnostic.source == source
    assert diagnostic.line >= 3
    assert diagnostic.column > 0
    assert diagnostic.field == "ROUTE"
    assert reason in diagnostic.reason


@pytest.mark.parametrize(
    ("binding", "reason"),
    [
        ("class page:\n    pass\n", "class definition"),
        ("del page\n", "delete binding"),
        ("if enabled:\n    page = other\n", "conditional assignment"),
        ("for page in values:\n    pass\n", "loop target"),
        ("with manager as page:\n    pass\n", "with target"),
        (
            "try:\n    pass\nexcept Exception as page:\n    pass\n",
            "exception target",
        ),
        ("match value:\n    case page:\n        pass\n", "match capture"),
        ("(page := other)\n", "named expression"),
        ("type page = object\n", "type alias"),
    ],
)
def test_handler_binding_forms_cannot_leave_a_stale_import(
    tmp_path: Path,
    binding: str,
    reason: str,
) -> None:
    source = tmp_path / "handler_binding.py"
    source.write_text(
        "from handlers import page\n"
        f"{binding}"
        "ROUTE = route(path='/rebound', page=page)\n",
        encoding="ascii",
    )
    with pytest.raises(DeclarationDiagnostic) as captured:
        parse_declaration(source)
    diagnostic = captured.value
    assert diagnostic.source == source
    assert diagnostic.field == "page"
    assert reason in diagnostic.reason


def test_star_import_is_rejected_as_unenumerable_binding(tmp_path: Path) -> None:
    source = tmp_path / "star_import.py"
    source.write_text(
        "from handlers import *\nROUTE = route(path='/star', page=page)\n",
        encoding="ascii",
    )
    with pytest.raises(DeclarationDiagnostic) as captured:
        parse_declaration(source)
    assert captured.value.field == "imports"
    assert "star import" in captured.value.reason


def test_nested_scope_and_comprehension_targets_do_not_bind_module_route(
    tmp_path: Path,
) -> None:
    source = tmp_path / "nested_scope.py"
    source.write_text(
        "def page():\n    pass\n"
        "def helper():\n    ROUTE = object()\n"
        "class Holder:\n    ROUTE = object()\n"
        "values = [ROUTE for ROUTE in ()]\n"
        "ROUTE = route(path='/nested', page=page)\n",
        encoding="ascii",
    )
    assert parse_declaration(source).path == "/nested"


def test_handler_binding_after_route_does_not_change_captured_reference(
    tmp_path: Path,
) -> None:
    source = tmp_path / "later_handler.py"
    source.write_text(
        "from handlers import page\n"
        "ROUTE = route(path='/captured', page=page)\n"
        "class page:\n    pass\n",
        encoding="ascii",
    )
    result = parse_declaration(source)
    assert (result.page.module, result.page.symbol) == ("handlers", "page")


@pytest.mark.parametrize(
    ("name", "field", "reason"),
    [
        ("nested_call.py", "page", "named local or imported handler"),
        ("computed.py", "path", "literal data"),
        ("decorator.py", "registration", "decorator-driven"),
        ("missing_handler.py", "page", "missing handler symbol"),
    ],
)
def test_unsupported_syntax_has_localized_diagnostic(
    name: str,
    field: str,
    reason: str,
) -> None:
    source = FIXTURES / name
    with pytest.raises(DeclarationDiagnostic) as captured:
        parse_declaration(source)
    diagnostic = captured.value
    assert diagnostic.source == source
    assert diagnostic.line > 0
    assert diagnostic.column > 0
    assert diagnostic.field == field
    assert reason in diagnostic.reason
    assert str(source) in str(diagnostic)
