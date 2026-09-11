"""Wire-format regression: Docker template output must remain valid JSON."""
import ast
import json
from pathlib import Path
import re


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
