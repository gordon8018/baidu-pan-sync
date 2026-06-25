from __future__ import annotations

from dataclasses import dataclass
import hashlib


@dataclass(frozen=True)
class ShareFile:
    subscription_id: str
    share_path: str
    size: int
    mtime: int | None = None
    md5: str | None = None
    fs_id: str | None = None

    @property
    def fingerprint(self) -> str:
        stable_id = self.md5 or self.fs_id or ""
        raw = "|".join(
            [
                self.subscription_id,
                self.share_path,
                str(self.size),
                str(self.mtime or ""),
                stable_id,
            ]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SyncJob:
    id: int
    run_id: int
    subscription_id: str
    fingerprint: str
    source_share_path: str
    matched_mapping: str
    remote_transfer_path: str
    local_path: str
    status: str

