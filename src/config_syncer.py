"""
Config file sync logic with automatic backup support.
"""

import json
import re
import shutil
from datetime import datetime
from glob import has_magic
from pathlib import Path
from typing import Callable, Optional


def _backup_path(dest: Path) -> Path:
    """Return a timestamped backup path for *dest*."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return dest.with_name(f"{dest.name}.bak_{ts}")


def _resolve_existing_files(base_dir: Path, file_spec: str) -> list[Path]:
    """Resolve file_spec under base_dir and return existing files."""
    if has_magic(file_spec):
        return sorted(path for path in base_dir.glob(file_spec) if path.is_file())

    candidate = base_dir / file_spec
    if candidate.is_file():
        return [candidate]
    return []


def backup_account_configs(
    account: dict,
    file_groups: list[str],
    group_definitions: dict,
    backup_root: Path | str,
    backup_label: str | None = None,
    log_callback: Optional[Callable[[str], None]] = None,
) -> dict:
    """
    Backup selected config files from *account* into a dated backup directory.

    Returns dict with keys "copied", "skipped", "failed", "backup_dir".
    """
    results: dict[str, list[str] | str] = {
        "copied": [],
        "skipped": [],
        "failed": [],
        "backup_dir": "",
    }

    def log(msg: str) -> None:
        if log_callback:
            log_callback(msg)

    sid3 = account.get("steamid3", "unknown")
    dated_label = backup_label or datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = Path(backup_root) / sid3 / dated_label
    backup_dir.mkdir(parents=True, exist_ok=True)

    for group_name in file_groups:
        entries = group_definitions.get(group_name, [])
        for path_key, filename in entries:
            dst_dir = backup_dir / path_key
            src_root = Path(account[path_key])
            src_files = _resolve_existing_files(src_root, filename)

            if not src_files:
                msg = f"[跳过] {group_name} – 待备份文件不存在: {src_root / filename}"
                log(msg)
                results["skipped"].append(msg)
                continue

            for src_file in src_files:
                dst_file = dst_dir / src_file.name
                try:
                    dst_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_file, dst_file)
                    msg = f"[备份] {group_name}: {src_file} → {dst_file}"
                    log(msg)
                    results["copied"].append(msg)
                except PermissionError as exc:
                    msg = f"[失败] {group_name} – 备份权限不足: {exc}"
                    log(msg)
                    results["failed"].append(msg)
                except OSError as exc:
                    msg = f"[失败] {group_name} – 备份文件操作错误: {exc}"
                    log(msg)
                    results["failed"].append(msg)

    results["backup_dir"] = str(backup_dir)
    return results


def sync_configs(
    source_account: dict,
    dest_account: dict,
    file_groups: list[str],
    group_definitions: dict,
    backup: bool = True,
    log_callback: Optional[Callable[[str], None]] = None,
) -> dict:
    """
    Copy selected config file groups from *source_account* to *dest_account*.

    Parameters
    ----------
    source_account:   account dict returned by get_cs2_accounts()
    dest_account:     account dict returned by get_cs2_accounts()
    file_groups:      list of group names (keys of CONFIG_FILE_GROUPS) to sync
    group_definitions: the CONFIG_FILE_GROUPS constant from steam_manager
    backup:           if True, existing destination files are backed up first
    log_callback:     optional callable(str) that receives log messages

    Returns
    -------
    dict with keys "copied", "skipped", "failed" – each a list of str messages.
    """
    results: dict[str, list[str]] = {"copied": [], "skipped": [], "failed": []}

    def log(msg: str) -> None:
        if log_callback:
            log_callback(msg)

    if source_account["steamid3"] == dest_account["steamid3"]:
        msg = "源账号和目标账号相同，跳过同步。"
        log(msg)
        results["skipped"].append(msg)
        return results

    for group_name in file_groups:
        entries = group_definitions.get(group_name, [])
        for path_key, filename in entries:
            src_root = Path(source_account[path_key])
            src_files = _resolve_existing_files(src_root, filename)
            dst_dir = Path(dest_account[path_key])

            if not src_files:
                msg = f"[跳过] {group_name} – 源文件不存在: {src_root / filename}"
                log(msg)
                results["skipped"].append(msg)
                continue

            for src_file in src_files:
                dst_file = dst_dir / src_file.name
                try:
                    dst_dir.mkdir(parents=True, exist_ok=True)

                    if dst_file.exists() and backup:
                        bak = _backup_path(dst_file)
                        shutil.copy2(dst_file, bak)
                        log(f"[备份] {dst_file.name} → {bak.name}")

                    shutil.copy2(src_file, dst_file)
                    msg = f"[成功] {group_name}: {src_file} → {dst_file}"
                    log(msg)
                    results["copied"].append(msg)

                except PermissionError as exc:
                    msg = f"[失败] {group_name} – 权限不足: {exc}"
                    log(msg)
                    results["failed"].append(msg)
                except OSError as exc:
                    msg = f"[失败] {group_name} – 文件操作错误: {exc}"
                    log(msg)
                    results["failed"].append(msg)

    return results


def _sanitize_profile_name(profile_name: str) -> str:
    """Return a filesystem-safe profile name."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (profile_name or "").strip())
    cleaned = cleaned.strip("._-")
    return cleaned or "profile"


def list_saved_profiles(storage_root: Path | str) -> list[dict]:
    """List saved config profiles from *storage_root*."""
    root = Path(storage_root)
    if not root.is_dir():
        return []

    profiles: list[dict] = []
    for profile_dir in root.iterdir():
        if not profile_dir.is_dir():
            continue

        meta = {
            "name": profile_dir.name,
            "display_name": profile_dir.name,
            "saved_at": "",
            "source_steamid3": "",
        }
        meta_file = profile_dir / "profile.json"
        if meta_file.is_file():
            try:
                loaded = json.loads(meta_file.read_text(encoding="utf-8"))
                meta.update(
                    {
                        "name": loaded.get("name", profile_dir.name),
                        "display_name": loaded.get("display_name", profile_dir.name),
                        "saved_at": loaded.get("saved_at", ""),
                        "source_steamid3": loaded.get("source_steamid3", ""),
                    }
                )
            except (json.JSONDecodeError, OSError):
                pass

        profiles.append(meta)

    profiles.sort(key=lambda p: p.get("saved_at", ""), reverse=True)
    return profiles


def save_profile_configs(
    source_account: dict,
    file_groups: list[str],
    group_definitions: dict,
    storage_root: Path | str,
    profile_name: str,
    log_callback: Optional[Callable[[str], None]] = None,
) -> dict:
    """
    Save selected config files from *source_account* into a local named profile.

    Returns dict with keys "copied", "skipped", "failed", "profile_name".
    """
    results: dict[str, list[str] | str] = {
        "copied": [],
        "skipped": [],
        "failed": [],
        "profile_name": "",
    }

    def log(msg: str) -> None:
        if log_callback:
            log_callback(msg)

    safe_name = _sanitize_profile_name(profile_name)
    profile_dir = Path(storage_root) / safe_name
    profile_dir.mkdir(parents=True, exist_ok=True)

    for group_name in file_groups:
        entries = group_definitions.get(group_name, [])
        for path_key, filename in entries:
            src_root = Path(source_account[path_key])
            src_files = _resolve_existing_files(src_root, filename)
            dst_dir = profile_dir / path_key

            if not src_files:
                msg = f"[跳过] {group_name} – 源文件不存在: {src_root / filename}"
                log(msg)
                results["skipped"].append(msg)
                continue

            for src_file in src_files:
                dst_file = dst_dir / src_file.name
                try:
                    dst_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_file, dst_file)
                    msg = f"[成功] {group_name}: {src_file} → {dst_file}"
                    log(msg)
                    results["copied"].append(msg)
                except PermissionError as exc:
                    msg = f"[失败] {group_name} – 权限不足: {exc}"
                    log(msg)
                    results["failed"].append(msg)
                except OSError as exc:
                    msg = f"[失败] {group_name} – 文件操作错误: {exc}"
                    log(msg)
                    results["failed"].append(msg)

    try:
        meta = {
            "name": safe_name,
            "display_name": profile_name.strip() or safe_name,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "source_steamid3": source_account.get("steamid3", ""),
            "source_name": source_account.get("name", ""),
            "groups": file_groups,
        }
        (profile_dir / "profile.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        msg = f"[失败] 保存配置档元数据失败: {exc}"
        log(msg)
        results["failed"].append(msg)

    results["profile_name"] = safe_name
    return results


def apply_saved_profile_configs(
    profile_name: str,
    dest_account: dict,
    file_groups: list[str],
    group_definitions: dict,
    storage_root: Path | str,
    backup: bool = True,
    log_callback: Optional[Callable[[str], None]] = None,
) -> dict:
    """
    Apply selected config files from a saved profile to *dest_account*.
    """
    results: dict[str, list[str]] = {"copied": [], "skipped": [], "failed": []}

    def log(msg: str) -> None:
        if log_callback:
            log_callback(msg)

    safe_name = _sanitize_profile_name(profile_name)
    profile_dir = Path(storage_root) / safe_name
    if not profile_dir.is_dir():
        msg = f"[失败] 配置档不存在: {profile_dir}"
        log(msg)
        results["failed"].append(msg)
        return results

    for group_name in file_groups:
        entries = group_definitions.get(group_name, [])
        for path_key, filename in entries:
            src_root = profile_dir / path_key
            src_files = _resolve_existing_files(src_root, filename)
            dst_dir = Path(dest_account[path_key])

            if not src_files:
                msg = f"[跳过] {group_name} – 配置档文件不存在: {src_root / filename}"
                log(msg)
                results["skipped"].append(msg)
                continue

            for src_file in src_files:
                dst_file = dst_dir / src_file.name
                try:
                    dst_dir.mkdir(parents=True, exist_ok=True)

                    if dst_file.exists() and backup:
                        bak = _backup_path(dst_file)
                        shutil.copy2(dst_file, bak)
                        log(f"[备份] {dst_file.name} → {bak.name}")

                    shutil.copy2(src_file, dst_file)
                    msg = f"[成功] {group_name}: {src_file} → {dst_file}"
                    log(msg)
                    results["copied"].append(msg)
                except PermissionError as exc:
                    msg = f"[失败] {group_name} – 权限不足: {exc}"
                    log(msg)
                    results["failed"].append(msg)
                except OSError as exc:
                    msg = f"[失败] {group_name} – 文件操作错误: {exc}"
                    log(msg)
                    results["failed"].append(msg)

    return results


def delete_saved_profile(storage_root: Path | str, profile_name: str) -> bool:
    """
    Delete a saved profile directory.

    Returns True if successfully deleted, False otherwise.
    """
    safe_name = _sanitize_profile_name(profile_name)
    profile_dir = Path(storage_root) / safe_name
    if not profile_dir.is_dir():
        return False
    try:
        shutil.rmtree(profile_dir)
        return True
    except OSError:
        return False
