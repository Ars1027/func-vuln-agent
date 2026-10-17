import json
import time
from pathlib import Path

import pytest
from app.api.service import create_app
from app.demo import CHECKED, COMMIT_URL, demo_services
from app.main import build_app
from fastapi.testclient import TestClient


def wait_terminal(client, task_id):
    for _ in range(200):
        task = client.get(f"/api/tasks/{task_id}").json()
        if task["status"] in {"completed", "failed"}:
            return task
        time.sleep(0.01)
    raise AssertionError("Synthetic task failed to terminate")


@pytest.mark.parametrize("mode", ["function_only", "rag_context", "conditions"])
def test_offline_batch_runs_real_graph_and_api(tmp_path, mode):
    app = create_app(demo_services(), tmp_path / "demo.db")
    data = (Path(__file__).parents[1] / "examples/synthetic.jsonl").read_bytes()
    with TestClient(app) as client:
        response = client.post(
            "/api/batches",
            files={"file": ("synthetic.jsonl", data)},
            data={"mode": mode},
        )
        assert response.status_code == 202
        task_id = response.json()["task_id"]
        task = wait_terminal(client, task_id)
        assert task["status"] == "completed", task
        snapshot = client.get(f"/api/tasks/{task_id}/reports").json()
        reports = snapshot["reports"]
        assert [report["idx"] for report in reports] == [1, "1", "unknown"]
        if mode == "conditions":
            assert [r["conditions"][0]["status"] for r in reports] == [
                "supported",
                "refuted",
                "unknown",
            ]
            safe = reports[1]
            refs = safe["conditions"][0]["evidence_ids"]
            assert any(
                e["id"] in refs and e.get("path") == "src/helper.c" for e in safe["evidence"]
            )
        else:
            assert all(not r["conditions"] for r in reports)
        if mode == "function_only":
            assert all(not r["trace"] and not r["evidence"] for r in reports)
        output = client.get(f"/api/tasks/{task_id}/result.jsonl")
        assert [json.loads(line) for line in output.text.splitlines()] == [
            {"idx": 1, "prediction": 1},
            {"idx": "1", "prediction": 0},
            {"idx": "unknown", "prediction": 0},
        ]
        metrics = client.get(f"/api/tasks/{task_id}/measurements").json()["measurements"]
        assert len(metrics) == 3
        assert all(m["input_tokens"] is None and m["output_tokens"] is None for m in metrics)
        assert all(m["mode"] == mode and m["status"] == "completed" for m in metrics)
        events = client.get(f"/api/tasks/{task_id}/events").text
        ids = [
            int(line.removeprefix("id: ")) for line in events.splitlines() if line.startswith("id:")
        ]
        assert ids == list(range(1, snapshot["seq"] + 1))


def test_manual_snapshot_and_single_detection(tmp_path):
    with TestClient(create_app(demo_services(), tmp_path / "demo.db")) as client:
        request = {"idx": "manual", "func": CHECKED, "commit_url": COMMIT_URL}
        assert client.post("/api/snapshots", json=request).status_code == 422
        prepared = client.post("/api/snapshots", json={**request, "revision": "commit"})
        assert prepared.status_code == 200
        assert set(prepared.json()) == {"idx", "func", "snapshot_ref"}
        created = client.post("/api/detections", json=prepared.json())
        assert wait_terminal(client, created.json()["task_id"])["status"] == "completed"


def test_real_factory_never_silently_uses_demo(tmp_path, monkeypatch):
    monkeypatch.setenv("FVA_DB_PATH", str(tmp_path / "real.db"))
    monkeypatch.setenv("FVA_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("FVA_MODEL", raising=False)
    with TestClient(build_app()) as client:
        response = client.post(
            "/api/detections",
            json={
                "idx": 1,
                "func": "void f() {}",
                "snapshot_ref": "s",
                "mode": "function_only",
            },
        )
        task = wait_terminal(client, response.json()["task_id"])
        assert task["status"] == "failed"
        assert task["failures"][0]["code"] == "model_unconfigured"
        response = client.post(
            "/api/snapshots",
            json={
                "idx": 1,
                "func": CHECKED,
                "commit_url": COMMIT_URL,
                "revision": "commit",
            },
        )
        assert response.status_code == 422
        # 真实准备层按允许的托管主机校验链接，不再回退到演示数据。
        assert response.json()["code"] == "unsupported_host"
