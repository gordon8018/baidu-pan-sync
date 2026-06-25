from pathlib import PureWindowsPath
from pathlib import Path
import tempfile
import unittest

from baidu_pan_sync.config import MappingRule, Subscription, load_config


class MappingTests(unittest.TestCase):
    def test_load_config_accepts_full_baidu_share_url_with_pwd_query(self):
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
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(config_text, encoding="utf-8")

            app_config = load_config(config_path)

        subscription = app_config.subscription_by_id("source_real")
        self.assertEqual(subscription.url, "https://pan.baidu.com/s/1ZAFeLGCAZOGANnSBhlFKCA")
        self.assertEqual(subscription.passcode, "h12i")

    def test_longest_prefix_rule_decides_where_incremental_file_lands(self):
        subscription = Subscription(
            id="source_a",
            url="https://pan.baidu.com/s/1sourceA",
            passcode="abcd",
            remote_transfer_root="/auto-sync/source_a",
            mappings=[
                MappingRule(share_path="/daily", local_dir=PureWindowsPath("D:/data/all")),
                MappingRule(share_path="/daily/stocks", local_dir=PureWindowsPath("D:/data/stocks")),
            ],
        )

        resolved = subscription.resolve_local_path("/daily/stocks/2026-06-22/a.csv")

        self.assertEqual(resolved.matched_share_path, "/daily/stocks")
        self.assertEqual(resolved.local_path, PureWindowsPath("D:/data/stocks/2026-06-22/a.csv"))

    def test_unmatched_path_fails_loud_so_new_upstream_directories_do_not_go_missing(self):
        subscription = Subscription(
            id="source_a",
            url="https://pan.baidu.com/s/1sourceA",
            passcode="abcd",
            remote_transfer_root="/auto-sync/source_a",
            mappings=[
                MappingRule(share_path="/daily/stocks", local_dir=PureWindowsPath("D:/data/stocks")),
            ],
        )

        with self.assertRaisesRegex(ValueError, "No mapping matched"):
            subscription.resolve_local_path("/daily/funds/2026-06-22/a.csv")

    def test_root_rule_keeps_the_share_relative_path_when_whole_subscription_maps_to_one_dir(self):
        subscription = Subscription(
            id="source_b",
            url="https://pan.baidu.com/s/1sourceB",
            passcode="efgh",
            remote_transfer_root="/auto-sync/source_b",
            mappings=[
                MappingRule(share_path="/", local_dir=PureWindowsPath("E:/warehouse/source_b")),
            ],
        )

        resolved = subscription.resolve_local_path("/nested/day/file.parquet")

        self.assertEqual(resolved.matched_share_path, "/")
        self.assertEqual(resolved.local_path, PureWindowsPath("E:/warehouse/source_b/nested/day/file.parquet"))

    def test_disabled_subscription_is_not_loaded_so_placeholder_urls_do_not_run(self):
        config_text = """
state_db: state.sqlite
subscriptions:
  - id: source_real
    share_url: https://pan.baidu.com/s/1ZAFeLGCAZOGANnSBhlFKCA?pwd=h12i
    remote_transfer_root: /auto-sync/source_real
    mappings:
      - share_path: /
        local_dir: D:/workspace/data/source_real
  - id: source_placeholder
    enabled: false
    url: https://pan.baidu.com/s/source-b
    passcode: efgh
    remote_transfer_root: /auto-sync/source_placeholder
    mappings:
      - share_path: /
        local_dir: D:/workspace/data/source_placeholder
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(config_text, encoding="utf-8")

            app_config = load_config(config_path)

        self.assertEqual([subscription.id for subscription in app_config.subscriptions], ["source_real"])

    def test_enabled_subscription_rejects_placeholder_share_url(self):
        config_text = """
state_db: state.sqlite
subscriptions:
  - id: source_placeholder
    url: https://pan.baidu.com/s/source-b
    passcode: efgh
    remote_transfer_root: /auto-sync/source_placeholder
    mappings:
      - share_path: /
        local_dir: D:/workspace/data/source_placeholder
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(config_text, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "unsupported Baidu share URL"):
                load_config(config_path)


if __name__ == "__main__":
    unittest.main()
