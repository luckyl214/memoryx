from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "db" / "schema.sql"
MIGRATIONS_DIR = REPO_ROOT / "db" / "migrations"

__all__ = ["REPO_ROOT", "SCHEMA_PATH", "MIGRATIONS_DIR"]
