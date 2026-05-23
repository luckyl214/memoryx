"""Test that SCHEMA_PATH points to the single authoritative schema file."""

from pathlib import Path
from memoryx.db import SCHEMA_PATH


def test_schema_path_points_to_authoritative_source():
    """P0-A: SCHEMA_PATH must point to memoryx/storage/sql/schema.sql,
    not the deprecated db/schema.sql compatibility mirror."""
    # Must be absolute path
    assert SCHEMA_PATH.is_absolute(), f"SCHEMA_PATH must be absolute: {SCHEMA_PATH}"

    # Must exist
    assert SCHEMA_PATH.exists(), f"SCHEMA_PATH does not exist: {SCHEMA_PATH}"

    # Must be the authoritative schema inside the package
    expected_suffix = Path("memoryx") / "storage" / "sql" / "schema.sql"
    assert str(SCHEMA_PATH).endswith(
        str(expected_suffix)
    ), f"SCHEMA_PATH must point to {expected_suffix}, got {SCHEMA_PATH}"

    # Must not point to the deprecated root db/schema.sql
    deprecated = Path("db") / "schema.sql"
    assert not str(SCHEMA_PATH).endswith(
        str(deprecated)
    ), f"SCHEMA_PATH must NOT point to deprecated {deprecated}"


def test_schema_path_is_readable():
    """The authoritative schema file must be readable and non-empty."""
    content = SCHEMA_PATH.read_text(encoding="utf-8")
    assert len(content) > 100, "Schema file should be substantial"
    assert "CREATE TABLE" in content, "Schema must contain CREATE TABLE statements"
    assert "memories" in content, "Schema must contain memories table"


def test_compatibility_mirror_still_exists():
    """P0-A: db/schema.sql is kept as compatibility mirror, not deleted."""
    from memoryx.db import REPO_ROOT
    mirror = REPO_ROOT / "db" / "schema.sql"
    assert mirror.exists(), (
        "Compatibility mirror db/schema.sql must still exist. "
        "It should not be deleted until all downstream consumers migrate."
    )
