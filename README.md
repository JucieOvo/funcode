# Funcode Python 迁移版

## 项目说明

该目录用于承载 Funcode 的 Python 版本实现，技术栈固定为：

1. LangChain `v1.0.8`
2. LangGraph `v1.0.1`
3. 默认模型 `deepseek-reasoner`

当前目录已提供 Python 工程底座、CLI 入口与配置解析层，后续子系统会继续在 `src/funcode/` 下补齐。

## 目录说明

```text
JS2PY/
├─ pyproject.toml
├─ README.md
└─ src/
   └─ funcode/
```

## 环境变量

默认从环境变量读取模型配置：

1. `DEEPSEEK_API_KEY`
2. `DEEPSEEK_BASE_URL`
3. `FUNCODE_MODEL`
4. `FUNCODE_REASONING_EFFORT`
5. `FUNCODE_DEFAULT_CWD`

## 使用方式

```powershell
python -m funcode.main run --prompt "请分析当前仓库"
```

```powershell
python -m funcode.main config
```

## 说明

该版本优先适配 Windows 11 运行环境，后续运行时、状态图、工具系统、子代理团队系统会继续补齐。
