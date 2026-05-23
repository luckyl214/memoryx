#!/bin/bash
set -e

echo "=========================================="
echo "  Mnemosyne-X — 认知记忆系统安装"
echo "=========================================="

PYTHON=${PYTHON:-python3}
echo "[1/5] 检查 Python 环境..."
if ! command -v $PYTHON &> /dev/null; then
    echo "❌ 未找到 Python3，请先安装 Python 3.9+"
    exit 1
fi
echo "  Python 版本: $($PYTHON --version)"

echo "[2/5] 创建虚拟环境..."
if [ ! -d ".venv" ]; then
    $PYTHON -m venv .venv
    echo "  ✅ 虚拟环境已创建"
else
    echo "  虚拟环境已存在"
fi
source .venv/bin/activate

echo "[3/5] 安装依赖..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "  ✅ 依赖安装完成"

echo "[4/5] 创建数据目录..."
mkdir -p db logs cache archive exports markdown
echo "  ✅ 数据目录已创建"

echo "[5/5] 验证安装..."
.venv/bin/python -c "import memoryx; print('  ✅ memoryx 加载成功，版本:', getattr(memoryx, '__version__', 'dev'))"

echo ""
echo "=========================================="
echo "  🎉 安装完成！"
echo "=========================================="
echo ""
echo "配置:  编辑 .env 填入 API 密钥"
echo "运行:   source .venv/bin/activate"
echo "测试:   pytest -q"
echo ""
