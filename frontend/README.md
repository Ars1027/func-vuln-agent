# frontend：检测界面（#6）

React + TypeScript 单页应用，负责单样本/批量输入、实时过程展示，以及按漏洞假设组织的条件证据报告。
字段与行为以 [`docs/interfaces.md`](../docs/interfaces.md) 为准，模块归属见 [`docs/team.md`](../docs/team.md)（Web：周德铭）。

## 运行

需要 Node.js 22.22+（与 `package.json` 的 `engines` 一致）：测试环境使用的 `jsdom@30` 要求
`^22.22.2 || ^24.15.0 || >=26`，用 Node 18/20 安装会得到不受支持的测试环境。先启动后端，再启动前端。

```sh
# 1. 仓库根目录：启动离线演示后端（合成材料 + 脚本模型，无需密钥）
uv run uvicorn app.demo:build_app --factory --app-dir backend --host 127.0.0.1 --port 8000

# 2. frontend 目录
npm install
npm run dev            # http://127.0.0.1:5173
```

开发服务器把 `/api` 代理到 `http://127.0.0.1:8000`，浏览器只发出同源请求，因此**后端不需要开放 CORS**。
后端地址可用 `VITE_PROXY_TARGET` 覆盖；变量说明见 [`.env.example`](.env.example)。

正式构建与本模块自检：

```sh
npm run typecheck      # tsc --noEmit
npm run test           # vitest run
npm run build          # 产物在 frontend/dist/
```

## 与后端的对应关系

| 界面动作 | 接口 |
| --- | --- |
| 准备快照并开始单条检测 | `POST /api/snapshots` → `POST /api/detections` |
| 上传课程 JSONL 批量检测 | `POST /api/batches`（multipart：`file`、`mode`） |
| 任务状态、完成计数、失败项 | `GET /api/tasks/{task_id}` |
| 报告快照（含运行中与失败样本） | `GET /api/tasks/{task_id}/reports` |
| 实时过程事件 | `GET /api/tasks/{task_id}/events?after_seq={seq}`（SSE） |
| 下载课程结果 | `GET /api/tasks/{task_id}/result.jsonl` |

`mode`（`function_only` / `rag_context` / `conditions`）由界面选择，作为运行配置提交，不进入样本内容。

## 状态更新规则

- **先快照后事件**：进入任务或点“刷新快照并续接”时，先读 `/reports`，再以该响应的 `seq` 作为
  `after_seq` 订阅事件；进行中的分析因此可以恢复。
- **只前进**：只应用比本地已应用序号更大的事件；迟到且 `seq` 更小的报告快照不覆盖当前状态。
- **按位置定位**：事件先按 `task_id` 过滤，再按样本原始类型的 `idx` 定位样本，最后在各自列表内按 `id` 合并。
  整数 `1` 与字符串 `"1"` 使用不同的键（`src/state/idx.ts`），不会互相覆盖。
- **失败保留**：`error` 事件把对应样本移入失败状态，但保留已到达的分析；执行失败不会被补成 `prediction=0`。
  快照里只有 `failures`、没有对应样本状态的失败项（服务重启中断排队输入）也会补成失败态，不漏项、不少计。
- **标识无损**：整数 `idx` 超出 JavaScript 安全整数范围（±2^53-1）时接口层直接报
  `idx_not_representable`，不接受已被 `JSON.parse` 舍入、可能合并不同样本的标识；需要大整数请改用字符串。
- **已受理不丢**：任务提交成功后立即记下 `task_id`，随后读取快照或状态失败时仍保留该任务并可重试。
- 事件流收到 `task_completed` 后主动关闭，避免服务端结束流后被浏览器反复重连；快照之后确认任务已终止时
  根本不再订阅——后端对终止任务会立即结束流，此时不会有 `task_completed` 送达。

## 目录

```text
frontend/
├── README.md          # 本文件：运行与接口对应关系
├── INTEGRATION.md     # 与 app.demo 的实测联调记录
├── src/
│   ├── api/           # client.ts（HTTP）、sse.ts（事件订阅）、types.ts（共享类型）
│   ├── state/         # idx.ts（样本标识等价键）、store.ts（归约器与选择器）
│   ├── hooks/         # useTaskStream（快照 + SSE 生命周期）、useElapsed（运行计时）、
│   │                  # useChangeFlash（变化提示）、useCopyToClipboard、useFollowLatest
│   ├── components/    # 业务组件：输入、任务进度、样本列表、假设/条件、证据、分析记录
│   │   └── ui/        # 通用展示件：ProgressBar、Skeleton、EmptyState、ElapsedTime、ConditionBreakdown
│   ├── lib/           # errors.ts（错误映射）、conditions.ts（条件计数）、demoSamples.ts
│   └── styles.css     # 设计变量、组件样式、关键帧动效与响应式断点
└── vite.config.ts     # /api 代理与 vitest 配置
```

`styles.css` 顶部的 `:root` 是唯一的设计变量来源（底面、边框、语义色、圆角、阴影）。
语义色只用于三处：条件状态（有支持证据 / 有反证 / 待确认）、执行失败、判定结论；
新增组件请复用这些变量，不要写死色值。

## 交互与视觉约定

**实时反馈**（数据从 SSE 流式到达，界面要让“正在推进”可见）
- 任务概览：完成/失败/分析中分段进度条 + 运行计时（结束后冻结为“耗时”），
  计数变化时对应格子闪一下背景；进度条宽度与条件色条颜色都带过渡，不做跳变。
- 分析记录：新记录到达自动滚到底部，用户手动上滚后暂停并显示“已暂停自动跟随”。
- 首次读取任务快照时用骨架屏占位，避免空白闪烁。

**动效**（只在挂载与状态变化时触发，重复渲染不重播）
- 列表项错峰入场（`--i` 计算延迟，封顶 8 项，触屏设备取消延迟）；条件状态变化时闪一次描边。
- 证据展开时才挂载内容节点，因此过渡用的是挂载动画而不是高度动画——
  这也保证“折叠时不产生 DOM”，与 `app.test.tsx` 中对 `pre.code-block` 的断言一致。
- 全局 `prefers-reduced-motion: reduce` 下动画时长被压到 0.001ms，功能不受影响。

**可访问性与易用性**
- 状态不只靠颜色：chip 带文字，进度条带 `role="progressbar"` 与 `aria-valuenow/max`，
  条件概览同时给出数字与色块。
- 键盘焦点统一 `:focus-visible` 外环；数字用 `tabular-nums`，避免刷新时宽度抖动。
- 悬停效果集中在 `@media (hover: hover) and (pointer: fine)`，触屏不会残留 hover 状态。

**响应式断点**：≥1600px 加宽两栏与样本列；≤1180px 收窄左栏；≤1024px 折叠为单栏并解除左栏吸附；
≤760px 统计网格两列、按钮与分段控件整行、进度条与计时改为纵向堆叠。

## 验证

```sh
npm run typecheck   # tsc --noEmit
npm run test        # 9 个测试文件 / 53 个用例
npm run build       # dist/ 构建产物
```

测试覆盖样本标识类型隔离、样本内 `id` 合并、重复事件与迟到旧快照、失败保留、按假设分组等归约器行为，
并用录制自 `app.demo` 的真实事件流做契约回归；`src/app.test.tsx` 在 jsdom 中走通单条与批量界面流程；
`src/components/ui/realtime.test.tsx` 覆盖进度条分段、条件计数、计时冻结与变化提示；
`src/hooks/useTaskStream.test.tsx` 覆盖已受理任务在读取失败后仍可重试、终止任务不再订阅、并发提交不互相覆盖；
`src/api/client.test.ts` 覆盖超范围整数 `idx` 的拒绝。
连到演示后端的实测命令与结果见[联调记录](INTEGRATION.md)。

## 剩余依赖

- 真实 RAG（#2）、版本快照与仓库工具（#3/#4）接入后才能在真实仓库上联调；当前演示入口只接受
  `examples/synthetic.jsonl` 中的合成样例。
- 部署形态（`npm run build` 产物由后端或独立静态服务托管）需要在 #1 集成阶段确定；若前后端不同源，
  需由后端补齐 CORS 或由入口反向代理 `/api`。
- 当前后端只支持本机单用户、无鉴权（见 `docs/backend.md`）；界面不把任务标识当访问凭证。
