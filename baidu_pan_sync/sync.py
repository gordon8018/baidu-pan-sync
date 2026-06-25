from __future__ import annotations

from pathlib import Path
from typing import Protocol
import os

from baidu_pan_sync.ledger import SyncLedger
from baidu_pan_sync.models import SyncJob


class Downloader(Protocol):
    def download_file(self, remote_path: str, part_path: Path) -> None:
        ...


class SyncExecutor:
    def __init__(self, ledger: SyncLedger, downloader: Downloader) -> None:
        self.ledger = ledger
        self.downloader = downloader

    def run_job(self, job: SyncJob) -> SyncJob:
        final_path = Path(job.local_path)
        part_path = final_path.with_suffix(final_path.suffix + ".part")
        try:
            part_path.parent.mkdir(parents=True, exist_ok=True)
            self.downloader.download_file(job.remote_transfer_path, part_path)
            expected_size = self.ledger.get_file_size(job.subscription_id, job.fingerprint)
            actual_size = part_path.stat().st_size
            if actual_size != expected_size:
                raise ValueError(f"Downloaded size mismatch: expected {expected_size}, got {actual_size}")
            os.replace(part_path, final_path)
            self.ledger.mark_job_verified(job.id, bytes_downloaded=actual_size)
            return self.ledger.get_job(job.id)
        except Exception as exc:
            self.ledger.mark_job_failed(job.id, str(exc))
            raise
