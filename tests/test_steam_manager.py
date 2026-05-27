"""
Tests for steam_manager – cross-platform (no Windows registry required).
"""

import sys
import os
import tempfile
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
    get_steam_avatar_url,
    restart_steam,
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


class TestGetSteamAvatarUrl(unittest.TestCase):
    def test_parses_avatar_url_from_miniprofile_html(self):
        html = (
            '<div class="playersection_avatar">\n'
            '  <img src="https://avatars.steamstatic.com/abc_medium.jpg" '
            'srcset="https://avatars.steamstatic.com/abc_medium.jpg 1x, '
            'https://avatars.steamstatic.com/abc_full.jpg 2x">\n'
            "</div>"
        )
        fake_response = MagicMock()
        fake_response.read.return_value = html.encode("utf-8")
        fake_response.__enter__.return_value = fake_response

        with patch("steam_manager.urlopen", return_value=fake_response):
            url = get_steam_avatar_url("76561198000000000")

        self.assertEqual(url, "https://avatars.steamstatic.com/abc_full.jpg")

    def test_uses_steam_api_fallback_when_miniprofile_fails(self):
        api_payload = (
            '{"response":{"players":[{"avatarfull":"https://avatars.steamstatic.com/'
            'api_full.jpg"}]}}'
        )
        miniprofile_error = OSError("network down")
        api_response = MagicMock()
        api_response.read.return_value = api_payload.encode("utf-8")
        api_response.__enter__.return_value = api_response

        with patch("steam_manager._read_steam_api_key", return_value="test-api-key"), \
             patch("steam_manager.urlopen", side_effect=[miniprofile_error, api_response]):
            url = get_steam_avatar_url("76561198000000000")

        self.assertEqual(url, "https://avatars.steamstatic.com/api_full.jpg")

    def test_returns_none_when_both_methods_fail(self):
        with patch("steam_manager._read_steam_api_key", return_value=None), \
             patch("steam_manager.urlopen", side_effect=OSError("network down")):
            url = get_steam_avatar_url("76561198000000000")
        self.assertIsNone(url)

    def test_prefers_full_avatar_when_multiple_images(self):
        html = (
            '<div class="playersection_avatar">\n'
            '  <img src="https://avatars.steamstatic.com/abc_medium.jpg">\n'
            '  <img src="https://avatars.steamstatic.com/abc_full.jpg">\n'
            "</div>"
        )
        fake_response = MagicMock()
        fake_response.read.return_value = html.encode("utf-8")
        fake_response.__enter__.return_value = fake_response

        with patch("steam_manager.urlopen", return_value=fake_response):
            url = get_steam_avatar_url("76561198000000000")

        self.assertEqual(url, "https://avatars.steamstatic.com/abc_full.jpg")

    def test_returns_single_avatar_when_no_full_size(self):
        html = (
            '<div class="playersection_avatar">'
            '<img src="https://avatars.steamstatic.com/plain_medium.jpg">'
            "</div>"
        )
        fake_response = MagicMock()
        fake_response.read.return_value = html.encode("utf-8")
        fake_response.__enter__.return_value = fake_response

        with patch("steam_manager.urlopen", return_value=fake_response):
            url = get_steam_avatar_url("76561198000000000")

        self.assertEqual(url, "https://avatars.steamstatic.com/plain_medium.jpg")


class TestRestartSteam(unittest.TestCase):
    def test_returns_false_when_steam_exe_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertFalse(restart_steam(tmpdir))

    @patch("steam_manager.subprocess.Popen")
    @patch("steam_manager.subprocess.run")
    def test_restarts_steam_when_exe_exists(self, mock_run, mock_popen):
        with tempfile.TemporaryDirectory() as tmpdir:
            steam_exe = Path(tmpdir) / "steam.exe"
            steam_exe.write_text("", encoding="utf-8")

            with patch("steam_manager.sys.platform", "win32"):
                self.assertTrue(restart_steam(tmpdir))
            mock_run.assert_called_once()
            mock_popen.assert_called_once()

    @patch("steam_manager.subprocess.Popen", side_effect=OSError("launch failed"))
    @patch("steam_manager.subprocess.run")
    def test_returns_false_when_launch_fails(self, mock_run, mock_popen):
        with tempfile.TemporaryDirectory() as tmpdir:
            steam_exe = Path(tmpdir) / "steam.exe"
            steam_exe.write_text("", encoding="utf-8")

            with patch("steam_manager.sys.platform", "win32"):
                self.assertFalse(restart_steam(tmpdir))
            mock_run.assert_called_once()
            mock_popen.assert_called_once()

    @patch("steam_manager.subprocess.run", side_effect=OSError("taskkill failed"))
    def test_returns_false_when_taskkill_fails(self, mock_run):
        with tempfile.TemporaryDirectory() as tmpdir:
            steam_exe = Path(tmpdir) / "steam.exe"
            steam_exe.write_text("", encoding="utf-8")

            with patch("steam_manager.sys.platform", "win32"):
                self.assertFalse(restart_steam(tmpdir))
            mock_run.assert_called_once()


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

        self.assertIn("cs2_user_keys_*_slot*.vcfg", all_files)
        self.assertIn("cs2_user_convars_*_slot*.vcfg", all_files)
        self.assertIn("cs2_video.txt", all_files)
        self.assertIn("cs2_machine_convars.vcfg", all_files)

    def test_video_settings_uses_local_cfg_path(self):
        entries = CONFIG_FILE_GROUPS["Video Settings (cs2_video.txt)"]
        self.assertIn(("cs2_cfg_path", "cs2_video.txt"), entries)


if __name__ == "__main__":
    unittest.main()
