"""
CS2 Config Manager – Main GUI Application.

A Windows utility for managing CS2 configuration files for Steam accounts.
"""

import sys
import threading
import tkinter as tk
from io import BytesIO
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.error import URLError
from urllib.request import Request, urlopen

# Ensure src/ is importable when run as a script or bundled executable.
if getattr(sys, "frozen", False):
    import os
    sys.path.insert(0, os.path.dirname(sys.executable))

from steam_manager import (
    CONFIG_FILE_GROUPS,
    find_steam_path,
    get_cs2_accounts,
    get_steam_avatar_url,
    switch_steam_account,
    STEAM_HTTP_USER_AGENT,
)
from config_syncer import (
    apply_saved_profile_configs,
    backup_account_configs,
    delete_saved_profile,
    list_saved_profiles,
    save_profile_configs,
    sync_configs,
)

try:
    from PIL import Image, ImageTk, UnidentifiedImageError
except ImportError:
    Image = None
    ImageTk = None
    UnidentifiedImageError = OSError

APP_TITLE = "CS2 配置管理器"
APP_VERSION = "2.0.0"
WINDOW_WIDTH = 680
WINDOW_HEIGHT = 640
BG_COLOR = "#1a1a2e"
SURFACE_COLOR = "#16213e"
CARD_COLOR = "#0f3460"
ACCENT_COLOR = "#e94560"
HIGHLIGHT_COLOR = "#315ca8"
TEXT_COLOR = "#eaeaea"
SUBTEXT_COLOR = "#a0a0b0"
SUCCESS_COLOR = "#4caf50"
WARNING_COLOR = "#ff9800"
ERROR_COLOR = "#f44336"
FONT_FAMILY = "Segoe UI"
AVATAR_SIZE = 48
ALL_CONFIG_FILE_GROUPS = tuple(CONFIG_FILE_GROUPS.keys())


class CS2ConfigManager(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_TITLE}  v{APP_VERSION}")
        self.configure(bg=BG_COLOR)
        self.resizable(True, True)
        self.minsize(700, 540)
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")

        self._steam_path: str | None = None
        self._accounts: list[dict] = []
        self._sync_vars: dict[str, tk.BooleanVar] = {}
        self._backup_var = tk.BooleanVar(value=True)
        self._dated_backup_var = tk.BooleanVar(value=False)
        self._profile_name_var = tk.StringVar()
        self._profile_var = tk.StringVar()
        self._profile_label_to_name: dict[str, str] = {}
        self._profile_storage_root = Path.home() / ".cs2-config-manager" / "profiles"
        self._account_backup_root = Path.home() / ".cs2-config-manager" / "account-backups"
        self._avatar_cache: dict[str, "ImageTk.PhotoImage"] = {}
        self._avatar_pending: set[str] = set()
        # Keep a reference to current avatar PhotoImage to prevent GC
        self._current_avatar_photo: "ImageTk.PhotoImage | None" = None

        self._build_ui()
        self._fit_window_to_content()
        self._refresh_profiles()
        self._detect_steam()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Build all UI widgets."""
        self._build_header()
        self._build_steam_path_bar()
        self._build_main_area()
        self._build_log_area()
        self._build_footer()

    def _build_header(self) -> None:
        header = tk.Frame(self, bg=CARD_COLOR, pady=12)
        header.pack(fill=tk.X)

        tk.Label(
            header,
            text="⚙  CS2 配置管理器",
            bg=CARD_COLOR,
            fg=TEXT_COLOR,
            font=(FONT_FAMILY, 18, "bold"),
        ).pack(side=tk.LEFT, padx=20)

        tk.Label(
            header,
            text=f"v{APP_VERSION}",
            bg=CARD_COLOR,
            fg=SUBTEXT_COLOR,
            font=(FONT_FAMILY, 10),
        ).pack(side=tk.LEFT, padx=4, pady=8)

    def _build_steam_path_bar(self) -> None:
        bar = tk.Frame(self, bg=SURFACE_COLOR, pady=8, padx=16)
        bar.pack(fill=tk.X)

        tk.Label(
            bar,
            text="Steam 路径:",
            bg=SURFACE_COLOR,
            fg=SUBTEXT_COLOR,
            font=(FONT_FAMILY, 9),
        ).pack(side=tk.LEFT)

        self._steam_path_label = tk.Label(
            bar,
            text="检测中…",
            bg=SURFACE_COLOR,
            fg=TEXT_COLOR,
            font=(FONT_FAMILY, 9),
        )
        self._steam_path_label.pack(side=tk.LEFT, padx=8)

        tk.Button(
            bar,
            text="浏览…",
            command=self._browse_steam,
            bg=CARD_COLOR,
            fg=TEXT_COLOR,
            relief=tk.FLAT,
            padx=10,
            cursor="hand2",
            font=(FONT_FAMILY, 9),
        ).pack(side=tk.RIGHT)

        tk.Button(
            bar,
            text="刷新账号",
            command=self._refresh_accounts,
            bg=CARD_COLOR,
            fg=TEXT_COLOR,
            relief=tk.FLAT,
            padx=10,
            cursor="hand2",
            font=(FONT_FAMILY, 9),
        ).pack(side=tk.RIGHT, padx=6)

    def _build_main_area(self) -> None:
        main = tk.Frame(self, bg=BG_COLOR)
        main.pack(fill=tk.BOTH, expand=True, padx=16, pady=10)

        content = tk.Frame(main, bg=BG_COLOR)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, weight=1)

        left_col = tk.Frame(content, bg=BG_COLOR)
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        right_col = tk.Frame(content, bg=BG_COLOR)
        right_col.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        self._build_account_selector(left_col)
        self._build_file_group_checkboxes(left_col)
        self._build_options(right_col)
        self._build_profile_storage(right_col)

    def _build_account_selector(self, parent: tk.Frame) -> None:
        self._section_label(parent, "账号选择")

        card = tk.Frame(parent, bg=SURFACE_COLOR, padx=12, pady=10)
        card.pack(fill=tk.X, pady=(4, 8))

        # Account selector row
        tk.Label(
            card,
            text="选择账号:",
            bg=SURFACE_COLOR,
            fg=SUBTEXT_COLOR,
            font=(FONT_FAMILY, 9),
        ).pack(anchor=tk.W)

        self._account_var = tk.StringVar()
        self._account_combo = ttk.Combobox(
            card,
            textvariable=self._account_var,
            state="readonly",
            font=(FONT_FAMILY, 10),
        )
        self._account_combo.pack(fill=tk.X, pady=(2, 8))
        self._account_combo.bind("<<ComboboxSelected>>", self._on_account_change)

        # Avatar display area
        avatar_frame = tk.Frame(card, bg=SURFACE_COLOR)
        avatar_frame.pack(fill=tk.X, pady=(0, 8))

        self._avatar_label = tk.Label(
            avatar_frame,
            bg=SURFACE_COLOR,
            width=AVATAR_SIZE,
            height=AVATAR_SIZE,
        )
        self._avatar_label.pack(side=tk.LEFT)

        self._account_info_label = tk.Label(
            avatar_frame,
            text="未选择账号",
            bg=SURFACE_COLOR,
            fg=SUBTEXT_COLOR,
            font=(FONT_FAMILY, 10),
            anchor=tk.W,
            justify=tk.LEFT,
        )
        self._account_info_label.pack(side=tk.LEFT, padx=(10, 0), fill=tk.X, expand=True)

        # Switch Steam account button
        tk.Button(
            card,
            text="🔄 切换Steam到当前账号",
            command=self._switch_steam_account,
            bg=HIGHLIGHT_COLOR,
            fg=TEXT_COLOR,
            relief=tk.FLAT,
            cursor="hand2",
            font=(FONT_FAMILY, 10, "bold"),
            pady=6,
        ).pack(fill=tk.X, pady=(0, 4))

        # Save account settings button
        tk.Button(
            card,
            text="💾 保存当前账号设置",
            command=self._save_profile,
            bg=CARD_COLOR,
            fg=TEXT_COLOR,
            relief=tk.FLAT,
            cursor="hand2",
            font=(FONT_FAMILY, 9),
            pady=4,
        ).pack(fill=tk.X, pady=(4, 0))

    def _build_file_group_checkboxes(self, parent: tk.Frame) -> None:
        self._section_label(parent, "配置文件类型")

        card = tk.Frame(parent, bg=SURFACE_COLOR, padx=12, pady=10)
        card.pack(fill=tk.X, pady=(4, 8))
        card.columnconfigure(0, weight=1)
        card.columnconfigure(1, weight=1)

        for index, group_name in enumerate(CONFIG_FILE_GROUPS):
            var = tk.BooleanVar(value=True)
            self._sync_vars[group_name] = var
            cb = tk.Checkbutton(
                card,
                text=group_name,
                variable=var,
                bg=SURFACE_COLOR,
                fg=TEXT_COLOR,
                selectcolor=CARD_COLOR,
                activebackground=SURFACE_COLOR,
                activeforeground=TEXT_COLOR,
                font=(FONT_FAMILY, 9),
            )
            cb.grid(
                row=index // 2,
                column=index % 2,
                sticky="w",
                padx=(0, 12),
                pady=1,
            )

    def _build_options(self, parent: tk.Frame) -> None:
        self._section_label(parent, "选项")

        card = tk.Frame(parent, bg=SURFACE_COLOR, padx=12, pady=8)
        card.pack(fill=tk.X, pady=(4, 8))

        tk.Checkbutton(
            card,
            text="操作前备份文件",
            variable=self._backup_var,
            bg=SURFACE_COLOR,
            fg=TEXT_COLOR,
            selectcolor=CARD_COLOR,
            activebackground=SURFACE_COLOR,
            activeforeground=TEXT_COLOR,
            font=(FONT_FAMILY, 9),
        ).pack(anchor=tk.W)

        tk.Checkbutton(
            card,
            text="操作前按日期备份账号配置",
            variable=self._dated_backup_var,
            bg=SURFACE_COLOR,
            fg=TEXT_COLOR,
            selectcolor=CARD_COLOR,
            activebackground=SURFACE_COLOR,
            activeforeground=TEXT_COLOR,
            font=(FONT_FAMILY, 9),
        ).pack(anchor=tk.W)

    def _build_profile_storage(self, parent: tk.Frame) -> None:
        self._section_label(parent, "已保存配置")

        card = tk.Frame(parent, bg=SURFACE_COLOR, padx=12, pady=8)
        card.pack(fill=tk.X, pady=(4, 8))

        tk.Label(
            card,
            text="配置档名称（留空将按账号名生成）:",
            bg=SURFACE_COLOR,
            fg=SUBTEXT_COLOR,
            font=(FONT_FAMILY, 9),
        ).pack(anchor=tk.W)

        tk.Entry(
            card,
            textvariable=self._profile_name_var,
            bg=CARD_COLOR,
            fg=TEXT_COLOR,
            insertbackground=TEXT_COLOR,
            relief=tk.FLAT,
            font=(FONT_FAMILY, 9),
        ).pack(fill=tk.X, pady=(2, 6))

        tk.Label(
            card,
            text="已保存配置档:",
            bg=SURFACE_COLOR,
            fg=SUBTEXT_COLOR,
            font=(FONT_FAMILY, 9),
        ).pack(anchor=tk.W)

        self._profile_combo = ttk.Combobox(
            card,
            textvariable=self._profile_var,
            state="readonly",
            font=(FONT_FAMILY, 9),
        )
        self._profile_combo.pack(fill=tk.X, pady=(2, 6))

        btn_row = tk.Frame(card, bg=SURFACE_COLOR)
        btn_row.pack(fill=tk.X)

        tk.Button(
            btn_row,
            text="刷新",
            command=self._refresh_profiles,
            bg=CARD_COLOR,
            fg=TEXT_COLOR,
            relief=tk.FLAT,
            cursor="hand2",
            font=(FONT_FAMILY, 9),
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))

        tk.Button(
            btn_row,
            text="应用到当前账号",
            command=self._start_apply_profile,
            bg=CARD_COLOR,
            fg=TEXT_COLOR,
            relief=tk.FLAT,
            cursor="hand2",
            font=(FONT_FAMILY, 9),
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(3, 3))

        tk.Button(
            btn_row,
            text="🗑 删除",
            command=self._delete_profile,
            bg=ERROR_COLOR,
            fg="white",
            relief=tk.FLAT,
            cursor="hand2",
            font=(FONT_FAMILY, 9),
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(3, 0))

    def _build_log_area(self) -> None:
        frame = tk.Frame(self, bg=BG_COLOR, padx=16, pady=0)
        frame.pack(fill=tk.X)

        self._section_label(frame, "操作日志")

        log_frame = tk.Frame(frame, bg="#0a0a14")
        log_frame.pack(fill=tk.X)

        self._log_text = tk.Text(
            log_frame,
            height=7,
            bg="#0a0a14",
            fg=TEXT_COLOR,
            font=("Consolas", 9),
            relief=tk.FLAT,
            state=tk.DISABLED,
            wrap=tk.WORD,
        )
        vsb = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=vsb.set)
        self._log_text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._log_text.tag_config("success", foreground=SUCCESS_COLOR)
        self._log_text.tag_config("warning", foreground=WARNING_COLOR)
        self._log_text.tag_config("error", foreground=ERROR_COLOR)
        self._log_text.tag_config("info", foreground=SUBTEXT_COLOR)

    def _build_footer(self) -> None:
        footer = tk.Frame(self, bg=SURFACE_COLOR, pady=4)
        footer.pack(fill=tk.X, side=tk.BOTTOM)

        self._status_var = tk.StringVar(value="就绪")
        tk.Label(
            footer,
            textvariable=self._status_var,
            bg=SURFACE_COLOR,
            fg=SUBTEXT_COLOR,
            font=(FONT_FAMILY, 9),
        ).pack(side=tk.LEFT, padx=12)

        tk.Label(
            footer,
            text="MIT License © 2026 Mercerry",
            bg=SURFACE_COLOR,
            fg=SUBTEXT_COLOR,
            font=(FONT_FAMILY, 8),
        ).pack(side=tk.RIGHT, padx=12)

    def _fit_window_to_content(self) -> None:
        """Resize and center the window so all content is visible by default."""
        self.update_idletasks()
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        req_width = self.winfo_reqwidth()
        req_height = self.winfo_reqheight()

        width = min(max(WINDOW_WIDTH, req_width + 24), screen_width - 40)
        height = min(max(WINDOW_HEIGHT, req_height + 40), screen_height - 80)
        x = max((screen_width - width) // 2, 0)
        y = max((screen_height - height) // 2, 0)

        self.geometry(f"{width}x{height}+{x}+{y}")

    # ------------------------------------------------------------------
    # Helper widgets
    # ------------------------------------------------------------------

    def _section_label(self, parent: tk.Widget, text: str) -> None:
        tk.Label(
            parent,
            text=text.upper(),
            bg=BG_COLOR if parent["bg"] == BG_COLOR else parent["bg"],
            fg=ACCENT_COLOR,
            font=(FONT_FAMILY, 8, "bold"),
        ).pack(anchor=tk.W, pady=(6, 0))

    # ------------------------------------------------------------------
    # Avatar logic (completely rewritten)
    # ------------------------------------------------------------------

    def _create_placeholder_avatar(self, name: str) -> "ImageTk.PhotoImage | None":
        """Create a colored circle placeholder with the first letter."""
        if Image is None or ImageTk is None:
            return None
        try:
            from PIL import ImageDraw, ImageFont

            img = Image.new("RGBA", (AVATAR_SIZE, AVATAR_SIZE), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.ellipse([0, 0, AVATAR_SIZE - 1, AVATAR_SIZE - 1], fill=(75, 79, 104))
            letter = (name[:1] or "?").upper()
            try:
                font = ImageFont.truetype("arial.ttf", AVATAR_SIZE // 2)
            except (OSError, IOError):
                font = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), letter, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            x = (AVATAR_SIZE - text_w) // 2
            y = (AVATAR_SIZE - text_h) // 2 - bbox[1]
            draw.text((x, y), letter, fill="white", font=font)
            return ImageTk.PhotoImage(img)
        except Exception:
            return None

    def _update_avatar_display(self) -> None:
        """Update the avatar label with the current account's avatar."""
        account = self._get_selected_account()
        if not account:
            self._avatar_label.config(image="", text="?", fg=SUBTEXT_COLOR,
                                      font=(FONT_FAMILY, 16, "bold"),
                                      width=AVATAR_SIZE, height=AVATAR_SIZE)
            self._account_info_label.config(text="未选择账号")
            self._current_avatar_photo = None
            return

        name = account.get("name", "?")
        steamid3 = account.get("steamid3", "")
        steamid64 = account.get("steamid64", "")
        self._account_info_label.config(
            text=f"{name}\nSteamID3: {steamid3}\nSteamID64: {steamid64}"
        )

        # Check memory cache first
        if steamid64 and steamid64 in self._avatar_cache:
            photo = self._avatar_cache[steamid64]
            self._current_avatar_photo = photo
            self._avatar_label.config(image=photo, text="", width=AVATAR_SIZE, height=AVATAR_SIZE)
            return

        # Show placeholder while loading
        placeholder = self._create_placeholder_avatar(name)
        if placeholder:
            self._current_avatar_photo = placeholder
            self._avatar_label.config(image=placeholder, text="", width=AVATAR_SIZE, height=AVATAR_SIZE)
        else:
            self._avatar_label.config(image="", text=name[:1].upper(),
                                      fg=TEXT_COLOR, font=(FONT_FAMILY, 16, "bold"),
                                      width=AVATAR_SIZE, height=AVATAR_SIZE)

        # Start async fetch
        if steamid64:
            self._fetch_avatar_async(steamid64)

    def _fetch_avatar_async(self, steamid64: str) -> None:
        """Fetch avatar image in background thread."""
        if steamid64 in self._avatar_pending:
            return
        self._avatar_pending.add(steamid64)
        threading.Thread(target=self._avatar_fetch_worker, args=(steamid64,), daemon=True).start()

    def _avatar_fetch_worker(self, steamid64: str) -> None:
        """Background worker: fetch avatar URL then download image data."""
        avatar_url = get_steam_avatar_url(steamid64)
        if not avatar_url:
            self.after(0, self._on_avatar_fetch_done, steamid64, None)
            return

        request = Request(avatar_url, headers={"User-Agent": STEAM_HTTP_USER_AGENT})
        try:
            with urlopen(request, timeout=8) as response:
                image_data = response.read()
        except (URLError, TimeoutError, OSError):
            self.after(0, self._on_avatar_fetch_done, steamid64, None)
            return

        self.after(0, self._on_avatar_fetch_done, steamid64, image_data)

    def _on_avatar_fetch_done(self, steamid64: str, image_data: bytes | None) -> None:
        """Called on main thread when avatar fetch completes."""
        self._avatar_pending.discard(steamid64)

        if not image_data or Image is None or ImageTk is None:
            return

        try:
            with Image.open(BytesIO(image_data)) as img:
                img = img.copy()
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGBA")
                if hasattr(Image, "Resampling"):
                    resample = Image.Resampling.LANCZOS
                else:
                    resample = Image.LANCZOS
                img = img.resize((AVATAR_SIZE, AVATAR_SIZE), resample)
                photo = ImageTk.PhotoImage(img)
        except (UnidentifiedImageError, OSError, ValueError, TypeError):
            return

        # Store in cache
        self._avatar_cache[steamid64] = photo

        # Update display if this account is still selected
        current = self._get_selected_account()
        if current and current.get("steamid64") == steamid64:
            self._current_avatar_photo = photo
            self._avatar_label.config(image=photo, text="", width=AVATAR_SIZE, height=AVATAR_SIZE)

    # ------------------------------------------------------------------
    # Business logic
    # ------------------------------------------------------------------

    def _detect_steam(self) -> None:
        """Auto-detect Steam installation in a background thread."""
        self._set_status("正在检测 Steam 安装路径…")
        threading.Thread(target=self._detect_steam_worker, daemon=True).start()

    def _detect_steam_worker(self) -> None:
        path = find_steam_path()
        self.after(0, self._on_steam_detected, path)

    def _on_steam_detected(self, path: str | None) -> None:
        if path:
            self._steam_path = path
            self._steam_path_label.config(text=path, fg=SUCCESS_COLOR)
            self._log(f"Steam 安装路径: {path}", "success")
            self._refresh_accounts()
        else:
            self._steam_path_label.config(text="未检测到 Steam，请手动选择路径", fg=ERROR_COLOR)
            self._log("未能自动检测到 Steam 安装路径，请使用「浏览…」按钮手动指定。", "error")
            self._set_status("未找到 Steam 安装路径")

    def _browse_steam(self) -> None:
        from tkinter import filedialog
        path = filedialog.askdirectory(title="选择 Steam 安装目录")
        if path:
            self._steam_path = path
            self._steam_path_label.config(text=path, fg=SUCCESS_COLOR)
            self._refresh_accounts()

    def _refresh_accounts(self) -> None:
        if not self._steam_path:
            return
        self._set_status("正在读取账号列表…")
        threading.Thread(target=self._refresh_accounts_worker, daemon=True).start()

    def _refresh_accounts_worker(self) -> None:
        accounts = get_cs2_accounts(self._steam_path)
        self.after(0, self._on_accounts_loaded, accounts)

    def _on_accounts_loaded(self, accounts: list[dict]) -> None:
        self._accounts = accounts
        labels = [
            f"{a['name']}  (SteamID3: {a['steamid3']})" for a in accounts
        ]

        self._account_combo["values"] = labels

        if labels:
            self._account_combo.current(0)
            self._log(f"找到 {len(accounts)} 个拥有 CS2 数据的账号。", "info")
            self._set_status(f"已加载 {len(accounts)} 个账号")
        else:
            self._log("未找到任何拥有 CS2 数据的账号。请确认 Steam 路径正确。", "warning")
            self._set_status("未找到 CS2 账号")

        self._update_avatar_display()

    def _refresh_profiles(self) -> None:
        profiles = list_saved_profiles(self._profile_storage_root)
        labels: list[str] = []
        self._profile_label_to_name.clear()
        for p in profiles:
            saved_at = p.get("saved_at", "")
            source_name = p.get("display_name", p.get("name", ""))
            label = f"{source_name} ({saved_at})" if saved_at else source_name
            labels.append(label)
            self._profile_label_to_name[label] = p.get("name", "")

        self._profile_combo["values"] = labels
        if labels:
            self._profile_combo.current(0)
        else:
            self._profile_var.set("")

    def _on_account_change(self, _event: "tk.Event | None" = None) -> None:
        self._update_avatar_display()

    def _get_selected_account(self) -> dict | None:
        label = self._account_var.get()
        for acc in self._accounts:
            expected = f"{acc['name']}  (SteamID3: {acc['steamid3']})"
            if expected == label:
                return acc
        return None

    def _switch_steam_account(self) -> None:
        """Switch Steam to the currently selected account."""
        account = self._get_selected_account()
        if not account:
            messagebox.showwarning(APP_TITLE, "请先选择一个账号。")
            return

        steamid64 = account.get("steamid64", "")
        if not steamid64:
            messagebox.showwarning(APP_TITLE, "该账号没有有效的 SteamID64。")
            return

        if not self._steam_path:
            messagebox.showwarning(APP_TITLE, "未检测到 Steam 路径。")
            return

        name = account.get("name", "")
        confirm = messagebox.askyesno(
            APP_TITLE,
            f"将切换 Steam 到账号:\n  {name}\n\n"
            "切换后需要重启 Steam 才能生效。\n确认继续？",
        )
        if not confirm:
            return

        success = switch_steam_account(self._steam_path, steamid64)
        if success:
            self._log(f"已切换 Steam 到账号: {name}，请重启 Steam。", "success")
            self._set_status(f"已切换到 {name}，请重启 Steam")
            messagebox.showinfo(APP_TITLE, f"已切换到 {name}\n请重启 Steam 使切换生效。")
        else:
            self._log(f"切换账号失败: {name}", "error")
            messagebox.showerror(APP_TITLE, "切换账号失败，请检查 Steam 路径和账号信息。")

    def _save_profile(self) -> None:
        account = self._get_selected_account()
        if not account:
            messagebox.showwarning(APP_TITLE, "请先选择一个账号。")
            return

        selected_groups = ALL_CONFIG_FILE_GROUPS
        profile_name = self._profile_name_var.get().strip() or f"{account['name']}_account_{account['steamid3']}"
        self._log("═" * 50)
        self._log(f"开始保存账号设置: {profile_name}", "info")

        results = save_profile_configs(
            source_account=account,
            file_groups=selected_groups,
            group_definitions=CONFIG_FILE_GROUPS,
            storage_root=self._profile_storage_root,
            profile_name=profile_name,
            log_callback=self._log_sync_line,
        )

        n_ok = len(results["copied"])
        n_skip = len(results["skipped"])
        n_fail = len(results["failed"])
        summary = f"账号设置保存完成：成功 {n_ok} 项，跳过 {n_skip} 项，失败 {n_fail} 项"
        self._log(summary, "success" if n_fail == 0 else "warning")
        self._log("═" * 50)
        self._set_status(summary)
        self._refresh_profiles()

        if n_fail:
            messagebox.showwarning(APP_TITLE, f"{summary}\n请检查操作日志获取详情。")
        else:
            messagebox.showinfo(APP_TITLE, summary)

    def _delete_profile(self) -> None:
        """Delete the selected saved profile with confirmation."""
        label = self._profile_var.get()
        profile_name = self._profile_label_to_name.get(label)
        if not profile_name:
            messagebox.showwarning(APP_TITLE, "请先选择一个已保存配置档。")
            return

        confirm = messagebox.askyesno(
            APP_TITLE,
            f"是否删除配置档 {label}？",
        )
        if not confirm:
            return

        success = delete_saved_profile(self._profile_storage_root, profile_name)
        if success:
            self._log(f"已删除配置档: {label}", "success")
            self._set_status(f"已删除配置档: {label}")
            self._refresh_profiles()
        else:
            self._log(f"删除配置档失败: {label}", "error")
            messagebox.showerror(APP_TITLE, f"删除配置档失败: {label}")

    def _start_apply_profile(self) -> None:
        account = self._get_selected_account()
        if not account:
            messagebox.showwarning(APP_TITLE, "请先选择目标账号。")
            return

        label = self._profile_var.get()
        profile_name = self._profile_label_to_name.get(label)
        if not profile_name:
            messagebox.showwarning(APP_TITLE, "请先选择一个已保存配置档。")
            return

        selected_groups = ALL_CONFIG_FILE_GROUPS

        confirm = messagebox.askyesno(
            APP_TITLE,
            f"将把配置档\n  {label}\n应用到账号\n  {account['name']}\n\n确认继续？",
        )
        if not confirm:
            return

        self._set_status("正在应用配置档…")
        self._log("═" * 50)
        self._log(f"开始应用配置档: {label} → {account['name']}", "info")

        threading.Thread(
            target=self._apply_profile_worker,
            args=(profile_name, account, selected_groups),
            daemon=True,
        ).start()

    def _apply_profile_worker(
        self, profile_name: str, account: dict, selected_groups: list[str]
    ) -> None:
        log_callback = lambda msg: self.after(0, self._log_sync_line, msg)
        if self._dated_backup_var.get():
            backup_results = backup_account_configs(
                account=account,
                file_groups=selected_groups,
                group_definitions=CONFIG_FILE_GROUPS,
                backup_root=self._account_backup_root,
                log_callback=log_callback,
            )
            if backup_results["failed"]:
                self.after(0, self._on_operation_done, backup_results)
                return

        results = apply_saved_profile_configs(
            profile_name=profile_name,
            dest_account=account,
            file_groups=selected_groups,
            group_definitions=CONFIG_FILE_GROUPS,
            storage_root=self._profile_storage_root,
            backup=self._backup_var.get(),
            log_callback=log_callback,
        )
        self.after(0, self._on_operation_done, results)

    def _log_sync_line(self, msg: str) -> None:
        if msg.startswith("[成功]"):
            tag = "success"
        elif msg.startswith("[失败]"):
            tag = "error"
        elif msg.startswith("[跳过]"):
            tag = "warning"
        elif msg.startswith("[备份]"):
            tag = "info"
        else:
            tag = None
        self._log(msg, tag)

    def _on_operation_done(self, results: dict) -> None:
        n_ok = len(results["copied"])
        n_skip = len(results["skipped"])
        n_fail = len(results["failed"])

        summary = f"操作完成：成功 {n_ok} 项，跳过 {n_skip} 项，失败 {n_fail} 项"
        self._log(summary, "success" if n_fail == 0 else "warning")
        self._log("═" * 50)
        self._set_status(summary)

        if n_fail:
            messagebox.showwarning(APP_TITLE, f"操作完成，但有 {n_fail} 项失败。\n请检查操作日志获取详情。")
        else:
            messagebox.showinfo(APP_TITLE, summary)

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------

    def _log(self, msg: str, tag: str | None = None) -> None:
        self._log_text.config(state=tk.NORMAL)
        self._log_text.insert(tk.END, msg + "\n", tag or "")
        self._log_text.see(tk.END)
        self._log_text.config(state=tk.DISABLED)

    def _set_status(self, msg: str) -> None:
        self._status_var.set(msg)


def main() -> None:
    app = CS2ConfigManager()
    app.mainloop()


if __name__ == "__main__":
    main()
