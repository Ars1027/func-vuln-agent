import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.api import create_app
from app.schemas.models import DetectionInput, Measurement, Report, RunConfig
from app.schemas.ports import AnalysisError, IntegrationError, Services
from fastapi.testclient import TestClient


class Preparation:
    def __init__(self):
        self.course_calls = []

    async def prepare_course(self, sample):
        self.course_calls.append(sample.idx)
        return DetectionInput(idx=sample.idx, func=sample.func, snapshot_ref="prepared")

    async def prepare_snapshot(self, request):
        return DetectionInput(idx=request.idx, func=request.func, snapshot_ref="snapshot")


class Exporter:
    def export(self, input_ids, reports):
        return "".join(
            json.dumps({"idx": idx, "prediction": report.prediction}) + "\n"
            for idx, report in zip(input_ids, reports, strict=True)
        )


class Runner:
    def __init__(self, gate=None):
        self.gate = gate
        self.calls = []

    async def run(self, sample, mode, emit):
        self.calls.append((sample, mode))
        evidence = {
            "id": "e1",
            "kind": "code",
            "snapshot_ref": sample.snapshot_ref,
            "path": "src/a.c",
            "start_line": 1,
            "end_line": 1,
            "content": sample.func,
        }
        await emit(
            "condition_update",
            {
                "hypotheses": [{"id": "h1", "statement": "overflow"}],
                "conditions": [
                    {
                        "id": "c1",
                        "hypothesis_id": "h1",
                        "statement": "too long",
                        "status": "unknown",
                        "evidence_ids": ["e1"],
                        "reason": "pending",
                    }
                ],
                "evidence": [evidence],
            },
        )
        await emit(
            "repository_read",
            {
                "tool": "read_file",
                "arguments": {"path": "src/a.c"},
                "matches": [
                    {"path": "src/a.c", "start_line": 1, "end_line": 1, "evidence_id": "e1"}
                ],
                "scope": "snapshot",
                "summary": "read current code",
                "evidence_ids": ["e1"],
            },
        )
        if self.gate is not None and sample.idx == "pending":
            await self.gate.wait()
        if sample.idx == "bad":
            raise AnalysisError(
                "tool_failed",
                "Repository read failed.",
                Measurement(
                    idx=sample.idx,
                    mode=mode,
                    config=RunConfig(),
                    status="failed",
                ),
            )
        return Report(
            idx=sample.idx,
            prediction=1,
            reason="Synthetic evidence.",
            hypotheses=[{"id": "h1", "statement": "overflow"}],
            conditions=[
                {
                    "id": "c1",
                    "hypothesis_id": "h1",
                    "statement": "too long",
                    "status": "supported",
                    "evidence_ids": ["e1"],
                    "reason": "seen",
                }
            ],
            evidence=[evidence],
            trace=[
                {
                    "tool": "read_file",
                    "arguments": {"path": "src/a.c"},
                    "summary": "read current code",
                    "evidence_ids": ["e1"],
                }
            ],
        ), Measurement(idx=sample.idx, mode=mode, config=RunConfig(), status="completed")


def app_for(path: Path, runner=None, config=None):
    runner = runner or Runner()
    preparation = Preparation()
    app = create_app(Services(runner, preparation, Exporter(), config or RunConfig()), path)
    return app, runner, preparation


def wait_status(client, task_id, status):
    for _ in range(100):
        view = client.get(f"/api/tasks/{task_id}").json()
        if view["status"] == status:
            return view
        time.sleep(0.01)
    raise AssertionError(f"Task did not reach {status}: {view}")


def test_detection_modes_strict_input_snapshot_and_replay(tmp_path):
    app, runner, _ = app_for(tmp_path / "tasks.db")
    with TestClient(app) as client:
        invalid = client.post(
            "/api/detections",
            json={
                "idx": 1,
                "func": "f",
                "snapshot_ref": "s",
                "target": 1,
            },
        )
        assert invalid.status_code == 422
        assert invalid.json()["code"] == "invalid_request"
        assert (
            client.post(
                "/api/detections",
                json={
                    "idx": 1,
                    "func": "f",
                    "snapshot_ref": "s",
                    "mode": "unknown",
                },
            ).status_code
            == 422
        )
        snapshot = client.post(
            "/api/snapshots",
            json={
                "idx": 1,
                "func": "f",
                "commit_url": "https://example.test/commit/a",
                "revision": "parent",
            },
        )
        assert snapshot.json() == {"idx": 1, "func": "f", "snapshot_ref": "snapshot"}

        created = client.post(
            "/api/detections",
            json={
                "idx": 1,
                "func": "f",
                "snapshot_ref": "s",
                "mode": "rag_context",
            },
        )
        assert created.status_code == 202
        task_id = created.json()["task_id"]
        assert wait_status(client, task_id, "completed")["mode"] == "rag_context"
        assert runner.calls[0][1] == "rag_context"
        assert "mode" not in runner.calls[0][0].model_fields_set
        snapshot = client.get(f"/api/tasks/{task_id}/reports").json()
        assert snapshot["seq"] >= 5
        assert snapshot["reports"][0]["prediction"] == 1
        stream = client.get(f"/api/tasks/{task_id}/events", headers={"Last-Event-ID": "0"})
        assert stream.status_code == 200
        assert "event: task_completed" in stream.text
        assert "id: 1\n" in stream.text
        assert client.get(f"/api/tasks/{task_id}/events?after_seq={snapshot['seq']}").text == ""
        assert (
            client.get(
                f"/api/tasks/{task_id}/events?after_seq=0", headers={"Last-Event-ID": "999"}
            ).text
            == stream.text
        )
        assert (
            client.get(f"/api/tasks/{task_id}/measurements").json()["measurements"][0]["mode"]
            == "rag_context"
        )


def test_batch_typed_ids_partial_failure_and_export_order(tmp_path):
    app, _, prep = app_for(tmp_path / "tasks.db")
    with TestClient(app) as client:
        rows = [
            {"idx": 1, "commit_url": "u", "target": 1, "func": "f"},
            {"idx": "1", "commit_url": "u", "target": 0, "func": "g"},
            {"idx": "bad", "commit_url": "u", "target": 1, "func": "h"},
        ]
        body = "\n".join(json.dumps(row) for row in rows)
        created = client.post(
            "/api/batches", files={"file": ("samples.jsonl", body)}, data={"mode": "function_only"}
        )
        assert created.status_code == 202
        task_id = created.json()["task_id"]
        view = wait_status(client, task_id, "failed")
        assert view["completed"] == 2
        assert view["failures"] == [
            {"idx": "bad", "code": "tool_failed", "message": "Repository read failed."}
        ]
        assert set(prep.course_calls) == {1, "1", "bad"}
        report_snapshot = client.get(f"/api/tasks/{task_id}/reports").json()
        assert [type(r["idx"]) for r in report_snapshot["reports"]] == [int, str]
        assert report_snapshot["active_samples"] == []
        assert report_snapshot["failed_samples"][0]["idx"] == "bad"
        assert client.get(f"/api/tasks/{task_id}/result.jsonl").status_code == 409
        measurements = client.get(f"/api/tasks/{task_id}/measurements").json()["measurements"]
        assert [m["status"] for m in measurements] == ["completed", "completed", "failed"]

        valid = client.post(
            "/api/batches",
            files={"file": ("samples.jsonl", "\n".join(json.dumps(row) for row in rows[:2]))},
        )
        good_id = valid.json()["task_id"]
        wait_status(client, good_id, "completed")
        result = client.get(f"/api/tasks/{good_id}/result.jsonl")
        assert result.status_code == 200
        assert [json.loads(line)["idx"] for line in result.text.splitlines()] == [1, "1"]


def test_invalid_batch_rejected_before_preparation(tmp_path):
    app, _, prep = app_for(tmp_path / "tasks.db")
    with TestClient(app) as client:
        duplicate = "\n".join(
            [
                json.dumps(
                    {
                        "idx": 1,
                        "commit_url": "u",
                        "target": 1,
                        "func": "f",
                    }
                )
            ]
            * 2
        )
        response = client.post("/api/batches", files={"file": ("x.jsonl", duplicate)})
        assert response.status_code == 422
        assert response.json()["code"] == "duplicate_idx"
        assert prep.course_calls == []
        invalid = client.post(
            "/api/batches",
            files={
                "file": (
                    "x.jsonl",
                    '{"idx": true, "commit_url": "u", "target": 1, "func": "f"}',
                )
            },
        )
        assert invalid.status_code == 422


def test_restart_keeps_finished_and_active_analysis(tmp_path):
    import asyncio

    db_path = tmp_path / "tasks.db"
    gate = asyncio.Event()
    app, _, _ = app_for(db_path, Runner(gate), RunConfig(model="original-model"))
    with TestClient(app) as client:
        rows = [
            {"idx": "done", "commit_url": "u", "target": 1, "func": "f"},
            {"idx": "pending", "commit_url": "u", "target": 1, "func": "g"},
        ]
        created = client.post(
            "/api/batches", files={"file": ("x.jsonl", "\n".join(json.dumps(row) for row in rows))}
        )
        task_id = created.json()["task_id"]
        for _ in range(100):
            state = client.get(f"/api/tasks/{task_id}/reports").json()
            if state["reports"] and state["active_samples"] and state["active_samples"][0]["trace"]:
                break
            time.sleep(0.01)
        else:
            raise AssertionError("Active trace was not persisted")
        prior_seq = state["seq"]
        assert state["active_samples"][0]["conditions"][0]["status"] == "unknown"
    restarted, _, _ = app_for(db_path, config=RunConfig(model="new-model"))
    with TestClient(restarted) as client:
        view = client.get(f"/api/tasks/{task_id}").json()
        assert view["status"] == "failed"
        assert view["failures"][0]["code"] == "interrupted"
        state = client.get(f"/api/tasks/{task_id}/reports").json()
        assert state["reports"][0]["idx"] == "done"
        assert state["active_samples"] == []
        assert state["failed_samples"][0]["trace"][0]["tool"] == "read_file"
        assert state["seq"] > prior_seq
        measurements = client.get(f"/api/tasks/{task_id}/measurements").json()["measurements"]
        assert measurements[1]["config"]["model"] == "original-model"
        assert measurements[1]["status"] == "failed"
        assert measurements[1]["model_calls"] is None
        assert measurements[1]["tool_calls"] is None
        assert measurements[1]["elapsed_seconds"] is None
        replay = client.get(f"/api/tasks/{task_id}/events?after_seq={prior_seq}").text
        assert "event: error" in replay
        assert "event: task_completed" in replay


def test_live_sse_continues_from_snapshot_without_gap(tmp_path):
    import asyncio

    gate = asyncio.Event()
    app, _, _ = app_for(tmp_path / "tasks.db", Runner(gate))
    with TestClient(app) as client:
        task_id = client.post(
            "/api/detections",
            json={
                "idx": "pending",
                "func": "f",
                "snapshot_ref": "s",
            },
        ).json()["task_id"]
        for _ in range(100):
            snapshot = client.get(f"/api/tasks/{task_id}/reports").json()
            if snapshot["active_samples"] and snapshot["active_samples"][0]["trace"]:
                break
            time.sleep(0.01)
        else:
            raise AssertionError("Active sample did not reach its trace update")
        with ThreadPoolExecutor(max_workers=1) as pool:
            url = f"/api/tasks/{task_id}/events?after_seq={snapshot['seq']}"
            stream = pool.submit(client.get, url)
            for _ in range(100):
                if app.state.store.subscribers.get(task_id):
                    break
                time.sleep(0.01)
            else:
                raise AssertionError("SSE listener did not subscribe")
            client.portal.call(gate.set)
            response = stream.result(timeout=2)
        event_ids = [
            int(line.removeprefix("id: "))
            for line in response.text.splitlines()
            if line.startswith("id: ")
        ]
        assert event_ids == list(range(snapshot["seq"] + 1, snapshot["seq"] + 3))
        assert "event: sample_completed" in response.text
        assert "event: task_completed" in response.text


def test_missing_task_and_unavailable_snapshot(tmp_path):
    class Unavailable(Preparation):
        async def prepare_snapshot(self, request):
            raise IntegrationError("adapter_unavailable", "Snapshot adapter unavailable.")

    app = create_app(
        Services(Runner(), Unavailable(), Exporter(), RunConfig()), tmp_path / "tasks.db"
    )
    with TestClient(app) as client:
        assert client.get("/api/tasks/missing").status_code == 404
        response = client.post(
            "/api/snapshots",
            json={
                "idx": 1,
                "func": "f",
                "commit_url": "u",
                "revision": "commit",
            },
        )
        assert response.status_code == 503
        assert response.json()["code"] == "adapter_unavailable"


def test_preparation_timeout_and_unexpected_adapter_errors_are_recorded(tmp_path):
    import asyncio

    class SlowPreparation(Preparation):
        async def prepare_course(self, sample):
            await asyncio.sleep(1)

        async def prepare_snapshot(self, request):
            raise RuntimeError("private adapter detail")

    class FailingExporter:
        def export(self, input_ids, reports):
            raise RuntimeError("private export detail")

    config = RunConfig(timeout_seconds=0.01)
    app = create_app(
        Services(Runner(), SlowPreparation(), FailingExporter(), config), tmp_path / "tasks.db"
    )
    with TestClient(app) as client:
        created = client.post(
            "/api/batches",
            files={
                "file": (
                    "x.jsonl",
                    json.dumps(
                        {
                            "idx": 7,
                            "commit_url": "u",
                            "target": 1,
                            "func": "f",
                        }
                    ),
                )
            },
        )
        task_id = created.json()["task_id"]
        assert (
            wait_status(client, task_id, "failed")["failures"][0]["code"] == "preparation_timeout"
        )
        measurement = client.get(f"/api/tasks/{task_id}/measurements").json()["measurements"][0]
        assert measurement["status"] == "failed"
        assert measurement["config"]["timeout_seconds"] == 0.01
        snapshot = client.post(
            "/api/snapshots",
            json={
                "idx": 7,
                "func": "f",
                "commit_url": "u",
                "revision": "commit",
            },
        )
        assert snapshot.status_code == 503
        assert "private" not in snapshot.text

    class GoodPreparation(Preparation):
        pass

    app = create_app(
        Services(Runner(), GoodPreparation(), FailingExporter(), RunConfig()),
        tmp_path / "export.db",
    )
    with TestClient(app) as client:
        task_id = client.post(
            "/api/detections",
            json={
                "idx": 7,
                "func": "f",
                "snapshot_ref": "s",
            },
        ).json()["task_id"]
        wait_status(client, task_id, "completed")
        export = client.get(f"/api/tasks/{task_id}/result.jsonl")
        assert export.status_code == 503
        assert export.json()["code"] == "internal_error"
        assert "private" not in export.text
