from __future__ import annotations

from datetime import datetime, timezone
import sqlite3

from baidu_pan_sync.config import LocalResolution
from baidu_pan_sync.models import ShareFile, SyncJob

TERMINAL_SUCCESS = "VERIFIED"


class SyncLedger:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self._ensure_schema()

    @classmethod
    def open(cls, path: str) -> "SyncLedger":
        return cls(sqlite3.connect(path))

    def __enter__(self) -> "SyncLedger":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def _ensure_schema(self) -> None:
        self.connection.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS sync_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                discovered_count INTEGER NOT NULL DEFAULT 0,
                new_count INTEGER NOT NULL DEFAULT 0,
                downloaded_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS share_files (
                subscription_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                source_share_path TEXT NOT NULL,
                size INTEGER NOT NULL,
                mtime INTEGER,
                md5 TEXT,
                fs_id TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                PRIMARY KEY (subscription_id, fingerprint)
            );

            CREATE TABLE IF NOT EXISTS sync_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                created_run_id INTEGER,
                subscription_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                source_share_path TEXT NOT NULL,
                matched_mapping TEXT NOT NULL,
                remote_transfer_path TEXT NOT NULL,
                local_path TEXT NOT NULL,
                status TEXT NOT NULL,
                retry_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (subscription_id, fingerprint),
                FOREIGN KEY (run_id) REFERENCES sync_runs(id)
            );
            """
        )
        self._ensure_column("sync_jobs", "created_run_id", "INTEGER")
        self.connection.commit()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        rows = self.connection.execute(f"PRAGMA table_info({table})").fetchall()
        if column not in {str(row["name"]) for row in rows}:
            self.connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def start_run(self) -> int:
        now = utc_now()
        cursor = self.connection.execute(
            "INSERT INTO sync_runs (started_at, status) VALUES (?, ?)",
            (now, "RUNNING"),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def schedule_if_needed(
        self,
        run_id: int,
        share_file: ShareFile,
        resolution: LocalResolution,
        remote_transfer_root: str,
    ) -> SyncJob | None:
        fingerprint = share_file.fingerprint
        existing = self._job_by_fingerprint(share_file.subscription_id, fingerprint)
        if existing and existing.status == TERMINAL_SUCCESS:
            return None
        if existing:
            self.connection.execute(
                "UPDATE sync_jobs SET run_id = ?, updated_at = ? WHERE id = ?",
                (run_id, utc_now(), existing.id),
            )
            self.connection.commit()
            return self._job_by_id(existing.id)

        now = utc_now()
        self.connection.execute(
            """
            INSERT OR REPLACE INTO share_files (
                subscription_id, fingerprint, source_share_path, size, mtime, md5, fs_id,
                first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                share_file.subscription_id,
                fingerprint,
                share_file.share_path,
                share_file.size,
                share_file.mtime,
                share_file.md5,
                share_file.fs_id,
                now,
                now,
            ),
        )
        remote_path = remote_transfer_root.rstrip("/") + share_file.share_path
        cursor = self.connection.execute(
            """
            INSERT INTO sync_jobs (
                run_id, created_run_id, subscription_id, fingerprint, source_share_path, matched_mapping,
                remote_transfer_path, local_path, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                run_id,
                share_file.subscription_id,
                fingerprint,
                share_file.share_path,
                resolution.matched_share_path,
                remote_path,
                str(resolution.local_path),
                "DISCOVERED",
                now,
                now,
            ),
        )
        self.connection.commit()
        return self._job_by_id(int(cursor.lastrowid))

    def mark_job_verified(self, job_id: int, bytes_downloaded: int) -> None:
        del bytes_downloaded
        self.connection.execute(
            "UPDATE sync_jobs SET status = ?, updated_at = ? WHERE id = ?",
            (TERMINAL_SUCCESS, utc_now(), job_id),
        )
        self.connection.commit()

    def mark_job_failed(self, job_id: int, error: str) -> None:
        self.connection.execute(
            """
            UPDATE sync_jobs
            SET status = ?, retry_count = retry_count + 1, last_error = ?, updated_at = ?
            WHERE id = ?
            """,
            ("FAILED", error, utc_now(), job_id),
        )
        self.connection.commit()

    def get_job(self, job_id: int) -> SyncJob:
        return self._job_by_id(job_id)

    def get_file_size(self, subscription_id: str, fingerprint: str) -> int:
        row = self.connection.execute(
            """
            SELECT size FROM share_files
            WHERE subscription_id = ? AND fingerprint = ?
            """,
            (subscription_id, fingerprint),
        ).fetchone()
        if row is None:
            raise LookupError(f"share file {subscription_id}/{fingerprint} was not found")
        return int(row["size"])

    def list_pending_jobs(self) -> list[SyncJob]:
        rows = self.connection.execute(
            """
            SELECT * FROM sync_jobs
            WHERE status != ?
            ORDER BY id
            """,
            (TERMINAL_SUCCESS,),
        ).fetchall()
        return [job for row in rows if (job := row_to_job(row)) is not None]

    def list_jobs_created_in_run(self, run_id: int) -> list[SyncJob]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM sync_jobs
            WHERE created_run_id = ?
            ORDER BY sync_jobs.id
            """,
            (run_id,),
        ).fetchall()
        return [job for row in rows if (job := row_to_job(row)) is not None]

    def _job_by_fingerprint(self, subscription_id: str, fingerprint: str) -> SyncJob | None:
        row = self.connection.execute(
            """
            SELECT * FROM sync_jobs
            WHERE subscription_id = ? AND fingerprint = ?
            """,
            (subscription_id, fingerprint),
        ).fetchone()
        return row_to_job(row)

    def _job_by_id(self, job_id: int) -> SyncJob:
        row = self.connection.execute(
            "SELECT * FROM sync_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"sync job {job_id} was not found")
        job = row_to_job(row)
        if job is None:
            raise LookupError(f"sync job {job_id} was not found")
        return job


def row_to_job(row: sqlite3.Row | None) -> SyncJob | None:
    if row is None:
        return None
    return SyncJob(
        id=int(row["id"]),
        run_id=int(row["run_id"]),
        subscription_id=str(row["subscription_id"]),
        fingerprint=str(row["fingerprint"]),
        source_share_path=str(row["source_share_path"]),
        matched_mapping=str(row["matched_mapping"]),
        remote_transfer_path=str(row["remote_transfer_path"]),
        local_path=str(row["local_path"]),
        status=str(row["status"]),
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
