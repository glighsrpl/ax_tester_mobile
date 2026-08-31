import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol

from mobile_tools.screen_scanner import MobileScanSnapshot
from schemas import Report

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SnapshotAnalysis:
    snapshot_index: int
    activity: str
    snapshot_id: str
    deterministic_report: Report
    llm_report: Report
    debug_data: dict[str, object]


class StaticAnalyzer(Protocol):
    async def analyze(self, snapshot: MobileScanSnapshot, snapshot_index: int) -> dict[str, object]: ...


async def consume_static_snapshots(
    queue: asyncio.Queue[tuple[int, MobileScanSnapshot] | None],
    static_analyzer: StaticAnalyzer,
) -> list[SnapshotAnalysis]:
    analyses: list[SnapshotAnalysis] = []
    while (item := await queue.get()) is not None:
        snapshot_index, snapshot = item
        try:
            result = await static_analyzer.analyze(snapshot, snapshot_index)
            deterministic = result.get("deterministic_report")
            llm = result.get("llm_report")
            debug_data = result.get("debug_data")
            if (
                not isinstance(deterministic, Report)
                or not isinstance(llm, Report)
                or not isinstance(debug_data, dict)
            ):
                raise TypeError("Static snapshot analysis returned an invalid result.")
            analyses.append(
                SnapshotAnalysis(
                    snapshot_index=snapshot_index,
                    activity=snapshot.activity,
                    snapshot_id=snapshot.snapshot_id,
                    deterministic_report=deterministic,
                    llm_report=llm,
                    debug_data=debug_data,
                )
            )
        except Exception:
            logger.exception("Static analysis failed for mobile snapshot; continuing pipeline")
    return analyses
