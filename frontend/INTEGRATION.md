# 前端接口联调记录（#6 · M2）

记录时间：2026-10-16。对象：`app.demo` 演示后端（合成材料 + 脚本模型）与前端开发服务器。
**合成材料只验证程序行为，不代表真实检测效果。**

## 环境

| 项 | 版本 / 说明 |
| --- | --- |
| Node.js | v24.19.0 |
| npm | 11.17.0 |
| Python | 3.14.7（本机未安装 `uv`，改用 `python -m venv .venv` + `pip` 安装 `pyproject.toml` 中的同一组依赖范围） |
| 后端 | `python -m uvicorn app.demo:build_app --factory --app-dir backend --host 127.0.0.1 --port 8000` |
| 前端 | `npm install` + `npm run dev` → `http://127.0.0.1:5173`，`/api` 代理到 8000 |

后端演示库写入 `artifacts/demo-tasks.sqlite3`，受 `.gitignore` 忽略。

## 联调步骤与实测结果

以下请求都发往 **5173 端口的 Vite 开发服务器**，用于同时验证界面所用的代理链路。

| # | 动作 | 实测结果 |
| --- | --- | --- |
| 1 | `GET /` | 200，返回 Vite 页面（581 字节） |
| 2 | `POST /api/snapshots`（`idx="1"`，合成漏洞版函数，`revision=parent`） | 200 `{"idx":"1","func":"void copy(...)","snapshot_ref":"s-a83f"}` |
| 3 | `POST /api/detections`（`snapshot_ref=s-a83f`，`mode=conditions`） | 202 `status=queued mode=conditions total=1`，返回 `task_id` |
| 4 | `GET /api/tasks/{task_id}` | `status=completed completed=1` |
| 5 | `GET /api/tasks/{task_id}/reports` | `seq=12`，`reports=1`，`active_samples=0`，`failed_samples=0`；`prediction=1`，条件 `status=supported`，证据 2 条 |
| 6 | `GET /api/tasks/{task_id}/events?after_seq=6` | 重放 `id: 7 … id: 12`（`retrieval`、`condition_update`、`repository_read`、`sample_completed`、`task_completed`）后关闭流 |

第 6 步确认了界面依赖的两个前提：`after_seq` 能从中途续接，且 `event:` 使用类型名
（`retrieval`、`condition_update` 等），因此前端按类型逐个注册监听器。

### 批量与标识类型隔离

`POST /api/batches`（multipart：`file=examples/synthetic.jsonl`、`mode=conditions`）实测：

```text
创建任务：{"task_id":"a6abb…","status":"queued","mode":"conditions","total":3,"completed":0,"failures":[]}
任务状态：{"status":"completed","mode":"conditions","total":3,"completed":3,"failures":[]}

idx=1        type=integer prediction=1 condition=supported
idx=1        type=string  prediction=0 condition=refuted
idx=unknown  type=string  prediction=0 condition=unknown

GET /api/tasks/{task_id}/result.jsonl
{"idx": 1, "prediction": 1}
{"idx": "1", "prediction": 0}
{"idx": "unknown", "prediction": 0}
```

这是界面必须按原类型区分 `idx` 的直接依据：整数 `1` 与字符串 `"1"` 是两个样本，判定相反，
界面分别显示为 `1（整数）` 与 `"1"（字符串）`，下载结果按输入顺序保持类型。

### 录制的真实事件流

第 3–6 步中 `data:` 载荷的 12 条事件被原样录制为
[`src/state/fixtures/demoEvents.ts`](src/state/fixtures/demoEvents.ts)，
并由 [`src/state/contract.test.ts`](src/state/contract.test.ts) 重放：

- 逐条应用后得到 `prediction=1`、`seq=12`、`completed=1/1`；
- `e1` 由三条 `condition_update` 反复推送，合并后只保留一条，`e2` 由检索事件产生；
- 代码证据定位到 `src/copy.c:1-1`，历史证据 `case_id=synthetic-history-001`；
- 重放整段事件与接收更旧的快照都不改变最终状态。

后端载荷结构变化时该测试会失败，用于守住前后端契约。

## 自动化验证

```sh
# frontend/
npm run typecheck   # tsc --noEmit，无输出即通过
npm run test        # 7 个测试文件 / 46 个用例通过
npm run build       # dist/ 构建成功
```

| 测试文件 | 覆盖内容 |
| --- | --- |
| `src/state/idx.test.ts` | 整数 `1` 与字符串 `"1"` 的等价键与显示、标识输入校验 |
| `src/state/store.test.ts` | 快照恢复、旧快照忽略、事件去重、样本内 `id` 合并、失败保留、按假设分组 |
| `src/state/contract.test.ts` | 录制事件流回放与中断续接 |
| `src/api/sse.test.ts` | `after_seq` 拼接与任务标识编码 |
| `src/app.test.tsx`（jsdom） | 先快照后事件、条件状态与证据导航、重复事件不影响界面、批量同名局部 ID 分离、失败展示、导出失败原因 |
| `src/lib/conditions.test.ts` | 条件状态计数与展示顺序 |
| `src/components/ui/realtime.test.tsx`（jsdom） | 进度条四段宽度与无障碍数值、条件概览计数、骨架屏行数、空状态文案、运行计时刷新与结束冻结、变化提示的触发与复位 |

后端未改动，仓库原有测试仍全部通过：`python -m pytest -q` → `86 passed`。

## 真实浏览器检查

本机没有 Playwright 浏览器，Chromium 三次下载均因网络超时失败；改用系统自带的
Edge 152 以 `--headless=new --remote-debugging-port=9222` 启动，经 CDP 驱动检查渲染结果：

| 视口 | 检查内容 |
| --- | --- |
| 1440×900 | 两栏布局；输入面板固定在视口内且自身可滚动；右栏为任务概览（6 格统计）、样本列表与详情 |
| 430×900 | 折叠为单栏；模式卡片、分段控件、统计网格按预期重排；按钮占满整行 |

并在浏览器中走通一次合成样例检测：任务状态「已完成 1/1」，条件显示「有支持证据」，
点击条件引用的 `e1` 后证据卡展开，显示 `src/copy.c:1-1` 与深色代码块原文。
以上视口未见溢出、错位或不可读文本。像素级复核仍以本地 `npm run dev` 为准。

## 尚未覆盖

- **动态交互的浏览器复核**：上表的截图检查覆盖的是布局与静态渲染；之后新增的进度条过渡、
  列表错峰入场、条件变化高亮、自动跟随滚动等动效未再逐项截图核对，需在本地
  `npm run dev` 打开页面确认观感（其中“计时在任务结束后冻结”“进度条分段宽度”“变化提示复位”
  已由 `src/components/ui/realtime.test.tsx` 断言）。
- **视觉细节复核**：浏览器检查是脚本化的（截图对比），未覆盖 hover、focus 环、滚动条等
  交互动效的人工判断。
- **真实数据链路**：#2 的 RAG、#3/#4 的快照与仓库工具接入前，只能使用合成样例；`app.demo`
  对非合成提交链接返回 `synthetic_input_only`。
- **不同源部署**：当前依赖 Vite 代理。若 `frontend/dist` 与后端分离部署，需要由部署入口反向代理
  `/api`，或由后端为界面来源补齐 CORS（属于 #1 集成范围）。
- **鉴权**：后端当前无身份校验、单用户本机部署（见 `docs/backend.md`），界面同样不提供登录。
