import asyncio

import pytest
from app.agent import AgentRunner
from app.agent.runner import update_conditions
from app.schemas.models import (
    CodeLocation,
    DetectionInput,
    HistoricalCase,
    HistoricalCondition,
    RepositoryResult,
    RunConfig,
)
from app.schemas.ports import AnalysisError, IntegrationError
from langchain_core.messages import AIMessage, ToolMessage

FUNC = "void copy(char *dst, char *src, size_t n) { memcpy(dst, src, n); }"


def call(name, args, tokens=True):
    message = AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": f"call-{name}"}],
    )
    if tokens:
        message.usage_metadata = {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14}
    return message


class ScriptModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.tools = []
        self.seen = []

    def bind_tools(self, tools):
        self.tools = [tool.name for tool in tools]
        return self

    async def ainvoke(self, messages):
        self.seen.append(list(messages))
        return self.responses.pop(0)


class FakeRepository:
    def __init__(self):
        self.calls = []
        self.wrong_snapshot = False

    def location(self, snapshot, content=FUNC, line=10):
        if self.wrong_snapshot:
            snapshot = "other-snapshot"
        return CodeLocation(
            snapshot_ref=snapshot,
            path="src/copy.c",
            start_line=line,
            end_line=line,
            content=content,
        )

    async def locate_function(self, snapshot_ref, func):
        self.calls.append(("locate", snapshot_ref, func))
        return self.location(snapshot_ref)

    async def search_code(self, snapshot_ref, query):
        self.calls.append(("search", snapshot_ref, query))
        return RepositoryResult(
            matches=[
                self.location(
                    snapshot_ref,
                    "if (n > remaining) return;",
                    7,
                )
            ]
        )

    async def read_file(self, snapshot_ref, path, start_line, end_line):
        self.calls.append(("read", snapshot_ref, path, start_line, end_line))
        return RepositoryResult(
            matches=[
                self.location(
                    snapshot_ref,
                    "if (n > remaining) return;",
                    7,
                )
            ]
        )

    async def find_symbol(self, snapshot_ref, symbol):
        self.calls.append(("symbol", snapshot_ref, symbol))
        return RepositoryResult(
            matches=[
                self.location(
                    snapshot_ref,
                    "size_t remaining = capacity - used;",
                    6,
                )
            ],
            scope="definition",
        )


class FakeRetriever:
    def __init__(self):
        self.calls = []

    async def search_cases(self, query, limit):
        self.calls.append((query, limit))
        return [
            HistoricalCase(
                case_id="history-1",
                source="train.jsonl:4",
                content="Past unchecked copy",
                trigger_conditions=[
                    HistoricalCondition(
                        statement="length exceeds capacity",
                        source="train.jsonl:4",
                        excerpt="memcpy",
                    )
                ],
                safety_conditions=[
                    HistoricalCondition(
                        statement="bound check covers copy",
                        source="train.jsonl:5",
                        excerpt="if (n > cap)",
                    )
                ],
            )
        ]


def sample(idx=1, snapshot="opaque-one"):
    return DetectionInput(idx=idx, func=FUNC, snapshot_ref=snapshot)


def test_model_tool_schema_exposes_condition_fields():
    schema = update_conditions.args_schema.model_json_schema()
    assert schema["properties"]["conditions"]["items"]["$ref"] == "#/$defs/Condition"
    assert {"id", "hypothesis_id", "statement", "status", "reason"} <= set(
        schema["$defs"]["Condition"]["required"]
    )
    assert "evidence_ids" in schema["$defs"]["Condition"]["properties"]


def update(status, evidence_ids, reason):
    return call(
        "update_conditions",
        {
            "hypotheses": [{"id": "h1", "statement": "copy may overflow destination"}],
            "conditions": [
                {
                    "id": "c1",
                    "hypothesis_id": "h1",
                    "statement": "length can exceed remaining capacity",
                    "status": status,
                    "evidence_ids": evidence_ids,
                    "reason": reason,
                }
            ],
        },
    )


async def run_script(
    responses, mode="conditions", repo=None, retriever=None, config=None, target=None
):
    repo = repo or FakeRepository()
    retriever = retriever or FakeRetriever()
    model = ScriptModel(responses)
    events = []

    async def emit(kind, payload):
        events.append((kind, payload))

    runner = AgentRunner(repo, retriever, lambda _: model, config or RunConfig(model="script"))
    report, measurement = await runner.run(target or sample(), mode, emit)
    return report, measurement, events, repo, retriever, model


@pytest.mark.parametrize("status,prediction", [("supported", 1), ("refuted", 0)])
async def test_condition_can_be_supported_or_refuted_by_current_code(status, prediction):
    report, measurement, events, repo, retriever, model = await run_script(
        [
            call("search_cases", {"query": "copy bounds", "limit": 3}),
            call("search_code", {"query": "remaining"}),
            update(status, ["e1", "e3"], "current code establishes this status"),
            call("finish", {"prediction": prediction, "reason": "current code and remaining risk"}),
        ]
    )
    assert report.prediction == prediction
    assert report.conditions[0].status == status
    assert [e.id for e in report.evidence] == ["e1", "e2", "e3"]
    assert [e.kind for e in report.evidence] == ["code", "historical", "code"]
    assert measurement.model_calls == 4 and measurement.tool_calls == 3
    assert measurement.input_tokens == 40 and measurement.output_tokens == 16
    assert {kind for kind, _ in events} == {"retrieval", "repository_read", "condition_update"}
    assert events[0][0] == "condition_update"
    assert events[0][1]["evidence"][0]["id"] == "e1"
    assert events[1][0] == "repository_read"
    retrieval_position = next(i for i, event in enumerate(events) if event[0] == "retrieval")
    assert events[retrieval_position - 1][1]["evidence"][0]["id"] == "e2"
    assert all(call_[1] == "opaque-one" for call_ in repo.calls)
    assert retriever.calls == [("copy bounds", 3)]
    assert all("opaque-one" not in str(messages) for messages in model.seen)
    assert "trigger_conditions" in str(model.seen)


async def test_unknown_condition_and_cross_function_investigation():
    report, _, _, repo, _, _ = await run_script(
        [
            call("find_symbol", {"symbol": "remaining"}),
            call("read_file", {"path": "src/copy.c", "start_line": 7, "end_line": 7}),
            update("unknown", ["e1", "e2", "e3"], "call path remains unresolved"),
            call("finish", {"prediction": 0, "reason": "unknown call path limits judgment"}),
        ]
    )
    assert report.conditions[0].status == "unknown"
    assert report.prediction == 0
    assert [item.tool for item in report.trace] == ["locate_function", "find_symbol", "read_file"]
    assert [call_[0] for call_ in repo.calls] == ["locate", "symbol", "read"]


async def test_modes_hide_extra_context_and_function_only_never_reads_repository():
    repo = FakeRepository()
    report, _, _, _, _, model = await run_script(
        [call("finish", {"prediction": 0, "reason": "function alone is inconclusive"})],
        mode="function_only",
        repo=repo,
        target=sample("1", "secret-ref"),
    )
    assert report.idx == "1" and not report.evidence
    assert repo.calls == []
    assert model.tools == ["finish"]
    visible = str(model.seen)
    assert "secret-ref" not in visible and "'idx'" not in visible

    _, zero_budget_measure, _, _, _, _ = await run_script(
        [call("finish", {"prediction": 0, "reason": "function only"})],
        mode="function_only",
        config=RunConfig(model="script", max_tool_calls=0),
    )
    assert zero_budget_measure.tool_calls == 0

    _, _, _, _, _, rag_model = await run_script(
        [
            call("search_cases", {"query": "copy"}),
            call("finish", {"prediction": 0, "reason": "no current proof"}),
        ],
        mode="rag_context",
    )
    assert "update_conditions" not in rag_model.tools
    tool_text = " ".join(
        str(message.content)
        for turn in rag_model.seen
        for message in turn
        if isinstance(message, ToolMessage)
    )
    assert "trigger_conditions" not in tool_text
    assert "safety_conditions" not in tool_text


@pytest.mark.parametrize("bad_evidence", [["e999"], ["e2"]])
async def test_forged_or_historical_only_evidence_rejected(bad_evidence):
    responses = [
        call("search_cases", {"query": "copy"}),
        update("supported", bad_evidence, "unsupported claim"),
    ]
    with pytest.raises(AnalysisError) as caught:
        await run_script(responses)
    assert caught.value.code == "malformed_model_output"
    assert caught.value.measurement.status == "failed"


async def test_wrong_snapshot_and_budget_fail_explicitly():
    repo = FakeRepository()
    repo.wrong_snapshot = True
    with pytest.raises(AnalysisError) as caught:
        await run_script([call("finish", {"prediction": 0, "reason": "x"})], repo=repo)
    assert caught.value.code == "snapshot_mismatch"
    assert caught.value.measurement.tool_calls == 1

    with pytest.raises(AnalysisError) as caught:
        await run_script(
            [call("search_code", {"query": "copy"})],
            config=RunConfig(model="script", max_tool_calls=1),
        )
    assert caught.value.code == "budget_exhausted"
    assert caught.value.measurement.status == "failed"

    with pytest.raises(AnalysisError) as caught:
        await run_script(
            [call("search_code", {"query": "copy"})],
            config=RunConfig(model="script", max_model_calls=1),
        )
    assert caught.value.code == "budget_exhausted"
    assert caught.value.measurement.model_calls == 1


async def test_model_timeout_and_tool_failure_have_distinct_errors():
    class SlowModel(ScriptModel):
        async def ainvoke(self, messages):
            await asyncio.sleep(0.1)
            return await super().ainvoke(messages)

    async def emit(_kind, _payload):
        pass

    runner = AgentRunner(
        FakeRepository(),
        FakeRetriever(),
        lambda _: SlowModel([call("finish", {"prediction": 0, "reason": "r"})]),
        RunConfig(model="script", timeout_seconds=0.01),
    )
    with pytest.raises(AnalysisError) as caught:
        await runner.run(sample(), "conditions", emit)
    assert caught.value.code == "timeout"
    assert caught.value.measurement.model_calls == 1
    assert caught.value.measurement.input_tokens is None

    class BrokenRepository(FakeRepository):
        async def search_code(self, snapshot_ref, query):
            raise RuntimeError("private adapter detail")

    with pytest.raises(AnalysisError) as caught:
        await run_script([call("search_code", {"query": "copy"})], repo=BrokenRepository())
    assert caught.value.code == "tool_failed"
    assert "private" not in caught.value.message

    async def fail_with_integration_error(_snapshot_ref, _query):
        raise IntegrationError("repository_missing", "Requested file was not found.")

    repo = FakeRepository()
    repo.search_code = fail_with_integration_error
    with pytest.raises(AnalysisError) as caught:
        await run_script([call("search_code", {"query": "copy"})], repo=repo)
    assert caught.value.code == "repository_missing"


async def test_model_failure_missing_usage_and_sample_isolation():
    repo = FakeRepository()
    models = [
        ScriptModel(
            [
                call("search_code", {"query": "copy"}),
                call("finish", {"prediction": 1, "reason": "r"}, tokens=False),
            ]
        ),
        ScriptModel([call("finish", {"prediction": 0, "reason": "r"})]),
    ]
    runner = AgentRunner(repo, FakeRetriever(), lambda _: models.pop(0), RunConfig(model="script"))

    async def emit(_kind, _payload):
        pass

    first, measure = await runner.run(sample(1, "snapshot-a"), "conditions", emit)
    assert measure.input_tokens is None and measure.output_tokens is None
    second, _ = await runner.run(sample("1", "snapshot-b"), "conditions", emit)
    assert first.idx == 1 and second.idx == "1"
    assert first.evidence[0].snapshot_ref == "snapshot-a"
    assert second.evidence[0].snapshot_ref == "snapshot-b"
    assert first.evidence[0].id == second.evidence[0].id == "e1"

    with pytest.raises(AnalysisError) as caught:
        await run_script([AIMessage(content="I think it is safe")])
    assert caught.value.code == "malformed_model_output"
    assert caught.value.measurement.model_calls == 1

    with pytest.raises(AnalysisError) as caught:
        await run_script([])
    assert caught.value.code == "model_failed"
    assert caught.value.measurement.input_tokens is None


async def test_tool_snapshot_argument_and_invalid_finish_are_rejected():
    with pytest.raises(AnalysisError) as caught:
        await run_script([call("search_code", {"query": "copy", "snapshot_ref": "other"})])
    assert caught.value.code == "malformed_model_output"

    with pytest.raises(AnalysisError) as caught:
        await run_script([call("finish", {"prediction": 2, "reason": "invalid"})])
    assert caught.value.code == "malformed_model_output"

    repo = FakeRepository()
    with pytest.raises(AnalysisError) as caught:
        await run_script(
            [
                call("read_file", {"path": "../other.c", "start_line": 1, "end_line": 2}),
            ],
            repo=repo,
        )
    assert caught.value.code == "malformed_model_output"
    assert [item[0] for item in repo.calls] == ["locate"]
