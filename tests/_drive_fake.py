"""In-memory stand-in for `algua.knowledge.drive.DriveClient` (same method set, no network).

`fail` maps a method name to the 1-based call number that raises `DriveError(drive_unavailable)`,
so a test can cut a multi-write operation in half and check that a re-run converges.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from algua.knowledge.drive import DriveError


class FakeDrive:
    def __init__(self) -> None:
        self.tabs: dict[tuple[str, str], dict] = {}
        self.fail: dict[str, int] = {}
        self.counts: dict[str, int] = {}

    # helpers for tests
    def seed(self, sheet: str, tab: str, header: Sequence[str],
             rows: Sequence[Mapping[str, str]] = ()) -> None:
        self.tabs[(sheet, tab)] = {"header": list(header),
                                   "rows": [{h: str(r.get(h, "")) for h in header} for r in rows]}

    def rows(self, sheet: str, tab: str) -> list[dict[str, str]]:
        return [dict(r) for r in self._tab(sheet, tab)["rows"]]

    def _tick(self, method: str) -> None:
        self.counts[method] = self.counts.get(method, 0) + 1
        if self.fail.get(method) == self.counts[method]:
            raise DriveError("drive_unavailable", f"fake failure in {method}")

    def _tab(self, sheet: str, tab: str) -> dict:
        return self.tabs.setdefault((sheet, tab), {"header": [], "rows": []})

    # DriveClient surface
    def sheet_id(self, name: str, tabs: Sequence[str]) -> str:
        for t in tabs:
            self._tab(name, t)
        return f"id-{name}"

    def read_tab(self, sheet: str, tab: str, required: Sequence[str]) -> list[dict[str, str]]:
        self._tick("read_tab")
        t = self._tab(sheet, tab)
        for h in required:
            if h not in t["header"]:
                raise DriveError("drive_schema", f"{sheet}/{tab}: missing header {h}")
        out = []
        for i, r in enumerate(t["rows"], start=2):
            if any(str(v).strip() for v in r.values()):
                out.append({**{h: r.get(h, "") for h in t["header"]}, "_row": str(i)})
        return out

    def ensure_header(self, sheet: str, tab: str, header: Sequence[str]) -> None:
        t = self._tab(sheet, tab)
        t["header"] += [h for h in header if h not in t["header"]]

    def append_rows(self, sheet: str, tab: str, rows: Sequence[Mapping[str, str]]) -> None:
        self._tick("append_rows")
        t = self._tab(sheet, tab)
        t["rows"] += [{h: str(r.get(h, "")) for h in t["header"]} for r in rows]

    def update_cells(self, sheet: str, tab: str, row: int, values: Mapping[str, str]) -> None:
        self._tick("update_cells")
        t = self._tab(sheet, tab)
        for k in values:
            if k not in t["header"]:
                raise DriveError("drive_schema", f"{sheet}/{tab}: missing header {k}")
        t["rows"][row - 2].update({k: str(v) for k, v in values.items()})

    def replace_tab(self, sheet: str, tab: str, header: Sequence[str],
                    rows: Sequence[Mapping[str, str]]) -> None:
        self._tick("replace_tab")
        self.seed(sheet, tab, header, rows)
