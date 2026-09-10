from pathlib import Path

import pytest

from tests.artifact_inventory import assert_runtime_sources


@pytest.fixture
def source_trees(tmp_path):
    actual, candidate, repository = [tmp_path / name for name in ("app", "candidate", "repository")]
    for root in (actual, candidate):
        for name in ("core/services/uploads.py", "core/migrations/0001_initial.py", "kairos/settings.py", "manage.py", "docker-entrypoint.sh"):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic " + name)
    for root in (actual / "legacy-extracted", repository / "legacy/extracted"):
        root.mkdir(parents=True)
        (root / "inventory.json").write_text('{"status":"legacy_unverified"}')
    return actual, candidate, repository


def test_full_inventory_matches(source_trees):
    assert_runtime_sources(*source_trees)


@pytest.mark.parametrize("name", ["core/services/uploads.py", "core/migrations/0001_initial.py", "kairos/settings.py", "manage.py", "docker-entrypoint.sh", "legacy-extracted/inventory.json"])
@pytest.mark.parametrize("change", ["divergent", "missing"])
def test_full_inventory_rejects_divergence_or_missing(source_trees, name, change):
    path = source_trees[0] / name
    if change == "missing":
        path.unlink()
    else:
        path.write_text("wrong revision")
    with pytest.raises(AssertionError):
        assert_runtime_sources(*source_trees)


@pytest.mark.parametrize("name", ["core/old_vulnerable.py", "kairos/stale_config.py", "legacy-extracted/unlisted.json"])
def test_full_inventory_rejects_extra_inherited_source(source_trees, name):
    (source_trees[0] / name).write_text("unexpected inherited file")
    with pytest.raises(AssertionError):
        assert_runtime_sources(*source_trees)


def test_full_inventory_rejects_symlink(source_trees):
    path = source_trees[0] / "core/link.py"
    try:
        path.symlink_to(Path("services/uploads.py"))
    except OSError:
        pytest.skip("Creating symlinks requires platform support")
    with pytest.raises(AssertionError, match="Symlink"):
        assert_runtime_sources(*source_trees)
