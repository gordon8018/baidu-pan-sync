from pathlib import Path
from pathlib import PureWindowsPath
import tempfile
import unittest

from baidu_pan_sync.config import LocalResolution
from baidu_pan_sync.ledger import SyncLedger
from baidu_pan_sync.models import ShareFile
from baidu_pan_sync.sync import SyncExecutor


class FakeDownloader:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls: list[tuple[str, Path]] = []

    def download_file(self, remote_path: str, part_path: Path) -> None:
        self.calls.append((remote_path, part_path))
        part_path.parent.mkdir(parents=True, exist_ok=True)
        part_path.write_bytes(self.payload)


class SyncExecutorTests(unittest.TestCase):
    def test_downloads_to_part_file_then_marks_job_verified_after_size_check(self):
        share_file = ShareFile(
            subscription_id="source_a",
            share_path="/daily/stocks/2026-06-22/a.csv",
            size=10,
            mtime=1782144000,
            md5="abc",
            fs_id="1001",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            final_path = Path(temp_dir) / "data" / "stocks" / "2026-06-22" / "a.csv"
            resolution = LocalResolution(
                matched_share_path="/daily/stocks",
                local_path=PureWindowsPath(final_path),
            )
            downloader = FakeDownloader(b"0123456789")

            with SyncLedger.open(str(Path(temp_dir) / "state.sqlite")) as ledger:
                run_id = ledger.start_run()
                job = ledger.schedule_if_needed(run_id, share_file, resolution, "/auto-sync/source_a")

                result = SyncExecutor(ledger, downloader).run_job(job)
                reloaded = ledger.get_job(job.id)

            self.assertEqual(result.status, "VERIFIED")
            self.assertEqual(reloaded.status, "VERIFIED")
            self.assertEqual(final_path.read_bytes(), b"0123456789")
            self.assertFalse(final_path.with_suffix(final_path.suffix + ".part").exists())
            self.assertEqual(downloader.calls, [("/auto-sync/source_a/daily/stocks/2026-06-22/a.csv", final_path.with_suffix(".csv.part"))])

    def test_size_mismatch_keeps_part_file_and_records_failure(self):
        share_file = ShareFile(
            subscription_id="source_a",
            share_path="/daily/stocks/2026-06-22/a.csv",
            size=10,
            mtime=1782144000,
            md5="abc",
            fs_id="1001",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            final_path = Path(temp_dir) / "data" / "stocks" / "2026-06-22" / "a.csv"
            resolution = LocalResolution(
                matched_share_path="/daily/stocks",
                local_path=PureWindowsPath(final_path),
            )

            with SyncLedger.open(str(Path(temp_dir) / "state.sqlite")) as ledger:
                run_id = ledger.start_run()
                job = ledger.schedule_if_needed(run_id, share_file, resolution, "/auto-sync/source_a")

                with self.assertRaisesRegex(ValueError, "Downloaded size mismatch"):
                    SyncExecutor(ledger, FakeDownloader(b"short")).run_job(job)
                reloaded = ledger.get_job(job.id)

            self.assertEqual(reloaded.status, "FAILED")
            self.assertFalse(final_path.exists())
            self.assertTrue(final_path.with_suffix(".csv.part").exists())


if __name__ == "__main__":
    unittest.main()
