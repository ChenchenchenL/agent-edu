# MVP 验证基线固化技术实现计划

## 1. 文档定位

本文档用于指导 `agent-edu` 的 MVP 验证基线固化。

目标不是新增大而全的测试体系，而是把当前已经存在的 `tests/test_mvp_acceptance.py`、Docker blackbox、API integration、Makefile 入口和观测文档收敛成一套稳定、可重复、可定位失败层级的发布前验证基线。

固化优先级：

1. 默认验证路径不依赖真实外部 LLM / embedding provider。
2. 一条命令能跑完本地 MVP 主链路验证。
3. Docker 环境有可重复的黑盒验证入口。
4. 失败时能快速定位到 API、worker、DB、audit、memory、skill runtime、provider 或 frontend integration。
5. gated real-provider regression 继续作为可选增强，不进入默认路径。

## 2. 当前状态判断

当前已有基础：

- `Makefile` 已有 `mvp-check`，会构建 API image 并运行 `tests/test_mvp_acceptance.py -v`。
- `tests/test_mvp_acceptance.py` 已串联 profile、goal、plan、task、session、chat、hint、quiz、memory、worker、audit。
- `Makefile` 已有 `docker-api-test`，通过 tester 容器对运行中的 API 做 blackbox 验证。
- `docs/DOCKER_VALIDATION.md` 已说明 Docker validation、real-provider regression、observability、triage order。
- `docs/AGENT_EDU_MVP_GAPS.md` 中 G1/G3/G4/G5 已标记完成，G2 仍是部分。

主要缺口：

- `mvp-check` 当前只跑单个 acceptance 测试，尚未形成分层 baseline。
- Docker blackbox 与 MVP acceptance 没有统一成明确的 release gate。
- worker / background job 验证虽然被 acceptance 间接覆盖，但缺少单独 smoke 层说明。
- frontend “页面不转圈、API base/proxy 正确、关键路由可加载”尚未纳入 MVP smoke。
- failure triage 有文档，但命令、层级和交付条件还不够固化。

## 3. 验证基线目标

### 3.1 默认本地基线

默认本地基线应该覆盖：

- service/unit 层核心回归。
- API integration 层主要端点和错误路径。
- MVP acceptance 层端到端主链路。
- worker/job 层 due job 执行、retry/failure 语义。
- audit / memory / skill usage 的关键持久化断言。

建议入口：

```bash
make mvp-check
```

该入口最终应执行：

```bash
python3 -m pytest \
  tests/test_mvp_acceptance.py \
  tests/test_api_integration.py \
  tests/test_worker_runtime.py \
  tests/test_task_runtime_skill.py \
  -q
```

是否继续通过 Docker image 执行由 Makefile 决定，但文档中必须说明默认环境。

### 3.2 Docker blackbox 基线

Docker 基线应该覆盖：

- `postgres`、`redis`、`api` 能启动。
- `/healthz` 和 `/readyz` 正常。
- API blackbox 能创建并读取核心资源。
- 容器内 API base URL 正确。
- 网络、proxy、DB migration、runtime env 配置可定位。

建议入口：

```bash
make docker-api-test
```

后续增强入口：

```bash
make docker-mvp-check
```

如果新增该入口，建议语义是：启动 Docker stack 后，在 tester 容器中运行 MVP acceptance / blackbox smoke，而不是只在 API image 内运行 in-process test。

### 3.3 Frontend smoke 基线

前端不需要在 MVP 基线中覆盖所有交互细节，但必须覆盖“不会一直转圈”的最低要求。

建议覆盖：

- Vite build 或 TypeScript check。
- API client base URL / proxy 配置存在明确默认值。
- `/sessions` 可加载 session list 空态或数据态。
- `/sessions/:id` 可加载 learning workspace。
- `/operator` 可加载治理 dashboard 的 loading / error / empty 状态。
- `/goals` 和 `/goals/:id` 可加载 goal / task / review context。

建议入口：

```bash
npm run lint
npm --prefix packages/frontend run build
```

如果后续引入 Playwright，再增加：

```bash
npm --prefix packages/frontend run test:e2e -- --project=chromium
```

### 3.4 Gated real-provider 基线

真实 provider 回归仍应 gated。

入口保持：

```bash
make real-provider-regression
```

必须满足：

- 仅在 `AGENT_EDU_RUN_REAL_PROVIDER_REGRESSION=1` 时运行。
- 明确需要 provider credentials。
- 不阻塞默认本地 CI。
- 失败时归类为 provider contract / network / credential / rate limit，而不是默认业务逻辑失败。

## 4. 建议技术实现

### 4.1 Makefile 分层入口

建议将 Makefile 中验证入口拆成三个层级。

#### `mvp-check`

本地默认发布前检查，目标是快、稳定、无外部 provider。

建议实现：

```makefile
mvp-check:
	docker compose build api
	docker compose run --rm api pytest \
		tests/test_mvp_acceptance.py \
		tests/test_api_integration.py \
		tests/test_worker_runtime.py \
		tests/test_task_runtime_skill.py \
		-q
```

如运行时间过长，可拆成：

```makefile
mvp-smoke:
	docker compose run --rm api pytest tests/test_mvp_acceptance.py -v

mvp-regression:
	docker compose run --rm api pytest \
		tests/test_api_integration.py \
		tests/test_worker_runtime.py \
		tests/test_task_runtime_skill.py \
		-q
```

#### `docker-mvp-check`

Docker stack 黑盒检查，目标是验证容器、网络、API base URL 和真实服务边界。

建议实现：

```makefile
docker-mvp-check:
	docker compose up -d --build postgres redis api
	docker compose --profile test run --rm --no-deps \
		-e AGENT_EDU_API_BASE_URL=http://api:8000 \
		tester \
		pytest tests/test_docker_blackbox.py tests/test_mvp_acceptance.py -q
```

注意：如果 `tests/test_mvp_acceptance.py` 依赖 in-process `app_client_factory`，不能直接用于 blackbox。此时应新增 `tests/test_mvp_blackbox.py`，用 HTTP client 调用 `AGENT_EDU_API_BASE_URL`。

#### `release-check`

发布前完整检查。

建议实现：

```makefile
release-check: mvp-check docker-api-test
```

可选包含 frontend：

```makefile
release-check: lint mvp-check docker-api-test
```

如果 frontend build 稳定后，再加入：

```makefile
release-check: lint frontend-build mvp-check docker-api-test
```

### 4.2 新增 `tests/test_mvp_blackbox.py`

目的：

- 不依赖 FastAPI in-process test client。
- 对运行中的 API 容器做 MVP 主链路 smoke。
- 与 `test_mvp_acceptance.py` 互补。

建议覆盖最小链路：

1. `GET /healthz`
2. `GET /readyz`
3. create profile
4. create goal
5. generate plan
6. list tasks
7. create session
8. chat explanation
9. quiz generation
10. execute first task
11. update task status completed
12. browse audit events with operator key if configured

边界：

- 不直接连 DB。
- 不读取内部 repository。
- 只通过 HTTP API 断言。
- 默认使用 mock provider。
- 如果 worker 无法在 blackbox 中自动执行，可只验证 job 被创建；worker 执行另由 worker smoke 覆盖。

### 4.3 强化 `tests/test_mvp_acceptance.py`

现有 acceptance 已覆盖主链路，可以补强以下断言：

- `workflow_run` failure 不出现未处理异常。
- audit 中包含 `task.` 或 `workflow.` 关键事件，而不只检查 session / quiz / memory / llm。
- review scheduling worker 执行后，不仅有 review task，还应确认 job completed 或相应 audit。
- memory retrieval API 空结果也必须保持稳定 schema。
- skill usage event 至少记录 chat / quiz / review scheduling 中一类 surface。

不建议：

- 把每个细节都塞进单个超长测试。
- 让 acceptance 依赖真实 provider。
- 在 acceptance 中测试所有 permission denial，permission 应由 API integration / security tests 覆盖。

### 4.4 新增 worker smoke 测试分组

目的：

- 将后台 job 的可运行性从 MVP acceptance 中独立出来。
- 减少“页面可用但 worker 实际坏了”的误判。

建议文件：

```text
tests/test_mvp_worker_smoke.py
```

建议覆盖：

- due job claim。
- handler success 后 complete。
- handler exception 后 retry 或 fail。
- unsupported job type fail closed。
- durable audit 写入。
- `run_due_autonomy_jobs(limit=N)` 尊重 limit。

如果 `test_worker_runtime.py` 已覆盖这些场景，可不新增文件，而是在文档中将其列为 MVP baseline 的 worker 层。

### 4.5 新增 frontend smoke

目的：

- 防止“后端正常，前端一直转圈”的回归。

建议最低实现：

1. 在 `packages/frontend/package.json` 增加或确认：

   ```json
   {
     "scripts": {
       "build": "tsc -b && vite build"
     }
   }
   ```

2. Makefile 增加：

   ```makefile
   frontend-build:
   	npm --prefix packages/frontend run build
   ```

3. 如引入 Playwright，新增 `tests/e2e` 或 `packages/frontend/e2e`：

   - mock API 模式：验证 loading -> data / empty / error 状态。
   - Docker API 模式：验证真实 API 下关键路由不永久 loading。

MVP 阶段推荐先做 build + mock API route smoke，不急于引入完整 E2E。

### 4.6 生成验证报告

建议增加轻量报告，不要引入复杂测试平台。

可选实现：

```bash
pytest tests/test_mvp_acceptance.py tests/test_api_integration.py \
  --junitxml=artifacts/mvp-pytest.xml
```

Makefile 可增加：

```makefile
mvp-report:
	mkdir -p artifacts
	docker compose run --rm api pytest tests/test_mvp_acceptance.py tests/test_api_integration.py \
		--junitxml=artifacts/mvp-pytest.xml
```

注意：

- `artifacts/` 应加入 `.gitignore`。
- 报告不是必须项，优先级低于稳定 baseline。

## 5. 失败定位标准

### 5.1 API / readiness 失败

优先检查：

```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
docker compose logs api
```

典型原因：

- DB 未启动。
- migration 未执行。
- settings 缺失。
- provider 配置不合法。

### 5.2 Worker 失败

优先检查：

- `autonomy.job.claimed`
- `autonomy.job.completed`
- retry / failed audit。
- scheduled job attempt_count。
- handler 是否注册。

判断标准：

- job 不能被 silent complete。
- handler exception 后必须进入 retry/fail。
- max attempts exhausted 后必须可审计。

### 5.3 Memory / reflection / skill 失败

优先检查：

- `memory.*` audit。
- session memory event 表。
- long-term memory candidate / knowledge / behavior API。
- skill usage event。
- curator recommendation backlog。

判断标准：

- MVP smoke 不要求长期记忆质量达到生产级。
- 但 schema 必须稳定，写入/读取不能失败，audit 不能缺失。

### 5.4 Frontend 一直转圈

优先检查：

- `VITE_API_BASE_URL` 或 dev proxy。
- browser network 是否请求 `/api/v1/...`。
- API 返回 401/403/500 还是 pending。
- React Query 是否处理 error / empty state。
- backend `/readyz` 是否正常。

判断标准：

- 页面不能无限 loading。
- API failure 必须显示 error state。
- 空数据必须显示 empty state。

### 5.5 Provider 失败

默认 MVP baseline 不应依赖真实 provider。

如果 real-provider regression 失败，按以下归类：

- credential missing。
- network / proxy。
- provider timeout。
- rate limit。
- response contract drift。

## 6. 推荐执行阶段

### Phase 0：记录当前 baseline

执行：

```bash
make mvp-check
make docker-api-test
```

交付：

- 记录当前通过/失败情况。
- 若失败，先区分是环境问题还是代码问题。

### Phase 1：整理 Makefile 命令

执行：

- 增加 `mvp-smoke`。
- 增加 `mvp-regression`。
- 保留 `mvp-check` 作为组合入口。
- 可选增加 `frontend-build`。
- 可选增加 `release-check`。

交付：

- README / docs 能指向单一验证入口。
- 不改变测试本身。

### Phase 2：补强 MVP acceptance 断言

执行：

- 增加 task / workflow / job audit 断言。
- 增加 skill usage event 断言。
- 增加 worker job completed 断言。

交付：

- MVP 主链路失败时能定位到具体层。
- 不把 acceptance 扩成全量回归。

### Phase 3：新增 Docker MVP blackbox

执行：

- 新增 `tests/test_mvp_blackbox.py`。
- 通过 `AGENT_EDU_API_BASE_URL` 调用运行中 API。
- 加入 `docker-mvp-check`。

交付：

- G2 从“部分”推进到可重复 Docker MVP smoke。
- 验证容器网络和真实 API 边界。

### Phase 4：新增 frontend smoke

执行：

- 确认 frontend build 脚本。
- Makefile 增加 `frontend-build`。
- 可选引入 Playwright mock API smoke。

交付：

- 前端不再只靠人工打开页面验证。
- “一直转圈”类回归可在 smoke 阶段暴露。

### Phase 5：文档收口

执行：

- 更新 `docs/DOCKER_VALIDATION.md`。
- 更新 `docs/AGENT_EDU_MVP_GAPS.md` 的 G2 状态。
- 更新 `docs/NEXT_FEATURES.md` 的 MVP 验证基线状态。

交付：

- 命令、测试、文档一致。
- 后续发布前只需引用一个 baseline 文档。

## 7. 技术难点与解决方案

### 7.1 In-process acceptance 与 Docker blackbox 混淆

难点：

- `tests/test_mvp_acceptance.py` 使用 app fixture 和内部 DB 查询。
- Docker blackbox 应只通过 HTTP API 验证。

解决：

- 保留 `test_mvp_acceptance.py` 作为 in-process end-to-end。
- 新增 `test_mvp_blackbox.py` 作为 Docker HTTP smoke。
- 不强行复用一个测试文件处理两种模式。

### 7.2 Worker 是否应该在 blackbox 中执行

难点：

- Docker blackbox 如果没有 worker 服务，review scheduling 不一定能自动执行。

解决：

- blackbox 主链路只要求 job 创建和 API 可见。
- worker runtime 由 `test_worker_runtime.py` 或单独 worker smoke 覆盖。
- 如果 compose 后续加入 worker 服务，再扩展 blackbox 覆盖 worker 完整执行。

### 7.3 测试耗时过长

难点：

- API integration、MVP acceptance、Docker blackbox、frontend build 全跑可能影响迭代速度。

解决：

- 分层命令：

  - `mvp-smoke`：最快主链路。
  - `mvp-regression`：核心回归。
  - `docker-api-test`：容器黑盒。
  - `release-check`：发布前完整。

- 默认开发只跑 `mvp-smoke`，PR / release 跑更完整命令。

### 7.4 真实 provider 不稳定

难点：

- 网络、限流、模型输出漂移会导致默认测试不稳定。

解决：

- 默认 baseline 使用 mock provider。
- real-provider regression gated。
- provider contract drift 单独记录，不阻塞本地默认验证。

### 7.5 Frontend smoke 需要 API 数据

难点：

- 真实 API 数据准备复杂。
- 前端一直转圈通常来自 loading/error/empty 处理不完整。

解决：

- 第一阶段用 mock API route smoke 覆盖 loading -> empty / data / error。
- 第二阶段再接 Docker API 做关键路由 smoke。
- 不在 frontend smoke 中验证后端业务正确性。

## 8. 交付条件

### 8.1 命令交付

- `make mvp-smoke` 可运行最快主链路。
- `make mvp-regression` 可运行核心 backend regression。
- `make mvp-check` 可作为默认发布前本地入口。
- `make docker-api-test` 继续可用。
- 如新增 `make docker-mvp-check`，必须只依赖 Docker stack 和 tester 容器。
- 如新增 `make frontend-build`，必须在本地和 CI 中可重复。

### 8.2 测试交付

- MVP acceptance 覆盖 profile -> goal -> plan -> task -> session -> chat/hint/quiz -> memory -> worker -> audit。
- Docker blackbox 覆盖 health/readiness 和核心 API smoke。
- Worker smoke 覆盖 claim / complete / retry / fail。
- Frontend smoke 至少覆盖 build；如引入 E2E，覆盖 loading / empty / error。

### 8.3 安全与治理交付

- 默认测试不使用真实 secrets。
- operator key 使用测试环境变量。
- audit-required path 有断言。
- memory / skill / reflection 的 governed path 不通过测试 shortcut 绕过。
- real-provider regression gated。

### 8.4 文档交付

- `docs/DOCKER_VALIDATION.md` 更新为最新命令。
- `docs/AGENT_EDU_MVP_GAPS.md` 中 G2 状态与实现一致。
- `docs/NEXT_FEATURES.md` 中 MVP baseline 状态更新。
- README 或开发文档指出推荐验证顺序。

## 9. 推荐 PR 拆分

建议拆成 4 个 PR：

1. Makefile 分层命令：`mvp-smoke`、`mvp-regression`、`mvp-check`、可选 `frontend-build`。
2. 补强 `tests/test_mvp_acceptance.py` 和 worker smoke 断言。
3. 新增 Docker MVP blackbox 测试和 `docker-mvp-check`。
4. 更新 `docs/DOCKER_VALIDATION.md`、`docs/AGENT_EDU_MVP_GAPS.md`、`docs/NEXT_FEATURES.md`。

每个 PR 要求：

- 默认路径不依赖真实 provider。
- 测试失败能定位层级。
- 不引入 sleep 或 flaky timing。
- 不用测试 shortcut 绕过 auth、audit、approval 或 governed lifecycle。
