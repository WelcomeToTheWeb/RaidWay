"""In-memory report store keyed by report id."""

from __future__ import annotations

import threading
import uuid
from typing import Optional

from ..models import Report


class ReportStore:
    def __init__(self) -> None:
        self._reports: dict[str, Report] = {}
        self._lock = threading.Lock()

    def add(self, report: Report, report_id: Optional[str] = None) -> str:
        rid = report_id or uuid.uuid4().hex[:12]
        with self._lock:
            self._reports[rid] = report
        return rid

    def get(self, report_id: str) -> Optional[Report]:
        return self._reports.get(report_id)

    def delete(self, report_id: str) -> bool:
        with self._lock:
            return self._reports.pop(report_id, None) is not None

    def list_ids(self) -> list[str]:
        return sorted(self._reports.keys())


store = ReportStore()
