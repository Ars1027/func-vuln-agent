from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

Idx = StrictInt | StrictStr
Mode = Literal["function_only", "rag_context", "conditions"]
TaskStatus = Literal["queued", "running", "completed", "failed"]
EventType = Literal[
    "task_status",
    "retrieval",
    "repository_read",
    "condition_update",
    "sample_completed",
    "error",
    "task_completed",
]
NonEmpty = Annotated[str, Field(min_length=1)]
Prediction = Annotated[StrictInt, Field(ge=0, le=1)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DetectionInput(Contract):
    idx: Idx
    func: NonEmpty
    snapshot_ref: NonEmpty


class DetectionRequest(DetectionInput):
    mode: Mode = "conditions"


class CourseSample(Contract):
    """Preparation/evaluation only; never pass this object to the model."""

    idx: Idx
    commit_url: NonEmpty
    target: Prediction
    func: NonEmpty


class SnapshotRequest(Contract):
    idx: Idx
    func: NonEmpty
    commit_url: NonEmpty
    revision: Literal["commit", "parent"]


class HistoricalCondition(Contract):
    statement: NonEmpty
    source: NonEmpty
    excerpt: NonEmpty


class HistoricalCase(Contract):
    case_id: NonEmpty
    content: str
    source: NonEmpty
    trigger_conditions: list[HistoricalCondition] = Field(default_factory=list)
    safety_conditions: list[HistoricalCondition] = Field(default_factory=list)


class CodeLocation(Contract):
    """Adapter guarantees that content is verbatim in this single snapshot."""

    snapshot_ref: NonEmpty
    path: NonEmpty
    start_line: Annotated[StrictInt, Field(ge=1)]
    end_line: Annotated[StrictInt, Field(ge=1)]
    content: str

    @model_validator(mode="after")
    def valid_location(self):
        if self.end_line < self.start_line:
            raise ValueError("end_line must be >= start_line")
        # Model-readable locations cannot expose Git metadata or escape the snapshot.
        parts = self.path.replace("\\", "/").split("/")
        if any(p.casefold() in {"..", ".git"} for p in parts) or self.path.startswith(("/", "\\")):
            raise ValueError("path must stay inside the snapshot, excluding .git")
        if ":" in self.path:
            raise ValueError("path must be relative")
        return self


class RepositoryResult(Contract):
    matches: list[CodeLocation] = Field(default_factory=list)
    scope: str = ""


class CodeEvidence(CodeLocation):
    id: NonEmpty
    kind: Literal["code"] = "code"


class HistoricalEvidence(Contract):
    id: NonEmpty
    kind: Literal["historical"] = "historical"
    content: str
    case_id: NonEmpty
    source: NonEmpty


Evidence = Annotated[CodeEvidence | HistoricalEvidence, Field(discriminator="kind")]


class Hypothesis(Contract):
    id: NonEmpty
    statement: NonEmpty


class Condition(Contract):
    id: NonEmpty
    hypothesis_id: NonEmpty
    statement: NonEmpty
    status: Literal["supported", "refuted", "unknown"]
    evidence_ids: list[str] = Field(default_factory=list)
    reason: NonEmpty


class TraceEntry(Contract):
    tool: str
    arguments: dict[str, Any]
    summary: str
    evidence_ids: list[str] = Field(default_factory=list)


class AnalysisState(Contract):
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    conditions: list[Condition] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    trace: list[TraceEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_references(self):
        for items in (self.hypotheses, self.conditions, self.evidence):
            ids = [item.id for item in items]
            if len(ids) != len(set(ids)):
                raise ValueError("IDs must be unique within each sample list")
        hypotheses = {h.id for h in self.hypotheses}
        evidence = {e.id: e for e in self.evidence}
        for condition in self.conditions:
            if condition.hypothesis_id not in hypotheses:
                raise ValueError("condition references unknown hypothesis")
            if any(eid not in evidence for eid in condition.evidence_ids):
                raise ValueError("condition references unknown evidence")
            if condition.status != "unknown" and not any(
                evidence[eid].kind == "code" for eid in condition.evidence_ids
            ):
                raise ValueError("supported/refuted conditions require code evidence")
        for entry in self.trace:
            if any(eid not in evidence for eid in entry.evidence_ids):
                raise ValueError("trace references unknown evidence")
        return self


class ActiveSample(AnalysisState):
    idx: Idx


class Report(AnalysisState):
    idx: Idx
    prediction: Prediction
    reason: NonEmpty


class RunConfig(Contract):
    model: str = "unconfigured"
    temperature: float = 0
    max_output_tokens: int = Field(default=2048, ge=1)
    max_model_calls: int = Field(default=16, ge=1)
    max_tool_calls: int = Field(default=32, ge=0)
    timeout_seconds: float = Field(default=120, gt=0)
    data_version: str | None = None
    index_version: str | None = None
    prompt_version: str = "conditions-v1"


class Measurement(Contract):
    idx: Idx
    mode: Mode
    config: RunConfig
    model_calls: int | None = 0
    tool_calls: int | None = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    elapsed_seconds: float | None = 0
    status: Literal["completed", "failed"]


class Failure(Contract):
    idx: Idx
    code: str
    message: str


class Event(Contract):
    task_id: str
    seq: int
    timestamp: datetime
    type: EventType
    payload: dict[str, Any]
    idx: Idx | None = None


class ReportsSnapshot(Contract):
    task_id: str
    seq: int
    reports: list[Report] = Field(default_factory=list)
    active_samples: list[ActiveSample] = Field(default_factory=list)
    failed_samples: list[ActiveSample] = Field(default_factory=list)
    failures: list[Failure] = Field(default_factory=list)


class TaskView(Contract):
    task_id: str
    status: TaskStatus
    mode: Mode
    total: int
    completed: int
    failures: list[Failure]


def idx_key(idx: Idx) -> tuple[type, int | str]:
    """JSON integer 1 and string '1' identify different samples."""
    return type(idx), idx
