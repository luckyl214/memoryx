from __future__ import annotations

from .sqlite_async import AsyncSQLite


class StorageMaintenance:
    async def check_integrity(self, db: AsyncSQLite) -> str:
        row = await db.fetchone("PRAGMA integrity_check;")
        if row is None:
            return "unknown"
        return str(next(iter(dict(row).values())))

    async def compact(self, db: AsyncSQLite) -> bool:
        await db.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        await db.vacuum()
        await db.execute("PRAGMA optimize;")
        return True

    async def quick_check(self, db: AsyncSQLite) -> str:
        row = await db.fetchone("PRAGMA quick_check;")
        if row is None:
            return "unknown"
        return str(next(iter(dict(row).values())))
