# 指定版本快照与代码证据工具（#3 / #4）

本目录实现 [接口约定](../../../docs/interfaces.md) 中的 `Preparation` 与 `Repository`：
按课程 `target` 或显式 `revision` 物化单个提交的文件树，并在此快照内提供代码搜索、
按行读取和符号定义/调用查询。检测内核、API 与报告由其他模块负责。

## 1. 版本选择与输入

| 入口 | 选版规则 |
| --- | --- |
| `prepare_course(sample)` | `target=1` 取修复提交的父提交；`target=0` 取修复提交本身 |
| `prepare_snapshot(request)` | 直接使用请求中的 `revision=commit` 或 `revision=parent`（Web 明确选择、Bot 传 `commit`） |

返回 `DetectionInput{idx, func, snapshot_ref}`，保留输入的 `idx` 原类型与 `func` 原文。
标签、`commit_url`、`revision`、diff 与另一版本只存在于准备层，不进入 `DetectionInput`
或任何工具结果。多父提交返回 `multi_parent_commit`，根提交请求父版本返回
`parent_unavailable`；函数在快照中缺失或不唯一时准备失败
（`function_not_found` / `function_ambiguous`）；源码因大小上限未扫描且没有找到函数时返回
`function_scan_limit`，不会把扫描不完整当作函数不存在。字符串、字符与 C++ 原始字符串
内部的空白必须一致，只在字面量外折叠排版空白。

## 2. 提交链接与获取边界

支持 `https://<host>/<owner>/<repo>/commit/<sha>`，可选 `.patch` / `.diff` 后缀、查询串与
片段；`sha` 为 7–40 位十六进制。默认主机白名单只有 `github.com`，可用
`FVA_REPOSITORY_HOSTS`（逗号分隔）扩展，课程数据确认主机后需要核对默认值。

拒绝非 https、带凭据或端口、IP 字面量、白名单外主机（`unsupported_commit_url`、
`unsupported_host`）；拒绝解析到私网、回环、链路本地、保留地址或 CGNAT 的托管主机
（`private_network_target`）以及无法解析的主机（`network_unavailable`）。

Git 命令固定带 `http.followRedirects=false`、`protocol.allow=never`、
`protocol.https.allow=always`、禁用凭据助手与钩子；子进程环境会清除 `GIT_DIR`、
`GIT_CONFIG_*`（含 `GIT_CONFIG_COUNT/KEY_n/VALUE_n`）等可注入配置，避免 `url.insteadOf`
把已校验的地址改写到其他主机。解析得到的公网地址会通过 `http.curloptResolve` 固定给
Git，连接阶段不再重新解析主机名（需 Git ≥ 2.31，否则返回 `git_unsupported`）。
浅拉取失败后的回退最多获取 `max_fetch_depth`（默认 200）层历史，不再保留完整分支历史。
缩写 SHA 超出浅历史查找范围时返回 `commit_lookup_limited`，要求提供完整 40 位 SHA；
这不等于提交不存在。完整 SHA 的已发布快照在镜像被回收后仍可直接离线复用。
拉取失败、提交缺失与导出失败分别返回 `repository_fetch_failed`、`commit_not_found`、
`snapshot_export_failed`；`git` 不在 PATH 时返回 `git_unavailable`；超时与取消分别返回
`repository_fetch_timeout`、`repository_cancelled`，被取消时会终止 Git 及其子进程；
流式文件树与 blob 读取也有超时和取消监视，阻塞管道读取不会绕过取消。

## 3. 存储与快照内容

```
storage/
  git/<repo-hash>.git          # 裸镜像缓存，仅准备层访问
  snapshots/<snapshot_ref>/    # 物化后的文件树，不含 .git
  refs/<snapshot_ref>.json     # 提交与仓库元数据，位于快照之外
  tmp/                         # 原子发布的临时目录
```

`snapshot_ref` 为 `snap-<16 位十六进制>`，由仓库地址与提交哈希派生，不携带标签或选版
语义。物化直接读取提交树 blob，不应用 `export-ignore` / `export-subst`；只导出普通文件，
跳过符号链接与子模块，路径遵循共享 `normalize_snapshot_path` 规则，拒绝 `.git`、反斜杠、
`..`、空段、非 UTF-8、尾随点/空格、冒号，以及文件或目录组件的大小写冲突。
文件树按 4 KiB 分块读取，超过 200000 个文件立即停止，不先把整个 `ls-tree` 输出载入内存。
单快照默认上限 256 MiB，镜像与快照各默认 2 GiB 总量配额。

镜像配额在拉取前、拉取中的通信轮询（至多每 200ms 一次）以及拉取结束/失败后检查。
镜像回收在缓存级串行，只回收空闲超过 `min_idle_seconds`（默认 600s）且未被解析/导出
操作锁定的镜像；超限时终止本次拉取并移除本次镜像，包括 Windows 上的只读对象文件。
运行中巡检允许检查间隔内的瞬时超额，严格磁盘硬配额需由部署环境提供。

**已发布快照不自动回收**：接口没有引用到期或释放协议，排队任务与长任务可能继续使用旧
`snapshot_ref`，因此不能凭空闲时间删除证据。快照配额不足时拒绝新发布并返回
`storage_quota_exceeded`；需要释放空间时，须先确认相关任务与引用已不再使用。
配额检查、元数据登记和文件树原子改名在同一存储锁内执行，避免并发发布重复计数。
发布仍按 `snapshot_ref` 幂等，重试会清理上次中断留下的孤儿目录；启动时清理 `tmp/` 残留。
文本读取只接受 UTF-8
（无 NUL 字节），否则 `file_unreadable`。工具只接受登记过的 `snapshot_ref`，格式错误或
未登记一律 `snapshot_not_found`，不按路径猜测其他快照。

## 4. 证据工具

| 工具 | 语义 | 覆盖范围 |
| --- | --- | --- |
| `search_code(query)` | 在快照的 C/C++ 源文件中做大小写敏感的字面量搜索，空白折叠后匹配，返回匹配所在完整行 | 文本级；不区分注释/字符串；默认最多 20 条，计数到 50000 条预算为止并在 `scope` 说明 |
| `read_file(path, start_line, end_line)` | 按 1 起始行号流式读取原文，`end_line` 超出文件时钳制并在 `scope` 说明 | 单文件默认最多 2 MiB，超限 `file_too_large`；单次最多 400 行，超限 `range_too_large`；起始行越界 `line_out_of_range` |
| `find_symbol(symbol)` | 按标识符边界定位定义、`#define` 宏、声明、调用与其他引用 | 依据括号/花括号与作用域文本形态分类，头文件中的 `name(...);` 视为声明，命名空间/类作用域变量视为定义；注释与字符串不剔除；默认最多 20 条 |

扫描覆盖 C/C++ 常见后缀（含 `.cc/.cpp/.cxx/.hpp/.tcc/.tpp/.ii/.cu/.cuh/.ixx/.cppm` 等）
以及含预处理指令的无扩展名头文件；被判为其他类型的文件会计入 `scope` 的
`skipped ... other extensions`，超过单文件扫描上限的记入 `oversized`，非文本文件记入
`non-text`；`locate_function` 找不到函数时也会在错误信息中说明这些缺口。符号扫描预算按
文件字节数计算，避免多字节文本绕过 64 MiB 上限。`find_symbol` 的出现次数超过
`max_occurrences` 后只停止计数，仍继续扫描以保留后续定义；作用域状态只向前扫描一次，
单次分类向前查看最多 400 个字符，在 `scope` 标明覆盖范围及
`counts beyond N were not tallied`。定义/宏、声明、调用、其他引用分别保留有限候选，
避免前面的低优先级引用挤掉后面的声明和调用。

`find_symbol` 返回顺序为定义/宏、声明、调用、其他引用，`scope` 列出前若干条的
`路径:行号 分类` 与统计，便于 Agent 追踪辅助函数、调用方与全局变量。`locate_function`
在准备阶段定位待测函数，作为首条代码证据。所有位置都包含快照相对路径、1 起始行号与
原文片段，`content` 为原文完整行。定位与读取统一以 LF 分行，CRLF 规范为 LF；
孤立 CR、换页符或 Unicode 分隔字符不另算一行。NUL 检查覆盖整个文件，按行读取时
先用固定大小的块检查，不将文件整体载入内存。

工具只做检索与读取，不判断证据支持还是反驳某个条件；条件状态由 Agent 结合报告证据判定。

## 5. “未找到”与“执行失败”

- 搜索/符号查询无结果：返回 `matches=[]`，`scope` 记录扫描文件数与 0 条匹配；
- 文件不存在、路径越界、非文本、行号越界、区间过大、快照未登记：抛 `IntegrationError`，
  由运行时报告为样本失败，绝不补成 `prediction=0`。

错误码：`invalid_path`、`path_escape`、`file_not_found`、`file_unreadable`、
`line_out_of_range`、`range_too_large`、`invalid_line_range`、`invalid_symbol`、
`empty_query`、`snapshot_not_found`、`snapshot_too_large`、`snapshot_write_failed`、
`storage_quota_exceeded`、`git_unsupported`、`repository_cancelled`、
`repository_fetch_timeout`、`empty_snapshot`、`file_too_large`、`function_scan_limit`、
`commit_lookup_limited`。`POST /api/snapshots` 对 `unsupported_commit_url` / `unsupported_host`
返回 HTTP 422；DNS、网络、缺失依赖等执行失败仍返回 503。

## 6. 验证记录

命令（仓库根目录）：

```sh
python -m ruff check .
python -m ruff format --check .
python -m pytest -q
```

本轮结果：`192 passed`，ruff 检查与格式检查通过；逐条审核处理见
[PR #13 复核记录](../../../docs/pr-13-review.md)。新增测试：

| 文件 | 覆盖 |
| --- | --- |
| `tests/test_repository_prepare.py` | `target=1/0` 与 `revision=commit/parent` 选版一致、`idx/func` 保留且结果不含选版信息、重复准备复用快照且不再解析 DNS、地址固定参数、快照间隔离、引用不可猜测、多父提交、根提交、仓库/提交缺失、函数不一致与重复、URL 白名单、私网与 DNS 失败 |
| `tests/test_repository_tools.py` | 行号与原文一致、`end_line` 钳制、行区间上限、缺失文件、目录穿越、`.git` 路径、二进制与非 UTF-8 文件、隐藏目录与 `.tcc`/无扩展名头文件扫描、搜索命中/无命中/截断/按大小排除、符号扫描字节预算、边界检查与检查后数据变化、定义与声明与调用与注释引用分类、相似标识符不合并、宏、命名空间全局变量、跨文件调用路径、出现次数截断仍保留定义、非法符号、未知快照引用 |
| `tests/test_repository_store.py` | 发布幂等、孤儿目录修复、同一引用并发发布、并发发布共享配额且不重复计数、临时目录清理、已发放快照不被回收、镜像回收跳过在用目录、延后出现的 NUL 与非 UTF-8 文本拒绝、无扩展名预览有界读取 |
| `tests/test_repository_git.py` | 真实 Git：拉取提交、解析父提交、按提交导出、不应用 `export-ignore`、快照不含 `.git`、镜像缓存复用、缺失仓库与提交、子进程安全参数与配置注入清理、歧义路径拒绝 |

`tests/test_repository_*.py` 的仓库内容均为人工编写的合成 C 片段，配合内存 `FakeGit`
（`tests/fake_git.py`）或本地临时 Git 仓库，不调用网络与课程数据，不代表真实检测效果。
`tests/test_demo.py::test_real_factory_never_silently_uses_demo` 随本次接入更新：真实工厂
对演示链接返回 HTTP 422 / `unsupported_host`，不再回退到合成适配器。

## 7. 依赖与后续

- 部署环境需提供 `git`（在 PATH 中，≥ 2.31 才能固定已验证地址）；未安装时准备与仓库
  工具返回 `git_unavailable`。本机验证使用便携版 Git（仅放在被忽略的 `work/` 目录，不
  提交）。
- 缓存配额默认各 2 GiB，可通过 `RepositoryAdapters(max_storage_bytes=...)` 调整；
  配额锁与镜像使用锁是进程内锁，部署侧需保证只有一个准备服务写入同一存储目录。
- 课程数据尚未到达，`commit_url` 的实际主机与路径形式、父提交规则需在数据到位后核对；
  如出现 `github.com` 以外的主机，通过 `FVA_REPOSITORY_HOSTS` 显式加入并补充验证。
- 函数定位与符号查询是文本级启发式，不覆盖宏展开、条件编译与编译器 AST；复杂仓库的
  定位质量仍需课程样本评估。
- 本模块只提供代码证据；`AgentRunner` 负责分配证据 ID、记录 trace 与条件状态。
