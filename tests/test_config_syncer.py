"""
Tests for config_syncer – file copy and backup logic.
"""

import os
import sys
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config_syncer import sync_configs, _backup_path
from steam_manager import CONFIG_FILE_GROUPS


def _make_account(tmpdir: str, sid3: str) -> dict:
    """Create a minimal account structure under *tmpdir* and return the account dict."""
    cfg_path = Path(tmpdir) / "userdata" / sid3 / "730" / "local" / "cfg"
    remote_path = Path(tmpdir) / "userdata" / sid3 / "730" / "remote"
    cfg_path.mkdir(parents=True, exist_ok=True)
    remote_path.mkdir(parents=True, exist_ok=True)
    return {
        "steamid64": "",
        "steamid3": sid3,
        "name": f"Player_{sid3}",
        "cs2_cfg_path": cfg_path,
        "cs2_remote_path": remote_path,
    }


class TestBackupPath(unittest.TestCase):
    def test_backup_has_bak_suffix(self):
        p = Path("/some/dir/config.cfg")
        bak = _backup_path(p)
        self.assertTrue(bak.name.startswith("config.cfg.bak_"))

    def test_backup_in_same_dir(self):
        p = Path("/some/dir/config.cfg")
        bak = _backup_path(p)
        self.assertEqual(bak.parent, p.parent)


class TestSyncConfigs(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_copies_autoexec(self):
        src = _make_account(self._tmpdir, "111")
        dst = _make_account(self._tmpdir, "222")

        # Write a sample autoexec.cfg to source
        autoexec_src = Path(src["cs2_cfg_path"]) / "autoexec.cfg"
        autoexec_src.write_text("bind TAB +scoreboard\n", encoding="utf-8")

        groups = ["Autoexec (autoexec.cfg)"]
        logs: list[str] = []
        results = sync_configs(
            src, dst, groups, CONFIG_FILE_GROUPS,
            backup=False,
            log_callback=logs.append,
        )

        autoexec_dst = Path(dst["cs2_cfg_path"]) / "autoexec.cfg"
        self.assertTrue(autoexec_dst.is_file())
        self.assertEqual(autoexec_dst.read_text(encoding="utf-8"), "bind TAB +scoreboard\n")
        self.assertEqual(len(results["copied"]), 1)
        self.assertEqual(len(results["failed"]), 0)

    def test_skips_missing_source_file(self):
        src = _make_account(self._tmpdir, "333")
        dst = _make_account(self._tmpdir, "444")

        groups = ["Autoexec (autoexec.cfg)"]
        logs: list[str] = []
        results = sync_configs(
            src, dst, groups, CONFIG_FILE_GROUPS,
            backup=False,
            log_callback=logs.append,
        )

        self.assertEqual(len(results["copied"]), 0)
        self.assertEqual(len(results["skipped"]), 1)

    def test_backup_created_when_enabled(self):
        src = _make_account(self._tmpdir, "555")
        dst = _make_account(self._tmpdir, "666")

        # Write source file
        src_file = Path(src["cs2_cfg_path"]) / "autoexec.cfg"
        src_file.write_text("echo hello\n", encoding="utf-8")

        # Write existing destination file
        dst_file = Path(dst["cs2_cfg_path"]) / "autoexec.cfg"
        dst_file.write_text("echo old\n", encoding="utf-8")

        groups = ["Autoexec (autoexec.cfg)"]
        sync_configs(src, dst, groups, CONFIG_FILE_GROUPS, backup=True)

        # A .bak_ file should exist next to the destination
        bak_files = list(Path(dst["cs2_cfg_path"]).glob("autoexec.cfg.bak_*"))
        self.assertEqual(len(bak_files), 1)
        self.assertEqual(bak_files[0].read_text(encoding="utf-8"), "echo old\n")
        # Destination should now contain the source content
        self.assertEqual(dst_file.read_text(encoding="utf-8"), "echo hello\n")

    def test_no_backup_when_disabled(self):
        src = _make_account(self._tmpdir, "777")
        dst = _make_account(self._tmpdir, "888")

        src_file = Path(src["cs2_cfg_path"]) / "autoexec.cfg"
        src_file.write_text("echo new\n", encoding="utf-8")

        dst_file = Path(dst["cs2_cfg_path"]) / "autoexec.cfg"
        dst_file.write_text("echo old\n", encoding="utf-8")

        groups = ["Autoexec (autoexec.cfg)"]
        sync_configs(src, dst, groups, CONFIG_FILE_GROUPS, backup=False)

        bak_files = list(Path(dst["cs2_cfg_path"]).glob("autoexec.cfg.bak_*"))
        self.assertEqual(len(bak_files), 0)

    def test_same_account_skipped(self):
        src = _make_account(self._tmpdir, "999")
        logs: list[str] = []
        results = sync_configs(
            src, src, ["Autoexec (autoexec.cfg)"], CONFIG_FILE_GROUPS,
            backup=False,
            log_callback=logs.append,
        )
        self.assertEqual(len(results["copied"]), 0)
        self.assertEqual(len(results["skipped"]), 1)

    def test_multiple_groups_copied(self):
        src = _make_account(self._tmpdir, "aaa")
        dst = _make_account(self._tmpdir, "bbb")

        (Path(src["cs2_cfg_path"]) / "autoexec.cfg").write_text("a", encoding="utf-8")
        (Path(src["cs2_cfg_path"]) / "config.cfg").write_text("b", encoding="utf-8")

        groups = ["Autoexec (autoexec.cfg)", "Game Config (config.cfg)"]
        results = sync_configs(src, dst, groups, CONFIG_FILE_GROUPS, backup=False)

        self.assertEqual(len(results["copied"]), 2)
        self.assertEqual(len(results["failed"]), 0)


if __name__ == "__main__":
    unittest.main()
