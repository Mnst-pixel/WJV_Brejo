"""Wire-format regression: Docker template output must remain valid JSON."""
import ast
import json
from pathlib import Path
import re


def test_caddy_probe_uses_the_deployment_capability_bounding_set():
    root = Path(__file__).resolve().parents[2]
    path = root / "scripts/releases/verify-product-mounts-c12e53a.sh"
    source = path.read_text().split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    call = next(node for node in ast.walk(ast.parse(source))
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "create" and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "edge")
    options = [node.value if isinstance(node, ast.Constant) else None for node in call.args[2].elts]
    capabilities = [options[index + 1] for index, value in enumerate(options) if value == "--cap-add"]
    compose = json.loads((root / "infra/compose/compose.yaml").read_text())
    assert capabilities == compose["services"]["edge"]["cap_add"] == ["NET_BIND_SERVICE"]
    assert options[options.index("--user") + 1] == "1000:1000"


def test_redis_cli_empty_error_separators_do_not_hide_unexpected_replies():
    path = Path(__file__).resolve().parents[1] / "releases/verify-product-mounts-c12e53a.sh"
    source = path.read_text().split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    function = next(node for node in ast.parse(source).body
                    if isinstance(node, ast.FunctionDef) and node.name == "reply_lines")
    scope = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), scope)
    parse = scope["reply_lines"]
    assert parse("OK\nOK\nverified\nNOPERM denied\n\nNOPERM denied\n\n") == [
        "OK", "OK", "verified", "NOPERM denied", "NOPERM denied"]
    assert parse("OK\n\nUNEXPECTED\n\n") == ["OK", "UNEXPECTED"]
    assert parse("\n\n") == []


def test_docker_identity_templates_form_complete_json_documents():
    path = Path(__file__).resolve().parents[1] / "releases/verify-product-mounts-c12e53a.sh"
    source = path.read_text().split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    templates = [node.value for node in ast.walk(ast.parse(source))
                 if isinstance(node, ast.Constant) and isinstance(node.value, str)
                 and node.value.startswith('{"') and "{{json" in node.value]
    assert len(templates) == 2
    for value in (None, 'quoted " value\nsecond line', "kairos"):
        documents = [json.loads(re.sub(r"\{\{json .*?\}\}", lambda _: json.dumps(value), template))
                     for template in templates]
        assert {frozenset(document) for document in documents} == {
            frozenset({"id", "image", "project", "service"}),
            frozenset({"name", "image", "project", "run"}),
        }
