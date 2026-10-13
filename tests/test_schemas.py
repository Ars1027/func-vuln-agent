import pytest
from app.schemas.models import (
    AnalysisState,
    CodeEvidence,
    Condition,
    DetectionRequest,
    HistoricalEvidence,
    Hypothesis,
    Report,
    idx_key,
)
from pydantic import ValidationError


def test_identifiers_keep_json_types_and_forbid_labels_in_detection_input():
    a = DetectionRequest(idx=1, func="void f() {}", snapshot_ref="s")
    b = DetectionRequest(idx="1", func="void f() {}", snapshot_ref="s")
    assert idx_key(a.idx) != idx_key(b.idx)
    for extra in ({"target": 0}, {"revision": "parent"}, {"commit_url": "secret"}):
        with pytest.raises(ValidationError):
            DetectionRequest(**a.model_dump(), **extra)
    for idx in (True, 1.5, None):
        with pytest.raises(ValidationError):
            DetectionRequest(idx=idx, func="f", snapshot_ref="s")


def test_condition_references_and_polarity_require_code_evidence():
    hypothesis = Hypothesis(id="h", statement="复制可能越界")
    historical = HistoricalEvidence(id="e", content="synthetic", case_id="c", source="fixture")
    condition = Condition(
        id="c",
        hypothesis_id="h",
        statement="长度可以超过容量",
        status="unknown",
        evidence_ids=["e"],
        reason="尚未定位当前代码",
    )
    AnalysisState(hypotheses=[hypothesis], conditions=[condition], evidence=[historical])
    for status in ("supported", "refuted"):
        condition.status = status
        with pytest.raises(ValidationError, match="code evidence"):
            AnalysisState(hypotheses=[hypothesis], conditions=[condition], evidence=[historical])
    code = CodeEvidence(
        id="e",
        snapshot_ref="s",
        path="src/c.c",
        start_line=1,
        end_line=1,
        content="if (n > capacity) return;",
    )
    AnalysisState(hypotheses=[hypothesis], conditions=[condition], evidence=[code])
    condition.evidence_ids = ["missing"]
    with pytest.raises(ValidationError, match="unknown evidence"):
        AnalysisState(hypotheses=[hypothesis], conditions=[condition], evidence=[code])


@pytest.mark.parametrize("prediction", [False, True, "0", -1, 2])
def test_prediction_is_only_integer_zero_or_one(prediction):
    with pytest.raises(ValidationError):
        Report(idx=1, prediction=prediction, reason="reason")


@pytest.mark.parametrize(
    "path", ["../x", ".git/config", ".GIT/config", "src/../../x", "/etc/a", "C:/a"]
)
def test_code_locations_are_relative_snapshot_paths(path):
    with pytest.raises(ValidationError):
        CodeEvidence(
            id="e",
            snapshot_ref="s",
            path=path,
            start_line=1,
            end_line=1,
            content="x",
        )
