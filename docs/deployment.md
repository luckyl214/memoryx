# 部署指南

## 生产环境部署

### 系统要求

| 资源 | 最低配置 | 推荐配置 |
|------|----------|----------|
| CPU | 2 核 | 4 核 |
| 内存 | 2GB | 4GB |
| 磁盘 | 10GB | 50GB |
| Python | 3.11+ | 3.12 |

### 1. 安装

```bash
# 克隆仓库
git clone https://github.com/lucky99/memoryx.git
cd memoryx

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑配置
vim .env
```

**必要配置**：

```env
# Embedding API（必需）
MEMORYX_EMBEDDING_ENDPOINT=https://api.siliconflow.cn/v1/embeddings
MEMORYX_EMBEDDING_API_KEY=your_api_key
MEMORYX_EMBEDDING_MODEL=Qwen/Qwen3-Embedding-8B

# 数据库（可选，默认自动创建）
MEMORYX_DB_PATH=./memoryx.db

# 向量存储（可选，默认自动创建）
MEMORYX_VECTORS_PATH=./data/vectors.json
```

### 3. 初始化

```bash
# 创建数据库
python3 scripts/init_db.py

# 验证安装
python3 scripts/verify_memoryx.py
```

### 4. 运行服务

```bash
# 开发模式
python3 -m memoryx.server --dev

# 生产模式
python3 -m memoryx.server --prod
```

### 5. Systemd 服务（Linux）

```bash
# 创建服务文件
sudo tee /etc/systemd/system/memoryx.service > /dev/null <<EOF
[Unit]
Description=Mnemosyne-X Memory Service
After=network.target

[Service]
Type=simple
User=memoryx
WorkingDirectory=/opt/memoryx
Environment="PATH=/opt/memoryx/.venv/bin"
ExecStart=/opt/memoryx/.venv/bin/python -m memoryx.server --prod
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# 启动服务
sudo systemctl daemon-reload
sudo systemctl enable memoryx
sudo systemctl start memoryx

# 查看状态
sudo systemctl status memoryx
```

---

## Hermes Agent 集成

### 方案 A：hooks 集成（推荐）

```bash
# 1. 复制 hooks
cp hooks/pre_response.sh ~/.hermes/hooks/
cp hooks/post_response.sh ~/.hermes/hooks/
chmod +x ~/.hermes/hooks/*.sh

# 2. 复制技能
cp -r skills/memoryx ~/.hermes/skills/

# 3. 添加到 PINNED_SKILLS
# 编辑 ~/.hermes/skills/PINNED_SKILLS.json，添加 "memoryx"

# 4. 重启 Gateway
hermes gateway restart

# 5. 验证
hermes "搜索关于用户的记忆"
```

### 方案 B：插件集成

```python
# 在 Hermes 插件中使用
from memoryx.hermes_adapter import MemoryXHermesAdapter

adapter = MemoryXHermesAdapter(
    db_path="/path/to/memoryx.db",
    embedding_endpoint="https://api.example.com/embeddings",
    embedding_api_key="your_api_key"
)

# 对话前：注入相关记忆
context = await adapter.get_context(user_query, session_id)

# 对话后：存储重要信息
await adapter.store_from_response(query, response)
```

---

## 数据迁移

### 从 TencentDB 迁移

```bash
python3 scripts/migrate_tencentdb_to_memoryx.py
```

### 从原生记忆系统迁移

```bash
python3 scripts/migrate_native_to_memoryx.py
```

### 从其他系统迁移

```bash
python3 scripts/migrate.py --from mem0 --to memoryx --source /path/to/mem0.db
```

支持迁移的系统：
- TencentDB
- Mem0
- Letta
- Zep
- Cognee
- Hindsight
- GBrain
- JSON 文件

---

## 备份与恢复

### 备份

```bash
# 完整备份
python3 scripts/backup.py --full --output ./backups/

# 增量备份
python3 scripts/backup.py --incremental --output ./backups/
```

### 恢复

```bash
# 从备份恢复
python3 scripts/restore.py --backup ./backups/memoryx_20260522.tar.gz
```

---

## 监控

### 健康检查

```bash
# 运行健康检查
python3 scripts/health_check.py

# 输出示例
✓ Database: OK
✓ Embedding API: OK (latency: 45ms)
✓ Vector Store: OK (10 vectors)
✓ Memory Count: 34
✓ Disk Usage: 2.3GB / 50GB
```

### 日志

```bash
# 查看日志
tail -f logs/memoryx.log

# 查看错误日志
tail -f logs/error.log
```

---

## 性能调优

### 数据库优化

```sql
-- 分析查询
EXPLAIN QUERY PLAN SELECT * FROM memories WHERE content MATCH '用户偏好';

-- 重建索引
REINDEX;

-- 清理碎片
VACUUM;
```

### 向量优化

```python
# 批量嵌入（减少 API 调用）
vectors = await embedding_manager.embed_texts(batch_texts)

# 启用缓存
embedding_manager.enable_cache(max_size=1000)
```

### 检索优化

```python
# 使用增量检索
results = await engine.search(query, progressive=True)

# 限制返回字段
results = await engine.search(query, fields=["memory_id", "content", "memory_type"])
```

---

## 故障排除

### 问题：Embedding API 超时

**原因**：网络问题或 API 限流

**解决方案**：
```bash
# 检查网络
curl -I https://api.siliconflow.cn

# 增加超时
MEMORYX_EMBEDDING_TIMEOUT=30
```

### 问题：数据库锁定

**原因**：并发写入过多

**解决方案**：
```bash
# 检查连接
sqlite3 memoryx.db "PRAGMA lock_status;"

# 增加超时
MEMORYX_DB_TIMEOUT=30
```

### 问题：内存占用过高

**原因**：缓存未清理

**解决方案**：
```bash
# 清理缓存
python3 scripts/cleanup.py --cache
```
