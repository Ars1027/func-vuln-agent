"""Offline synthetic integration fixture. Never used by the real app.main factory."""

import json
import os
from collections.abc import Sequence

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent import AgentRunner
from app.api.service import create_app
from app.schemas.models import (
    CodeLocation,
    CourseSample,
    DetectionInput,
    HistoricalCase,
    HistoricalCondition,
    Idx,
    Report,
    RepositoryResult,
    RunConfig,
    SnapshotRequest,
    idx_key,
)
from app.schemas.ports import IntegrationError, Services

COPY = "void copy(char *dst, const char *src, size_t n) { memcpy(dst, src, n); }"
CHECKED = (
    "void copy(char *dst, size_t cap, const char *src, size_t n) "
    "{ copy_checked(dst, cap, src, n); }"
)
UNKNOWN = "void copy(char *dst, const char *src, size_t n) { external_copy(dst, src, n); }"
HELPER = (
    "void copy_checked(char *dst, size_t cap, const char *src, size_t n) {\n"
    "    if (n > cap) return;\n"
    "    memcpy(dst, src, n);\n"
    "}"
)
COMMIT_URL = "https://example.invalid/synthetic/commit/001"
UNKNOWN_URL = "https://example.invalid/synthetic/commit/002"

# Neutral opaque references, identical file paths across versions.
SOURCES = {
    "s-a83f": {"src/copy.c": COPY},
    "s-592b": {"src/copy.c": CHECKED, "src/helper.c": HELPER},
    "s-7d21": {"src/copy.c": UNKNOWN},
}


class SyntheticAdapters:
    """Fixed in-memory fixtures, not a Git client, index or course exporter."""

    async def prepare_course(self, sample: CourseSample) -> DetectionInput:
        return await self.prepare_snapshot(
            SnapshotRequest(
                idx=sample.idx,
                func=sample.func,
                commit_url=sample.commit_url,
                revision="parent" if sample.target == 1 else "commit",
            )
        )

    async def prepare_snapshot(self, request: SnapshotRequest) -> DetectionInput:
        refs = {
            (COMMIT_URL, "parent"): "s-a83f",
            (COMMIT_URL, "commit"): "s-592b",
            (UNKNOWN_URL, "commit"): "s-7d21",
        }
        ref = refs.get((request.commit_url, request.revision))
        if ref is None:
            raise IntegrationError("synthetic_input_only", "演示仅支持 examples/synthetic.jsonl。")
        await self.locate_function(ref, request.func)
        return DetectionInput(idx=request.idx, func=request.func, snapshot_ref=ref)

    def _files(self, snapshot_ref: str) -> dict[str, str]:
        if snapshot_ref not in SOURCES:
            raise IntegrationError("snapshot_not_found", "合成快照不存在。")
        return SOURCES[snapshot_ref]

    async def locate_function(self, snapshot_ref: str, func: str) -> CodeLocation:
        content = self._files(snapshot_ref)["src/copy.c"]
        if func != content:
            raise IntegrationError("function_mismatch", "函数与合成快照不一致。")
        return CodeLocation(
            snapshot_ref=snapshot_ref,
            path="src/copy.c",
            start_line=1,
            end_line=1,
            content=content,
        )

    async def search_code(self, snapshot_ref: str, query: str) -> RepositoryResult:
        matches = [
            CodeLocation(
                snapshot_ref=snapshot_ref,
                path=path,
                start_line=1,
                end_line=len(content.splitlines()),
                content=content,
            )
            for path, content in self._files(snapshot_ref).items()
            if query in content
        ]
        return RepositoryResult(matches=matches, scope="synthetic literal substring search")

    async def read_file(
        self,
        snapshot_ref: str,
        path: str,
        start_line: int,
        end_line: int,
    ) -> RepositoryResult:
        files = self._files(snapshot_ref)
        if path not in files:
            raise IntegrationError("file_not_found", "合成快照内没有该文件。")
        lines = files[path].splitlines()
        if start_line < 1 or end_line < start_line or end_line > len(lines):
            raise IntegrationError("invalid_line_range", "行区间超出合成文件。")
        return RepositoryResult(
            matches=[
                CodeLocation(
                    snapshot_ref=snapshot_ref,
                    path=path,
                    start_line=start_line,
                    end_line=end_line,
                    content="\n".join(lines[start_line - 1 : end_line]),
                )
            ],
            scope="synthetic line slice",
        )

    async def find_symbol(self, snapshot_ref: str, symbol: str) -> RepositoryResult:
        result = await self.search_code(snapshot_ref, symbol)
        result.scope = "synthetic text matches only; not AST symbol resolution"
        return result

    async def search_cases(self, query: str, limit: int) -> list[HistoricalCase]:
        return [
            HistoricalCase(
                case_id="synthetic-history-001",
                content="Synthetic history: memcpy into a fixed buffer without a size check.",
                source="app.demo:artificial-history",
                trigger_conditions=[
                    HistoricalCondition(
                        statement="Copy length can exceed destination capacity",
                        source="app.demo:artificial-history",
                        excerpt="without a size check",
                    )
                ],
                safety_conditions=[
                    HistoricalCondition(
                        statement="Reject lengths larger than remaining destination capacity",
                        source="app.demo:artificial-history",
                        excerpt="fixed buffer",
                    )
                ],
            )
        ][:limit]

    def export(self, input_ids: Sequence[Idx], reports: Sequence[Report]) -> str:
        # The API checks completeness and orders reports before calling this fixture.
        by_id = {idx_key(report.idx): report for report in reports}
        return "".join(
            json.dumps({"idx": idx, "prediction": by_id[idx_key(idx)].prediction}) + "\n"
            for idx in input_ids
        )


class SyntheticModel:
    """Deterministic tool script for three exact fixtures, explicitly not an LLM."""

    def __init__(self):
        self.tools = set()
        self.step = 0

    def bind_tools(self, tools):
        self.tools = {tool.name for tool in tools}
        return self

    async def ainvoke(self, messages):
        func = next(m.content for m in messages if isinstance(m, HumanMessage))
        if func not in {COPY, CHECKED, UNKNOWN}:
            raise IntegrationError("synthetic_input_only", "脚本模型仅支持固定合成函数。")
        prediction = 1 if func == COPY else 0
        reason = {
            COPY: "合成脚本：调用中没有容量参数或上界检查，按预设示例输出 1。",
            CHECKED: (
                "合成脚本：helper 中先检查 n > cap；在 cap 表示有效容量的假设下反驳该越界条件。"
            ),
            UNKNOWN: (
                "合成脚本：外部函数实现未知，证据不足；"
                "预设输出 0，仅演示 unknown 可正常结束，不证明安全。"
            ),
        }[func]
        plan = []
        if "search_cases" in self.tools:
            plan.append(("search_cases", {"query": "copy length and capacity", "limit": 1}))
        hypothesis = {"id": "h1", "statement": "复制长度可能超过目标容量"}
        condition = {
            "id": "c1",
            "hypothesis_id": "h1",
            "statement": "复制长度可超过剩余容量",
            "status": "unknown",
            "evidence_ids": ["e1"],
            "reason": "尚未检查边界条件。",
        }
        if "update_conditions" in self.tools:
            plan.append(
                ("update_conditions", {"hypotheses": [hypothesis], "conditions": [condition]})
            )
        if "find_symbol" in self.tools:
            symbol = "external_copy" if func == UNKNOWN else "copy_checked"
            plan.append(("find_symbol", {"symbol": symbol}))
        if "update_conditions" in self.tools:
            ids = ["e1"]
            for message in messages:
                if isinstance(message, ToolMessage):
                    ids.extend(
                        match["evidence_id"]
                        for match in json.loads(message.content).get("matches", [])
                        if match["evidence_id"] not in ids
                    )
            status = {COPY: "supported", CHECKED: "refuted", UNKNOWN: "unknown"}[func]
            final_condition = {**condition, "status": status, "evidence_ids": ids, "reason": reason}
            plan.append(
                (
                    "update_conditions",
                    {
                        "hypotheses": [hypothesis],
                        "conditions": [final_condition],
                    },
                )
            )
        plan.append(("finish", {"prediction": prediction, "reason": reason}))
        name, arguments = plan[self.step]
        self.step += 1
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": name,
                    "args": arguments,
                    "id": f"synthetic-{self.step}",
                }
            ],
        )


def demo_services() -> Services:
    adapters = SyntheticAdapters()
    config = RunConfig(
        model="synthetic-script-not-an-llm",
        data_version="synthetic-v1",
        index_version="synthetic-history-v1",
    )
    return Services(
        runner=AgentRunner(adapters, adapters, lambda config: SyntheticModel(), config),
        preparation=adapters,
        exporter=adapters,
        config=config,
    )


def build_app():
    return create_app(
        demo_services(),
        os.getenv("FVA_DB_PATH", "artifacts/demo-tasks.sqlite3"),
        concurrency=int(os.getenv("FVA_CONCURRENCY", "2")),
    )
