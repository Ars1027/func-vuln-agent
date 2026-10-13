# 团队分工

每个 issue 由一位成员负责实现、测试和文档。共享接口与最终集成由组长陈子星负责。

| 成员 | Issue | 模块与交付 |
| --- | --- | --- |
| 陈子星（组长，`Ars1027`） | [#1](https://github.com/Ars1027/func-vuln-agent/issues/1)、[#5](https://github.com/Ars1027/func-vuln-agent/issues/5) | 接口、条件驱动 Agent、API、SSE、集成验收 |
| 安晟毅 | [#2](https://github.com/Ars1027/func-vuln-agent/issues/2) | 历史案例的成立条件、安全条件、来源与 RAG |
| 史鹏飞 | [#3](https://github.com/Ars1027/func-vuln-agent/issues/3)、[#4](https://github.com/Ars1027/func-vuln-agent/issues/4) | 指定版本快照、上下文查询与代码证据 |
| 周德铭 | [#6](https://github.com/Ars1027/func-vuln-agent/issues/6) | Web 输入、实时过程、条件状态与证据展示 |
| 臧天心 | [#7](https://github.com/Ars1027/func-vuln-agent/issues/7)、[#8](https://github.com/Ars1027/func-vuln-agent/issues/8) | 课程评分、方法对照实验、GitHub Bot |

安晟毅、史鹏飞、周德铭、臧天心的 GitHub 账号待补充；issue 正文已按姓名分配。

## 模块归属

以下为实现时的目录约定：

| 模块 | 负责人 | 目录 |
| --- | --- | --- |
| Agent、API、共享类型 | 陈子星 | `backend/app/agent/`、`api/`、`schemas/` |
| RAG | 安晟毅 | `backend/app/rag/` |
| 版本准备、仓库工具 | 史鹏飞 | `backend/app/repository/` |
| Web | 周德铭 | `frontend/` |
| 评测、Bot | 臧天心 | `backend/app/evaluation/`、`bot/` |

## 推进顺序

| 里程碑 | 任务与完成目标 |
| --- | --- |
| M1 接口与数据准备 | #1 接口检查点，#2 历史案例及条件检索，#3 快照准备 |
| M2 单函数检测闭环 | #4 证据定位工具，#5 自主分析与反证检查，#6 Web 报告 |
| M3 批量评测 | #7 课程结果与对照实验，#1 最终集成验收 |
| M4 GitHub Bot | #8 GitHub 触发与报告回复 |

#1 在 M1 交付接口基线，M3 完成验收后关闭。其他任务依赖该检查点即可开始。史鹏飞按 #3、#4 推进，臧天心按 #7、#8 推进；各人按当前 issue 交付。

协作方式见 [CONTRIBUTING.md](../CONTRIBUTING.md)，AI 任务入口见 [角色提示词](prompts/README.md)。
