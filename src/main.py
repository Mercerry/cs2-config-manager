"""
CS2 Config Manager – Main GUI Application.

A Windows utility for syncing CS2 configuration files between Steam accounts.
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
    STEAM_HTTP_USER_AGENT,
)
from config_syncer import (
    apply_saved_profile_configs,
    backup_account_configs,
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

APP_TITLE = "CS2 配置同步管理器"
APP_VERSION = "1.1.0"
WINDOW_WIDTH = 680
WINDOW_HEIGHT = 640
BG_COLOR = "#1a1a2e"
SURFACE_COLOR = "#16213e"
CARD_COLOR = "#0f3460"
ACCENT_COLOR = "#e94560"
TEXT_COLOR = "#eaeaea"
SUBTEXT_COLOR = "#a0a0b0"
SUCCESS_COLOR = "#4caf50"
WARNING_COLOR = "#ff9800"
ERROR_COLOR = "#f44336"
FONT_FAMILY = "Segoe UI"
AVATAR_SIZE = 28


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
        self._avatar_cache: dict[str, tk.PhotoImage] = {}
        self._avatar_pending: set[str] = set()

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
            text="⚙  CS2 配置同步管理器",
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

        self._build_account_selectors(content)
        self._build_file_group_checkboxes(content)
        self._build_options(content)
        self._build_profile_storage(content)
        self._build_sync_button(content)

    def _build_account_selectors(self, parent: tk.Frame) -> None:
        self._section_label(parent, "账号选择")

        card = tk.Frame(parent, bg=SURFACE_COLOR, padx=12, pady=10)
        card.pack(fill=tk.X, pady=(4, 8))

        # Source account
        tk.Label(
            card,
            text="源账号（复制配置来自）:",
            bg=SURFACE_COLOR,
            fg=SUBTEXT_COLOR,
            font=(FONT_FAMILY, 9),
        ).pack(anchor=tk.W)

        self._src_var = tk.StringVar()
        self._src_combo = ttk.Combobox(
            card,
            textvariable=self._src_var,
            state="readonly",
            font=(FONT_FAMILY, 10),
        )
        self._src_combo.pack(fill=tk.X, pady=(2, 8))
        self._src_combo.bind("<<ComboboxSelected>>", self._on_account_change)
        self._src_avatar_canvas, self._src_avatar_label = self._build_avatar_badge(card, "源账号")

        # Destination account
        tk.Label(
            card,
            text="目标账号（配置写入到）:",
            bg=SURFACE_COLOR,
            fg=SUBTEXT_COLOR,
            font=(FONT_FAMILY, 9),
        ).pack(anchor=tk.W)

        self._dst_var = tk.StringVar()
        self._dst_combo = ttk.Combobox(
            card,
            textvariable=self._dst_var,
            state="readonly",
            font=(FONT_FAMILY, 10),
        )
        self._dst_combo.pack(fill=tk.X, pady=(2, 0))
        self._dst_combo.bind("<<ComboboxSelected>>", self._on_account_change)
        self._dst_avatar_canvas, self._dst_avatar_label = self._build_avatar_badge(card, "目标账号")

    def _build_file_group_checkboxes(self, parent: tk.Frame) -> None:
        self._section_label(parent, "同步文件类型")

        card = tk.Frame(parent, bg=SURFACE_COLOR, padx=12, pady=10)
        card.pack(fill=tk.X, pady=(4, 8))
        card.columnconfigure(0, weight=1)
        card.columnconfigure(1, weight=1)

        style = ttk.Style()
        style.configure(
            "Custom.TCheckbutton",
            background=SURFACE_COLOR.__str__(),
            foreground=TEXT_COLOR.__str__(),
            font=(FONT_FAMILY, 9),
        )

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
            text="同步前备份目标文件",
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
            text="同步前按日期备份目标账号配置",
            variable=self._dated_backup_var,
            bg=SURFACE_COLOR,
            fg=TEXT_COLOR,
            selectcolor=CARD_COLOR,
            activebackground=SURFACE_COLOR,
            activeforeground=TEXT_COLOR,
            font=(FONT_FAMILY, 9),
        ).pack(anchor=tk.W)

    def _build_sync_button(self, parent: tk.Frame) -> None:
        self._sync_btn = tk.Button(
            parent,
            text="▶  开始同步",
            command=self._start_sync,
            bg=ACCENT_COLOR,
            fg="white",
            relief=tk.FLAT,
            font=(FONT_FAMILY, 12, "bold"),
            pady=10,
            cursor="hand2",
        )
        self._sync_btn.pack(fill=tk.X, pady=(4, 0))

    def _build_profile_storage(self, parent: tk.Frame) -> None:
        self._section_label(parent, "配置存储")

        card = tk.Frame(parent, bg=SURFACE_COLOR, padx=12, pady=8)
        card.pack(fill=tk.X, pady=(4, 8))

        tk.Label(
            card,
            text="配置档名称（留空将自动生成）:",
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

        tk.Button(
            card,
            text="保存源账号配置到本地",
            command=self._save_profile,
            bg=CARD_COLOR,
            fg=TEXT_COLOR,
            relief=tk.FLAT,
            cursor="hand2",
            font=(FONT_FAMILY, 9),
        ).pack(fill=tk.X, pady=(0, 6))

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
            text="刷新配置档",
            command=self._refresh_profiles,
            bg=CARD_COLOR,
            fg=TEXT_COLOR,
            relief=tk.FLAT,
            cursor="hand2",
            font=(FONT_FAMILY, 9),
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        tk.Button(
            btn_row,
            text="应用到目标账号",
            command=self._start_apply_profile,
            bg=CARD_COLOR,
            fg=TEXT_COLOR,
            relief=tk.FLAT,
            cursor="hand2",
            font=(FONT_FAMILY, 9),
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

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

    def _build_avatar_badge(
        self, parent: tk.Frame, placeholder: str
    ) -> tuple[tk.Canvas, tk.Label]:
        row = tk.Frame(parent, bg=SURFACE_COLOR)
        row.pack(fill=tk.X, pady=(0, 8))
        canvas = tk.Canvas(
            row,
            width=AVATAR_SIZE,
            height=AVATAR_SIZE,
            bg=SURFACE_COLOR,
            highlightthickness=0,
            bd=0,
        )
        canvas.pack(side=tk.LEFT)
        label = tk.Label(
            row,
            text=placeholder,
            bg=SURFACE_COLOR,
            fg=SUBTEXT_COLOR,
            font=(FONT_FAMILY, 9),
        )
        label.pack(side=tk.LEFT, padx=(8, 0))
        return canvas, label

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

        self._src_combo["values"] = labels
        self._dst_combo["values"] = labels

        if labels:
            self._src_combo.current(0)
            self._dst_combo.current(min(1, len(labels) - 1))
            self._log(f"找到 {len(accounts)} 个拥有 CS2 数据的账号。", "info")
            self._set_status(f"已加载 {len(accounts)} 个账号")
        else:
            self._log("未找到任何拥有 CS2 数据的账号。请确认 Steam 路径正确。", "warning")
            self._set_status("未找到 CS2 账号")

        self._update_account_avatars()

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

    def _on_account_change(self, _event: tk.Event | None = None) -> None:
        self._update_account_avatars()

    def _get_selected_account(self, var: tk.StringVar) -> dict | None:
        label = var.get()
        for acc in self._accounts:
            expected = f"{acc['name']}  (SteamID3: {acc['steamid3']})"
            if expected == label:
                return acc
        return None

    def _update_account_avatars(self) -> None:
        src = self._get_selected_account(self._src_var)
        dst = self._get_selected_account(self._dst_var)
        self._draw_avatar(self._src_avatar_canvas, self._src_avatar_label, src, "源账号")
        self._draw_avatar(self._dst_avatar_canvas, self._dst_avatar_label, dst, "目标账号")

    def _draw_avatar(
        self,
        canvas: tk.Canvas,
        label: tk.Label,
        account: dict | None,
        fallback_name: str,
    ) -> None:
        canvas.delete("all")
        if not account:
            color = "#4b4f68"
            short = "?"
            text = fallback_name
        else:
            name = account.get("name", fallback_name)
            short = (name[:1] or "?").upper()
            text = f"{name} (SteamID3: {account.get('steamid3', '')})"
            steamid64 = account.get("steamid64", "")
            if steamid64:
                cached = self._avatar_cache.get(steamid64)
                if cached:
                    canvas.create_image(AVATAR_SIZE // 2, AVATAR_SIZE // 2, image=cached)
                    label.config(text=text)
                    return
                self._ensure_avatar_fetch(steamid64)
            color = "#4b4f68"

        canvas.create_oval(2, 2, AVATAR_SIZE - 2, AVATAR_SIZE - 2, fill=color, outline="")
        canvas.create_text(
            AVATAR_SIZE // 2,
            AVATAR_SIZE // 2,
            text=short,
            fill="white",
            font=(FONT_FAMILY, 10, "bold"),
        )
        label.config(text=text)

    def _ensure_avatar_fetch(self, steamid64: str) -> None:
        if not steamid64 or steamid64 in self._avatar_cache or steamid64 in self._avatar_pending:
            return
        self._avatar_pending.add(steamid64)
        threading.Thread(target=self._load_avatar_worker, args=(steamid64,), daemon=True).start()

    def _load_avatar_worker(self, steamid64: str) -> None:
        avatar_url = get_steam_avatar_url(steamid64)
        if not avatar_url:
            self.after(0, self._on_avatar_failed, steamid64)
            return
        request = Request(avatar_url, headers={"User-Agent": STEAM_HTTP_USER_AGENT})
        try:
            with urlopen(request, timeout=5) as response:
                image_data = response.read()
        except (URLError, TimeoutError, OSError):
            self.after(0, self._on_avatar_failed, steamid64)
            return
        self.after(0, self._on_avatar_loaded, steamid64, image_data)

    def _on_avatar_failed(self, steamid64: str) -> None:
        self._avatar_pending.discard(steamid64)

    def _on_avatar_loaded(self, steamid64: str, image_data: bytes) -> None:
        self._avatar_pending.discard(steamid64)
        if not image_data or Image is None or ImageTk is None:
            return
        try:
            with Image.open(BytesIO(image_data)) as img:
                processed = img.copy()
                if processed.mode not in ("RGB", "RGBA"):
                    processed = processed.convert("RGBA")
                if hasattr(Image, "Resampling"):
                    resample_filter = Image.Resampling.LANCZOS
                else:
                    resample_filter = Image.LANCZOS
                resized = processed.resize((AVATAR_SIZE, AVATAR_SIZE), resample_filter)
                photo = ImageTk.PhotoImage(resized)
        except (UnidentifiedImageError, OSError, ValueError, TypeError):
            return
        self._avatar_cache[steamid64] = photo
        self._update_account_avatars()

    def _start_sync(self) -> None:
        src = self._get_selected_account(self._src_var)
        dst = self._get_selected_account(self._dst_var)

        if not src or not dst:
            messagebox.showwarning(APP_TITLE, "请先选择源账号和目标账号。")
            return

        selected_groups = [g for g, v in self._sync_vars.items() if v.get()]
        if not selected_groups:
            messagebox.showwarning(APP_TITLE, "请至少选择一种要同步的文件类型。")
            return

        confirm = messagebox.askyesno(
            APP_TITLE,
            f"将从\n  {src['name']}\n同步配置到\n  {dst['name']}\n\n"
            f"同步项目: {', '.join(selected_groups)}\n\n确认继续？",
        )
        if not confirm:
            return

        self._sync_btn.config(state=tk.DISABLED, text="同步中…")
        self._set_status("正在同步…")
        self._log("═" * 50)
        self._log(f"开始同步: {src['name']} → {dst['name']}", "info")

        threading.Thread(
            target=self._sync_worker,
            args=(src, dst, selected_groups),
            daemon=True,
        ).start()

    def _save_profile(self) -> None:
        src = self._get_selected_account(self._src_var)
        if not src:
            messagebox.showwarning(APP_TITLE, "请先选择源账号。")
            return

        selected_groups = [g for g, v in self._sync_vars.items() if v.get()]
        if not selected_groups:
            messagebox.showwarning(APP_TITLE, "请至少选择一种要保存的文件类型。")
            return

        profile_name = self._profile_name_var.get().strip() or f"{src['name']}_{src['steamid3']}"
        self._log("═" * 50)
        self._log(f"开始保存配置档: {profile_name}", "info")

        results = save_profile_configs(
            source_account=src,
            file_groups=selected_groups,
            group_definitions=CONFIG_FILE_GROUPS,
            storage_root=self._profile_storage_root,
            profile_name=profile_name,
            log_callback=self._log_sync_line,
        )

        n_ok = len(results["copied"])
        n_skip = len(results["skipped"])
        n_fail = len(results["failed"])
        summary = f"配置档保存完成：成功 {n_ok} 项，跳过 {n_skip} 项，失败 {n_fail} 项"
        self._log(summary, "success" if n_fail == 0 else "warning")
        self._log("═" * 50)
        self._set_status(summary)
        self._refresh_profiles()

        if n_fail:
            messagebox.showwarning(APP_TITLE, f"{summary}\n请检查操作日志获取详情。")
        else:
            messagebox.showinfo(APP_TITLE, summary)

    def _start_apply_profile(self) -> None:
        dst = self._get_selected_account(self._dst_var)
        if not dst:
            messagebox.showwarning(APP_TITLE, "请先选择目标账号。")
            return

        label = self._profile_var.get()
        profile_name = self._profile_label_to_name.get(label)
        if not profile_name:
            messagebox.showwarning(APP_TITLE, "请先选择一个已保存配置档。")
            return

        selected_groups = [g for g, v in self._sync_vars.items() if v.get()]
        if not selected_groups:
            messagebox.showwarning(APP_TITLE, "请至少选择一种要应用的文件类型。")
            return

        confirm = messagebox.askyesno(
            APP_TITLE,
            f"将把配置档\n  {label}\n应用到目标账号\n  {dst['name']}\n\n"
            f"同步项目: {', '.join(selected_groups)}\n\n确认继续？",
        )
        if not confirm:
            return

        self._sync_btn.config(state=tk.DISABLED, text="应用中…")
        self._set_status("正在应用配置档…")
        self._log("═" * 50)
        self._log(f"开始应用配置档: {label} → {dst['name']}", "info")

        threading.Thread(
            target=self._apply_profile_worker,
            args=(profile_name, dst, selected_groups),
            daemon=True,
        ).start()

    def _apply_profile_worker(
        self, profile_name: str, dst: dict, selected_groups: list[str]
    ) -> None:
        log_callback = lambda msg: self.after(0, self._log_sync_line, msg)
        if self._dated_backup_var.get():
            backup_results = backup_account_configs(
                account=dst,
                file_groups=selected_groups,
                group_definitions=CONFIG_FILE_GROUPS,
                backup_root=self._account_backup_root,
                log_callback=log_callback,
            )
            if backup_results["failed"]:
                self.after(0, self._on_sync_done, backup_results)
                return

        results = apply_saved_profile_configs(
            profile_name=profile_name,
            dest_account=dst,
            file_groups=selected_groups,
            group_definitions=CONFIG_FILE_GROUPS,
            storage_root=self._profile_storage_root,
            backup=self._backup_var.get(),
            log_callback=log_callback,
        )
        self.after(0, self._on_sync_done, results)

    def _sync_worker(
        self, src: dict, dst: dict, selected_groups: list[str]
    ) -> None:
        log_callback = lambda msg: self.after(0, self._log_sync_line, msg)
        if self._dated_backup_var.get():
            backup_results = backup_account_configs(
                account=dst,
                file_groups=selected_groups,
                group_definitions=CONFIG_FILE_GROUPS,
                backup_root=self._account_backup_root,
                log_callback=log_callback,
            )
            if backup_results["failed"]:
                self.after(0, self._on_sync_done, backup_results)
                return

        results = sync_configs(
            source_account=src,
            dest_account=dst,
            file_groups=selected_groups,
            group_definitions=CONFIG_FILE_GROUPS,
            backup=self._backup_var.get(),
            log_callback=log_callback,
        )
        self.after(0, self._on_sync_done, results)

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

    def _on_sync_done(self, results: dict) -> None:
        n_ok = len(results["copied"])
        n_skip = len(results["skipped"])
        n_fail = len(results["failed"])

        summary = f"同步完成：成功 {n_ok} 项，跳过 {n_skip} 项，失败 {n_fail} 项"
        self._log(summary, "success" if n_fail == 0 else "warning")
        self._log("═" * 50)
        self._set_status(summary)
        self._sync_btn.config(state=tk.NORMAL, text="▶  开始同步")

        if n_fail:
            messagebox.showwarning(APP_TITLE, f"同步完成，但有 {n_fail} 项失败。\n请检查操作日志获取详情。")
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
