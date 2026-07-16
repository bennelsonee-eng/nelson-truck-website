"""Admin: nightly site-health reports (Word .docx + Excel .xlsx data workbook).

Each site serves only ITS OWN reports: this backend infers its site key from the
database it's connected to (titan_web -> 'titan', nelson_web -> 'nelson') and only
lists / serves files named '<key>_health_YYYY-MM-DD.*'. Admin-gated.

The .docx is the narrative report; the .xlsx is the companion data workbook — one
tab per issue with every flagged SKU and its supporting data (Mfr Part #, AAIA
code, Product code, brand, name, description, retail, in-stock).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.config import get_settings
from app.dependencies import require_admin
from app.models import User

router = APIRouter(prefix="/api/admin/health-reports", tags=["admin"])

REPORTS_DIR = Path(os.getenv("HEALTH_REPORT_DIR", "/home/titan/site-health-reports"))


def _site_key() -> str:
    """Which site's reports this backend serves, from its DB name."""
    dsn = (get_settings().database_url or "").lower()
    return "nelson" if "nelson" in dsn else "titan"


def _valid_name(filename: str, ext: str) -> bool:
    return bool(re.match(rf"^{_site_key()}_health_\d{{4}}-\d{{2}}-\d{{2}}\.{ext}$", filename))


@router.get("")
async def list_reports(user: User = Depends(require_admin)) -> list[dict]:
    """Newest-first list of this site's nightly reports with headline counts."""
    if not REPORTS_DIR.exists():
        return []
    key = _site_key()
    out: list[dict] = []
    for docx in sorted(REPORTS_DIR.glob(f"{key}_health_*.docx"), reverse=True):
        date_str = docx.stem.split("_health_")[-1]
        xlsx = docx.with_suffix(".xlsx")
        entry: dict = {
            "date": date_str,
            "filename": docx.name,
            "xlsx_filename": xlsx.name if xlsx.exists() else None,
            "size_kb": round(docx.stat().st_size / 1024),
            "xlsx_size_kb": round(xlsx.stat().st_size / 1024) if xlsx.exists() else None,
            "generated_at": None,
            "high": None, "med": None, "low": None, "sellable": None,
            "in_stock": None, "index_drift": None,
        }
        sidecar = docx.with_suffix(".json")
        if sidecar.exists():
            try:
                data = json.loads(sidecar.read_text())
                entry["generated_at"] = data.get("generated_at")
                sv = next(iter((data.get("sites") or {}).values()), {})
                sev = sv.get("severity") or {}
                entry.update({
                    "high": sev.get("HIGH"), "med": sev.get("MED"), "low": sev.get("LOW"),
                    "sellable": sv.get("sellable"), "in_stock": sv.get("in_stock"),
                    "index_drift": sv.get("index_drift"),
                })
            except (ValueError, OSError):
                pass
        out.append(entry)
    return out


@router.get("/{filename}/download")
async def download_report(filename: str, user: User = Depends(require_admin)) -> FileResponse:
    """Serve a report .docx (this site's only)."""
    if not _valid_name(filename, "docx"):
        raise HTTPException(status_code=400, detail="Invalid report name")
    path = REPORTS_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(
        str(path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
    )


@router.get("/{filename}/data")
async def download_data(filename: str, user: User = Depends(require_admin)) -> FileResponse:
    """Serve the companion .xlsx data workbook (this site's only)."""
    if not _valid_name(filename, "xlsx"):
        raise HTTPException(status_code=400, detail="Invalid workbook name")
    path = REPORTS_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Workbook not found")
    return FileResponse(
        str(path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )
