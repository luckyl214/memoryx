#!/usr/bin/env python3
"""
补全迁移：迁移 TencentDB 中剩余的 2026-05-22 对话记录到 memoryx
"""

import os
import sqlite3
import json
from pathlib import Path
from datetime import datetime, timezone

# 路径配置（使用相对路径）
SCRIPT_DIR = Path(__file__).parent.resolve()
TENCENTDB_DIR = Path(os.getenv("TENCENTDB_DIR", "${TENCENTDB_DIR:-~/.memory-tencentdb}"))
MEMORYX_DB = SCRIPT_DIR.parent / "memoryx.db"


def migrate_remaining_conversations():
    """迁移剩余的对话记录"""
    
    # 打开 TencentDB
    tencentdb_path = TENCENTDB_DIR / "vectors.db"
    if not tencentdb_path.exists():
        print(f"⚠️ TencentDB 数据库不存在: {tencentdb_path}")
        return
    
    # 打开 memoryx
    mx_conn = sqlite3.connect(str(MEMORYX_DB))
    mx_cursor = mx_conn.cursor()
    
    # 检查 memoryx 中已有的 2026-05-22 记录
    mx_cursor.execute(
        "SELECT COUNT(*) FROM conversation_logs WHERE created_at LIKE '2026-05-22%'"
    )
    existing_count = mx_cursor.fetchone()[0]
    print(f"memoryx 中已有的 2026-05-22 记录: {existing_count}")
    
    # 从 TencentDB 获取 2026-05-22 的记录
    tencentdb = sqlite3.connect(str(tencentdb_path))
    tencentdb_cursor = tencentdb.cursor()
    
    tencentdb_cursor.execute(
        "SELECT COUNT(*) FROM l0_conversations WHERE recorded_at LIKE '2026-05-22%'"
    )
    tencentdb_count = tencentdb_cursor.fetchone()[0]
    print(f"TencentDB 中的 2026-05-22 记录: {tencentdb_count}")
    
    if existing_count >= tencentdb_count:
        print("✅ 所有记录已迁移，无需补全")
        return
    
    # 获取未迁移的记录
    tencentdb_cursor.execute(
        """
        SELECT record_id, session_key, session_id, role, message_text, recorded_at, timestamp
        FROM l0_conversations 
        WHERE recorded_at LIKE '2026-05-22%'
    """
    )
    
    records = tencentdb_cursor.fetchall()
    print(f"需要迁移的记录数: {len(records)}")
    
    migrated = 0
    for record in records:
        record_id, session_key, session_id, role, message_text, recorded_at, timestamp = record
        
        # 检查是否已存在（使用 log_id）
        mx_cursor.execute(
            "SELECT COUNT(*) FROM conversation_logs WHERE log_id = ?",
            (record_id,)
        )
        if mx_cursor.fetchone()[0] > 0:
            continue
        
        # 插入到 memoryx
        # memoryx 的 schema: log_id, session_id, role, content, created_at
        mx_cursor.execute(
            """
            INSERT INTO conversation_logs 
            (log_id, session_id, role, content, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (record_id, session_key, role, message_text, recorded_at)
        )
        migrated += 1
    
    mx_conn.commit()
    print(f"✅ 成功迁移 {migrated} 条记录")
    
    # 验证
    mx_cursor.execute(
        "SELECT COUNT(*) FROM conversation_logs WHERE created_at LIKE '2026-05-22%'"
    )
    total = mx_cursor.fetchone()[0]
    print(f"memoryx 中 2026-05-22 的总记录数: {total}")
    
    mx_conn.close()
    tencentdb.close()


if __name__ == "__main__":
    migrate_remaining_conversations()
