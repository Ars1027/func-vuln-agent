# PR #13 审核意见复核

复核日期：2026-10-17。代码基线：`972fcab704609b0b7ff91f3deb2ae0171936c7c1`。
覆盖 [PR #13](https://github.com/Ars1027/func-vuln-agent/pull/13) 的全部 51 条审核讨论，
包括已关闭的 25 条 Sourcery 讨论与尚未关闭的 26 条 Codex 讨论；讨论是否过期不作为
代码是否已修复的判断依据。

26 条 Codex 意见中，本次修复或补强 18 项，8 项已由作者的后续提交覆盖。
以下链接定位原审核意见；“已覆盖”表示保留现有实现，不重复改写。

| 原意见 | 复核结论与处理 |
| --- | --- |
| [缩写 SHA 的浅历史查找](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4301885879) | 补强：保留最多 200 层回退，超出范围返回 `commit_lookup_limited` 并要求完整 SHA，不拉取无限历史，也不误报不存在。真实 Git 验证范围内缩写和超范围后完整 SHA 的重试。 |
| [文件读取缺少字节上限](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4301885882) | 修复：读取前检查 `max_file_bytes`，超长单行也返回 `file_too_large`。 |
| [按最终快照加锁发布](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4301885885) | 已覆盖：`SnapshotStore.publish` 按最终 `snapshot_ref` 加锁且幂等。 |
| [先导出完整归档再检查限制](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4301885888) | 已覆盖：已移除临时归档，按树/blob 检查大小后写入。文件树枚举的另一处内存问题另行修复。 |
| [准备超时后 Git 继续运行](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4301885890) | 补强：已有取消事件；本次覆盖阻塞管道读取，并终止 Git 的子进程树。实际子进程测试验证取消与超时。 |
| [DNS 校验地址未用于连接](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4301885892) | 已覆盖：校验后的地址通过 `http.curloptResolve` 固定给 Git，低版本 Git 明确失败。 |
| [大文件中函数被误报不存在](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4301885893) | 修复：扫描因大小限制不完整且未匹配时返回 `function_scan_limit`，保留扫描上限。 |
| [一次保存所有搜索出现位置](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4301885896) | 已覆盖：搜索匹配使用生成器，结果和匹配计数有上限。 |
| [证据行分隔规则不一致](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4301885897) | 修复：定位、搜索和按行读取统一用 LF；CRLF 统一为 LF，其他分隔字符不另起行。覆盖六类特殊字符。 |
| [函数字面量空白被折叠](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4301885899) | 修复：保留字符、普通字符串、转义引号和 C++ 原始字符串内部的空白，防止不一致函数通过准备。 |
| [镜像配额仅在下载后检查](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4302023959) | 修复：拉取前、中、后检查；中途超限终止进程树，失败后删除本次镜像。处理 Windows 只读 pack 文件；不把软件巡检当作文件系统硬配额。 |
| [文件树先全部加载再检查数量](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4302023961) | 修复：4 KiB 分块消费 NUL 分隔记录，超过文件数上限立即停止；测试证明未消费完整输出。 |
| [符号分类超过预算后仍二次方扫描](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4302023964) | 修复：作用域游标只向前扫描一次，分类前瞻限制为 400 字符；次数达到上限后仍能保留后续定义，返回 `N+` 次数。 |
| [使用中的快照被回收](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4302023965) | 修复：现有接口没有引用释放协议，因此已发放快照不自动删除。配额不足时拒绝新快照，避免等待模型或排队中的任务丢失证据。 |
| [快照超限后仍能从缓存命中](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4302023966) | 已覆盖：发布前检查配额；本次进一步把检查和发布放到同一存储锁内。失败快照不会登记为可用。 |
| [导出未使用共享路径规则](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4302023968) | 修复：调用 `normalize_snapshot_path`，拒绝尾随点/空格、冒号等歧义，并检查文件和目录组件的大小写冲突。 |
| [镜像回收后无法离线复用快照](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4302023970) | 修复：`revision=commit` 且提供完整 SHA 时先查已物化快照，再考虑镜像和 DNS。 |
| [早期普通引用挤掉声明和调用](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4302023971) | 修复：按优先级分别保留有限候选后排序，声明和调用不会被早期低优先级引用挤掉。 |
| [非法链接返回服务错误](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4302023973) | 修复：链接格式和托管主机参数错误返回 HTTP 422；网络等执行失败保持 503。同步 API 测试和后端文档。 |
| [NUL 只检查前 8 KiB](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4302023975) | 修复：完整文本检查全部字节；按行读取以固定大小块检查整个文件，9 KiB 后出现 NUL 也拒绝。 |
| [不同仓库并发回收镜像](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4302079203) | 补强：已有缓存级配额锁与空闲窗口；本次回收还需取得镜像使用锁，解析/导出时持有该锁，本地命中刷新使用时间。 |
| [不同快照并发回收](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4302079209) | 已覆盖：原实现已有跨引用的配额串行；本次为保护引用取消自动快照回收，发布仍串行。 |
| [遗漏 C++ 后缀和无扩展名头文件](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4302079212) | 已覆盖：已支持额外后缀及预处理指令识别，其他类型写入扫描范围。 |
| [UTF-8 按字符而非字节计预算](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4302079217) | 已覆盖：使用 `FileEntry.size` 累计字节。 |
| [无扩展名预览读取整个文件](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4302293215) | 修复：先检查文件大小，预览用 `read(4096)`，不再先 `read_bytes()` 再切片。 |
| [发布并发导致配额重复计数](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4302293217) | 修复：删除独立预留计数，配额检查、元数据登记和目录改名在同一锁内完成；两个恰好放得下的并发发布均成功。 |

25 条已关闭的 Sourcery 意见也检查了对应实现：DNS 固定、配置环境清理、有界历史回退、
移除归档、读取/搜索预算、原子发布、扫描覆盖、UTF-8 校验、缓存、半成品镜像与临时目录
清理等已有实现。其涉及快照回收和镜像总量的内容，以上述新策略为准。
通用 subprocess 告警不需要添加 `shlex.escape`：当前传递参数列表并使用 `shell=False`，
没有把输入拼接成 Shell 命令；`CompletedProcess` 本身也不启动进程。

验证使用合成源码和本地临时 Git 仓库，不访问课程数据或真实远程仓库：

- `uv run --frozen pytest -q`：192 passed（基线 155，本次新增 37）。
- `uv run --frozen ruff check backend tests`：通过。
- `uv run --frozen ruff format --check backend tests`：通过。

当前主机为 Windows，进程树终止与只读 Git pack 清理已实测；POSIX 的进程组路径
未在本机运行。多进程共用存储仍需单写入服务，镜像下载的瞬时磁盘峰值仍需部署侧硬配额。

## 后续轮次复核

本轮代码基线为 `7bc56b2f27bb448235989edb6d6c214cc0a59b96`，累计核对 59 条审核讨论。
前 51 条沿用上表逐项确认；新增 8 条及其处理如下。讨论是否关闭、是否过期均不替代代码验证。

| 原意见 | 当前实现 |
| --- | --- |
| [函数定位不随取消停止](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4302370162) | 已覆盖；本轮把工作线程取消与等待退出提取为共用实现，取消不会提前释放调用方并发名额。 |
| [注释中的函数被接受](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4302370166) | 已覆盖；排除注释/字符串中的候选，保留函数原文与合法注释，覆盖 C/C++ 续行和被续行拆开的注释分隔符。 |
| [搜索返回重复行](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4302370170) | 已覆盖；按路径/行区间去重，出现次数及预算仍逐次统计。 |
| [大量小文件绕过快照配额](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4302475662) | 修复：字节配额之外新增全局 200000 条目上限，计入文件、目录、快照根与元数据；重启从磁盘重算，并计入孤儿树和元数据。配额检查、孤儿清理与发布串行。 |
| [搜索和符号查询取消后仍运行](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4302475664) | 修复：所有仓库工具及本地/网络物化均传递取消事件并等待线程退出；遍历、归一化、符号上下文、按行读取和发布配额扫描检查取消。 |
| [符号结果重复挤占候选](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4302475666) | 修复：各优先级在限额前去重，返回前合并同一位置的不同分类并保留最高优先级；出现次数和字节预算不变。 |
| [extern 变量声明被当作定义](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4302475667) | 修复：无初始化的 extern 标量/数组为声明，带等号或花括号初始化的变量为定义；处理多行声明、同句多个变量、注释中的关键词及 C/C++ 链接块。 |
| [流式 Popen 通用审计](https://github.com/Ars1027/func-vuln-agent/pull/13#discussion_r4302349602) | 已核查 argv 列表和 shell=False，补齐局部审计注释；不添加会改写参数内容的 Shell 转义。 |

同类失败路径也补齐：Git 管道写入、刷新、读取及异常响应返回 `snapshot_export_failed`；
清理已退出子进程的管道时，关闭刷新错误不会覆盖原始失败或取消，目标文件写盘错误仍独立处理。
镜像拉取期间的全量配额扫描至多每秒一次，拉取前后检查继续保留。

本轮验证使用合成源码、本地临时 Git 仓库和实际子进程，不访问课程数据：

- `uv run --frozen pytest -q --tb=short`：284 passed（本轮新增 68 个用例）。
- `uv run --frozen ruff check backend tests`：通过。
- `uv run --frozen ruff format --check backend tests`：通过。
