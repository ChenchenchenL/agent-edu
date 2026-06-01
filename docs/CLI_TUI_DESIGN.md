# CLI / TUI 设计说明

## 文档定位

本文说明 `agent-edu` 当前的 CLI-first 产品落地方向，以及 TUI 如何挂接现有后端能力。

它回答的问题是：

> 为什么先做终端工作台、怎么运行、当前已经落地到什么程度。

---

## 一、当前设计结论

当前用户表面优先级：

1. `agent-edu` CLI
2. `agent-edu tui`
3. 后续 QQ / 微信等外部接入
4. Web 端放后续

原因：

- 当前后端已经有稳定的 session / goal / task / memory / workflow API
- CLI/TUI 可以最快复用这些边界，形成可长期使用的学习工作台
- 后续新接入面不应重复业务逻辑，只应复用同一个应用层 contract

---

## 二、运行模式

当前 CLI / TUI 采用 dual mode，但不是两套业务实现。

统一策略：

- remote mode：通过 HTTP 访问已启动的 FastAPI 服务
- embedded mode：进程内挂载 FastAPI ASGI app，再通过同一个 HTTP client contract 调用

这意味着：

- CLI / TUI
- 未来 QQ / 微信 connector
- 后续自动化工具

都可以复用同一组 API 语义，而不是分别直连 service / repository。

---

## 三、当前已落地能力

### 1. CLI 命令入口

已提供安装入口：

```bash
agent-edu ...
```

当前命令面：

```text
agent-edu doctor
agent-edu profile list
agent-edu goal list
agent-edu goal select
agent-edu task today
agent-edu task execute
agent-edu task status
agent-edu session resume
agent-edu memory search
agent-edu memory browse
agent-edu tui
```

输出模式：

- 默认 human-readable
- `--json`
- `--quiet`

### 2. 本地上下文

CLI 会保存本地上下文：

- active profile
- active goal
- last session
- last task
- refresh interval

默认文件：

```text
~/.agent-edu/config.json
```

测试或临时环境可用：

```text
AGENT_EDU_CLI_CONFIG_PATH
```

### 3. TUI 最小工作台

当前 TUI 是 learner-first 终端工作台，默认围绕：

```text
active profile -> active goal -> today task -> bound session
```

当前界面信息面：

- 左侧：当前 profile / goal / today tasks / review queue
- 中间：当前 session transcript 与输入框
- 右侧：long-term memory 摘要与最近 workflow

当前支持的主要 slash command：

- `/refresh`
- `/today`
- `/task <n>`
- `/done`
- `/skip`
- `/hint`
- `/session`
- `/memory`

---

## 四、为 TUI 补齐的 API 面

为了让 TUI 不自己拼数据，后端新增了：

- workspace summary endpoint
- filtered task listing
- knowledge memory browse endpoint
- behavior memory browse endpoint

这样 TUI 可以直接消费：

- 当前目标
- active plan
- 今日任务
- review 队列
- 最近 workflow
- 最近 session
- read-only long-term memory 摘要

---

## 五、当前边界

当前 CLI / TUI 仍然是最小可用版本，不是最终形态。

还未完成：

- 更完整的 TUI 任务导航与快捷键体系
- quiz / review / assessment 的更强交互流
- TUI 内 operator 治理写操作
- 后台定时任务驱动的真正长期自治体验
- QQ / 微信 connector
- Web 端

当前原则保持不变：

> UI/CLI 不直接碰数据库，不复制业务逻辑，只复用应用层 API contract。
