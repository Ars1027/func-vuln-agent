"""在对应负责人接入 #2/#3/#4/#7 前，显式报告适配器缺失。"""

from collections.abc import Sequence
from typing import NoReturn

from app.schemas.models import (
    CodeLocation,
    CourseSample,
    DetectionInput,
    HistoricalCase,
    Idx,
    Report,
    RepositoryResult,
    SnapshotRequest,
)
from app.schemas.ports import IntegrationError


def unavailable(module: str) -> NoReturn:
    raise IntegrationError("dependency_unavailable", f"尚未接入{module}，请配置对应适配器。")


class UnavailableAdapters:
    """正式服务缺少适配器时明确报错，不自动使用演示数据替代。"""

    async def prepare_course(self, sample: CourseSample) -> DetectionInput:
        unavailable("课程版本准备模块（#3）")

    async def prepare_snapshot(self, request: SnapshotRequest) -> DetectionInput:
        unavailable("快照准备模块（#3）")

    async def locate_function(self, snapshot_ref: str, func: str) -> CodeLocation:
        unavailable("函数定位模块（#3）")

    async def search_code(self, snapshot_ref: str, query: str) -> RepositoryResult:
        unavailable("仓库搜索模块（#4）")

    async def read_file(
        self,
        snapshot_ref: str,
        path: str,
        start_line: int,
        end_line: int,
    ) -> RepositoryResult:
        unavailable("仓库读取模块（#4）")

    async def find_symbol(self, snapshot_ref: str, symbol: str) -> RepositoryResult:
        unavailable("符号查询模块（#4）")

    async def search_cases(self, query: str, limit: int) -> list[HistoricalCase]:
        unavailable("历史案例检索模块（#2）")

    def export(self, input_ids: Sequence[Idx], reports: Sequence[Report]) -> str:
        unavailable("课程结果导出模块（#7）")
