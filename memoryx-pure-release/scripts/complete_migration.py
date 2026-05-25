#!/usr/bin/env python3
"""
补全迁移：用户画像、entities、relations
"""
LEGACY_SCHEMA_MIGRATION = True  # exempt from source_schema_consistency checks

import sqlite3
import json
import hashlib
import uuid
from pathlib import Path
from datetime import datetime, timezone
# 路径配置（使用相对路径，自动解析）
SCRIPT_DIR = Path(__file__).parent.resolve()
MEMORYX_DIR = SCRIPT_DIR.parent  # scripts/ -> memoryx/
MEMORYX_DB = MEMORYX_DIR / "memoryx.db"
DATA_DIR = MEMORYX_DIR / "data"
TENCENTDB_DIR = Path(os.getenv("TENCENTDB_DIR", ""))  # 需手动配置

def checksum(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

def uuid4_hex() -> str:
    return uuid.uuid4().hex

def migrate_persona_and_entities() -> dict:
    """迁移用户画像和实体关系"""
    result = {"persona": False, "entities": 0, "relations": 0, "errors": []}
    
    print("\n【补全：用户画像 + entities + relations】")
    
    if not MEMORYX_DB.exists():
        print("   ❌ memoryx 数据库不存在")
        return result
    
    conn = sqlite3.connect(str(MEMORYX_DB))
    conn.execute("PRAGMA foreign_keys=ON")
    
    persona_file = TENCENTDB_DIR / "persona.md"
    if not persona_file.exists():
        print("   ⚠️ persona.md 不存在")
        return result
    
    try:
        with open(persona_file, "r", encoding="utf-8") as f:
            content = f.read()
        
        memory_id = "example_user"
        
        # 检查是否已存在
        existing = conn.execute(
            "SELECT memory_id FROM memories WHERE memory_id = ?",
            (memory_id,)
        ).fetchone()
        
        if existing:
            print("   ⏭️ 用户画像已存在，更新内容...")
            conn.execute("""
                UPDATE memories SET 
                    content = ?, 
                    checksum = ?,
                    updated_at = ?
                WHERE memory_id = ?
            """, (content, checksum(content), datetime.now(timezone.utc).isoformat(), memory_id))
        else:
            # 插入用户画像记忆
            conn.execute("""
                INSERT INTO memories (
                    memory_id, memory_type, content, importance_score, confidence_score,
                    decay_score, recency_score, access_count, checksum, active_state,
                    scope, entities_json, tags_json, category, layer, source, valid_from, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                memory_id,
                "PERSONA",
                content,
                1.0,
                1.0,
                0.0,
                1.0,
                0,
                checksum(content),
                1,
                "global",
                "[]",
                json.dumps(["persona", "user_profile"], ensure_ascii=False),
                "user",
                "long_term",
                "tencentdb",
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
            ))
            print("   ✅ 用户画像已插入")
        
        result["persona"] = True
        
        # 插入 entities
        entities = [
            ("entity-用户", "用户", "user", {"is_primary": True}),
            ("entity-用户", "用户", "legal_name", {}),
            ("entity-用户", "用户", "pen_name", {}),
            ("entity-memoryx", "memoryx", "project", {"type": "cognitive_memory_system"}),
            ("entity-TencentDB", "TencentDB", "project", {"type": "agent_memory"}),
        ]
        
        for entity_id, name, etype, meta in entities:
            existing = conn.execute(
                "SELECT entity_id FROM entities WHERE entity_id = ?",
                (entity_id,)
            ).fetchone()
            
            if not existing:
                conn.execute("""
                    INSERT INTO entities (
                        entity_id, entity_name, entity_type, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    entity_id,
                    name,
                    etype,
                    json.dumps(meta, ensure_ascii=False),
                    datetime.now(timezone.utc).isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                ))
                result["entities"] += 1
        
        print(f"   ✅ 实体插入: {result['entities']} 个")
        
        # 插入 relations
        relations = [
            ("rel-main-penname", "entity-用户", "entity-用户", "alias", 1.0),
            ("rel-main-legal", "entity-用户", "entity-用户", "legal_name_of", 1.0),
            ("rel-user-memoryx", "entity-用户", "entity-memoryx", "developer", 0.9),
            ("rel-memoryx-tencentdb", "entity-memoryx", "entity-TencentDB", "replaces", 0.8),
        ]
        
        for rel_id, src, tgt, rel_type, weight in relations:
            existing = conn.execute(
                "SELECT relation_id FROM relations WHERE relation_id = ?",
                (rel_id,)
            ).fetchone()
            
            if not existing:
                conn.execute("""
                    INSERT INTO relations (
                        relation_id, source_entity_id, target_entity_id, relation_type, weight, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    rel_id,
                    src,
                    tgt,
                    rel_type,
                    weight,
                    datetime.now(timezone.utc).isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                ))
                result["relations"] += 1
        
        print(f"   ✅ 关系插入: {result['relations']} 个")
        
        # 审计日志
        conn.execute("""
            INSERT INTO audit_logs (audit_id, action, subject_id, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            uuid4_hex(),
            "complete_migration",
            "example_user",
            json.dumps({"entities": result["entities"], "relations": result["relations"]}, ensure_ascii=False),
            datetime.now(timezone.utc).isoformat(),
        ))
        
        conn.commit()
        
    except Exception as e:
        result["errors"].append(str(e))
        print(f"   ❌ 错误: {e}")
        conn.rollback()
    
    conn.close()
    return result

def verify_complete() -> dict:
    """验证完整迁移"""
    print("\n【完整验证】")
    
    conn = sqlite3.connect(str(MEMORYX_DB))
    
    stats = {}
    tables = ["memories", "episodic_memories", "conversation_logs", 
              "entities", "relations", "palace_drawers", "audit_logs"]
    
    for table in tables:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        stats[table] = row[0]
        print(f"   {table}: {row[0]} 条")
    
    # 记忆类型分布
    print("\n   记忆类型分布:")
    type_dist = conn.execute(
        "SELECT memory_type, COUNT(*) FROM memories GROUP BY memory_type"
    ).fetchall()
    for mem_type, count in type_dist:
        print(f"      {mem_type}: {count}")
    
    # 实体列表
    print("\n   实体列表:")
    entities = conn.execute(
        "SELECT entity_id, entity_name, entity_type FROM entities"
    ).fetchall()
    for eid, name, etype in entities:
        print(f"      {name} ({etype})")
    
    # 关系列表
    print("\n   关系列表:")
    relations = conn.execute(
        "SELECT r.relation_id, e1.entity_name || ' -> ' || e2.entity_name as path, r.relation_type, r.weight "
        "FROM relations r JOIN entities e1 ON r.source_entity_id = e1.entity_id JOIN entities e2 ON r.target_entity_id = e2.entity_id"
    ).fetchall()
    for rid, path, rel_type, weight in relations:
        print(f"      {path} [{rel_type}] ({weight})")
    
    conn.close()
    return stats

def main():
    print("="*70)
    print("🔄 补全迁移：用户画像 + entities + relations")
    print("="*70)
    
    migrate_persona_and_entities()
    verify_complete()
    
    print("\n" + "="*70)
    print("✅ 补全迁移完成！")
    print("="*70)

if __name__ == "__main__":
    main()
