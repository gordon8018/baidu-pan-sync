from pathlib import Path
import subprocess
import tempfile
import unittest

from baidu_pan_sync.baidupcs import BaiduPcsGo


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, str], dict[str, object]]] = []

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append((command, kwargs["env"], kwargs))  # type: ignore[index]
        if "--saveto" in command:
            saveto = Path(command[command.index("--saveto") + 1])
            remote_name = Path(command[2]).name
            (saveto / remote_name).write_bytes(b"0123456789")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


class BaiduPcsGoTests(unittest.TestCase):
    def test_download_file_uses_isolated_config_dir_and_moves_output_to_part_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runner = RecordingRunner()
            pcs = BaiduPcsGo(binary=Path("BaiduPCS-Go"), config_dir=root / "pcs-config", runner=runner)
            part_path = root / "downloads" / "a.csv.part"

            pcs.download_file("/auto-sync/source_a/daily/stocks/a.csv", part_path)

            self.assertEqual(
                runner.calls[0][0],
                ["BaiduPCS-Go", "download", "/auto-sync/source_a/daily/stocks/a.csv", "--saveto", str(part_path.parent)],
            )
            self.assertEqual(runner.calls[0][1]["BAIDUPCS_GO_CONFIG_DIR"], str(root / "pcs-config"))
            self.assertEqual(part_path.read_bytes(), b"0123456789")

    def test_transfer_share_changes_remote_workdir_before_transfer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runner = RecordingRunner()
            pcs = BaiduPcsGo(binary=Path("BaiduPCS-Go"), config_dir=root / "pcs-config", runner=runner)

            pcs.transfer_share("https://pan.baidu.com/s/source-a", "abcd", "/auto-sync/source_a")

            self.assertEqual(
                [call[0] for call in runner.calls],
                [
                    ["BaiduPCS-Go", "mkdir", "-p", "/auto-sync/source_a"],
                    ["BaiduPCS-Go", "cd", "/auto-sync/source_a"],
                    ["BaiduPCS-Go", "transfer", "https://pan.baidu.com/s/source-a", "abcd"],
                ],
            )

    def test_ensure_remote_dir_creates_missing_remote_path(self):
        runner = RecordingRunner()
        pcs = BaiduPcsGo(binary=Path("BaiduPCS-Go"), config_dir=Path("pcs-config"), runner=runner)

        pcs.ensure_remote_dir("/auto-sync/source_a")

        self.assertEqual(runner.calls[0][0], ["BaiduPCS-Go", "mkdir", "-p", "/auto-sync/source_a"])

    def test_subprocess_output_is_decoded_as_utf8_with_replacement_on_windows(self):
        runner = RecordingRunner()
        pcs = BaiduPcsGo(binary=Path("BaiduPCS-Go"), config_dir=Path("pcs-config"), runner=runner)

        pcs.run("version")

        self.assertEqual(runner.calls[0][2]["encoding"], "utf-8")
        self.assertEqual(runner.calls[0][2]["errors"], "replace")


if __name__ == "__main__":
    unittest.main()
