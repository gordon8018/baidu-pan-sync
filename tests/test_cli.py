import json
from pathlib import Path
import tempfile
import unittest

from baidu_pan_sync.cli import main
from baidu_pan_sync import cli


class CliTests(unittest.TestCase):
    def test_manifest_from_listing_command_writes_standard_manifest(self):
        listing = [
            {
                "path": "/daily/stocks/2026-06-22/a.csv",
                "isdir": 0,
                "size": 10,
                "server_mtime": 1782144000,
                "md5": "abc",
                "fs_id": "1001",
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            listing_path = root / "listing.json"
            manifest_path = root / "manifest.json"
            listing_path.write_text(json.dumps(listing), encoding="utf-8")

            exit_code = main(
                [
                    "manifest-from-listing",
                    "--subscription-id",
                    "source_a",
                    "--listing",
                    str(listing_path),
                    "--output",
                    str(manifest_path),
                ]
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
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
                }
            ],
        )

    def test_plan_reads_share_manifest_and_resumes_incomplete_job_without_duplication(self):
        config_text = """
state_db: state.sqlite
subscriptions:
  - id: source_a
    url: https://pan.baidu.com/s/1sourceA
    passcode: abcd
    remote_transfer_root: /auto-sync/source_a
    mappings:
      - share_path: /daily/stocks
        local_dir: D:/data/stocks
"""
        manifest = [
            {
                "subscription_id": "source_a",
                "share_path": "/daily/stocks/2026-06-22/a.csv",
                "size": 10,
                "mtime": 1782144000,
                "md5": "abc",
                "fs_id": "1001",
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.yaml"
            manifest_path = root / "manifest.json"
            output_path = root / "plan.json"
            config_path.write_text(config_text, encoding="utf-8")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            first_exit_code = main(
                [
                    "plan",
                    "--config",
                    str(config_path),
                    "--manifest",
                    str(manifest_path),
                    "--output",
                    str(output_path),
                ]
            )
            first_plan = json.loads(output_path.read_text(encoding="utf-8"))

            second_exit_code = main(
                [
                    "plan",
                    "--config",
                    str(config_path),
                    "--manifest",
                    str(manifest_path),
                    "--output",
                    str(output_path),
                ]
            )

            second_plan = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(first_exit_code, 0)
        self.assertEqual(second_exit_code, 0)
        self.assertEqual(len(first_plan["jobs"]), 1)
        self.assertEqual(len(second_plan["jobs"]), 1)
        self.assertEqual(first_plan["jobs"][0]["id"], second_plan["jobs"][0]["id"])

    def test_run_planned_downloads_pending_jobs_from_local_payload_source(self):
        config_text = """
state_db: state.sqlite
subscriptions:
  - id: source_a
    url: https://pan.baidu.com/s/1sourceA
    passcode: abcd
    remote_transfer_root: /auto-sync/source_a
    mappings:
      - share_path: /daily/stocks
        local_dir: {local_dir}
"""
        manifest = [
            {
                "subscription_id": "source_a",
                "share_path": "/daily/stocks/2026-06-22/a.csv",
                "size": 10,
                "mtime": 1782144000,
                "md5": "abc",
                "fs_id": "1001",
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_dir = root / "data" / "stocks"
            payload_root = root / "payloads"
            payload_file = payload_root / "auto-sync" / "source_a" / "daily" / "stocks" / "2026-06-22" / "a.csv"
            payload_file.parent.mkdir(parents=True)
            payload_file.write_bytes(b"0123456789")

            config_path = root / "config.yaml"
            manifest_path = root / "manifest.json"
            output_path = root / "plan.json"
            run_output_path = root / "run.json"
            config_path.write_text(config_text.format(local_dir=str(local_dir).replace("\\", "/")), encoding="utf-8")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            main(["plan", "--config", str(config_path), "--manifest", str(manifest_path), "--output", str(output_path)])
            exit_code = main(
                [
                    "run-planned",
                    "--config",
                    str(config_path),
                    "--payload-root",
                    str(payload_root),
                    "--output",
                    str(run_output_path),
                ]
            )
            run_summary = json.loads(run_output_path.read_text(encoding="utf-8"))

            self.assertEqual(exit_code, 0)
            self.assertEqual(run_summary["verified"], 1)
            self.assertEqual((local_dir / "2026-06-22" / "a.csv").read_bytes(), b"0123456789")

    def test_run_baidupcs_uses_real_adapter_options_for_pending_jobs(self):
        config_text = """
state_db: state.sqlite
subscriptions:
  - id: source_a
    url: https://pan.baidu.com/s/1sourceA
    passcode: abcd
    remote_transfer_root: /auto-sync/source_a
    mappings:
      - share_path: /daily/stocks
        local_dir: {local_dir}
"""
        manifest = [
            {
                "subscription_id": "source_a",
                "share_path": "/daily/stocks/2026-06-22/a.csv",
                "size": 10,
                "mtime": 1782144000,
                "md5": "abc",
                "fs_id": "1001",
            }
        ]

        class StubPcs:
            instances: list["StubPcs"] = []

            def __init__(self, binary: Path, config_dir: Path) -> None:
                self.binary = binary
                self.config_dir = config_dir
                self.calls: list[tuple[str, Path]] = []
                StubPcs.instances.append(self)

            def download_file(self, remote_path: str, part_path: Path) -> None:
                self.calls.append((remote_path, part_path))
                part_path.parent.mkdir(parents=True, exist_ok=True)
                part_path.write_bytes(b"0123456789")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_dir = root / "data" / "stocks"
            config_path = root / "config.yaml"
            manifest_path = root / "manifest.json"
            output_path = root / "plan.json"
            run_output_path = root / "run.json"
            config_path.write_text(config_text.format(local_dir=str(local_dir).replace("\\", "/")), encoding="utf-8")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            original_pcs = cli.BaiduPcsGo
            cli.BaiduPcsGo = StubPcs  # type: ignore[assignment]
            try:
                main(["plan", "--config", str(config_path), "--manifest", str(manifest_path), "--output", str(output_path)])
                exit_code = main(
                    [
                        "run-baidupcs",
                        "--config",
                        str(config_path),
                        "--baidupcs-bin",
                        "D:/tools/BaiduPCS-Go.exe",
                        "--baidupcs-config-dir",
                        str(root / "pcs-config"),
                        "--output",
                        str(run_output_path),
                    ]
                )
            finally:
                cli.BaiduPcsGo = original_pcs  # type: ignore[assignment]
            run_summary = json.loads(run_output_path.read_text(encoding="utf-8"))

            self.assertEqual(exit_code, 0)
            self.assertEqual(run_summary["verified"], 1)
            self.assertEqual(StubPcs.instances[0].binary, Path("D:/tools/BaiduPCS-Go.exe"))
            self.assertEqual(StubPcs.instances[0].config_dir, root / "pcs-config")
            self.assertEqual(
                StubPcs.instances[0].calls,
                [("/auto-sync/source_a/daily/stocks/2026-06-22/a.csv", local_dir / "2026-06-22" / "a.csv.part")],
            )

    def test_transfer_baidupcs_uses_configured_share_url_and_remote_root(self):
        config_text = """
state_db: state.sqlite
subscriptions:
  - id: source_real
    share_url: https://pan.baidu.com/s/1ZAFeLGCAZOGANnSBhlFKCA?pwd=h12i
    remote_transfer_root: /auto-sync/source_real
    mappings:
      - share_path: /
        local_dir: D:/workspace/data/source_real
"""

        class StubPcs:
            instances: list["StubPcs"] = []

            def __init__(self, binary: Path, config_dir: Path) -> None:
                self.binary = binary
                self.config_dir = config_dir
                self.transfers: list[tuple[str, str, str]] = []
                StubPcs.instances.append(self)

            def transfer_share(self, url: str, passcode: str, remote_transfer_root: str) -> None:
                self.transfers.append((url, passcode, remote_transfer_root))

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.yaml"
            output_path = root / "transfer.json"
            config_path.write_text(config_text, encoding="utf-8")

            original_pcs = cli.BaiduPcsGo
            cli.BaiduPcsGo = StubPcs  # type: ignore[assignment]
            try:
                exit_code = main(
                    [
                        "transfer-baidupcs",
                        "--config",
                        str(config_path),
                        "--subscription-id",
                        "source_real",
                        "--baidupcs-bin",
                        "D:/tools/BaiduPCS-Go.exe",
                        "--baidupcs-config-dir",
                        str(root / "pcs-config"),
                        "--output",
                        str(output_path),
                    ]
                )
            finally:
                cli.BaiduPcsGo = original_pcs  # type: ignore[assignment]
            summary = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(summary, {"transferred": ["source_real"]})
        self.assertEqual(StubPcs.instances[0].binary, Path("D:/tools/BaiduPCS-Go.exe"))
        self.assertEqual(StubPcs.instances[0].transfers, [(
            "https://pan.baidu.com/s/1ZAFeLGCAZOGANnSBhlFKCA",
            "h12i",
            "/auto-sync/source_real",
        )])

    def test_plan_and_transfer_skips_remote_transfer_when_manifest_has_no_new_jobs(self):
        config_text = """
state_db: state.sqlite
subscriptions:
  - id: source_real
    share_url: https://pan.baidu.com/s/1ZAFeLGCAZOGANnSBhlFKCA?pwd=h12i
    remote_transfer_root: /auto-sync/source_real
    mappings:
      - share_path: /
        local_dir: D:/workspace/data/source_real
"""
        manifest = [
            {
                "subscription_id": "source_real",
                "share_path": "/daily/stocks/2026-06-22/a.csv",
                "size": 10,
                "mtime": 1782144000,
                "md5": "abc",
                "fs_id": "1001",
            }
        ]

        class StubPcs:
            instances: list["StubPcs"] = []

            def __init__(self, binary: Path, config_dir: Path) -> None:
                self.transfers: list[tuple[str, str, str]] = []
                StubPcs.instances.append(self)

            def transfer_share(self, url: str, passcode: str, remote_transfer_root: str) -> None:
                self.transfers.append((url, passcode, remote_transfer_root))

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.yaml"
            manifest_path = root / "manifest.json"
            output_path = root / "plan-transfer.json"
            config_path.write_text(config_text, encoding="utf-8")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            original_pcs = cli.BaiduPcsGo
            cli.BaiduPcsGo = StubPcs  # type: ignore[assignment]
            try:
                first_exit_code = main(
                    [
                        "plan-and-transfer-baidupcs",
                        "--config",
                        str(config_path),
                        "--manifest",
                        str(manifest_path),
                        "--subscription-id",
                        "source_real",
                        "--baidupcs-bin",
                        "D:/tools/BaiduPCS-Go.exe",
                        "--baidupcs-config-dir",
                        str(root / "pcs-config"),
                        "--output",
                        str(output_path),
                    ]
                )
                first_summary = json.loads(output_path.read_text(encoding="utf-8"))
                second_exit_code = main(
                    [
                        "plan-and-transfer-baidupcs",
                        "--config",
                        str(config_path),
                        "--manifest",
                        str(manifest_path),
                        "--subscription-id",
                        "source_real",
                        "--baidupcs-bin",
                        "D:/tools/BaiduPCS-Go.exe",
                        "--baidupcs-config-dir",
                        str(root / "pcs-config"),
                        "--output",
                        str(output_path),
                    ]
                )
                second_summary = json.loads(output_path.read_text(encoding="utf-8"))
            finally:
                cli.BaiduPcsGo = original_pcs  # type: ignore[assignment]

        self.assertEqual(first_exit_code, 0)
        self.assertEqual(second_exit_code, 0)
        self.assertEqual(first_summary["new_jobs"], 1)
        self.assertTrue(first_summary["transferred"])
        self.assertEqual(second_summary["new_jobs"], 0)
        self.assertFalse(second_summary["transferred"])
        self.assertEqual(len(StubPcs.instances[0].transfers), 1)

    def test_sync_baidu_share_transfers_only_new_share_fs_ids_then_downloads_pending_jobs(self):
        config_text = """
state_db: state.sqlite
subscriptions:
  - id: source_real
    share_url: https://pan.baidu.com/s/1sourceReal?pwd=abcd
    remote_transfer_root: /auto-sync/source_real
    mappings:
      - share_path: /
        local_dir: {local_dir}
"""

        class StubShareClient:
            instances: list["StubShareClient"] = []

            def __init__(self, cookie: str, sekeys: dict[str, str] | None = None) -> None:
                self.cookie = cookie
                self.sekeys = sekeys or {}
                self.transfers: list[tuple[str, str, list[str], str]] = []
                StubShareClient.instances.append(self)

            def list_share(self, url: str, passcode: str) -> list[dict[str, object]]:
                return [
                    {
                        "path": "/daily/a.csv",
                        "isdir": 0,
                        "size": 10,
                        "server_mtime": 1782144000,
                        "md5": "abc",
                        "fs_id": "1001",
                    }
                ]

            def transfer_files(
                self,
                url: str,
                passcode: str,
                fs_ids: list[str],
                remote_transfer_root: str,
            ) -> None:
                self.transfers.append((url, passcode, fs_ids, remote_transfer_root))

        class StubPcs:
            def __init__(self, binary: Path, config_dir: Path) -> None:
                self.binary = binary
                self.config_dir = config_dir

            def ensure_remote_dir(self, remote_path: str) -> None:
                pass

            def download_file(self, remote_path: str, part_path: Path) -> None:
                part_path.parent.mkdir(parents=True, exist_ok=True)
                part_path.write_bytes(b"0123456789")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_dir = root / "data" / "source_real"
            config_path = root / "config.yaml"
            cookie_path = root / "cookies.txt"
            output_path = root / "sync.json"
            config_path.write_text(config_text.format(local_dir=str(local_dir).replace("\\", "/")), encoding="utf-8")
            cookie_path.write_text("BDUSS=redacted; STOKEN=redacted", encoding="utf-8")

            original_share_client = cli.BaiduShareClient
            original_pcs = cli.BaiduPcsGo
            cli.BaiduShareClient = StubShareClient  # type: ignore[assignment]
            cli.BaiduPcsGo = StubPcs  # type: ignore[assignment]
            try:
                first_exit_code = main(
                    [
                        "sync-baidu-share",
                        "--config",
                        str(config_path),
                        "--cookie-file",
                        str(cookie_path),
                        "--baidupcs-bin",
                        "D:/tools/BaiduPCS-Go.exe",
                        "--baidupcs-config-dir",
                        str(root / "pcs-config"),
                        "--output",
                        str(output_path),
                    ]
                )
                first_summary = json.loads(output_path.read_text(encoding="utf-8"))
                second_exit_code = main(
                    [
                        "sync-baidu-share",
                        "--config",
                        str(config_path),
                        "--cookie-file",
                        str(cookie_path),
                        "--baidupcs-bin",
                        "D:/tools/BaiduPCS-Go.exe",
                        "--baidupcs-config-dir",
                        str(root / "pcs-config"),
                        "--output",
                        str(output_path),
                    ]
                )
                second_summary = json.loads(output_path.read_text(encoding="utf-8"))
                downloaded_exists = (local_dir / "daily" / "a.csv").exists()
            finally:
                cli.BaiduShareClient = original_share_client  # type: ignore[assignment]
                cli.BaiduPcsGo = original_pcs  # type: ignore[assignment]

        self.assertEqual(first_exit_code, 0)
        self.assertEqual(second_exit_code, 0)
        self.assertEqual(first_summary["new_jobs"], 1)
        self.assertEqual(first_summary["transferred"], 1)
        self.assertEqual(first_summary["verified"], 1)
        self.assertEqual(second_summary["new_jobs"], 0)
        self.assertEqual(second_summary["transferred"], 0)
        self.assertEqual(second_summary["verified"], 0)
        self.assertEqual(
            StubShareClient.instances[0].transfers,
            [("https://pan.baidu.com/s/1sourceReal", "abcd", ["1001"], "/auto-sync/source_real")],
        )
        self.assertTrue(downloaded_exists)

    def test_sync_baidu_share_creates_remote_transfer_root_before_share_api_transfer(self):
        config_text = """
state_db: state.sqlite
subscriptions:
  - id: source_real
    share_url: https://pan.baidu.com/s/1sourceReal?pwd=abcd
    remote_transfer_root: /auto-sync/source_real
    mappings:
      - share_path: /
        local_dir: {local_dir}
"""

        class StubShareClient:
            instances: list["StubShareClient"] = []

            def __init__(self, cookie: str, sekeys: dict[str, str] | None = None) -> None:
                self.cookie = cookie
                self.sekeys = sekeys or {}
                StubShareClient.instances.append(self)

            def list_share(self, url: str, passcode: str) -> list[dict[str, object]]:
                return [
                    {
                        "path": "/daily/a.csv",
                        "isdir": 0,
                        "size": 10,
                        "server_mtime": 1782144000,
                        "md5": "abc",
                        "fs_id": "1001",
                    }
                ]

            def transfer_files(
                self,
                url: str,
                passcode: str,
                fs_ids: list[str],
                remote_transfer_root: str,
            ) -> None:
                if remote_transfer_root not in StubPcs.created_roots:
                    raise RuntimeError(
                        "Baidu share transfer failed with errno 2: {'show_msg': '转存路径不存在'}"
                    )

        class StubPcs:
            created_roots: list[str] = []

            def __init__(self, binary: Path, config_dir: Path) -> None:
                self.binary = binary
                self.config_dir = config_dir

            def ensure_remote_dir(self, remote_path: str) -> None:
                StubPcs.created_roots.append(remote_path)

            def download_file(self, remote_path: str, part_path: Path) -> None:
                part_path.parent.mkdir(parents=True, exist_ok=True)
                part_path.write_bytes(b"0123456789")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_dir = root / "data" / "source_real"
            config_path = root / "config.yaml"
            cookie_path = root / "cookies.txt"
            output_path = root / "sync.json"
            config_path.write_text(config_text.format(local_dir=str(local_dir).replace("\\", "/")), encoding="utf-8")
            cookie_path.write_text("BDUSS=redacted; STOKEN=redacted", encoding="utf-8")

            original_share_client = cli.BaiduShareClient
            original_pcs = cli.BaiduPcsGo
            cli.BaiduShareClient = StubShareClient  # type: ignore[assignment]
            cli.BaiduPcsGo = StubPcs  # type: ignore[assignment]
            try:
                exit_code = main(
                    [
                        "sync-baidu-share",
                        "--config",
                        str(config_path),
                        "--cookie-file",
                        str(cookie_path),
                        "--baidupcs-bin",
                        "D:/tools/BaiduPCS-Go.exe",
                        "--baidupcs-config-dir",
                        str(root / "pcs-config"),
                        "--output",
                        str(output_path),
                    ]
                )
            finally:
                cli.BaiduShareClient = original_share_client  # type: ignore[assignment]
                cli.BaiduPcsGo = original_pcs  # type: ignore[assignment]

        self.assertEqual(exit_code, 0)
        self.assertEqual(StubPcs.created_roots, ["/auto-sync/source_real"])

    def test_sync_baidu_share_marks_files_before_subscription_baseline_as_verified(self):
        config_text = """
state_db: state.sqlite
subscriptions:
  - id: source_real
    share_url: https://pan.baidu.com/s/1sourceReal?pwd=abcd
    baseline_before: 2026-06-20
    remote_transfer_root: /auto-sync/source_real
    mappings:
      - share_path: /
        local_dir: {local_dir}
"""

        class StubShareClient:
            instances: list["StubShareClient"] = []

            def __init__(self, cookie: str, sekeys: dict[str, str] | None = None) -> None:
                self.cookie = cookie
                self.sekeys = sekeys or {}
                self.transfers: list[tuple[str, str, list[str], str]] = []
                StubShareClient.instances.append(self)

            def list_share(self, url: str, passcode: str) -> list[dict[str, object]]:
                return [
                    {
                        "path": "/daily/old.csv",
                        "isdir": 0,
                        "size": 10,
                        "server_mtime": 1781798399,
                        "md5": "old",
                        "fs_id": "1001",
                    },
                    {
                        "path": "/daily/new.csv",
                        "isdir": 0,
                        "size": 10,
                        "server_mtime": 1782000000,
                        "md5": "new",
                        "fs_id": "1002",
                    },
                ]

            def transfer_files(
                self,
                url: str,
                passcode: str,
                fs_ids: list[str],
                remote_transfer_root: str,
            ) -> None:
                self.transfers.append((url, passcode, fs_ids, remote_transfer_root))

        class StubPcs:
            def __init__(self, binary: Path, config_dir: Path) -> None:
                self.binary = binary
                self.config_dir = config_dir

            def ensure_remote_dir(self, remote_path: str) -> None:
                pass

            def download_file(self, remote_path: str, part_path: Path) -> None:
                if remote_path.endswith("old.csv"):
                    raise AssertionError("baseline files should not be downloaded")
                part_path.parent.mkdir(parents=True, exist_ok=True)
                part_path.write_bytes(b"0123456789")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_dir = root / "data" / "source_real"
            config_path = root / "config.yaml"
            cookie_path = root / "cookies.txt"
            output_path = root / "sync.json"
            config_path.write_text(config_text.format(local_dir=str(local_dir).replace("\\", "/")), encoding="utf-8")
            cookie_path.write_text("BDUSS=redacted; STOKEN=redacted", encoding="utf-8")

            original_share_client = cli.BaiduShareClient
            original_pcs = cli.BaiduPcsGo
            cli.BaiduShareClient = StubShareClient  # type: ignore[assignment]
            cli.BaiduPcsGo = StubPcs  # type: ignore[assignment]
            try:
                exit_code = main(
                    [
                        "sync-baidu-share",
                        "--config",
                        str(config_path),
                        "--cookie-file",
                        str(cookie_path),
                        "--baidupcs-bin",
                        "D:/tools/BaiduPCS-Go.exe",
                        "--baidupcs-config-dir",
                        str(root / "pcs-config"),
                        "--output",
                        str(output_path),
                    ]
                )
                summary = json.loads(output_path.read_text(encoding="utf-8"))
                old_exists = (local_dir / "daily" / "old.csv").exists()
                new_exists = (local_dir / "daily" / "new.csv").exists()
            finally:
                cli.BaiduShareClient = original_share_client  # type: ignore[assignment]
                cli.BaiduPcsGo = original_pcs  # type: ignore[assignment]

        self.assertEqual(exit_code, 0)
        self.assertEqual(summary["new_jobs"], 1)
        self.assertEqual(summary["baseline_verified"], 1)
        self.assertEqual(summary["transferred"], 1)
        self.assertEqual(summary["verified"], 1)
        self.assertEqual(
            StubShareClient.instances[0].transfers,
            [("https://pan.baidu.com/s/1sourceReal", "abcd", ["1002"], "/auto-sync/source_real")],
        )
        self.assertFalse(old_exists)
        self.assertTrue(new_exists)

    def test_sync_baidu_share_can_fallback_to_baidupcs_full_transfer_when_share_api_fails(self):
        config_text = """
state_db: state.sqlite
subscriptions:
  - id: source_real
    share_url: https://pan.baidu.com/s/1sourceReal?pwd=abcd
    remote_transfer_root: /auto-sync/source_real
    mappings:
      - share_path: /
        local_dir: {local_dir}
"""

        class FailingShareClient:
            def __init__(self, cookie: str, sekeys: dict[str, str] | None = None) -> None:
                self.cookie = cookie
                self.sekeys = sekeys or {}

            def list_share(self, url: str, passcode: str) -> list[dict[str, object]]:
                raise RuntimeError("Baidu share verify failed with errno 9019")

        class StubPcs:
            instances: list["StubPcs"] = []

            def __init__(self, binary: Path, config_dir: Path) -> None:
                self.transfers: list[tuple[str, str, str]] = []
                StubPcs.instances.append(self)

            def transfer_share(self, url: str, passcode: str, remote_transfer_root: str) -> None:
                self.transfers.append((url, passcode, remote_transfer_root))

            def download_file(self, remote_path: str, part_path: Path) -> None:
                raise AssertionError("no jobs should be downloaded when discovery failed")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_dir = root / "data" / "source_real"
            config_path = root / "config.yaml"
            cookie_path = root / "cookies.txt"
            output_path = root / "sync.json"
            config_path.write_text(config_text.format(local_dir=str(local_dir).replace("\\", "/")), encoding="utf-8")
            cookie_path.write_text("BDUSS=redacted; STOKEN=redacted", encoding="utf-8")

            original_share_client = cli.BaiduShareClient
            original_pcs = cli.BaiduPcsGo
            cli.BaiduShareClient = FailingShareClient  # type: ignore[assignment]
            cli.BaiduPcsGo = StubPcs  # type: ignore[assignment]
            try:
                exit_code = main(
                    [
                        "sync-baidu-share",
                        "--config",
                        str(config_path),
                        "--cookie-file",
                        str(cookie_path),
                        "--baidupcs-bin",
                        "D:/tools/BaiduPCS-Go.exe",
                        "--baidupcs-config-dir",
                        str(root / "pcs-config"),
                        "--allow-full-transfer-fallback",
                        "--output",
                        str(output_path),
                    ]
                )
                summary = json.loads(output_path.read_text(encoding="utf-8"))
            finally:
                cli.BaiduShareClient = original_share_client  # type: ignore[assignment]
                cli.BaiduPcsGo = original_pcs  # type: ignore[assignment]

        self.assertEqual(exit_code, 0)
        self.assertEqual(summary["fallback_full_transfers"], ["source_real"])
        self.assertEqual(
            StubPcs.instances[0].transfers,
            [("https://pan.baidu.com/s/1sourceReal", "abcd", "/auto-sync/source_real")],
        )

    def test_sync_baidu_share_reads_and_writes_share_sekeys_file(self):
        config_text = """
state_db: state.sqlite
subscriptions:
  - id: source_real
    share_url: https://pan.baidu.com/s/1sourceReal?pwd=abcd
    remote_transfer_root: /auto-sync/source_real
    mappings:
      - share_path: /
        local_dir: {local_dir}
"""

        class StubShareClient:
            instances: list["StubShareClient"] = []

            def __init__(self, cookie: str, sekeys: dict[str, str] | None = None) -> None:
                self.cookie = cookie
                self.sekeys = sekeys or {}
                StubShareClient.instances.append(self)

            def list_share(self, url: str, passcode: str) -> list[dict[str, object]]:
                self.sekeys["1sourceReal"] = "fresh"
                return []

            def transfer_files(
                self,
                url: str,
                passcode: str,
                fs_ids: list[str],
                remote_transfer_root: str,
            ) -> None:
                raise AssertionError("no transfer expected")

        class StubPcs:
            def __init__(self, binary: Path, config_dir: Path) -> None:
                pass

            def download_file(self, remote_path: str, part_path: Path) -> None:
                raise AssertionError("no jobs should be downloaded")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_dir = root / "data" / "source_real"
            config_path = root / "config.yaml"
            cookie_path = root / "cookies.txt"
            sekeys_path = root / "sekeys.json"
            output_path = root / "sync.json"
            config_path.write_text(config_text.format(local_dir=str(local_dir).replace("\\", "/")), encoding="utf-8")
            cookie_path.write_text("BDUSS=redacted; STOKEN=redacted", encoding="utf-8")
            sekeys_path.write_text('{"1sourceReal": "stale"}', encoding="utf-8")

            original_share_client = cli.BaiduShareClient
            original_pcs = cli.BaiduPcsGo
            cli.BaiduShareClient = StubShareClient  # type: ignore[assignment]
            cli.BaiduPcsGo = StubPcs  # type: ignore[assignment]
            try:
                exit_code = main(
                    [
                        "sync-baidu-share",
                        "--config",
                        str(config_path),
                        "--cookie-file",
                        str(cookie_path),
                        "--share-sekeys-file",
                        str(sekeys_path),
                        "--baidupcs-bin",
                        "D:/tools/BaiduPCS-Go.exe",
                        "--baidupcs-config-dir",
                        str(root / "pcs-config"),
                        "--output",
                        str(output_path),
                    ]
                )
                saved_sekeys = json.loads(sekeys_path.read_text(encoding="utf-8"))
            finally:
                cli.BaiduShareClient = original_share_client  # type: ignore[assignment]
                cli.BaiduPcsGo = original_pcs  # type: ignore[assignment]

        self.assertEqual(exit_code, 0)
        self.assertEqual(StubShareClient.instances[0].sekeys["1sourceReal"], "fresh")
        self.assertEqual(saved_sekeys, {"1sourceReal": "fresh"})


if __name__ == "__main__":
    unittest.main()
