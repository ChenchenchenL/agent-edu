# Hermes CLI / TUI 样式参考

## 文档定位

本文整理 `Hermes-Agent` 官方 CLI / TUI 的终端交互样式与组织形式，目的是为 `agent-edu` 后续 CLI-first 产品形态提供参考。

它回答的问题不是“教育智能体功能怎么做”，而是：

> 如果 `agent-edu` 先做 CLI，终端界面应该采用什么样的交互形式、信息布局和命令结构。

本文只复用 Hermes 的终端产品设计思路，不照搬其通用 agent 产品边界。

---

## 调研范围

调研日期：`2026-05-22`

主要参考来源：

- Hermes Agent CLI Guide:
  `https://hermes-agent.nousresearch.com/docs/user-guide/cli`
- Hermes Agent TUI Guide:
  `https://hermes-agent.nousresearch.com/docs/user-guide/tui`
- Hermes Agent CLI Commands Reference:
  `https://hermes-agent.nousresearch.com/docs/reference/cli-commands`
- Hermes Agent Skins Feature:
  `https://hermes-agent.nousresearch.com/docs/user-guide/features/skins`

---

## 一、Hermes 值得借鉴的 CLI 形态

### 1. 一个 runtime，两种终端表面

Hermes 不是只有一种“命令行”。

它实际上拆成两类入口：

- 经典 CLI：适合一次性命令、脚本调用、自动化流水线
- 交互式 TUI：适合持续对话、观察状态、在终端里长期使用

这点很关键。

对 `agent-edu` 来说，不应该把 CLI 理解成“只能敲一条命令然后退出”，而应该设计成：

- `agent-edu <subcommand>` 用于脚本化和运维化
- `agent-edu tui` 用于长期学习陪伴

### 2. 命令面与会话面分离

Hermes 的命令参考页体现出一个清晰边界：

- 配置、模型、provider、profile 这类是命令对象
- 长对话、交互、状态观察这类放到 TUI 里

这意味着 CLI 不应该把所有复杂交互都塞进参数。

对 `agent-edu` 更合理的做法是：

- 命令行负责 CRUD、调度、查询、自动化
- TUI 负责学习过程、教学反馈、任务推进、记忆查看

### 3. 自然语言输入和显式命令并存

Hermes TUI 不是纯按钮式终端，也不是纯自然语言黑箱。

它兼顾两种交互：

- 直接输入自然语言
- 使用 slash command / 明确命令切换动作

这对教育场景非常适合，因为学习交互本身就包含两类行为：

- “解释一下矩阵乘法” 这种自然语言学习请求
- “生成今日任务” “查看复习队列” 这种系统操作请求

因此 `agent-edu` 应该保留双通道：

- 对话输入
- 显式控制命令

### 4. 终端不是只有输出文本，还要展示状态

Hermes 的 TUI 指向的是“状态化终端”，不是“stdout 聊天”。

可借鉴的表现包括：

- 会话主区域
- 输入区域
- 状态栏
- 帮助 / 命令提示
- 当前模型 / provider / profile 提示
- 后台任务或工具执行反馈

对 `agent-edu` 来说，这一点比普通聊天更重要，因为学习体验高度依赖状态可见性：

- 当前学习目标是什么
- 今天还有几个任务
- 这个回答来自哪个教学模式
- 是否刚触发了复习安排
- 是否生成了新的 plan 版本

### 5. 样式层与 agent 行为层分离

Hermes 的 `skins` 设计说明一个很有价值的原则：

- 终端视觉与交互风格可以换
- 但核心能力、工具边界、运行时逻辑不应依赖某种皮肤

对 `agent-edu` 来说，这意味着：

- CLI/TUI 的“教学终端风格”可以有不同主题
- 但 goal / task / memory / audit / safety 的结构不能随皮肤变化

也就是说：

> 样式可以变，学习状态机和治理边界不能变。

---

## 二、Hermes CLI 形式中最适合 `agent-edu` 的部分

### 1. 命令树清晰，子命令对象稳定

Hermes 的命令参考体现了稳定的命令树思想。

`agent-edu` 也应该采用对象化子命令，而不是做一个“大一统聊天命令”。

建议基础命令树：

```text
agent-edu tui
agent-edu session ...
agent-edu chat ...
agent-edu quiz ...
agent-edu goal ...
agent-edu plan ...
agent-edu task ...
agent-edu review ...
agent-edu memory ...
agent-edu workflow ...
agent-edu autonomy ...
agent-edu observe ...
```

这里的重点不是命令数量，而是“每个对象是否稳定存在于领域模型中”。

### 2. 同时支持 human mode 和 automation mode

Hermes 的 CLI 思路天然适合两种使用方式：

- 人直接用
- 脚本 / 管道 / 自动化系统调用

`agent-edu` 也必须同时支持：

- 适合人读的终端输出
- 稳定 JSON 输出

建议输出模式：

- 默认：rich text / terminal-friendly
- `--json`：稳定机器输出
- `--quiet`：只返回结果主体

否则后续 scheduler、worker、回归测试和运维工具都会重复造接口。

### 3. TUI 应是“学习工作台”，不是单聊天室

Hermes 的 TUI 给人的启发是：终端可以是工作台。

对 `agent-edu`，建议 TUI 首页不是空聊天框，而是学习工作台：

- 顶栏：当前 learner / goal / active plan / provider
- 左栏：今日任务、待复习、最近 workflow
- 主栏：教学对话与任务执行
- 右栏：知识点掌握度、长期记忆摘要、最近反思提示
- 底栏：slash commands、状态、失败重试提示

这种结构比纯聊天更符合教育任务组织场景。

### 4. 会话恢复与历史回看必须是一级能力

Hermes 的 session-oriented 思路很值得借鉴。

`agent-edu` 已经有 session、goal、plan、task、workflow、memory。
CLI/TUI 必须把这些历史对象直接暴露出来，而不是只保留“当前一轮输入输出”。

建议一级操作：

- 恢复最近 session
- 切换 active goal
- 查看 plan 版本 diff
- 查看今日 task 历史
- 查看 memory evidence
- 查看最近 autonomy worker 执行记录

---

## 三、Hermes 适合借鉴的具体终端样式

### 1. 启动页形式

推荐形式：

- 简短 ASCII 标题
- 当前环境摘要
- 可继续的最近学习对象
- 常用命令提示

示例：

```text
agent-edu
Learner: default
Goal: Linear Algebra in 12 weeks
Plan: v4 active
Tasks today: 3 due / 1 review

Type a question, or use:
/today   /plan   /review   /quiz   /hint   /memory   /status
```

### 2. 回复块形式

Hermes 风格更接近“结构化终端响应”，不是无边界文本流。

教育终端建议每次回复显式展示：

- reply type：`explain` / `hint` / `quiz` / `plan` / `review`
- bound goal / task / session
- 是否使用了 memory / retrieval / tool
- 简洁正文
- 下一步动作建议

示例：

```text
[explain] session=s_123 task=t_456 memory=2 tool=none

矩阵乘法的本质是“线性变换的复合”……

Next:
- /quiz matrices --count 3
- /hint
- /task done
```

### 3. 状态栏形式

终端底部建议持续展示：

- current mode
- provider / model
- active goal
- due reviews
- worker status
- last audit outcome

这能显著降低“系统到底做了什么”的不透明感。

### 4. slash command 形式

Hermes 的混合控制方式值得直接借鉴。

对 `agent-edu`，建议第一批 slash commands：

```text
/today
/goal
/plan
/replan
/review
/quiz
/hint
/mastery
/memory
/session
/status
/help
```

这些命令都应映射到明确的应用服务，而不是在前端里拼逻辑。

---

## 四、哪些地方不要照搬 Hermes

### 1. 不要做成通用 agent 终端

`agent-edu` 的终端应该明显体现“学习任务组织”。

如果完全照抄 Hermes，很容易退化成：

- 一个可以调用很多能力的通用助手

而不是：

- 一个围绕目标、计划、任务、复习和掌握度组织学习的教育终端

### 2. 不要让工具调用盖过教学主链路

Hermes 更偏通用 agent runtime。

教育场景里，工具调用是支撑层，不应该成为主视觉中心。

CLI/TUI 的中心对象仍应是：

- learner goal
- study plan
- daily task
- review loop
- mastery signal

### 3. 不要把“皮肤”做成“人格”

Hermes 的 skins 很适合借鉴做外观层，但教育系统必须避免：

- 用外观和语气掩盖真实教学能力不足
- 用人格化包装代替可解释学习组织能力

所以外观主题可以后置，先把学习结构和可观测性做对。

---

## 五、`agent-edu` 的 CLI-first 设计建议

### 1. 产品表面建议

建议分两层：

- Layer 1: object CLI
  - 面向脚本、测试、调试、运维
- Layer 2: interactive TUI
  - 面向长期使用的学习终端

### 2. 第一版 CLI MVP 建议范围

先做这些最稳：

- `agent-edu tui`
- `agent-edu chat send`
- `agent-edu session create|list|get`
- `agent-edu goal create|list|get|update`
- `agent-edu plan get|list|replan`
- `agent-edu task today|list|done|skip|fail`
- `agent-edu memory list|inspect`
- `agent-edu workflow list|get`
- `agent-edu autonomy state|pause|resume`

先不要在第一版做过重的内容：

- 通用外部 tool marketplace
- 高自由度 agent scripting
- 复杂主题 / 皮肤系统
- 直接在 CLI 中暴露高风险反思 / 进化写操作

### 3. 第二版再补的部分

适合后续增强：

- review queue 视图
- mastery heatmap
- plan diff 视图
- memory evidence drill-down
- worker / scheduler live status
- operator review / governance 面板

---

## 六、最终结论

Hermes 最值得借鉴的，不是某个具体颜色或某个命令名，而是这套终端产品方法：

- 一个统一 runtime
- 两种交互表面：CLI + TUI
- 状态可见
- 命令对象稳定
- 自然语言和显式控制并存
- 视觉样式与核心能力边界分离

对 `agent-edu` 来说，最优解不是“做一个聊天命令行”，而是：

> 做一个以 `goal -> plan -> task -> review -> memory` 为核心对象的学习终端工作台。

这才符合教育智能体的长期演化方向。
