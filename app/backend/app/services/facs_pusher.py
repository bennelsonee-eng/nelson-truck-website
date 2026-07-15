"""FACS push pipeline — drops IMS315 CSVs to a remote FTP folder.

FACS doesn't accept POSTs; it polls a shared FTP directory for new files.
Our job is to drop files and confirm pickup.

Pickup signal: file disappears from the FTP folder = FACS grabbed it.
If a file sits more than `FACS_PICKUP_LAG_ALERT_MINUTES` (config), alert admin.

Has a "local mode" — when `FACS_FTP_HOST` is empty, files are written to
`/tmp/facs_dropbox` (or `app/data/facs_dropbox/` in dev) instead of FTP.
This makes dev/test work without needing FTP creds.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from io import BytesIO
from pathlib import Path
from typing import Iterable

import aioftp

from app.config import get_settings
from app.services.ims315 import GeneratedCSV


__all__ = [
    "PushOutcome",
    "PushResult",
    "push_csv",
    "push_csvs",
    "list_dropbox_files",
]


log = logging.getLogger(__name__)


class PushOutcome(str, Enum):
    OK = "ok"
    FAILED = "failed"
    LOCAL_DROPPED = "local_dropped"  # written to local dev dropbox (no FTP host configured)


@dataclass(frozen=True)
class PushResult:
    filename: str
    outcome: PushOutcome
    error: str | None = None


def _local_dropbox() -> Path:
    """Local dev fallback when no FTP host is configured."""
    p = Path(__file__).resolve().parents[3] / "data" / "facs_dropbox"
    p.mkdir(parents=True, exist_ok=True)
    return p


async def push_csv(csv: GeneratedCSV) -> PushResult:
    """Upload one CSV to the FACS FTP dropbox (or local fallback)."""
    settings = get_settings()

    if not settings.facs_ftp_host:
        # Local-mode: drop file to dev dropbox folder
        target = _local_dropbox() / csv.filename
        target.write_text(csv.content, encoding="utf-8", newline="")
        log.info("[facs.local] wrote %s (%d bytes)", target, len(csv.content))
        return PushResult(filename=csv.filename, outcome=PushOutcome.LOCAL_DROPPED)

    # Production: real FTP upload
    try:
        async with aioftp.Client.context(
            settings.facs_ftp_host,
            settings.facs_ftp_port,
            settings.facs_ftp_user,
            settings.facs_ftp_pass,
        ) as client:
            remote = f"{settings.facs_dropbox_path.rstrip('/')}/{csv.filename}"
            data = csv.content.encode("utf-8")
            stream = BytesIO(data)
            await client.upload_stream(remote, stream)
            log.info("[facs.ftp] uploaded %s (%d bytes)", remote, len(data))
            return PushResult(filename=csv.filename, outcome=PushOutcome.OK)
    except Exception as e:
        log.exception("[facs.ftp] upload failed for %s", csv.filename)
        return PushResult(filename=csv.filename, outcome=PushOutcome.FAILED, error=str(e))


async def push_csvs(csvs: Iterable[GeneratedCSV]) -> list[PushResult]:
    """Push a batch of CSVs in sequence."""
    results = []
    for c in csvs:
        results.append(await push_csv(c))
    return results


async def list_dropbox_files() -> list[str]:
    """List filenames currently in the dropbox (FTP or local).

    Used by the heartbeat monitor to detect un-picked-up files.
    """
    settings = get_settings()

    if not settings.facs_ftp_host:
        d = _local_dropbox()
        return sorted(p.name for p in d.iterdir() if p.is_file())

    try:
        async with aioftp.Client.context(
            settings.facs_ftp_host,
            settings.facs_ftp_port,
            settings.facs_ftp_user,
            settings.facs_ftp_pass,
        ) as client:
            files = []
            async for path, info in client.list(settings.facs_dropbox_path):
                if info.get("type") == "file":
                    files.append(path.name)
            return sorted(files)
    except Exception as e:
        log.exception("[facs.ftp] list failed")
        return []
