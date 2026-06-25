from pathlib import Path
import json
import tempfile
import unittest

from scripts.set_share_sekey import extract_sekey, main as set_share_sekey_main


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ScriptTests(unittest.TestCase):
    def test_daily_runner_uses_selective_sync_entrypoint(self):
        script = (PROJECT_ROOT / "scripts" / "run-daily-sync.ps1").read_text(encoding="utf-8")

        self.assertIn("sync-baidu-share", script)
        self.assertNotIn("transfer-baidupcs", script)
        self.assertIn("--cookie-file", script)
        self.assertIn("--baidupcs-bin", script)

    def test_windows_task_registers_daily_1600_runner(self):
        script = (PROJECT_ROOT / "scripts" / "register-windows-task.ps1").read_text(encoding="utf-8")

        self.assertIn("New-ScheduledTaskTrigger", script)
        self.assertIn("-Daily", script)
        self.assertIn("16:00", script)
        self.assertIn("run-daily-sync.ps1", script)

    def test_set_share_sekey_accepts_copied_share_list_url(self):
        config_text = """
state_db: state.sqlite
subscriptions:
  - id: tick_data
    share_url: https://pan.baidu.com/s/1-pvzD7UEydADqnVlIsrXeg?pwd=62kh
    remote_transfer_root: /auto-sync/tick_data
    mappings:
      - share_path: /
        local_dir: D:/workspace/data/tick_data
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.yaml"
            sekeys_path = root / "sekeys.json"
            config_path.write_text(config_text, encoding="utf-8")

            exit_code = set_share_sekey_main(
                [
                    "--config",
                    str(config_path),
                    "--subscription-id",
                    "tick_data",
                    "--sekeys-file",
                    str(sekeys_path),
                    "--sekey",
                    "https://pan.baidu.com/share/list?sekey=hC%252Babc%253D&root=1",
                ]
            )

            saved = json.loads(sekeys_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(saved, {"1-pvzD7UEydADqnVlIsrXeg": "hC%2Babc%3D"})

    def test_set_share_sekey_accepts_raw_query_pair(self):
        self.assertEqual(extract_sekey("sekey=hC%2Babc%3D"), "hC%2Babc%3D")


if __name__ == "__main__":
    unittest.main()
