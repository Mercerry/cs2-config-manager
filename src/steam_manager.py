"""
Steam installation detection and account management utilities.
Supports Windows via Registry lookup and common path fallbacks.
"""

import os
import re
import json
import subprocess
import sys
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

CS2_APP_ID = "730"
STEAM_HTTP_USER_AGENT = "CS2ConfigManager/1.1"
SUBPROCESS_NO_WINDOW = (
    getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if sys.platform == "win32"
    else 0
)


class _PlayerAvatarImgParser(HTMLParser):
    """Extract avatar image URLs from Steam mini profile avatar section."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.avatar_urls: list[str] = []
        self._player_avatar_div_depth = 0

    def handle_starttag(self, tag: str, attrs):
        attrs_dict = dict(attrs)
        tag_lower = tag.lower()
        if tag_lower == "div":
            classes = (attrs_dict.get("class") or "").split()
            if "playersection_avatar" in classes or self._player_avatar_div_depth > 0:
                self._player_avatar_div_depth += 1
            return
        if tag_lower == "img" and self._player_avatar_div_depth > 0:
            src = unescape((attrs_dict.get("src") or "").strip())
            srcset = unescape((attrs_dict.get("srcset") or "").strip())
            srcset_best = _extract_best_srcset_url(srcset)
            if srcset_best and srcset_best.startswith(("http://", "https://")):
                self.avatar_urls.append(srcset_best)
            if src.startswith(("http://", "https://")):
                self.avatar_urls.append(src)

    def handle_endtag(self, tag: str):
        if tag.lower() == "div" and self._player_avatar_div_depth > 0:
            self._player_avatar_div_depth -= 1


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


def _extract_best_srcset_url(srcset: str) -> Optional[str]:
    """Extract highest-resolution URL from an img srcset attribute."""
    best_url = None
    best_scale = 0.0
    for item in srcset.split(","):
        parts = item.strip().split()
        if not parts:
            continue
        url = parts[0]
        scale = 1.0
        if len(parts) > 1 and parts[1].endswith("x"):
            try:
                scale = float(parts[1][:-1])
            except ValueError:
                scale = 1.0
        if scale > best_scale:
            best_scale = scale
            best_url = url
    return best_url


def _read_steam_api_key() -> Optional[str]:
    """Read Steam Web API key from api.txt near executable or current directory."""
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "api.txt")
    else:
        candidates.append(Path(sys.argv[0]).resolve().parent / "api.txt")
    candidates.append(Path.cwd() / "api.txt")

    seen: set[Path] = set()
    for key_path in candidates:
        if key_path in seen:
            continue
        seen.add(key_path)
        if not key_path.is_file():
            continue
        try:
            content = key_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if content:
            content_without_bom = content.lstrip("\ufeff")
            return content_without_bom.splitlines()[0].strip()
    return None


def _get_avatar_from_miniprofile(steamid64: str) -> Optional[str]:
    """Fetch avatar URL by parsing Steam mini profile HTML."""
    steamid3 = _steamid64_to_steamid3(steamid64)
    if not steamid3:
        return None

    profile_url = f"https://steamcommunity.com/miniprofile/{steamid3}?l=en"
    request = Request(profile_url, headers={"User-Agent": STEAM_HTTP_USER_AGENT})
    try:
        with urlopen(request, timeout=5) as response:
            content = response.read().decode("utf-8", errors="replace")
    except (URLError, TimeoutError, OSError):
        return None

    parser = _PlayerAvatarImgParser()
    parser.feed(content)
    parser.close()
    avatar_urls = parser.avatar_urls
    if not avatar_urls:
        return None
    for avatar_url in avatar_urls:
        if "_full." in avatar_url.lower():
            return avatar_url
    return avatar_urls[0]


def _get_avatar_from_steam_api(steamid64: str) -> Optional[str]:
    """Fetch avatar URL from Steam Web API using api.txt key."""
    api_key = _read_steam_api_key()
    if not api_key:
        return None

    query = urlencode({"key": api_key, "steamids": steamid64})
    api_url = f"https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/?{query}"
    request = Request(api_url, headers={"User-Agent": STEAM_HTTP_USER_AGENT})
    try:
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except (URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None

    players = payload.get("response", {}).get("players", [])
    if not players:
        return None
    player = players[0]
    for key in ("avatarfull", "avatarmedium", "avatar"):
        value = player.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    return None


def get_steam_avatar_url(steamid64: str) -> Optional[str]:
    """
    Fetch avatar URL with fallback strategy:
    1) Parse Steam mini profile HTML.
    2) Use Steam Web API with key from api.txt.
    """
    if not steamid64:
        return None
    avatar_url = _get_avatar_from_miniprofile(steamid64)
    if avatar_url:
        return avatar_url
    return _get_avatar_from_steam_api(steamid64)


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
    "Video Settings (cs2_video.txt)": [
        ("cs2_cfg_path", "cs2_video.txt"),
    ],
    "Key Bindings (cs2_user_keys_*_slot*.vcfg)": [
        ("cs2_cfg_path", "cs2_user_keys_*_slot*.vcfg"),
    ],
    "Console Variables (cs2_user_convars_*_slot*.vcfg)": [
        ("cs2_cfg_path", "cs2_user_convars_*_slot*.vcfg"),
    ],
    "Machine Console Variables (cs2_machine_convars.vcfg)": [
        ("cs2_cfg_path", "cs2_machine_convars.vcfg"),
    ],
    "Practice Config (practiceserver.cfg)": [
        ("cs2_cfg_path", "practiceserver.cfg"),
    ],
}


def switch_steam_account(steam_path: str, target_steamid64: str) -> bool:
    """
    Update Steam's loginusers.vdf to set the target account as the most recent.

    Sets MostRecent=1 for the target and MostRecent=0 for others.
    On Windows, also updates Steam's AutoLoginUser registry value so the
    restarted client signs into the selected account instead of the previous one.
    Returns True on success, False on failure.
    """
    vdf_path = Path(steam_path) / "config" / "loginusers.vdf"
    if not vdf_path.is_file():
        return False

    try:
        text = vdf_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False

    # Update MostRecent flags: set target to "1", others to "0"
    parsed = _parse_vdf_simple(text)
    users_key = None
    for key in ("users", "Users"):
        if key in parsed:
            users_key = key
            break
    if users_key is None:
        return False

    users = parsed[users_key]
    if target_steamid64 not in users:
        return False

    target_info = users[target_steamid64]
    account_name = ""
    for key in ("AccountName", "accountname"):
        value = target_info.get(key)
        if isinstance(value, str) and value.strip():
            account_name = value.strip()
            break
    if account_name and not _set_steam_autologin_user(account_name):
        return False

    for sid64, info in users.items():
        if sid64 == target_steamid64:
            # Steam VDF uses varying case for this key; set both to be safe
            info["MostRecent"] = "1"
            info["mostrecent"] = "1"
            if "RememberPassword" not in info and "rememberpassword" not in info:
                info["RememberPassword"] = "1"
        else:
            info["MostRecent"] = "0"
            info["mostrecent"] = "0"

    # Rebuild VDF content
    lines = ['"users"', "{"]
    for sid64, info in users.items():
        lines.append(f'\t"{sid64}"')
        lines.append("\t{")
        for k, v in info.items():
            if not isinstance(v, str):
                continue
            lines.append(f'\t\t"{k}"\t\t"{v}"')
        lines.append("\t}")
    lines.append("}")

    try:
        vdf_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        return False
    return True


def _set_steam_autologin_user(account_name: str) -> bool:
    """Update Steam's Windows registry keys for auto-login."""
    if sys.platform != "win32":
        return True
    if not account_name:
        return False

    try:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            winreg.SetValueEx(key, "AutoLoginUser", 0, winreg.REG_SZ, account_name)
            winreg.SetValueEx(key, "RememberPassword", 0, winreg.REG_DWORD, 1)
        return True
    except OSError:
        return False


def restart_steam(steam_path: str) -> bool:
    """Restart Steam on Windows; return True on restart success, else False."""
    if sys.platform != "win32":
        return False

    steam_exe = Path(steam_path) / "steam.exe"
    if not steam_exe.is_file():
        return False

    try:
        subprocess.run(
            ["taskkill", "/IM", "steam.exe", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=SUBPROCESS_NO_WINDOW,
        )
        subprocess.Popen(
            [str(steam_exe)],
            cwd=str(Path(steam_path)),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=SUBPROCESS_NO_WINDOW,
        )
        return True
    except OSError:
        return False
