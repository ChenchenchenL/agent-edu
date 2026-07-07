# SKILL_AUTONOMY_SEQUENCE.md

## 文档定位

这份文档定义 `agent-edu` 的 skill 系统从当前的“受控硬编码 + 最小动态绑定”演进到“高度自主化自治能力系统”的实施顺序。

它回答四个问题：

- 先改什么
- 后改什么
- 哪些能力现在不能提前做
- 每个阶段做到什么程度才算完成

这不是最终架构全图，也不是实现细节文档。它是后续拆分 PR、排期和验收的顺序基线。

---

## 一、目标定义

目标不是把现有 `skill_name` 机制继续扩容，而是把系统升级为：

- 运行时按目标、上下文、证据和治理预算选择能力
- 高风险变更可以自动进入受限 sandbox 评测
- skill 可以依据 outcome signal 进行受限自治演化
- 用户可以导入外部教学 skill 包，并在治理链路下完成安装、评测、绑定和回滚

最终形态应满足：

1. runtime 不再要求上层先指定固定 `skill_name`
2. router 能在多个候选能力之间做排序、降级和回退
3. evolution 能自动完成 `proposal -> sandbox -> evaluation -> stage` 的受限闭环
4. activate / replace / privilege broaden 仍然受治理约束
5. 外部 skill 通过 package registry 管理，不允许“下载即启用”

---

## 二、当前系统的核心限制

当前 skill 系统的中心仍然是“人工定义可用 skill 集”，而不是“运行时自主选择能力”。

主要限制如下：

1. runtime 入口仍然要求传入 `skill_name`
2. resolver 仍按 `skill_name + surface` 查唯一 selectable artifact
3. binding resolver 只是 first-match filter，不是 candidate ranking
4. high-risk proposal 不能自动进入 sandbox
5. `patch_needed` / `merge_candidate` 仍是不可执行 recommendation
6. `tool_plan` 仍是硬编码白名单，不是策略模板层
7. explainability 只能解释结果，不能解释候选比较过程

因此，后续顺序不能从“开放外部下载 skill”开始，必须先把 runtime 和治理模型改对。

---

## 三、实施原则

### 1. 先改运行时抽象，再扩能力来源

如果运行时仍然是 `skill_name` 驱动，那么把外部 skill 加进来只会把硬编码问题扩散到更多来源。

### 2. 先分离 sandbox gate 和 activation gate

高风险变更可以自动评测，但不能自动上线。这两类决策必须拆开。

### 3. 不开放任意工具编排

不引入通用 DAG 自由编排。运行时只能在“批准模板集合”里选和填参。

### 4. 先做内建候选源自治，再做外部生态

先让 builtin / staged / active / baseline fallback 这几类来源能被统一路由，再接 package import。

### 5. explainability 必须同步建设

自治强度一旦上升，没有 drill-down 解释链路，系统就不可运营。

---

## 四、推荐实施顺序

### Phase 0：冻结目标和术语

目标：

- 统一后续实现中对 `skill`、`capability`、`artifact`、`binding`、`router`、`package` 的定义

本阶段输出：

- 本文档
- 后续实现所依赖的术语表与输入输出契约草案

完成标准：

- 后续 PR 不再新增彼此冲突的 runtime 词汇
- “名字驱动 skill” 与 “能力驱动 capability” 的边界被明确记录

---

### Phase 1：把 runtime 从 `skill_name` 驱动升级为 `CapabilityRequest` 驱动

目标：

- 让运行时可以按任务目标请求能力，而不是先指定某个 skill 名字

建议新增对象：

- `CapabilityRequest`
- `CapabilityCandidate`
- `CapabilitySelection`

`CapabilityRequest` 建议输入字段：

- `learner_goal_id`
- `surface`
- `topic_key`
- `task_type`
- `trigger_source`
- `risk_budget`
- `tenant_policy_id`

`CapabilitySelection` 建议输出字段：

- `selected_artifact_id`
- `selected_capability`
- `reason_codes`
- `fallback_chain`
- `confidence`
- `tool_plan_template_id`

本阶段输出：

- 新的 runtime 路由契约
- 兼容旧接口的桥接层
- 旧 `skill_name` 调用路径逐步转为内部适配

完成标准：

- 上层业务至少有一条主路径不再直接传固定 `skill_name`
- 旧接口仍可工作，但只作为兼容桥

禁止提前做的事：

- 不在这一阶段开放外部下载 skill
- 不在这一阶段开放任意 tool DAG

---

### Phase 2：引入真正的 `SkillRouterService`

目标：

- 从“first-match binding”升级为“多候选排序 + 置信度 + 降级”

候选来源最少支持：

- active artifact
- staged artifact shadow / probe
- tenant-installed external artifact
- baseline builtin fallback

排序信号最少支持：

- topic coverage
- surface compatibility
- learner mastery band
- recent usage outcome
- failure rate
- trust level
- rollback pressure

本阶段输出：

- `SkillRouterService`
- candidate ranking 结果对象
- fallback chain 和 loser reason 记录

完成标准：

- runtime explain 可展示 winner 与主要淘汰原因
- 低置信度时会自动降级到 baseline，而不是硬上候选 skill

禁止提前做的事：

- 不允许模型自由发明候选
- 不允许绕过现有 artifact/readiness/governance 状态

---

### Phase 3：拆开 sandbox admission 和 activation governance

目标：

- 允许 high-risk proposal 自动进入更严格的 sandbox
- 继续禁止 high-risk proposal 自动激活到生产

需要拆开的治理动作：

- `sandbox_admission`
- `evaluation`
- `stage`
- `activate`
- `replace`
- `broaden_scope`
- `privilege_change`

治理原则：

- 自动 sandbox 可以更严格
- 自动 stage 可以有限开放
- 自动 activate 必须继续受 readiness / blast radius / privilege delta 约束

本阶段输出：

- 独立的 sandbox 准入策略
- 独立的 activation / replacement 策略
- high-risk 的受限资源策略

完成标准：

- high-risk proposal 可以自动排队进 sandbox
- high-risk proposal 默认不能自动 activate / replace_selectable

---

### Phase 4：把 curator recommendation 升级成受限自治执行器

目标：

- 让 curator 不只会“建议”，而是能完成受限治理动作

最小自治闭环：

1. auto-create proposal
2. auto-enqueue sandbox
3. auto-run evaluation
4. auto-stage trusted low/medium risk artifact

需要从不可执行变为受限可执行的 recommendation：

- `patch_needed`
- `merge_candidate`

仍然保留人工 gate 的动作：

- activate
- replace current selectable
- broaden tenant scope
- add privileged tool permission

本阶段输出：

- curator 执行状态机
- recommendation 到 proposal 的自动转化
- 失败后的挂起、压制、回滚原因码

完成标准：

- curator 能把合格 recommendation 自动推进到 sandbox/eval/stage
- 高风险或高 blast radius 的动作仍停在人工 gate

---

### Phase 5：把 `tool_plan` 升级为策略驱动模板系统

目标：

- 维持治理边界，同时摆脱当前模块常量式硬编码

建议三层结构：

1. `ToolCapability`
2. `SurfacePolicy`
3. `PlanTemplate`

职责定义：

- `ToolCapability`：工具能力分类、schema、输出引用规则
- `SurfacePolicy`：每个 surface 可调用哪些 capability、步数上限、变量范围、是否允许读前一步输出
- `PlanTemplate`：由 skill artifact 提供候选模板，runtime 只负责选择和变量填充

本阶段输出：

- 模板化 tool plan 契约
- 模板选择器
- policy 校验器

完成标准：

- runtime 不再依赖硬编码常量表定义全部合法 sequence
- 模型仍然不能自由生成任意 plan

禁止提前做的事：

- 不开放任意外部 HTTP/tool capability
- 不开放无审计的模板变量扩展

---

### Phase 6：建立外部 skill package registry 和安装链路

目标：

- 让用户可以导入外部热门教学 skill，但整个过程受包管理和治理模型约束

外部 skill package 最少应包含：

- manifest
- provider / version / provenance
- surface / capability / topic scope
- directives contract
- input / output schema
- tool permission profile
- sandbox eval bundle
- compatibility range
- signature / hash
- suppress / rollback / kill switch metadata

安装流程：

1. import
2. verify
3. normalize
4. sandbox
5. evaluate
6. stage
7. bind

默认禁止：

- 下载后直接 selectable
- 未验签直接安装
- 未评测直接参与 runtime 选择
- 外部包自行扩权

本阶段输出：

- package manifest schema
- import/install service
- provenance / signature verification
- tenant-level install / uninstall / suppress / rollback API

完成标准：

- 用户可安装外部教学 skill 包
- 外部 skill 包必须先经过治理链路才可进入 runtime candidate set

---

### Phase 7：补齐 outcome feedback loop

目标：

- 让 skill 真正根据效果变化自己的路由权重和演化节奏

核心 outcome signal：

- learner completion
- correction rate
- quiz uplift
- replan success
- runtime failure
- operator suppress / restore
- memory conflict pressure

这些 signal 需要反推：

- routing weight
- patch trigger
- merge trigger
- demotion trigger
- suppression trigger

本阶段输出：

- 统一 outcome signal 模型
- route weight update 逻辑
- curator trigger 策略

完成标准：

- 新旧候选 skill 的优先级会随效果变化
- 表现差的 skill 可被自动降权或压制

---

### Phase 8：补齐 explainability 和 operator drill-down

目标：

- 让每次 runtime 选择都可被解释、审计和回放

至少要能回答：

- 为什么选它
- 为什么没选另一个
- 使用了哪些 evidence
- 当前 confidence 是多少
- 是否走了 fallback
- 如果失败，降级到了什么

本阶段输出：

- router explain API
- candidate comparison 视图
- fallback trace
- rollout / suppression / replacement drill-down

完成标准：

- operator 可以查看某次实际选择的完整解释链
- explain 输出足以支撑运营排障和治理复盘

---

## 五、不推荐的错误顺序

下面这些做法会让系统更乱，不应先做：

1. 先做“外部 skill 下载市场”，再改 runtime
2. 先开放任意 tool DAG，再补治理
3. 先让 high-risk proposal 自动 activate，再拆 sandbox gate
4. 先把更多名字注册到 skill registry，再改 capability 抽象
5. 先做 UI 市场和推荐页，再补 package verification

这些路径的问题都是同一个：把表面能力做大，但没有先改运行时和治理中心。

---

## 六、建议的第一批实施范围

如果接下来只做一轮高价值改造，建议范围限制在：

1. `CapabilityRequest` / `CapabilitySelection` 契约
2. `SkillRouterService`
3. runtime explain 的候选比较输出
4. sandbox admission 与 activation governance 解耦

这四项完成后，系统才真正进入“能力路由 + 受限自治”的轨道。

在这之前，不建议启动“用户下载热门 skill 自主配置”的产品面能力。

---

## 七、验收口径

当以下条件同时成立时，可以认为 skill 系统开始具备“高度自治化”的基础：

1. runtime 入口不再依赖固定 `skill_name`
2. 存在多候选 ranking 和置信度降级
3. high-risk proposal 可以自动进入受限 sandbox
4. curator 可自动推进 proposal 到 sandbox/eval/stage
5. tool plan 由策略模板控制，而不是硬编码常量表
6. 外部 skill 包必须经过 verify + sandbox + evaluate + stage
7. operator 能解释一次 skill 选择和一次失败降级

只满足其中一两项，不应宣称系统已经实现“自主技能系统”。

