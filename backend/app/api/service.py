"""本地单进程检测 API，持久化保存任务及事件状态。"""

import asyncio
import json
import sqlite3
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, Header, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import ValidationError

from app.schemas.models import (
    ActiveSample,
    CourseSample,
    DetectionInput,
    DetectionRequest,
    Event,
    Failure,
    Measurement,
    Mode,
    Report,
    ReportsSnapshot,
    RunConfig,
    SnapshotRequest,
    TaskView,
    TraceEntry,
    idx_key,
)
from app.schemas.ports import AnalysisError, IntegrationError, Services


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, **context: object):
        self.status = status
        self.body = {"code": code, "message": message, **context}


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _model_dump(value: object) -> str:
    return _dump(value.model_dump(mode="json"))


def _merge_by_id(previous: list[dict], changes: list[dict]) -> list[dict]:
    result = {item["id"]: item for item in previous}
    for item in changes:
        result[item["id"]] = item
    return list(result.values())


class TaskStore:
    def __init__(self, db_path: str | Path, config: RunConfig):
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # 应用工厂可能在 ASGI 生命周期线程之外运行，例如使用 TestClient 时。
        # 所有存储操作仍在同一个 ASGI 事件循环中执行。
        self.db = sqlite3.connect(str(db_path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, status TEXT NOT NULL, mode TEXT NOT NULL,
                total INTEGER NOT NULL, seq INTEGER NOT NULL DEFAULT 0,
                config_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS inputs (
                task_id TEXT NOT NULL REFERENCES tasks(id), position INTEGER NOT NULL,
                idx_json TEXT NOT NULL, kind TEXT NOT NULL, input_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued', report_json TEXT,
                failure_json TEXT, active_json TEXT, measurement_json TEXT,
                PRIMARY KEY (task_id, position)
            );
            CREATE TABLE IF NOT EXISTS events (
                task_id TEXT NOT NULL REFERENCES tasks(id), seq INTEGER NOT NULL,
                event_json TEXT NOT NULL, PRIMARY KEY (task_id, seq)
            );
        """)
        self.config = config
        self.subscribers: dict[str, set[asyncio.Event]] = {}

    def close(self) -> None:
        self.db.close()

    def _event(self, task_id: str, event_type: str, payload: dict, idx: int | str | None) -> Event:
        seq = self.db.execute("SELECT seq FROM tasks WHERE id = ?", (task_id,)).fetchone()[0] + 1
        event = Event(
            task_id=task_id,
            seq=seq,
            timestamp=datetime.now(UTC),
            type=event_type,
            payload=payload,
            idx=idx,
        )
        self.db.execute("UPDATE tasks SET seq = ? WHERE id = ?", (seq, task_id))
        self.db.execute(
            "INSERT INTO events(task_id, seq, event_json) VALUES (?, ?, ?)",
            (task_id, seq, _model_dump(event)),
        )
        return event

    def _notify(self, task_id: str) -> None:
        for subscriber in self.subscribers.get(task_id, ()):
            subscriber.set()

    def create(self, rows: list[tuple[str, CourseSample | DetectionInput]], mode: Mode) -> str:
        task_id = uuid4().hex
        with self.db:
            self.db.execute(
                "INSERT INTO tasks(id, status, mode, total, config_json) "
                "VALUES (?, 'queued', ?, ?, ?)",
                (task_id, mode, len(rows), _model_dump(self.config)),
            )
            for position, (kind, sample) in enumerate(rows):
                self.db.execute(
                    "INSERT INTO inputs(task_id, position, idx_json, kind, input_json) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (task_id, position, _dump(sample.idx), kind, _model_dump(sample)),
                )
            self._event(task_id, "task_status", {"status": "queued", "mode": mode}, None)
        self._notify(task_id)
        return task_id

    def start(self, task_id: str) -> None:
        with self.db:
            self.db.execute("UPDATE tasks SET status = 'running' WHERE id = ?", (task_id,))
            self._event(task_id, "task_status", {"status": "running"}, None)
        self._notify(task_id)

    def start_sample(self, task_id: str, position: int) -> None:
        row = self.db.execute(
            "SELECT idx_json FROM inputs WHERE task_id = ? AND position = ?", (task_id, position)
        ).fetchone()
        idx = json.loads(row["idx_json"])
        active = ActiveSample(idx=idx)
        with self.db:
            self.db.execute(
                "UPDATE inputs SET status = 'running', active_json = ? "
                "WHERE task_id = ? AND position = ?",
                (_model_dump(active), task_id, position),
            )
            self._event(
                task_id,
                "condition_update",
                {
                    "hypotheses": [],
                    "conditions": [],
                    "evidence": [],
                },
                idx,
            )
        self._notify(task_id)

    def append_analysis(self, task_id: str, position: int, event_type: str, payload: dict) -> None:
        row = self.db.execute(
            "SELECT idx_json, active_json FROM inputs WHERE task_id = ? AND position = ?",
            (task_id, position),
        ).fetchone()
        idx = json.loads(row["idx_json"])
        active = json.loads(row["active_json"])
        if event_type == "condition_update":
            for key in ("hypotheses", "conditions", "evidence"):
                active[key] = _merge_by_id(active[key], payload.get(key, []))
        elif event_type in {"retrieval", "repository_read"}:
            if event_type == "retrieval":
                arguments = {"query": payload.get("query", "")}
                if "limit" in payload:
                    arguments["limit"] = payload["limit"]
                tool = "search_cases"
            else:
                arguments = payload.get("arguments", {})
                tool = payload.get("tool", "repository")
            active["trace"].append(
                TraceEntry(
                    tool=tool,
                    arguments=arguments,
                    summary=payload.get("summary", ""),
                    evidence_ids=payload.get("evidence_ids", []),
                ).model_dump(mode="json")
            )
        active = ActiveSample.model_validate(active)
        with self.db:
            self.db.execute(
                "UPDATE inputs SET active_json = ? WHERE task_id = ? AND position = ?",
                (_model_dump(active), task_id, position),
            )
            self._event(task_id, event_type, payload, idx)
        self._notify(task_id)

    def finish_sample(
        self,
        task_id: str,
        position: int,
        report: Report | None,
        failure: Failure | None,
        measurement: Measurement | None,
    ) -> None:
        idx = report.idx if report is not None else failure.idx
        with self.db:
            self.db.execute(
                "UPDATE inputs SET status = ?, report_json = ?, failure_json = ?, "
                "active_json = CASE WHEN ? = 'completed' THEN NULL ELSE active_json END, "
                "measurement_json = ? WHERE task_id = ? AND position = ?",
                (
                    "completed" if report is not None else "failed",
                    _model_dump(report) if report is not None else None,
                    _model_dump(failure) if failure is not None else None,
                    "completed" if report is not None else "failed",
                    _model_dump(measurement) if measurement is not None else None,
                    task_id,
                    position,
                ),
            )
            if report is not None:
                self._event(
                    task_id, "sample_completed", {"report": report.model_dump(mode="json")}, idx
                )
            else:
                self._event(task_id, "error", failure.model_dump(mode="json"), idx)
        self._notify(task_id)

    def complete(self, task_id: str) -> None:
        failed = self.db.execute(
            "SELECT COUNT(*) FROM inputs WHERE task_id = ? AND status != 'completed'", (task_id,)
        ).fetchone()[0]
        status = "failed" if failed else "completed"
        with self.db:
            self.db.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))
            self._event(task_id, "task_completed", {"status": status}, None)
        self._notify(task_id)

    def recover(self) -> None:
        rows = self.db.execute(
            "SELECT id FROM tasks WHERE status IN ('queued', 'running')"
        ).fetchall()
        for row in rows:
            task_id = row["id"]
            task = self._task(task_id)
            config = RunConfig.model_validate_json(task["config_json"])
            unfinished = self.db.execute(
                "SELECT position, idx_json, status FROM inputs WHERE task_id = ? "
                "AND status IN ('queued', 'running') ORDER BY position",
                (task_id,),
            ).fetchall()
            for item in unfinished:
                failure = Failure(
                    idx=json.loads(item["idx_json"]),
                    code="interrupted",
                    message="Analysis was interrupted by service restart.",
                )
                measurement = Measurement(
                    idx=failure.idx,
                    mode=task["mode"],
                    config=config,
                    status="failed",
                    model_calls=None if item["status"] == "running" else 0,
                    tool_calls=None if item["status"] == "running" else 0,
                    elapsed_seconds=None if item["status"] == "running" else 0,
                )
                self.finish_sample(task_id, item["position"], None, failure, measurement)
            self.complete(task_id)

    def _task(self, task_id: str) -> sqlite3.Row:
        row = self.db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise ApiError(404, "task_not_found", "Task not found.", task_id=task_id)
        return row

    def task_view(self, task_id: str) -> TaskView:
        task = self._task(task_id)
        rows = self.db.execute(
            "SELECT report_json, failure_json FROM inputs WHERE task_id = ? ORDER BY position",
            (task_id,),
        ).fetchall()
        return TaskView(
            task_id=task_id,
            status=task["status"],
            mode=task["mode"],
            total=task["total"],
            completed=sum(row["report_json"] is not None for row in rows),
            failures=[
                Failure.model_validate_json(row["failure_json"])
                for row in rows
                if row["failure_json"] is not None
            ],
        )

    def reports(self, task_id: str) -> ReportsSnapshot:
        # 多次读取之间没有 await，同一个 ASGI 事件循环不会在快照读取途中修改状态。
        with self.db:
            task = self._task(task_id)
            rows = self.db.execute(
                "SELECT status, report_json, failure_json, active_json FROM inputs "
                "WHERE task_id = ? ORDER BY position",
                (task_id,),
            ).fetchall()
            return ReportsSnapshot(
                task_id=task_id,
                seq=task["seq"],
                reports=[
                    Report.model_validate_json(row["report_json"])
                    for row in rows
                    if row["report_json"] is not None
                ],
                active_samples=[
                    ActiveSample.model_validate_json(row["active_json"])
                    for row in rows
                    if row["status"] == "running" and row["active_json"] is not None
                ],
                failed_samples=[
                    ActiveSample.model_validate_json(row["active_json"])
                    for row in rows
                    if row["status"] == "failed" and row["active_json"] is not None
                ],
                failures=[
                    Failure.model_validate_json(row["failure_json"])
                    for row in rows
                    if row["failure_json"] is not None
                ],
            )

    def measurements(self, task_id: str) -> list[Measurement]:
        self._task(task_id)
        rows = self.db.execute(
            "SELECT measurement_json FROM inputs WHERE task_id = ? ORDER BY position", (task_id,)
        ).fetchall()
        return [
            Measurement.model_validate_json(row["measurement_json"])
            for row in rows
            if row["measurement_json"] is not None
        ]

    def export_data(self, task_id: str) -> tuple[list[int | str], list[Report]]:
        task = self._task(task_id)
        rows = self.db.execute(
            "SELECT idx_json, report_json FROM inputs WHERE task_id = ? ORDER BY position",
            (task_id,),
        ).fetchall()
        ids = [json.loads(row["idx_json"]) for row in rows]
        if (
            task["status"] != "completed"
            or len(rows) != task["total"]
            or any(row["report_json"] is None for row in rows)
            or len({idx_key(idx) for idx in ids}) != len(ids)
        ):
            raise ApiError(
                409,
                "result_incomplete",
                "Task does not have a complete unique result set.",
                task_id=task_id,
            )
        reports = [Report.model_validate_json(row["report_json"]) for row in rows]
        if any(
            idx_key(idx) != idx_key(report.idx) for idx, report in zip(ids, reports, strict=True)
        ):
            raise ApiError(
                409, "result_mismatch", "Report identifiers do not match inputs.", task_id=task_id
            )
        return ids, reports

    def events_after(self, task_id: str, seq: int) -> tuple[list[Event], bool]:
        task = self._task(task_id)
        rows = self.db.execute(
            "SELECT event_json FROM events WHERE task_id = ? AND seq > ? ORDER BY seq",
            (task_id, seq),
        ).fetchall()
        return [Event.model_validate_json(row["event_json"]) for row in rows], task["status"] in {
            "completed",
            "failed",
        }


def _parse_batch(content: bytes) -> list[tuple[str, CourseSample]]:
    try:
        source = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ApiError(422, "invalid_jsonl", "Batch file must be UTF-8 JSONL.") from exc
    rows: list[tuple[str, CourseSample]] = []
    seen: set[tuple[type, int | str]] = set()
    for line_number, line in enumerate(source.splitlines(), 1):
        if not line.strip():
            continue
        try:
            sample = CourseSample.model_validate_json(line)
        except ValidationError as exc:
            raise ApiError(422, "invalid_jsonl", f"Invalid sample on line {line_number}.") from exc
        key = idx_key(sample.idx)
        if key in seen:
            raise ApiError(
                422, "duplicate_idx", f"Duplicate idx on line {line_number}.", idx=sample.idx
            )
        seen.add(key)
        rows.append(("course", sample))
    if not rows:
        raise ApiError(422, "empty_batch", "Batch file has no samples.")
    return rows


def create_app(services: Services, db_path: str | Path, *, concurrency: int = 2) -> FastAPI:
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    store = TaskStore(db_path, services.config)
    semaphore = asyncio.Semaphore(concurrency)
    workers: set[asyncio.Task] = set()

    async def run_sample(
        task_id: str,
        position: int,
        kind: str,
        input_value: CourseSample | DetectionInput,
        mode: Mode,
    ) -> None:
        async with semaphore:
            store.start_sample(task_id, position)
            idx = input_value.idx
            started = time.perf_counter()
            phase = "preparation" if kind == "course" else "analysis"

            def failed_measurement() -> Measurement:
                return Measurement(
                    idx=idx,
                    mode=mode,
                    config=services.config,
                    elapsed_seconds=time.perf_counter() - started,
                    status="failed",
                    model_calls=0 if phase == "preparation" else None,
                    tool_calls=0 if phase == "preparation" else None,
                )

            async def emit(event_type: str, payload: dict) -> None:
                store.append_analysis(task_id, position, event_type, payload)

            try:
                sample = (
                    await asyncio.wait_for(
                        services.preparation.prepare_course(input_value),
                        timeout=services.config.timeout_seconds,
                    )
                    if kind == "course"
                    else input_value
                )
                if idx_key(sample.idx) != idx_key(idx):
                    raise IntegrationError("preparation_mismatch", "Prepared sample idx changed.")
                phase = "analysis"
                report, measurement = await services.runner.run(sample, mode, emit)
                if idx_key(report.idx) != idx_key(idx) or idx_key(measurement.idx) != idx_key(idx):
                    raise IntegrationError("report_mismatch", "Result idx changed during analysis.")
                if measurement.mode != mode or measurement.status != "completed":
                    raise IntegrationError(
                        "measurement_mismatch", "Measurement does not match task."
                    )
                store.finish_sample(task_id, position, report, None, measurement)
            except asyncio.CancelledError:
                raise
            except TimeoutError:
                failure = (
                    Failure(
                        idx=idx, code="preparation_timeout", message="Sample preparation timed out."
                    )
                    if phase == "preparation"
                    else Failure(idx=idx, code="analysis_timeout", message="Analysis timed out.")
                )
                store.finish_sample(task_id, position, None, failure, failed_measurement())
            except IntegrationError as exc:
                failure = Failure(idx=idx, code=exc.code, message=exc.message)
                measurement = exc.measurement if isinstance(exc, AnalysisError) else None
                if (
                    measurement is None
                    or idx_key(measurement.idx) != idx_key(idx)
                    or measurement.mode != mode
                    or measurement.status != "failed"
                ):
                    measurement = failed_measurement()
                store.finish_sample(task_id, position, None, failure, measurement)
            except Exception:
                failure = Failure(idx=idx, code="internal_error", message="Analysis failed.")
                store.finish_sample(task_id, position, None, failure, failed_measurement())

    async def run_task(
        task_id: str, rows: list[tuple[str, CourseSample | DetectionInput]], mode: Mode
    ) -> None:
        store.start(task_id)
        children = [
            asyncio.create_task(run_sample(task_id, pos, kind, sample, mode))
            for pos, (kind, sample) in enumerate(rows)
        ]
        try:
            await asyncio.gather(*children)
            store.complete(task_id)
        except asyncio.CancelledError:
            for child in children:
                child.cancel()
            await asyncio.gather(*children, return_exceptions=True)
            raise

    def schedule(rows: list[tuple[str, CourseSample | DetectionInput]], mode: Mode) -> TaskView:
        task_id = store.create(rows, mode)
        worker = asyncio.create_task(run_task(task_id, rows, mode))
        workers.add(worker)
        worker.add_done_callback(workers.discard)
        return store.task_view(task_id)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        store.recover()
        try:
            yield
        finally:
            for worker in tuple(workers):
                worker.cancel()
            if workers:
                await asyncio.gather(*workers, return_exceptions=True)
            store.close()

    app = FastAPI(lifespan=lifespan)
    app.state.store = store

    @app.exception_handler(ApiError)
    async def api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(exc.body, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {"code": "invalid_request", "message": "Request validation failed."}, status_code=422
        )

    @app.post("/api/detections", status_code=202)
    async def create_detection(request: DetectionRequest) -> TaskView:
        return schedule(
            [("direct", DetectionInput.model_validate(request.model_dump(exclude={"mode"})))],
            request.mode,
        )

    @app.post("/api/batches", status_code=202)
    async def create_batch(
        file: UploadFile = File(...), mode: Mode = Form("conditions")
    ) -> TaskView:
        return schedule(_parse_batch(await file.read()), mode)

    @app.post("/api/snapshots")
    async def create_snapshot(request: SnapshotRequest) -> DetectionInput:
        try:
            sample = await asyncio.wait_for(
                services.preparation.prepare_snapshot(request),
                timeout=services.config.timeout_seconds,
            )
            if idx_key(sample.idx) != idx_key(request.idx):
                raise IntegrationError("preparation_mismatch", "Prepared sample idx changed.")
            return sample
        except IntegrationError as exc:
            raise ApiError(503, exc.code, exc.message, idx=request.idx) from exc
        except TimeoutError as exc:
            raise ApiError(
                503, "preparation_timeout", "Snapshot preparation timed out.", idx=request.idx
            ) from exc
        except Exception as exc:
            raise ApiError(
                503, "internal_error", "Snapshot preparation failed.", idx=request.idx
            ) from exc

    @app.get("/api/tasks/{task_id}")
    async def get_task(task_id: str) -> TaskView:
        return store.task_view(task_id)

    @app.get("/api/tasks/{task_id}/reports")
    async def get_reports(task_id: str) -> ReportsSnapshot:
        return store.reports(task_id)

    @app.get("/api/tasks/{task_id}/measurements")
    async def get_measurements(task_id: str) -> dict:
        return {
            "task_id": task_id,
            "measurements": [m.model_dump(mode="json") for m in store.measurements(task_id)],
        }

    @app.get("/api/tasks/{task_id}/result.jsonl")
    async def export_result(task_id: str) -> PlainTextResponse:
        ids, reports = store.export_data(task_id)
        try:
            result = services.exporter.export(ids, reports)
        except IntegrationError as exc:
            raise ApiError(503, exc.code, exc.message, task_id=task_id) from exc
        except Exception as exc:
            raise ApiError(503, "internal_error", "Result export failed.", task_id=task_id) from exc
        return PlainTextResponse(result, media_type="application/x-ndjson")

    @app.get("/api/tasks/{task_id}/events")
    async def stream_events(
        task_id: str,
        request: Request,
        after_seq: int | None = None,
        last_event_id: str | None = Header(default=None),
    ) -> StreamingResponse:
        store._task(task_id)
        if after_seq is None:
            try:
                after_seq = int(last_event_id) if last_event_id is not None else 0
            except ValueError as exc:
                raise ApiError(
                    422, "invalid_sequence", "Last-Event-ID must be an integer."
                ) from exc
        if after_seq < 0:
            raise ApiError(422, "invalid_sequence", "Sequence must be nonnegative.")

        async def generate() -> AsyncIterator[str]:
            wake = asyncio.Event()
            store.subscribers.setdefault(task_id, set()).add(wake)
            seq = after_seq
            try:
                while True:
                    wake.clear()
                    events, terminal = store.events_after(task_id, seq)
                    for event in events:
                        seq = event.seq
                        yield (
                            f"id: {event.seq}\nevent: {event.type}\ndata: {_model_dump(event)}\n\n"
                        )
                    if terminal:
                        return
                    if await request.is_disconnected():
                        return
                    await wake.wait()
            finally:
                store.subscribers[task_id].discard(wake)

        return StreamingResponse(
            generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    return app
