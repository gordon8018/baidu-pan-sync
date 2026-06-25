from pathlib import PureWindowsPath
import tempfile
import unittest

from baidu_pan_sync.config import LocalResolution
from baidu_pan_sync.ledger import SyncLedger
from baidu_pan_sync.models import ShareFile


class LedgerTests(unittest.TestCase):
    def test_verified_file_is_not_scheduled_again_on_later_runs(self):
        share_file = ShareFile(
            subscription_id="source_a",
            share_path="/daily/stocks/2026-06-22/a.csv",
            size=10,
            mtime=1782144000,
            md5="abc",
            fs_id="1001",
        )
        resolution = LocalResolution(
            matched_share_path="/daily/stocks",
            local_path=PureWindowsPath("D:/data/stocks/2026-06-22/a.csv"),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with SyncLedger.open(f"{temp_dir}/state.sqlite") as ledger:
                first_run = ledger.start_run()
                first_job = ledger.schedule_if_needed(first_run, share_file, resolution, "/auto-sync/source_a")
                ledger.mark_job_verified(first_job.id, bytes_downloaded=10)

                second_run = ledger.start_run()
                second_job = ledger.schedule_if_needed(second_run, share_file, resolution, "/auto-sync/source_a")

        self.assertIsNotNone(first_job)
        self.assertIsNone(second_job)

    def test_incomplete_job_is_resumed_instead_of_creating_duplicate_work(self):
        share_file = ShareFile(
            subscription_id="source_a",
            share_path="/daily/stocks/2026-06-22/a.csv",
            size=10,
            mtime=1782144000,
            md5="abc",
            fs_id="1001",
        )
        resolution = LocalResolution(
            matched_share_path="/daily/stocks",
            local_path=PureWindowsPath("D:/data/stocks/2026-06-22/a.csv"),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with SyncLedger.open(f"{temp_dir}/state.sqlite") as ledger:
                first_run = ledger.start_run()
                first_job = ledger.schedule_if_needed(first_run, share_file, resolution, "/auto-sync/source_a")

                second_run = ledger.start_run()
                resumed_job = ledger.schedule_if_needed(second_run, share_file, resolution, "/auto-sync/source_a")

        self.assertEqual(first_job.id, resumed_job.id)
        self.assertEqual(resumed_job.status, "DISCOVERED")
        self.assertEqual(resumed_job.run_id, second_run)

    def test_same_path_with_new_content_gets_a_new_fingerprint_and_new_job(self):
        old_file = ShareFile(
            subscription_id="source_a",
            share_path="/daily/stocks/2026-06-22/a.csv",
            size=10,
            mtime=1782144000,
            md5="old",
            fs_id="1001",
        )
        new_file = ShareFile(
            subscription_id="source_a",
            share_path="/daily/stocks/2026-06-22/a.csv",
            size=12,
            mtime=1782147600,
            md5="new",
            fs_id="1002",
        )
        resolution = LocalResolution(
            matched_share_path="/daily/stocks",
            local_path=PureWindowsPath("D:/data/stocks/2026-06-22/a.csv"),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with SyncLedger.open(f"{temp_dir}/state.sqlite") as ledger:
                run_id = ledger.start_run()
                old_job = ledger.schedule_if_needed(run_id, old_file, resolution, "/auto-sync/source_a")
                ledger.mark_job_verified(old_job.id, bytes_downloaded=10)
                new_job = ledger.schedule_if_needed(run_id, new_file, resolution, "/auto-sync/source_a")

        self.assertIsNotNone(new_job)
        self.assertNotEqual(old_job.fingerprint, new_job.fingerprint)

    def test_pending_jobs_excludes_verified_files_so_daily_runner_does_not_redownload(self):
        old_file = ShareFile(
            subscription_id="source_a",
            share_path="/daily/stocks/2026-06-22/a.csv",
            size=10,
            mtime=1782144000,
            md5="old",
            fs_id="1001",
        )
        pending_file = ShareFile(
            subscription_id="source_a",
            share_path="/daily/stocks/2026-06-23/a.csv",
            size=10,
            mtime=1782230400,
            md5="new",
            fs_id="1002",
        )
        resolution = LocalResolution(
            matched_share_path="/daily/stocks",
            local_path=PureWindowsPath("D:/data/stocks/a.csv"),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with SyncLedger.open(f"{temp_dir}/state.sqlite") as ledger:
                run_id = ledger.start_run()
                old_job = ledger.schedule_if_needed(run_id, old_file, resolution, "/auto-sync/source_a")
                ledger.mark_job_verified(old_job.id, bytes_downloaded=10)
                pending_job = ledger.schedule_if_needed(run_id, pending_file, resolution, "/auto-sync/source_a")

                pending_jobs = ledger.list_pending_jobs()

        self.assertEqual([job.id for job in pending_jobs], [pending_job.id])

    def test_jobs_created_in_run_excludes_resumed_incomplete_jobs(self):
        share_file = ShareFile(
            subscription_id="source_a",
            share_path="/daily/stocks/2026-06-22/a.csv",
            size=10,
            mtime=1782144000,
            md5="abc",
            fs_id="1001",
        )
        resolution = LocalResolution(
            matched_share_path="/daily/stocks",
            local_path=PureWindowsPath("D:/data/stocks/a.csv"),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with SyncLedger.open(f"{temp_dir}/state.sqlite") as ledger:
                first_run = ledger.start_run()
                created_job = ledger.schedule_if_needed(first_run, share_file, resolution, "/auto-sync/source_a")

                second_run = ledger.start_run()
                resumed_job = ledger.schedule_if_needed(second_run, share_file, resolution, "/auto-sync/source_a")

                created_first = ledger.list_jobs_created_in_run(first_run)
                created_second = ledger.list_jobs_created_in_run(second_run)

        self.assertEqual([job.id for job in created_first], [created_job.id])
        self.assertEqual(resumed_job.id, created_job.id)
        self.assertEqual(created_second, [])


if __name__ == "__main__":
    unittest.main()
