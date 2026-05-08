"""
Config file sync logic with automatic backup support.
"""

import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional


def _backup_path(dest: Path) -> Path:
    """Return a timestamped backup path for *dest*."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return dest.with_name(f"{dest.name}.bak_{ts}")


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
            src_file = Path(source_account[path_key]) / filename
            dst_dir = Path(dest_account[path_key])
            dst_file = dst_dir / filename

            if not src_file.is_file():
                msg = f"[跳过] {group_name} – 源文件不存在: {src_file}"
                log(msg)
                results["skipped"].append(msg)
                continue

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
