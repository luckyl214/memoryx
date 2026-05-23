# Contributing to Mnemosyne-X

我们欢迎任何形式的贡献。以下是参与指南。

## 开发准则

本项目遵循 **Karpathy Guidelines**：

1. **Think Before Coding** — 编码前先暴露假设，不要猜
2. **Simplicity First** — 只解决当前问题，不做推测
3. **Surgical Changes** — 只改必须改的，不顺便优化无关部分
4. **Goal-Driven** — 定义可验证目标，先测试后实现

## 开发流程

1. Fork 本仓库
2. 创建特性分支: `git checkout -b feature/your-feature`
3. 编写测试（先红后绿）
4. 实现最小代码使测试通过
5. 运行全量回归: `pytest -q`
6. 提交 PR

## 测试规范

```bash
# 运行全部测试
pytest -q

# 运行定向测试
pytest -q tests/test_your_module.py

# 确保所有测试通过后再提 PR
```

## 代码风格

- Python 3.11+ type hints 必须
- async/await 优先
- 无 ORM，无重量级框架
- 所有 API 调用必须 retry + timeout + backoff
- 所有 IO 必须 async

## 模块结构

每个新模块需包含：

```
module/
├── __init__.py    # 导出
├── engine.py      # 主实现
├── models.py      # 数据模型（如需要）
└── tests/
    └── test_module.py
```

## 提问/报告 Issue

请提供：
- 复现步骤
- 预期行为 vs 实际行为
- 错误日志（如有）
