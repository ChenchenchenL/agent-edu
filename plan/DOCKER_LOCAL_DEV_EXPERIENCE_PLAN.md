# Docker 与本地开发体验收口执行计划

## 1. 文档定位

本文档用于指导 `agent-edu` 收口 `### 9. Docker 与本地开发体验收口`，把当前“能跑起来但不够清晰”的开发与验证路径，整理成一套新开发者可重复执行、可排错、可验证的标准工作流。

本计划不是为了追求一套花哨的 DevOps 平台，也不是为了把所有开发模式都兼容到底，而是要回答三个直接问题：

1. 当前仓库的 Docker 拓扑到底是什么。
2. 前端、后端、worker 在本地应该如何组合启动。
3. 当页面一直转圈、API 不通、worker 不跑、migration 失败时，开发者应该按什么顺序排查。

本文档只负责：

- Docker 启动与 smoke 验证路径
- 前端 API base URL / proxy / backend health 说明
- 常见问题的启动与排错收口
- 本地开发与 Docker 开发模式的边界定义

与其他计划的关系：

- MVP 验证基线以 [plan/MVP_VALIDATION_BASELINE_PLAN.md](/home/cl/agent-edu/plan/MVP_VALIDATION_BASELINE_PLAN.md) 为主。
- 运行保护与告警基线以 [plan/COST_RATE_LIMIT_CIRCUIT_BREAKER_ALERTING_PLAN.md](/home/cl/agent-edu/plan/COST_RATE_LIMIT_CIRCUIT_BREAKER_ALERTING_PLAN.md) 为主。
- Web-first 产品表面与 operator drill-down 不在本文档中定义，分别以 `docs/AGENT_EDU_MVP_GAPS.md` 与 [plan/OPERATOR_DETAIL_GOVERNANCE_PLAN.md](/home/cl/agent-edu/plan/OPERATOR_DETAIL_GOVERNANCE_PLAN.md) 为主。

优先级：

1. 先把真实启动拓扑写清楚，再谈优化体验。
2. 先把“可重复验证”收口，再谈全容器化前端。
3. 先把 blank spinner、API 不通、worker 不跑、migration 失败这些高频故障变成可诊断问题。
4. 先减少文档漂移，再增加更多启动模式。

## 2. 当前状态判断

当前仓库并不是没有 Docker 和本地开发能力，而是能力已经存在，但缺统一入口、缺清晰口径、缺 frontend integration 的标准化说明。

### 2.1 当前 Docker 拓扑是 backend-first，不是 full-stack

当前 `docker compose` 启动的是：

- `api`
- `worker`
- `postgres`
- `redis`
- `prometheus`
- `grafana`
- `tester`

对应文件：

- [compose.yaml](/home/cl/agent-edu/compose.yaml)
- [compose.override.yaml](/home/cl/agent-edu/compose.override.yaml)

关键事实：

1. 当前 compose 默认不包含 `frontend` 服务。
2. `api` 容器启动命令里已经执行 `alembic upgrade head`。
3. `worker` 依赖 `api` healthy 后才启动。
4. `prometheus` / `grafana` 使用 profile，不是默认启动。

现状结论：

- 当前 Docker 栈本质上是 backend stack，不是“一条命令起完整 Web 产品”。
- 如果开发者只执行 `make dev-up`，不会自动得到浏览器可访问的前端服务。

这是当前最核心的认知落差之一。

### 2.2 当前 README 与实际仓库存在明显漂移

当前文档存在多处漂移：

- [README.md](/home/cl/agent-edu/README.md)
  - 写了 `cp .env.example .env`
  - 但仓库中并不存在 `.env.example`
- [README.md](/home/cl/agent-edu/README.md)
  - 结尾混入了一段 API 日志与中文报错
- [packages/frontend/README.md](/home/cl/agent-edu/packages/frontend/README.md)
  - 仍是默认 Vite 模板说明
  - 并未描述本仓库的前端启动方式
- [docs/DOCKER_VALIDATION.md](/home/cl/agent-edu/docs/DOCKER_VALIDATION.md)
  - 已覆盖 API blackbox、real provider、observability
  - 但没有覆盖前端启动、代理和 browser-side smoke

现状结论：

1. 当前文档无法作为新开发者的唯一启动入口。
2. “前端怎么起、是否在 Docker 里、如何连后端”仍需靠阅读源码和试错。

### 2.3 当前前端接入方式是本地 Vite 代理，不是容器内直连

当前前端接入事实：

- [packages/frontend/vite.config.ts](/home/cl/agent-edu/packages/frontend/vite.config.ts)
  - dev server 通过 `/api` 代理到 `VITE_API_PROXY_TARGET`
  - 默认目标是 `http://localhost:8000`
- [packages/frontend/src/api/client.ts](/home/cl/agent-edu/packages/frontend/src/api/client.ts)
  - dev 模式 API base 默认是 `/api/v1`
  - prod 模式默认是 `http://localhost:8000/api/v1`
  - transport timeout 是 `60s`
- [packages/agent_core/src/agent_core/api/app.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/api/app.py)
  - CORS 当前只允许 `http://localhost:5173`

现状结论：

1. 当前仓库默认假设前端是“本地 Vite dev server + 代理到本机 8000 API”。
2. 如果开发者换端口、改 host、直接预览构建产物、或未来把前端容器化，当前配置并不自解释。
3. “前端一直转圈”通常不是前端容器没起，而是：
   - 后端 8000 不可达
   - Vite proxy target 不对
   - API health 不通过
   - 请求超时后又被 Query retry 一次

### 2.4 当前 blank spinner 不是纯前端问题，但也不是纯后端问题

当前浏览器侧行为并非无限无界：

- [packages/frontend/src/api/client.ts](/home/cl/agent-edu/packages/frontend/src/api/client.ts)
  - 请求 60 秒超时
  - 超时会抛 `ApiError(504, ...)`
- [packages/frontend/src/App.tsx](/home/cl/agent-edu/packages/frontend/src/App.tsx)
  - Query 默认 `retry: 1`

但这仍会带来两个实际体验问题：

1. 当后端不可达时，页面看起来会“长时间转圈”，而不是快速失败。
2. 当前仓库没有一份明确 runbook 解释：
   - 前端 spinner 先查什么
   - API ready 查什么
   - worker 是否在跑查什么

现状结论：

- 当前 blank spinner 是“前端 transport timeout + query retry + 缺 runbook + backend stack 与 frontend stack 拓扑未写清”的综合问题。

### 2.5 当前 Docker 验证基线偏 API/worker，不覆盖 Web 页面层

当前仓库已有相当多 Docker / live 验证资产：

- [Makefile](/home/cl/agent-edu/Makefile)
  - `make dev-up`
  - `make test-api`
  - `make docker-api-test`
  - `make real-provider-regression`
  - `make observability-up`
- [docs/DOCKER_VALIDATION.md](/home/cl/agent-edu/docs/DOCKER_VALIDATION.md)
  - 已定义 blackbox API 验证路径
- [tests/test_docker_blackbox.py](/home/cl/agent-edu/tests/test_docker_blackbox.py)
  - 已覆盖 `healthz / readyz / session / chat / hint / quiz / goal / plan / task / memory / audit`
- [tests/test_worker_runtime.py](/home/cl/agent-edu/tests/test_worker_runtime.py)
  - 已覆盖 worker 主函数的最小行为

现状结论：

1. 当前“容器内 API 是否工作”已有验证基线。
2. 当前“浏览器能否通过本地前端正确连上 Docker 后端”还没有同级基线。

### 2.6 当前本地开发反馈回路仍然偏慢

当前开发体验的关键事实：

- [compose.override.yaml](/home/cl/agent-edu/compose.override.yaml)
  - 只给 `api` 和 `tester` 挂载源码卷
  - 没给 `worker` 挂源码卷
- [compose.yaml](/home/cl/agent-edu/compose.yaml)
  - `api` 运行的是普通 `uvicorn`
  - 没有 `--reload`
- [Makefile](/home/cl/agent-edu/Makefile)
  - `make logs` 只看 `api`
  - 没有 `worker-logs`
  - 没有 `frontend-dev`
  - 没有 `stack-smoke`

现状结论：

1. API 即使挂了源码卷，也不会自动热重载。
2. worker 改动默认不会自动反映到运行中的容器。
3. API 和 worker 的日志、状态、smoke 验证入口不统一。

这会制造非常典型的错觉：

> “我改完代码了，API 像是新的，worker 却还在跑旧逻辑。”

### 2.7 当前 provider / migration / worker 问题会被折叠成同一种前端故障

当前高频故障源至少包括：

- API 未启动
- API 启动但 migration 失败
- provider key 缺失或 provider 配置错误
- worker 未启动
- Vite proxy target 错误
- CORS origin 不匹配
- Docker stack 正常，但前端未单独启动

这些故障在浏览器端经常会被用户感知成同一件事：

> 页面在加载，或请求失败，看不出到底是哪一层错了。

这就是为什么需要把排错手册收口成一份标准 runbook，而不是继续靠经验排障。

## 3. 目标与非目标

### 3.1 目标

本计划应达成：

1. 明确 `agent-edu` 当前推荐的本地开发拓扑。
2. 让新开发者在一份文档内完成：
   - 启动 backend stack
   - 启动前端
   - 验证 API / worker / frontend integration
   - 排查常见故障
3. 让 Docker 与本地前端的关系不再模糊。
4. 让 blank spinner、API 不通、worker 不跑、migration 失败都有固定排查顺序。
5. 让 README、Docker validation 文档、Make 入口和真实仓库行为保持一致。

### 3.2 非目标

本次不应做：

- 不要求现在就把前端正式放进 compose 默认栈。
- 不要求现在就引入大型浏览器 E2E 测试框架。
- 不重做整套 DevOps。
- 不把所有本地开发模式都包装成一键魔法。
- 不把应用层空页面或权限问题误当成纯 Docker 问题。

## 4. 关键边界

### 4.1 开发模式边界

建议明确区分两类模式：

1. `backend-docker + frontend-local`
2. `local-backend + local-frontend`

其中当前 MVP 推荐模式应是：

> `backend-docker + frontend-local`

原因：

- 当前 compose 已经稳定覆盖 API / worker / DB / Redis / observability。
- 当前前端天然就是 Vite 本地开发模式。
- 这是当前最少改动、最符合现状的 canonical dev path。

### 4.2 文档与实现边界

- 文档必须描述当前真实行为，不得假设前端已经容器化。
- 如果后续新增 `frontend` compose profile，应作为增强模式，而不是回写成当前事实。

### 4.3 验证边界

- API blackbox 通过，不等于 frontend integration 通过。
- 页面可打开，不等于 worker / migration / provider 全部正常。
- 本文档必须把这些验证层级区分清楚。

## 5. 需要增强的核心问题

### 5.1 当前没有“唯一推荐启动路径”

问题：

- README 提到了 Docker 与本地开发
- Docker validation 文档强调 API 验证
- 前端 README 没有项目级说明
- compose 又没有 frontend 服务

结果：

- 新开发者不清楚：
  - 是不是只要 `make dev-up`
  - 前端是否应该另起
  - worker 是否默认已起
  - 什么时候需要 `make migrate`

建议：

- 明确写死当前 canonical path：
  - `make dev-up`
  - `cd packages/frontend && npm run dev`
  - 浏览器打开 `http://localhost:5173`

### 5.2 当前启动文档存在明显漂移

问题：

- README 提到 `.env.example`，但文件不存在
- README 末尾混入日志
- frontend README 仍是模板文档

建议：

- 收口为一份真实 runbook
- README 保留高层入口
- 把具体启动、smoke、排错移到专门文档

### 5.3 当前 frontend integration 没有标准 smoke

问题：

- Docker blackbox 测的是 API，不是浏览器链路
- 无法覆盖：
  - Vite proxy target 错误
  - API base URL 错误
  - CORS origin 问题
  - frontend transport timeout / retry 体验

建议：

- 增加一条明确的 frontend smoke path：
  - 页面可加载
  - goals / sessions 页面不再无界 loading
  - session 创建和 message 请求能穿透到 Docker API

### 5.4 当前 proxy / base URL / CORS contract 过于隐式

问题：

- dev 模式依赖 `/api` 代理
- prod 模式默认 `http://localhost:8000/api/v1`
- API CORS 只允许 `http://localhost:5173`

这导致：

- 只要前端不在默认端口、默认 origin、默认 base URL，就容易出问题

建议：

- 把这三项作为一等配置说明：
  - `VITE_API_PROXY_TARGET`
  - `VITE_API_BASE_URL`
  - backend allowed origins

### 5.5 当前 API / worker 日志与状态入口不统一

问题：

- `make logs` 只看 API
- worker 是否活着，当前主要靠 `docker compose ps` 或手动翻日志
- 无单独 worker smoke / once-run 命令

建议：

- 增加明确入口：
  - `make logs-api`
  - `make logs-worker`
  - `make ps`
  - `make smoke-stack`
  - `make worker-once` 或等价 one-shot 检查

### 5.6 当前 Docker “热开发”语义不成立

问题：

- API 没有 `--reload`
- worker 没有源码挂载

这意味着当前 Docker 模式更接近：

> “便于复现实验环境”

而不是：

> “高反馈速度的热开发环境”

建议：

- 文档里必须明确这一点，避免误解。
- 如果后续要优化，再单独决定是否引入：
  - API `--reload`
  - worker source mount
  - worker dev profile

### 5.7 当前常见故障没有收口成固定 triage order

当前最需要固化的是故障排查顺序：

1. `docker compose ps`
2. `GET /healthz`
3. `GET /readyz`
4. API logs
5. worker logs
6. frontend dev server logs
7. browser network request
8. provider / migration / DB state

没有这套顺序时，同一个 blank spinner 会被反复误判成不同问题。

## 6. 推荐技术实现

### 6.1 定义唯一推荐开发模式

推荐当前阶段明确选择：

#### 推荐模式 A：`backend-docker + frontend-local`

启动路径：

1. `make dev-up`
2. `cd packages/frontend && npm install && npm run dev`
3. 打开 `http://localhost:5173`

说明：

- backend 在 Docker 中运行
- frontend 在本地 Vite 运行
- dev 代理转发到 `http://localhost:8000`

这是当前最符合代码事实的主路径。

#### 可选模式 B：`local-backend + local-frontend`

适用于：

- 需要高反馈速度时
- 不希望每次走 Docker build 时

但这不是当前 Docker 收口文档的主模式。

#### 后续增强模式 C：`full-stack Docker`

当前不作为 MVP 必选项。

如果后续要做，应以 `frontend` compose profile 形式落地，而不是默认强行加入现有栈。

### 6.2 文档收口结构

建议形成三层文档：

1. `README.md`
   - 只保留高层入口
2. `docs/DOCKER_VALIDATION.md`
   - 聚焦 blackbox / observability / release validation
3. 新增统一 runbook，例如：
   - `docs/LOCAL_DEV_RUNBOOK.md`

runbook 建议包含：

- 启动矩阵
- 推荐路径
- 环境变量说明
- 前端启动说明
- smoke 验证步骤
- 常见故障 triage

### 6.3 Make 入口收口

建议补齐以下入口：

- `make logs-api`
- `make logs-worker`
- `make ps`
- `make smoke-api`
- `make smoke-stack`
- `make frontend-dev-doc`
  - 至少打印当前前端启动命令和关键环境变量

如果不愿增加太多命令，最少也要把：

- API logs
- worker logs
- compose ps
- smoke 验证

这四类入口显式化。

### 6.4 环境变量与配置模板收口

建议新增或修复：

1. 根目录 `.env.example`
2. 前端 `.env.example` 或文档化的 env contract

至少要覆盖：

- backend:
  - `AGENT_EDU_DATABASE_URL`
  - `AGENT_EDU_REDIS_URL`
  - `AGENT_EDU_LLM_PROVIDER`
  - `AGENT_EDU_LLM_API_KEY`
  - `AGENT_EDU_LLM_BASE_URL`
  - `AGENT_EDU_ALLOWED_SKILLS`
- frontend:
  - `VITE_API_PROXY_TARGET`
  - `VITE_API_BASE_URL`

同时要明确：

- `make dev-up` 已经会执行 migration
- `make migrate` 是修复/显式迁移命令，不是每次都必须单独运行

### 6.5 frontend integration smoke 基线

推荐建立一个明确的 frontend smoke checklist。

最小应验证：

1. Vite dev server 可访问。
2. `GET /healthz` 与 `GET /readyz` 为成功。
3. Goals 页面能拉到 learner profile 或显示明确 empty/error。
4. Sessions 页面能创建会话。
5. Learning workspace 能发送一条 message，并收到响应。
6. 不出现长时间无界 spinner。

实现建议分两层：

#### 最小 MVP 层

- 先提供文档化 smoke 流程
- 配合 API blackbox 一起执行

#### 后续增强层

- 若要把 browser integration 也纳入发布门禁，再引入 Playwright 或等价浏览器 smoke

### 6.6 故障排查 runbook

建议固定排查顺序：

#### 1. 基础进程层

- `docker compose ps`
- frontend dev server 是否启动

#### 2. 后端健康层

- `GET /healthz`
- `GET /readyz`

#### 3. 日志层

- API logs
- worker logs
- frontend dev server 控制台

#### 4. 浏览器请求层

- Network 中是否请求到 `/api/v1/...`
- 请求是否被 Vite proxy 转发
- 是 `404 / 403 / 429 / 503 / 504` 哪一种

#### 5. 配置层

- provider key
- `VITE_API_PROXY_TARGET`
- `VITE_API_BASE_URL`
- allowed origins
- `AGENT_EDU_ALLOWED_SKILLS`

#### 6. 数据与迁移层

- migration 是否成功
- postgres / redis 是否 healthy
- worker 是否消费到 job

### 6.7 当前 blank spinner 的专项收口

建议在 runbook 中单列一节：

> 页面一直转圈时查什么

应明确区分：

1. 前端根本没起
2. 前端起了，但 Vite proxy target 不对
3. API `healthz` 通、`readyz` 不通
4. API 通，但 provider path 超时
5. API 可用，但页面缺 empty/error 落点
6. worker 没起，导致后台 job 不推进

这部分对当前仓库尤其重要，因为用户非常容易把 2 到 6 都理解成“Docker 不行”。

## 7. 推荐执行阶段

### Phase 0：冻结当前启动拓扑与事实

目标：先把真实启动模式写死。

执行：

1. 明确 compose 默认服务集合。
2. 明确当前不含 frontend 服务。
3. 明确当前推荐开发模式。
4. 记录前端 proxy / base URL / CORS 现状。

完成标准：

- 不再把“backend Docker stack”误说成“完整 Web stack”。

### Phase 1：修正文档漂移

目标：先让文档不再误导。

执行：

1. 清理 README 漂移内容。
2. 删除不存在的 `.env.example` 引导或补齐文件。
3. 把 frontend README 从模板文档改为项目文档，或直接指向统一 runbook。

完成标准：

- 新开发者从 README 进入后，不会走到不存在的文件或模板说明。

### Phase 2：新增统一 runbook

目标：一份文档完成启动、验证与排错。

执行：

1. 新增 `docs/LOCAL_DEV_RUNBOOK.md` 或等价文档。
2. 写清：
   - backend-docker + frontend-local
   - local-local
   - observability
   - smoke
   - triage

完成标准：

- 新开发者可在一份文档内完成完整启动与排错。

### Phase 3：收口 Make 入口

目标：降低“知道怎么做但命令分散”的摩擦。

执行：

1. 补 `logs-api / logs-worker / ps / smoke-*`。
2. 明确 `migrate` 与 `dev-up` 的关系。
3. 视需要补一个 worker one-shot 检查入口。

完成标准：

- 核心排错和 smoke 命令不需要开发者自己拼。

### Phase 4：补 frontend integration smoke

目标：把“前端能否连上 Docker 后端”纳入标准验证。

执行：

1. 增加文档化 smoke checklist。
2. 如团队接受，再加浏览器 smoke 自动化。

完成标准：

- frontend integration 不再只能靠人工碰运气。

### Phase 5：补开发体验增强项

目标：在不扰动主路径的前提下改善反馈速度。

可选执行：

1. API dev profile 支持 `--reload`
2. worker source mount / dev profile
3. 可选 frontend compose profile

完成标准：

- Docker 开发与本地开发边界更清楚。
- 不再误以为当前 compose 已支持热开发。

## 8. 关键难点与应对

### 8.1 当前最容易把“运行成功”和“产品可用”混为一谈

难点：

- API health 通过，不代表前端可用。
- backend stack 起了，不代表浏览器能访问产品。

应对：

- 把 backend health 与 frontend integration smoke 分层说明。

### 8.2 当前文档漂移已经开始误导真实操作

难点：

- README 提到了不存在的 `.env.example`
- frontend README 仍是模板

应对：

- 先修文档，再谈更多开发模式。

### 8.3 当前 Docker 开发体验并不是真热更新

难点：

- 开发者可能默认以为挂卷就会热更新。

应对：

- 在文档中明确：
  - API 当前无 `--reload`
  - worker 当前无源码挂载
- 这不是 bug，而是当前模式定义不清。

### 8.4 前端空转会掩盖多种后端故障

难点：

- blank spinner 是跨层故障表现，不是单点故障。

应对：

- 固定 triage order。
- 明确按：
  - process
  - health
  - logs
  - browser network
  - config
  - DB/worker

逐层排查。

## 9. 边界与依赖关系

本计划与其他计划的边界如下：

- 与 `MVP_VALIDATION_BASELINE_PLAN.md`
  - 本文档定义开发与验证入口收口。
  - MVP baseline 后续应消费这里的 smoke 与 runbook。
- 与 `COST_RATE_LIMIT_CIRCUIT_BREAKER_ALERTING_PLAN.md`
  - provider failure、timeout、rate limit 的运行保护语义由该文档定义。
  - 本文档只定义开发者如何看到并排查这些问题。
- 与 `OPERATOR_DETAIL_GOVERNANCE_PLAN.md`
  - operator 页面本身的产品设计不在本文档。
  - 但其本地启动与 API 连通性应纳入统一 runbook。

## 10. 交付条件

完成本计划，至少应交付：

1. 一份统一 local dev runbook。
2. 修正后的 README 入口。
3. 与当前仓库一致的环境变量模板或文档。
4. backend-docker + frontend-local 的标准 smoke 流程。
5. API、worker、frontend integration 的固定排错顺序。
6. 若不支持热开发，明确说明当前模式边界。

验收标准：

- 新开发者能在一份文档内完成启动、验证和排错。
- Docker 下核心 API、worker、frontend integration 能被重复验证。
- 开发者不会再误以为 `make dev-up` 已包含前端服务。
- blank spinner、migration 失败、worker 未运行、proxy/CORS 错误有明确排查路径。

## 11. 推荐实施顺序

推荐顺序：

1. Phase 0：冻结启动拓扑与现状。
2. Phase 1：修正文档漂移。
3. Phase 2：补统一 runbook。
4. Phase 3：补 Make 入口。
5. Phase 4：补 frontend integration smoke。
6. Phase 5：再做开发体验增强。

不要先做：

- 在文档仍然漂移的前提下继续加新的启动模式。
- 把当前 backend-only Docker 栈描述成 full-stack Docker。
- 在没有 frontend smoke 的情况下宣称 Web-first 本地开发路径已经收口。
- 把应用层空状态、权限问题、provider 问题全部归因成 Docker 问题。
