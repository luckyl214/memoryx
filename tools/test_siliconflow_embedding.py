#!/usr/bin/env python3
"""验证 SiliconFlow embedding key 和模型连通性"""
import os, json, requests, sys
from pathlib import Path

# 从 .env 加载
env_path = Path('/home/lucky/memoryx/.env')
for line in env_path.read_text().split('\n'):
    if '=' in line and not line.startswith('#'):
        k, v = line.strip().split('=', 1)
        os.environ.setdefault(k, v)

api_key = os.getenv('SILICONFLOW_API_KEY') or os.getenv('MEMORYX_EMBEDDING_API_KEY')
model = os.getenv('MEMORYX_EMBEDDING_MODEL', 'Qwen/Qwen3-Embedding-0.6B')

if not api_key:
    print("❌ SILICONFLOW_API_KEY 未设置")
    sys.exit(1)

print(f"Model: {model}")
print(f"Key prefix: {api_key[:10]}...")
print(f"Key length: {len(api_key)}")

url = "https://api.siliconflow.cn/v1/embeddings"
payload = {"model": "Qwen/Qwen3-Embedding-0.6B", "input": ["MemoryX embedding health check"]}
headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

try:
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    print(f"Status: {r.status_code}")
    if r.status_code != 200:
        print(f"Error: {r.text[:300]}")
        sys.exit(1)
    data = r.json()
    vec = data["data"][0]["embedding"]
    dim = len(vec)
    non_zero = any(abs(x) > 1e-12 for x in vec)
    print(f"Dim: {dim}")
    print(f"Non-zero: {non_zero}")
    print(f"First 5 values: {vec[:5]}")
    if dim > 0 and non_zero:
        print("✅ SiliconFlow Qwen3 embedding API 正常")
        sys.exit(0)
    else:
        print("❌ Embedding 全零或空")
        sys.exit(1)
except requests.exceptions.RequestException as e:
    print(f"❌ 请求失败: {e}")
    sys.exit(1)
