import asyncio
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
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
    def __init__(self, gate=None, config=None):
        self.gate = gate
        self.config = config or RunConfig()
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
                    config=self.config,
                    status="failed",
                ),
            )
        return Report(
            idx=sample.idx,
            prediction=0 if sample.idx == "1" else 1,
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
        ), Measurement(idx=sample.idx, mode=mode, config=self.config, status="completed")


def app_for(path: Path, runner=None, config=None, preparation=None, **options):
    runner = runner or Runner(config=config)
    if config is not None:
        runner.config = config
    preparation = preparation or Preparation()
    app = create_app(Services(runner, preparation, Exporter(), runner.config), path, **options)
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
        assert [json.loads(line) for line in result.text.splitlines()] == [
            {"idx": 1, "prediction": 1},
            {"idx": "1", "prediction": 0},
        ]


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


def test_preparation_timeout_and_unexpected_adapter_errors_are_recorded(tmp_path, caplog):
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
        Services(Runner(config=config), SlowPreparation(), FailingExporter(), config),
        tmp_path / "tasks.db",
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
    assert "create_snapshot failed" in caplog.text
    assert "export_result failed" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "test_api.py:" in caplog.text
    assert "private adapter detail" not in caplog.text
    assert "private export detail" not in caplog.text


def submit_batch(client, ids):
    rows = [{"idx": idx, "commit_url": "u", "target": 1, "func": "f"} for idx in ids]
    return client.post(
        "/api/batches", files={"file": ("x.jsonl", "\n".join(json.dumps(row) for row in rows))}
    )


@pytest.mark.parametrize("endpoint", ["batches", "snapshots"])
@pytest.mark.parametrize("field", ["idx", "func"])
@pytest.mark.parametrize("in_place", [False, True])
def test_preparation_preserves_original_idx_and_func(tmp_path, endpoint, field, in_place):
    class ChangedPreparation(Preparation):
        async def changed(self, value):
            changed = {"idx": value.idx, "func": value.func, "snapshot_ref": "prepared"}
            changed[field] = "1" if field == "idx" else "changed function"
            if in_place:
                setattr(value, field, changed[field])
            await asyncio.sleep(0)
            return DetectionInput(**changed)

        prepare_course = changed
        prepare_snapshot = changed

    app, runner, _ = app_for(tmp_path / "tasks.db", preparation=ChangedPreparation())
    with TestClient(app) as client:
        if endpoint == "batches":
            task_id = submit_batch(client, [1]).json()["task_id"]
            failure = wait_status(client, task_id, "failed")["failures"][0]
            measurement = client.get(f"/api/tasks/{task_id}/measurements").json()["measurements"][0]
            assert measurement["model_calls"] == measurement["tool_calls"] == 0
        else:
            response = client.post(
                "/api/snapshots",
                json={"idx": 1, "func": "f", "commit_url": "u", "revision": "commit"},
            )
            assert response.status_code == 503
            failure = response.json()
        assert failure["code"] == "preparation_mismatch"
        assert failure["idx"] == 1
        assert runner.calls == []


@pytest.mark.parametrize("failed", [False, True])
def test_measurement_elapsed_includes_preparation(tmp_path, monkeypatch, failed):
    now = 0

    class TimedPreparation(Preparation):
        async def prepare_course(self, sample):
            nonlocal now
            now += 5
            return await super().prepare_course(sample)

    class TimedRunner(Runner):
        async def run(self, sample, mode, emit):
            nonlocal now
            report, measurement = await super().run(sample, mode, emit)
            now += 3
            measurement = measurement.model_copy(
                update={"elapsed_seconds": 1, "model_calls": 7, "tool_calls": 2}
            )
            if failed:
                measurement.status = "failed"
                raise AnalysisError("tool_failed", "Tool failed.", measurement)
            return report, measurement

    monkeypatch.setattr("app.api.service.time.perf_counter", lambda: now)
    app, _, _ = app_for(tmp_path / "tasks.db", TimedRunner(), preparation=TimedPreparation())
    with TestClient(app) as client:
        task_id = submit_batch(client, [1]).json()["task_id"]
        wait_status(client, task_id, "failed" if failed else "completed")
        measurement = client.get(f"/api/tasks/{task_id}/measurements").json()["measurements"][0]
        assert measurement["elapsed_seconds"] == 8
        assert measurement["model_calls"] == 7
        assert measurement["tool_calls"] == 2


@pytest.mark.parametrize("failed", [False, True])
def test_mismatched_measurement_config_discards_untrusted_costs(tmp_path, failed):
    class WrongMeasurementRunner(Runner):
        async def run(self, sample, mode, emit):
            report, measurement = await super().run(sample, mode, emit)
            measurement = measurement.model_copy(
                update={
                    "config": RunConfig(model="wrong-model"),
                    "model_calls": 99,
                    "tool_calls": 99,
                    "input_tokens": 99,
                    "output_tokens": 99,
                    "elapsed_seconds": 999,
                    "status": "failed" if failed else "completed",
                }
            )
            if failed:
                raise AnalysisError("model_failed", "Model failed.", measurement)
            return report, measurement

    app, runner, _ = app_for(tmp_path / "tasks.db", WrongMeasurementRunner())
    with TestClient(app) as client:
        task_id = submit_batch(client, [1]).json()["task_id"]
        wait_status(client, task_id, "failed")
        measurement = client.get(f"/api/tasks/{task_id}/measurements").json()["measurements"][0]
        assert measurement["config"] == runner.config.model_dump()
        assert measurement["model_calls"] is None
        assert measurement["tool_calls"] is None
        assert measurement["input_tokens"] is None
        assert measurement["output_tokens"] is None
        assert measurement["elapsed_seconds"] < 999


@pytest.mark.parametrize(
    "operation", ["start", "start_sample", "finish_completed", "finish_failed", "complete"]
)
def test_storage_worker_failure_retains_results_and_joins_children(
    tmp_path, monkeypatch, caplog, operation
):
    class CancellableRunner(Runner):
        def __init__(self):
            super().__init__()
            self.cancelled_and_joined = False

        async def run(self, sample, mode, emit):
            result = await super().run(sample, mode, emit)
            if sample.idx == "pending":
                try:
                    await asyncio.Event().wait()
                finally:
                    await asyncio.sleep(0.01)
                    self.cancelled_and_joined = True
            return result

    runner = Runner() if operation == "complete" else CancellableRunner()
    app, _, _ = app_for(tmp_path / "tasks.db", runner, concurrency=3)
    method = "finish_sample" if operation.startswith("finish_") else operation
    original = getattr(app.state.store, method)
    injected = False

    def broken(*args):
        nonlocal injected
        if not injected and (method not in {"start_sample", "finish_sample"} or args[1] == 2):
            injected = True
            if operation == "finish_failed":
                assert args[3].code == "tool_failed"
            raise sqlite3.OperationalError("secret credential and function source")
        return original(*args)

    monkeypatch.setattr(app.state.store, method, broken)
    with TestClient(app) as client:
        last_idx = "bad" if operation == "finish_failed" else "broken"
        task_id = submit_batch(client, ["done", "pending", last_idx]).json()["task_id"]
        state = wait_status(client, task_id, "failed")
        snapshot = client.get(f"/api/tasks/{task_id}/reports").json()
        measurements = client.get(f"/api/tasks/{task_id}/measurements").json()["measurements"]
        assert snapshot["active_samples"] == []
        assert client.get(f"/api/tasks/{task_id}/result.jsonl").status_code == 409
        if operation == "start":
            assert state["completed"] == 0
            assert len(state["failures"]) == 3
            assert all(item["model_calls"] == 0 for item in measurements)
        elif operation in {"start_sample", "finish_completed", "finish_failed"}:
            assert state["completed"] == 1
            assert snapshot["reports"][0]["idx"] == "done"
            assert runner.cancelled_and_joined
            assert snapshot["failed_samples"][0]["idx"] == "pending"
            assert snapshot["failed_samples"][0]["trace"]
            assert measurements[1]["model_calls"] is None
            assert measurements[2]["model_calls"] == (0 if operation == "start_sample" else None)
        else:
            assert state["completed"] == 3
            assert state["failures"] == []
            assert len(snapshot["reports"]) == 3
        stream = client.get(f"/api/tasks/{task_id}/events").text
        assert "event: task_completed" in stream
        if operation == "complete":
            events = [
                json.loads(line.removeprefix("data: "))
                for line in stream.splitlines()
                if line.startswith("data: ")
            ]
            error = next(event for event in events if event["type"] == "error")
            assert error["idx"] is None
            assert error["payload"]["code"] == "internal_error"
    assert "run_task failed" in caplog.text
    assert "OperationalError" in caplog.text
    assert "secret credential and function source" not in caplog.text


def test_unavailable_storage_abort_is_logged_and_restart_recovers(tmp_path, monkeypatch, caplog):
    path = tmp_path / "tasks.db"
    app, _, _ = app_for(path)

    def offline(*args):
        raise sqlite3.OperationalError("private database detail")

    monkeypatch.setattr(app.state.store, "start", offline)
    monkeypatch.setattr(app.state.store, "abort", offline)
    with TestClient(app) as client:
        task_id = submit_batch(client, [1]).json()["task_id"]
        for _ in range(100):
            if "abort_task failed" in caplog.text:
                break
            time.sleep(0.01)
        assert "abort_task failed" in caplog.text
        assert client.get(f"/api/tasks/{task_id}").json()["status"] == "queued"
    restarted, _, _ = app_for(path)
    with TestClient(restarted) as client:
        assert wait_status(client, task_id, "failed")["failures"][0]["code"] == "interrupted"
    assert "private database detail" not in caplog.text


def test_unexpected_sample_failure_logs_locations_without_details(tmp_path, caplog):
    class BrokenRunner(Runner):
        async def run(self, sample, mode, emit):
            raise RuntimeError("secret model credential and code")

    app, _, _ = app_for(tmp_path / "tasks.db", BrokenRunner())
    with TestClient(app) as client:
        task_id = submit_batch(client, [1]).json()["task_id"]
        failure = wait_status(client, task_id, "failed")["failures"][0]
        assert failure["code"] == "internal_error"
    assert "run_sample failed" in caplog.text
    assert "RuntimeError" in caplog.text
    assert task_id in caplog.text
    assert "test_api.py:" in caplog.text
    assert "secret model credential and code" not in caplog.text


async def test_sse_cleanup_preserves_other_subscribers_and_removes_empty_set(tmp_path):
    app, _, _ = app_for(tmp_path / "tasks.db")
    store = app.state.store
    sample = DetectionInput(idx=1, func="f", snapshot_ref="s")
    task_id = store.create([("direct", sample)], "conditions")
    endpoint = next(route.endpoint for route in app.routes if route.path.endswith("/events"))

    class ConnectedRequest:
        async def is_disconnected(self):
            return False

    first = (await endpoint(task_id, ConnectedRequest(), 0, None)).body_iterator
    second = (await endpoint(task_id, ConnectedRequest(), 0, None)).body_iterator
    await anext(first)
    await anext(second)
    assert len(store.subscribers[task_id]) == 2
    await first.aclose()
    assert len(store.subscribers[task_id]) == 1
    await second.aclose()
    assert task_id not in store.subscribers
    store.close()


def test_batch_limits_reject_before_parsing_and_preparation(tmp_path):
    row = json.dumps({"idx": 1, "commit_url": "u", "target": 1, "func": "f"})
    app, runner, prep = app_for(
        tmp_path / "tasks.db", max_batch_bytes=len(row.encode()), max_batch_samples=1
    )
    with TestClient(app) as client:
        too_large = client.post(
            "/api/batches", files={"file": ("x.jsonl", b"\xff" * (len(row.encode()) + 1))}
        )
        assert too_large.status_code == 413
        assert too_large.json()["code"] == "batch_too_large"
        assert prep.course_calls == runner.calls == []
        task_id = client.post("/api/batches", files={"file": ("x.jsonl", row)}).json()["task_id"]
        wait_status(client, task_id, "completed")
    app, _, prep = app_for(tmp_path / "samples.db", max_batch_samples=1)
    with TestClient(app) as client:
        response = client.post("/api/batches", files={"file": ("x.jsonl", row + "\nnot json")})
        assert response.status_code == 413
        assert prep.course_calls == []


@pytest.mark.parametrize("option", ["max_batch_bytes", "max_batch_samples"])
@pytest.mark.parametrize("value", [0, -1])
def test_batch_limits_must_be_positive(tmp_path, option, value):
    with pytest.raises(ValueError, match="batch limits"):
        app_for(tmp_path / "tasks.db", **{option: value})
