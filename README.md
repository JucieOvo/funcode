# Funcode

面向终端代理式编码工作流的 Python 运行时实现。  
项目采用 `LangChain v1.0.8` 与 `LangGraph v1.0.1`，重点落在可恢复的代理运行时、上下文分叉、团队协作状态面，以及带真实门控的任务编排。

它不是某个现有商业产品的直接镜像发布，也不宣称与任何原品牌存在官方关系。  
更准确的说法是：它参考了成熟终端代理产品中已经被验证有效的工作流哲学，并把其中适合 Python 生态的部分做成了独立实现。

## 当前进度

当前版本已经不再是概念验证，而是可以真实运行的第一版发布子集。

已完成：

1. Python 包结构、CLI 入口与配置加载。
2. `agent / subagent / swarm / agentteam` 四层核心运行时。
3. `spawn / send_input / wait / resume / close / start_background / interrupt` 生命周期。
4. 子代理上下文分叉、父子 run 继承、worktree 继承、工具范围继承。
5. transcript 与 replacement-state 的真实落盘、恢复与继续执行。
6. 团队任务的依赖门控、并发门控、阻塞态表达与快照可观测性。
7. LSP、MCP、权限上下文、会话与输出子系统的基础可用实现。

## 当前已全面对齐的部分

在当前发布范围内，下面这部分已经做到了语义层完整对齐：

1. `agent`
   代理定义、运行实例、持久化状态与生命周期管理。
2. `subagent`
   父子关系、fork 语义、恢复语义、transcript 与 replacement-state 连续性。
3. `swarm`
   团队、任务、邮箱、快照、状态对账。
4. `agentteam`
   依赖约束、并发约束、阻塞状态、单独调用可观测性。

如果只看这四层运行时，本项目已经从“接口存在”走到了“语义成立”。

## 当前未完成部分

仍在建设中的部分主要有三类：

1. 完整前端交互层
   目前以可运行 CLI 为主，不追求完整复现某个成熟产品的全部交互外壳。
2. 更广泛的命令矩阵与边缘能力
   部分高阶命令、扩展工具、外围管理能力仍在逐步补齐。
3. 更完整的发布打磨
   例如更细的测试矩阵、更多平台验证、更多示例与说明文档。

因此，当前最适合的定位不是“全功能替代品”，而是：

**一套已经具备核心运行时能力的 Python 代理编码底座。**

## 适合谁使用

这个项目更适合以下场景：

1. 想在 Python 生态中研究代理运行时设计的人。
2. 需要多代理、子代理、团队编排能力的工程实验环境。
3. 希望在 LangChain + LangGraph 基础上继续演化终端代理工作流的人。

## 技术基线

当前固定基线如下：

1. LangChain `v1.0.8`
2. LangGraph `v1.0.1`
3. 默认模型 `deepseek-reasoner`
4. 优先适配 Windows 11

## 目录

```text
JS2PY/
├─ pyproject.toml
├─ README.md
├─ RELEASE_FUNCODE.md
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

## 基本使用

```powershell
python -m funcode.main help
```

```powershell
python -m funcode.main run --prompt "请分析当前仓库"
```

## 边界说明

本项目当前对外公开的介绍会刻意避免直接绑定特定品牌名称。  
这不是为了遮掩来源，而是为了明确边界：

1. 这里只介绍本项目自身已经实现的能力。
2. 不宣称与任何原品牌存在授权、隶属或官方兼容关系。
3. 对齐描述只针对运行时语义和工作流思想，不针对品牌身份。
