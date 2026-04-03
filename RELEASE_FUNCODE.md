# Funcode 发布子集与推送准备

作者：JucieOvo  
日期：2026-04-03

## 1. 发布目标

将 `JS2PY` 目录中的 Python 实现发布到：

- `https://github.com/JucieOvo/funcode`

目标是发布子集干净、最小、可运行，并且不携带本地验证垃圾目录。

## 2. 发布子集建议

建议保留：

1. `pyproject.toml`
2. `README.md`
3. `.gitignore`
4. `src/funcode/`
5. `src/tests/`（如需同时发布测试）

建议排除：

1. `tmp_*/` 全部临时验证目录
2. `tmp_js_bridge*` 全部临时文本
3. 运行时缓存目录：`.*code_py/`、`src/.*code_py/`、`**/.*-code-py/`、`**/.*_code_py/`
4. `dist/`
5. `docs/`（当前文档包含大量历史迁移内容，不建议进入首版发布）

## 3. 发布前检查清单

在发布目录执行：

1. 编译检查：`python -m py_compile` 指向 `src/funcode` 关键入口文件
2. 入口检查：`python -m funcode.main help`
3. 文本残留检查：按已确认的统一替换规则，确保发布子集不包含旧品牌关键词
4. 路径残留检查：确保发布子集中不存在旧品牌命名目录

## 4. 非交互推送步骤

建议使用独立发布目录，避免误带主仓库其他文件：

1. 创建发布目录：例如 `F:\funcode-release`
2. 仅复制“建议保留”条目到该目录
3. 在发布目录执行：
   - `git init`
   - `git add .`
   - `git commit -m "chore: initial funcode python release subset"`
4. 绑定目标远端并推送：
   - `git remote add origin https://github.com/JucieOvo/funcode.git`
   - `git branch -M main`
   - `git push -u origin main`

## 5. 当前阻塞点

当前环境无法连通目标仓库地址，远端连通验证失败（网络连接失败）。  
因此目前可完成“发布整理与推送准备”，但无法在本机完成最终远端推送验证。

