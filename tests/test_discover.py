import json
from pathlib import Path
import tempfile
import unittest

from baidu_pan_sync.discover import manifest_from_share_listing


class DiscoverTests(unittest.TestCase):
    def test_manifest_from_share_listing_keeps_files_and_skips_directories(self):
        listing = [
            {
                "path": "/daily/stocks",
                "isdir": 1,
                "size": 0,
                "server_mtime": 1782143000,
                "fs_id": "folder-1",
            },
            {
                "path": "/daily/stocks/2026-06-22/a.csv",
                "isdir": 0,
                "size": 10,
                "server_mtime": 1782144000,
                "md5": "abc",
                "fs_id": "1001",
            },
            {
                "server_filename": "b.csv",
                "parent_path": "/daily/stocks/2026-06-22",
                "is_dir": False,
                "size": 20,
                "mtime": 1782145000,
                "md5": "def",
                "fs_id": "1002",
            },
        ]

        manifest = manifest_from_share_listing("source_a", listing)

        self.assertEqual(
            manifest,
            [
                {
                    "subscription_id": "source_a",
                    "share_path": "/daily/stocks/2026-06-22/a.csv",
                    "size": 10,
                    "mtime": 1782144000,
                    "md5": "abc",
                    "fs_id": "1001",
                },
                {
                    "subscription_id": "source_a",
                    "share_path": "/daily/stocks/2026-06-22/b.csv",
                    "size": 20,
                    "mtime": 1782145000,
                    "md5": "def",
                    "fs_id": "1002",
                },
            ],
        )

    def test_manifest_from_share_listing_rejects_items_without_a_stable_path(self):
        with self.assertRaisesRegex(ValueError, "share path"):
            manifest_from_share_listing("source_a", [{"size": 10, "isdir": 0}])


if __name__ == "__main__":
    unittest.main()
