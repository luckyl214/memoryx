from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MemoryXSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="MEMORYX_",
        extra="ignore",
    )

    home: Path = Field(default=Path.home() / ".hermes" / "memoryx")
    log_level: str = Field(default="INFO")
    queue_size: int = Field(default=256, ge=16, le=4096)
    workers: int = Field(default=2, ge=1, le=8)
    handler_timeout_seconds: float = Field(default=5.0, gt=0.1, le=60.0)
    retry_attempts: int = Field(default=3, ge=1, le=10)
    retry_base_delay: float = Field(default=0.2, gt=0.0, le=10.0)
    retry_max_delay: float = Field(default=2.0, gt=0.0, le=30.0)
    drain_timeout_seconds: float = Field(default=10.0, gt=0.1, le=120.0)
    enqueue_timeout_seconds: float = Field(default=0.5, gt=0.01, le=10.0)
    queue_warning_threshold: float = Field(default=0.8, gt=0.1, le=1.0)
    log_rotation_bytes: int = Field(default=5 * 1024 * 1024, ge=1024 * 1024, le=50 * 1024 * 1024)
    log_backup_count: int = Field(default=5, ge=1, le=20)
    storage_enabled: bool = Field(default=True)
    extraction_every_n_turns: int = Field(default=0, ge=0, le=100)
    recall_preamble: str = Field(default="")
    sqlite_timeout_seconds: float = Field(default=30.0, gt=0.1, le=300.0)
    sqlite_wal_autocheckpoint: int = Field(default=1000, ge=100, le=100000)
    sqlite_mmap_size: int = Field(default=268435456, ge=0, le=2147483647)
    sqlite_cache_size_kib: int = Field(default=8192, ge=1024, le=262144)
    sqlite_busy_timeout_ms: int = Field(default=5000, ge=100, le=60000)

    @property
    def logs_dir(self) -> Path:
        return self.home / "logs"

    @property
    def dead_letters_dir(self) -> Path:
        return self.home / "dead_letters"

    @property
    def event_queue_dir(self) -> Path:
        return self.home / "queue"

    @property
    def plugin_dir(self) -> Path:
        return self.home / "api" / "hermes_plugin"

    @property
    def db_dir(self) -> Path:
        return self.home / "db"

    @property
    def db_path(self) -> Path:
        return self.db_dir / "memoryx.sqlite3"

    def bootstrap_directories(self) -> list[Path]:
        return [
            self.home / "core",
            self.home / "hooks",
            self.home / "extraction",
            self.home / "validation",
            self.home / "storage",
            self.home / "embeddings",
            self.home / "retrieval",
            self.home / "routing",
            self.home / "context",
            self.home / "injection",
            self.home / "consolidation",
            self.home / "temporal",
            self.home / "graph",
            self.home / "episodic",
            self.home / "reflection",
            self.home / "api",
            self.home / "safety",
            self.home / "observability",
            self.home / "evaluation",
            self.home / "workers",
            self.home / "db",
            self.home / "markdown",
            self.home / "archive",
            self.home / "exports",
            self.home / "logs",
            self.home / "dead_letters",
            self.home / "queue",
            self.home / "cache",
            self.home / "tests",
        ]

    def ensure_directories(self) -> None:
        for directory in self.bootstrap_directories():
            directory.mkdir(parents=True, exist_ok=True)


def get_settings() -> MemoryXSettings:
    return MemoryXSettings(_env_file=os.getenv("MEMORYX_ENV_FILE", ".env"))
