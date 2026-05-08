"""
Tests for steam_manager – cross-platform (no Windows registry required).
"""

import sys
import os
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Make src/ importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from steam_manager import (
    _steamid64_to_steamid3,
    _parse_vdf_simple,
    _common_steam_paths,
    find_steam_path,
    get_cs2_accounts,
    CONFIG_FILE_GROUPS,
)


class TestSteamID64Conversion(unittest.TestCase):
    def test_known_value(self):
        # SteamID64 76561198000000000 -> SteamID3 39734272
        self.assertEqual(_steamid64_to_steamid3("76561198000000000"), "39734272")

    def test_invalid_input(self):
        self.assertIsNone(_steamid64_to_steamid3("not_a_number"))

    def test_none_input(self):
        self.assertIsNone(_steamid64_to_steamid3(None))


class TestParseVdf(unittest.TestCase):
    _SAMPLE_VDF = """
"users"
{
    "76561198000000000"
    {
        "AccountName"    "alice"
        "PersonaName"    "Alice"
        "RememberPassword"    "1"
    }
    "76561198111111111"
    {
        "AccountName"    "bob"
        "PersonaName"    "Bob"
        "RememberPassword"    "0"
    }
}
"""

    def test_parse_returns_users(self):
        result = _parse_vdf_simple(self._SAMPLE_VDF)
        self.assertIn("users", result)

    def test_parse_contains_accounts(self):
        result = _parse_vdf_simple(self._SAMPLE_VDF)
        users = result.get("users", {})
        self.assertIn("76561198000000000", users)
        self.assertIn("76561198111111111", users)

    def test_parse_persona_name(self):
        result = _parse_vdf_simple(self._SAMPLE_VDF)
        users = result.get("users", {})
        self.assertEqual(users["76561198000000000"]["PersonaName"], "Alice")
        self.assertEqual(users["76561198111111111"]["PersonaName"], "Bob")

    def test_empty_vdf(self):
        result = _parse_vdf_simple("")
        self.assertIsInstance(result, dict)


class TestCommonSteamPaths(unittest.TestCase):
    def test_returns_list(self):
        paths = _common_steam_paths()
        self.assertIsInstance(paths, list)
        self.assertGreater(len(paths), 0)


class TestFindSteamPath(unittest.TestCase):
    def test_returns_none_when_not_found(self):
        # Patch _read_registry_steam_path to return None and ensure
        # none of the common paths exist in the test environment.
        with patch("steam_manager._read_registry_steam_path", return_value=None), \
             patch("steam_manager._common_steam_paths", return_value=["/nonexistent/path"]):
            result = find_steam_path()
        self.assertIsNone(result)

    def test_returns_path_when_registry_hit(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("steam_manager._read_registry_steam_path", return_value=tmpdir):
                result = find_steam_path()
            self.assertEqual(result, tmpdir)


class TestGetCs2Accounts(unittest.TestCase):
    def test_empty_userdata(self, tmp_path=None):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # Steam path exists but userdata is missing
            result = get_cs2_accounts(tmpdir)
        self.assertEqual(result, [])

    def test_account_with_cs2_dir(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # Simulate: steampath/userdata/39734272/730/
            cs2_dir = Path(tmpdir) / "userdata" / "39734272" / "730"
            cs2_dir.mkdir(parents=True)

            accounts = get_cs2_accounts(tmpdir)
            self.assertEqual(len(accounts), 1)
            self.assertEqual(accounts[0]["steamid3"], "39734272")

    def test_account_without_cs2_dir_excluded(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # A userdata entry without a 730 folder
            other_dir = Path(tmpdir) / "userdata" / "99999999" / "440"
            other_dir.mkdir(parents=True)

            accounts = get_cs2_accounts(tmpdir)
            self.assertEqual(accounts, [])

    def test_persona_name_from_loginusers(self):
        import tempfile
        steamid64 = "76561198039734272"  # -> 39734272 (+ 76561197960265728 = 76561198000000000)
        # Actually: 39734272 + 76561197960265728 = 76561198000000000
        steamid64_correct = str(39734272 + 76561197960265728)
        sid3 = "39734272"

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create CS2 dir
            cs2_dir = Path(tmpdir) / "userdata" / sid3 / "730"
            cs2_dir.mkdir(parents=True)

            # Create loginusers.vdf
            cfg_dir = Path(tmpdir) / "config"
            cfg_dir.mkdir()
            vdf_content = f'''
"users"
{{
    "{steamid64_correct}"
    {{
        "PersonaName"    "TestPlayer"
    }}
}}
'''
            (cfg_dir / "loginusers.vdf").write_text(vdf_content, encoding="utf-8")

            accounts = get_cs2_accounts(tmpdir)
            self.assertEqual(len(accounts), 1)
            self.assertEqual(accounts[0]["name"], "TestPlayer")
            self.assertEqual(accounts[0]["steamid64"], steamid64_correct)


class TestConfigFileGroups(unittest.TestCase):
    def test_all_groups_have_entries(self):
        for name, entries in CONFIG_FILE_GROUPS.items():
            self.assertIsInstance(entries, list, f"Group '{name}' entries should be a list")
            self.assertGreater(len(entries), 0, f"Group '{name}' should have at least one entry")

    def test_path_keys_valid(self):
        valid_keys = {"cs2_cfg_path", "cs2_remote_path"}
        for name, entries in CONFIG_FILE_GROUPS.items():
            for path_key, filename in entries:
                self.assertIn(
                    path_key,
                    valid_keys,
                    f"Group '{name}' has invalid path_key '{path_key}'",
                )

    def test_contains_cs2_default_files(self):
        all_files = set()
        for entries in CONFIG_FILE_GROUPS.values():
            for _path_key, filename in entries:
                all_files.add(filename)

        self.assertIn("cs2_user_keys_0_slot0.vcfg", all_files)
        self.assertIn("cs2_user_convars_0_slot0.vcfg", all_files)
        self.assertIn("cs2_video.txt", all_files)
        self.assertIn("cs2_machine_convars.vcfg", all_files)


if __name__ == "__main__":
    unittest.main()
