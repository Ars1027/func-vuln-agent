"""Integration seams; real adapters remain with the owners of #2, #3, #4 and #7."""

from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol

from app.schemas.models import (
    CodeLocation,
    CourseSample,
    DetectionInput,
    EventType,
    HistoricalCase,
    Idx,
    Measurement,
    Mode,
    Report,
    RepositoryResult,
    RunConfig,
    SnapshotRequest,
)

Emit = Callable[[EventType, dict[str, Any]], Awaitable[None]]


class IntegrationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class AnalysisError(IntegrationError):
    def __init__(self, code: str, message: str, measurement: Measurement | None = None):
        super().__init__(code, message)
        self.measurement = measurement


class Retriever(Protocol):
    async def search_cases(self, query: str, limit: int) -> list[HistoricalCase]: ...


class Repository(Protocol):
    async def locate_function(self, snapshot_ref: str, func: str) -> CodeLocation: ...
    async def search_code(self, snapshot_ref: str, query: str) -> RepositoryResult: ...
    async def read_file(
        self,
        snapshot_ref: str,
        path: str,
        start_line: int,
        end_line: int,
    ) -> RepositoryResult: ...
    async def find_symbol(self, snapshot_ref: str, symbol: str) -> RepositoryResult: ...


class Preparation(Protocol):
    async def prepare_course(self, sample: CourseSample) -> DetectionInput: ...
    async def prepare_snapshot(self, request: SnapshotRequest) -> DetectionInput: ...


class ResultExporter(Protocol):
    def export(self, input_ids: Sequence[Idx], reports: Sequence[Report]) -> str: ...


class Runner(Protocol):
    async def run(
        self,
        sample: DetectionInput,
        mode: Mode,
        emit: Emit,
    ) -> tuple[Report, Measurement]: ...


class Services:
    def __init__(
        self,
        runner: Runner,
        preparation: Preparation,
        exporter: ResultExporter,
        config: RunConfig,
    ):
        self.runner = runner
        self.preparation = preparation
        self.exporter = exporter
        self.config = config
