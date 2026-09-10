"""Compare all declared runtime sources, including unexpected inherited files."""
import hashlib
from pathlib import Path


def tree_inventory(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise AssertionError("Source directory missing or symlinked")
    result = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise AssertionError("Symlink in runtime source inventory")
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts:
            continue
        if path.is_file():
            result[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        elif not path.is_dir():
            raise AssertionError("Special file in runtime source inventory")
    return result


def assert_runtime_sources(actual, candidate, repository):
    actual, candidate, repository = map(Path, (actual, candidate, repository))
    for name in ("core", "kairos"):
        assert tree_inventory(actual / name) == tree_inventory(candidate / name), name
    assert tree_inventory(actual / "legacy-extracted") == tree_inventory(repository / "legacy/extracted"), "legacy"
    for name in ("manage.py", "docker-entrypoint.sh"):
        left, right = actual / name, candidate / name
        assert not left.is_symlink() and not right.is_symlink(), name
        assert left.is_file() and right.is_file(), name
        assert left.read_bytes() == right.read_bytes(), name
