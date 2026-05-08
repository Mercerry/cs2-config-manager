"""
Steam installation detection and account management utilities.
Supports Windows via Registry lookup and common path fallbacks.
"""

import os
import re
import sys
from pathlib import Path
from typing import Optional

CS2_APP_ID = "730"


def _read_registry_steam_path() -> Optional[str]:
    """Read the Steam installation path from the Windows Registry."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
        hive = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\WOW6432Node\Valve\Steam",
        )
        value, _ = winreg.QueryValueEx(hive, "InstallPath")
        winreg.CloseKey(hive)
        return value
    except Exception:
        pass
    try:
        import winreg
        hive = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Valve\Steam",
        )
        value, _ = winreg.QueryValueEx(hive, "InstallPath")
        winreg.CloseKey(hive)
        return value
    except Exception:
        return None


def _common_steam_paths() -> list[str]:
    """Return a list of common Steam installation paths to check."""
    candidates = []
    if sys.platform == "win32":
        for drive in ["C", "D", "E"]:
            candidates += [
                rf"{drive}:\Program Files (x86)\Steam",
                rf"{drive}:\Program Files\Steam",
                rf"{drive}:\Steam",
            ]
    else:
        # Linux / macOS fallbacks (for development/testing)
        candidates += [
            os.path.expanduser("~/.steam/steam"),
            os.path.expanduser("~/.local/share/Steam"),
            "/usr/share/steam",
        ]
    return candidates


def find_steam_path() -> Optional[str]:
    """
    Locate the Steam installation directory.

    Returns the path string if found, otherwise None.
    """
    # 1. Try the Windows Registry first.
    registry_path = _read_registry_steam_path()
    if registry_path and Path(registry_path).is_dir():
        return registry_path

    # 2. Fall back to well-known locations.
    for candidate in _common_steam_paths():
        if Path(candidate).is_dir():
            return candidate

    return None


# ---------------------------------------------------------------------------
# VDF helpers (minimal, no third-party dependency)
# ---------------------------------------------------------------------------

def _parse_vdf_simple(text: str) -> dict:
    """
    Parse a minimal subset of the Valve Data Format (VDF) used by Steam.

    Only handles the flat key/value pairs that appear at the top level of
    loginusers.vdf (no arrays, no nested sub-keys beyond the first level).
    Returns a dict of {outer_key: {inner_key: value, ...}}.
    """
    result: dict = {}
    stack: list = [result]

    pending: Optional[str] = None
    for m in re.finditer(r'"((?:[^"\\]|\\.)*)"|(\{)|(\})', text):
        string_val, open_brace, close_brace = m.group(1), m.group(2), m.group(3)
        if string_val is not None:
            if pending is None:
                pending = string_val
            else:
                # key/value pair
                if isinstance(stack[-1], dict):
                    stack[-1][pending] = string_val
                pending = None
        elif open_brace:
            new_dict: dict = {}
            if pending is not None and isinstance(stack[-1], dict):
                stack[-1][pending] = new_dict
                pending = None
            stack.append(new_dict)
        elif close_brace:
            finished = stack.pop()
            if stack and isinstance(stack[-1], dict):
                # The finished dict may already be attached; nothing extra needed.
                pass

    return result


def _load_loginusers(steam_path: str) -> dict:
    """Parse Steam/config/loginusers.vdf and return its contents."""
    vdf_path = Path(steam_path) / "config" / "loginusers.vdf"
    if not vdf_path.is_file():
        return {}
    text = vdf_path.read_text(encoding="utf-8", errors="replace")
    parsed = _parse_vdf_simple(text)
    # loginusers.vdf structure: {"users": {steamid64: {...}, ...}}
    for key in ("users", "Users"):
        if key in parsed:
            return parsed[key]
    return parsed


def _steamid64_to_steamid3(steamid64: str) -> Optional[str]:
    """
    Convert a SteamID64 string to the SteamID3 account ID used in userdata.

    SteamID3 = SteamID64 - 76561197960265728
    """
    try:
        return str(int(steamid64) - 76561197960265728)
    except (ValueError, TypeError):
        return None


def get_cs2_accounts(steam_path: str) -> list[dict]:
    """
    Return a list of Steam accounts that have CS2 (appid 730) userdata.

    Each entry is a dict with keys:
      - steamid64: str
      - steamid3:  str   (used as directory name under userdata/)
      - name:      str   (persona name, may be empty)
      - cs2_cfg_path:    Path  (local cfg directory)
      - cs2_remote_path: Path  (remote directory)
    """
    userdata_root = Path(steam_path) / "userdata"
    if not userdata_root.is_dir():
        return []

    loginusers = _load_loginusers(steam_path)

    # Build a lookup: steamid3 -> account info from loginusers.vdf
    id3_to_info: dict[str, dict] = {}
    for sid64, info in loginusers.items():
        sid3 = _steamid64_to_steamid3(sid64)
        if sid3:
            id3_to_info[sid3] = {"steamid64": sid64, **info}

    accounts = []
    for entry in userdata_root.iterdir():
        if not entry.is_dir():
            continue
        sid3 = entry.name
        cs2_dir = entry / CS2_APP_ID
        if not cs2_dir.is_dir():
            continue

        info = id3_to_info.get(sid3, {})
        persona = info.get("PersonaName", info.get("personaname", ""))

        accounts.append(
            {
                "steamid64": info.get("steamid64", ""),
                "steamid3": sid3,
                "name": persona or sid3,
                "cs2_cfg_path": cs2_dir / "local" / "cfg",
                "cs2_remote_path": cs2_dir / "remote",
            }
        )

    accounts.sort(key=lambda a: a["name"].lower())
    return accounts


# CS2 config files that can be synced
CONFIG_FILE_GROUPS = {
    "Autoexec (autoexec.cfg)": [
        ("cs2_cfg_path", "autoexec.cfg"),
    ],
    "Game Config (config.cfg)": [
        ("cs2_cfg_path", "config.cfg"),
    ],
    "Video Settings (video.txt)": [
        ("cs2_remote_path", "video.txt"),
    ],
    "Key Bindings (cs2_user_keys.vdf)": [
        ("cs2_remote_path", "cs2_user_keys.vdf"),
    ],
    "Console Variables (cs2_user_convars.vdf)": [
        ("cs2_remote_path", "cs2_user_convars.vdf"),
    ],
    "Practice Config (practiceserver.cfg)": [
        ("cs2_cfg_path", "practiceserver.cfg"),
    ],
}
