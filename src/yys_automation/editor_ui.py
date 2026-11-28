"""Presentation for the scenario editor; no desktop automation runs here."""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from src.yys_automation.recognition_pane import RecognitionPane


TYPE_LABELS = {
    "match_and_click": "识图并点击",
    "wait_for_image": "等待图片",
    "click_point": "坐标点击",
    "wait": "定时等待",
}


class DisclosureButton(ttk.Button):
    def __init__(self, parent: tk.Misc, title: str, panel: ttk.Frame, *, on_expand: Callable[[], None] | None = None) -> None:
        super().__init__(parent, text=f"▸ {title}", style="Disclosure.TButton", command=self._toggle)
        self.title = title
        self.panel = panel
        self.on_expand = on_expand
        self.panel.grid_remove()

    def _toggle(self) -> None:
        if self.panel.winfo_manager():
            self.panel.grid_remove()
            self.configure(text=f"▸ {self.title}")
        else:
            self.panel.grid()
            self.configure(text=f"▾ {self.title}")
            if self.on_expand is not None:
                self.on_expand()


class EditorSidebar(ttk.Frame):
    def __init__(self, body: ttk.PanedWindow, left: ttk.Frame, tools: ttk.Frame) -> None:
        super().__init__(body)
        self.body = body
        self.left = left
        self._sash_fraction: float | None = None
        self.toggle_button = ttk.Button(tools, text="▾ 收起右栏", style="Disclosure.TButton", command=self._toggle)
        self.body.add(self, weight=2)

    def expand(self) -> None:
        if self.winfo_manager():
            return
        self.left.configure(padding=(0, 0, 10, 0))
        self.body.add(self, weight=2)
        self.toggle_button.configure(text="▾ 收起右栏")
        if self._sash_fraction is not None:
            self.body.update_idletasks()
            self.body.sashpos(0, round(self.body.winfo_width() * self._sash_fraction))

    def _toggle(self) -> None:
        if not self.winfo_manager():
            self.expand()
            return
        if self.body.winfo_ismapped():
            self._sash_fraction = self.body.sashpos(0) / self.body.winfo_width()
        self.body.forget(self)
        self.left.configure(padding=0)
        self.toggle_button.configure(text="▸ 展开右栏")
        self.toggle_button.focus_set()


def build_editor(editor) -> None:
    root = editor.root
    root.configure(background="#f3f5f9")
    root.geometry("1120x720")
    root.minsize(960, 600)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=("Microsoft YaHei UI", 10), background="#f3f5f9", foreground="#24324b")
    style.configure("TFrame", background="#f3f5f9")
    style.configure("Card.TFrame", background="white")
    style.configure("Card.TLabel", background="white")
    style.configure("Muted.TLabel", foreground="#62718a")
    style.configure("Title.TLabel", font=("Microsoft YaHei UI", 17, "bold"))
    style.configure("LaunchValue.TLabel", background="white", font=("Microsoft YaHei UI", 10, "bold"))
    style.configure("RunMode.TLabel", foreground="#305dd6", font=("Microsoft YaHei UI", 10, "bold"))
    style.configure("LiveMode.TLabel", foreground="#8e460e", font=("Microsoft YaHei UI", 10, "bold"))
    style.configure("TButton", padding=(12, 6), width=0, background="#e8edf5", borderwidth=0)
    style.map("TButton", background=[("active", "#dce5f2"), ("disabled", "#edf0f5")], foreground=[("disabled", "#929aaa")])
    style.configure("Disclosure.TButton", anchor=tk.W)
    style.configure("Accent.TButton", background="#305dd6", foreground="white")
    style.map("Accent.TButton", background=[("disabled", "#b7c4e2"), ("active", "#234caf")], foreground=[("disabled", "white")])
    style.configure("Stop.TButton", foreground="#ad3541")
    for field in ("TEntry", "TCombobox", "TMenubutton"):
        style.configure(field, bordercolor="#ccd6e5", lightcolor="white", darkcolor="white")
        style.map(field, bordercolor=[("focus", "#305dd6")])
    style.configure("TEntry", padding=4, fieldbackground="white")
    style.map("TEntry", fieldbackground=[("disabled", "#edf0f5")])
    style.configure("TCombobox", padding=5, background="#eef2f8")
    style.map("TCombobox", fieldbackground=[("readonly", "white"), ("disabled", "#edf0f5")])
    style.configure("TMenubutton", background="#e8edf5", borderwidth=0)
    style.map("TMenubutton", background=[("active", "#dce5f2"), ("disabled", "#edf0f5")])
    style.configure("Treeview", rowheight=30, background="white", fieldbackground="white", borderwidth=0)
    style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"), padding=(8, 7),
                    background="#e9eef7", bordercolor="#dce4ef", lightcolor="#e9eef7", darkcolor="#e9eef7")
    style.map("Treeview", background=[("selected", "#dce7ff")], foreground=[("selected", "#183a83")])
    style.configure("TNotebook", bordercolor="#dce4ef", lightcolor="#dce4ef", darkcolor="#dce4ef")
    style.configure("TNotebook.Tab", padding=(14, 7))
    style.map("TNotebook.Tab", background=[("selected", "white")], foreground=[("selected", "#305dd6")])
    for scrollbar_style in ("Horizontal.TScrollbar", "Vertical.TScrollbar"):
        style.configure(scrollbar_style, background="#e0e6f0", troughcolor="#f3f5f9", bordercolor="#dce4ef",
                        lightcolor="#e0e6f0", darkcolor="#e0e6f0", arrowcolor="#536785", arrowsize=12)

    shell = ttk.Frame(root, padding=(18, 12))
    shell.pack(fill=tk.BOTH, expand=True)
    shell.columnconfigure(0, weight=1)
    shell.rowconfigure(5, weight=1)
    heading = ttk.Frame(shell)
    heading.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    ttk.Label(heading, text="场景工作台", style="Title.TLabel").pack(side=tk.LEFT)
    editor.saved_var = tk.StringVar(value="已加载")
    ttk.Label(heading, textvariable=editor.saved_var, style="Muted.TLabel").pack(side=tk.LEFT, padx=12)

    file_tools = ttk.Frame(heading)
    file_tools.pack(side=tk.RIGHT)
    editor.open_button = ttk.Button(file_tools, text="打开场景…", command=editor._choose_file)
    editor.open_button.pack(side=tk.LEFT, padx=(0, 5))
    editor.recent_button = ttk.Menubutton(file_tools, text="最近场景", padding=(10, 6))
    editor.recent_menu = tk.Menu(editor.recent_button, tearoff=False, postcommand=editor._refresh_recent_menu)
    editor.recent_button.configure(menu=editor.recent_menu)
    editor.recent_button.pack(side=tk.LEFT, padx=(0, 5))
    editor.save_button = ttk.Button(file_tools, text="保存", command=editor._save)
    editor.save_button.pack(side=tk.LEFT, padx=(0, 5))

    editor.files_panel = ttk.Frame(shell, padding=8, style="Card.TFrame")
    editor.files_panel.grid(row=1, column=0, sticky="ew", pady=(0, 8))
    editor.files_toggle = DisclosureButton(file_tools, "文件与设置", editor.files_panel)
    editor.files_toggle.pack(side=tk.LEFT)
    ttk.Label(editor.files_panel, text="场景路径", style="Card.TLabel").pack(side=tk.LEFT, padx=(0, 8))
    editor.path_var = tk.StringVar(value=str(editor.scenario_path or "scenario.yaml"))
    editor.path_entry = ttk.Entry(editor.files_panel, textvariable=editor.path_var, width=14)
    editor.path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
    editor.load_button = ttk.Button(editor.files_panel, text="加载路径", command=editor._load_from_entry)
    editor.load_button.pack(side=tk.LEFT, padx=(0, 6))
    editor.save_as_button = ttk.Button(editor.files_panel, text="另存为…", command=editor._save_as)
    editor.save_as_button.pack(side=tk.LEFT, padx=(0, 6))
    editor.global_settings_button = ttk.Button(editor.files_panel, text="全局设置", command=editor._open_global_settings)
    editor.global_settings_button.pack(side=tk.LEFT, padx=(0, 6))
    editor.validate_button = ttk.Button(editor.files_panel, text="校验配置", command=editor._validate)
    editor.validate_button.pack(side=tk.LEFT)

    notices = ttk.Frame(shell)
    notices.grid(row=2, column=0, sticky="ew")
    editor.file_notice = ttk.Frame(notices, padding=(0, 0, 0, 7))
    editor.relocate_button = ttk.Button(editor.file_notice, text="重新定位…", command=editor._relocate_scene)
    editor.relocate_button.pack(side=tk.RIGHT)
    editor.file_notice_var = tk.StringVar()
    notice = ttk.Label(editor.file_notice, textvariable=editor.file_notice_var, foreground="#ad3541", wraplength=770)
    notice.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
    notice.bind("<Configure>", lambda event: notice.configure(wraplength=max(140, event.width)))

    launch = ttk.Frame(shell, style="Card.TFrame")
    launch.grid(row=3, column=0, sticky="ew", pady=(0, 8))
    editor.scene_var = tk.StringVar(value="未加载场景")
    editor.window_var = tk.StringVar(value="按全局配置定位")
    editor.budget_var = tk.StringVar(value="—")
    editor.budget_source_var = tk.StringVar(value="加载场景后显示")
    for column, (title, value, subtext, weight) in enumerate([
        ("当前场景", editor.scene_var, None, 3),
        ("目标窗口", editor.window_var, None, 4),
        ("场景点击上限", editor.budget_var, editor.budget_source_var, 3),
    ]):
        launch.columnconfigure(column, weight=weight, uniform="launch")
        card = ttk.Frame(launch, style="Card.TFrame", padding=(12, 8))
        card.grid(row=0, column=column, sticky="nsew")
        ttk.Label(card, text=title, style="Card.TLabel", foreground="#62718a").pack(side=tk.LEFT, anchor=tk.N, padx=(0, 8))
        values = ttk.Frame(card, style="Card.TFrame")
        values.pack(side=tk.LEFT, anchor=tk.N, fill=tk.X, expand=True)
        value_label = ttk.Label(values, textvariable=value, style="LaunchValue.TLabel", anchor=tk.W, width=1)
        value_label.pack(fill=tk.X)
        value_label.bind("<Configure>", lambda event: event.widget.configure(wraplength=event.width))
        if subtext is not None:
            source_label = ttk.Label(values, textvariable=subtext, style="Card.TLabel", foreground="#62718a", width=1)
            source_label.pack(fill=tk.X)
            source_label.bind("<Configure>", lambda event: event.widget.configure(wraplength=event.width))

    actions = ttk.Frame(shell)
    actions.grid(row=4, column=0, sticky="ew", pady=(0, 8))
    editor.run_button = ttk.Button(actions, text="运行场景", style="Accent.TButton", command=editor._run_scenario)
    editor.run_button.pack(side=tk.LEFT, padx=(0, 5))
    editor.stop_button = ttk.Button(actions, text="停止任务", style="Stop.TButton", command=editor._stop_process, state="disabled")
    editor.stop_button.pack(side=tk.LEFT, padx=(0, 12))
    editor.test_button = ttk.Button(actions, text="测试单步", command=editor._test_current_step)
    editor.test_button.pack(side=tk.LEFT, padx=(0, 5))
    editor.preflight_button = ttk.Button(actions, text="识别检查", command=editor._show_recognition)
    editor.preflight_button.pack(side=tk.LEFT, padx=(0, 12))
    editor.dry_run_var = tk.BooleanVar(value=editor.dry_run)
    editor.dry_check = ttk.Checkbutton(actions, text="试运行", variable=editor.dry_run_var)
    editor.dry_check.pack(side=tk.LEFT)
    if editor.dry_run:
        editor.dry_check.state(["disabled"])
    editor.mode_var = tk.StringVar()
    editor.mode_label = ttk.Label(actions, textvariable=editor.mode_var, style="RunMode.TLabel")
    editor.mode_label.pack(side=tk.LEFT, padx=(6, 0))

    editor.status_var = tk.StringVar(value="就绪")
    editor.current_step_var = tk.StringVar(value="—")
    editor.clicks_var = tk.StringVar(value="0 / —")
    editor.cycles_var = tk.StringVar(value="0")
    editor.runtime_var = tk.StringVar(value="00:00")

    body = ttk.PanedWindow(shell, orient=tk.HORIZONTAL)
    body.grid(row=5, column=0, sticky="nsew")
    left = ttk.Frame(body, padding=(0, 0, 10, 0))
    body.add(left, weight=3)
    left.columnconfigure(0, weight=1)
    left.rowconfigure(1, weight=1)
    editor.summary_var = tk.StringVar(value="步骤列表")
    list_header = ttk.Frame(left)
    list_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    ttk.Label(list_header, textvariable=editor.summary_var, font=("Microsoft YaHei UI", 11, "bold")).pack(side=tk.LEFT)
    editor.scenario_settings_button = ttk.Button(list_header, text="场景设置", command=editor._open_scenario_settings)
    editor.scenario_settings_button.pack(side=tk.RIGHT)
    table = ttk.Frame(left)
    table.grid(row=1, column=0, sticky="nsew")
    table.rowconfigure(0, weight=1)
    table.columnconfigure(0, weight=1)
    editor.tree = ttk.Treeview(table, columns=("id", "type", "image", "timeout", "threshold", "x", "y", "wait"),
                              displaycolumns=("id", "type", "image", "threshold", "timeout"), show="headings", selectmode="browse")
    for key, text, width in [("id", "步骤 ID", 110), ("type", "动作", 105), ("image", "模板图片", 150),
                             ("threshold", "阈值", 60), ("timeout", "等待 / 秒", 80)]:
        editor.tree.heading(key, text=text)
        editor.tree.column(key, width=width, minwidth=60, stretch=key in {"id", "image"})
    editor.tree.tag_configure("even", background="#f7f9fd")
    editor.tree.grid(row=0, column=0, sticky="nsew")
    vertical = ttk.Scrollbar(table, orient=tk.VERTICAL, command=editor.tree.yview)
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal = ttk.Scrollbar(table, orient=tk.HORIZONTAL, command=editor.tree.xview)
    horizontal.grid(row=1, column=0, sticky="ew")

    def sync_horizontal_scrollbar(first, last):
        horizontal.set(first, last)
        if float(first) == 0 and float(last) == 1:
            horizontal.grid_remove()
        else:
            horizontal.grid()

    editor.tree.configure(yscrollcommand=vertical.set, xscrollcommand=sync_horizontal_scrollbar)
    editor.tree.bind("<<TreeviewSelect>>", editor._select_step)
    buttons = ttk.Frame(left, padding=(0, 10, 0, 0))
    buttons.grid(row=2, column=0, sticky="ew")
    editor.edit_buttons = []
    for text, command in [("新增步骤", editor._new_step), ("删除", editor._delete_step),
                          ("上移 ↑", lambda: editor._move_step(-1)), ("下移 ↓", lambda: editor._move_step(1))]:
        button = ttk.Button(buttons, text=text, command=command)
        button.pack(side=tk.LEFT, padx=(0, 6))
        editor.edit_buttons.append(button)

    right = editor.sidebar = EditorSidebar(body, left, actions)
    right.toggle_button.pack(side=tk.RIGHT)
    ttk.Label(actions, text="Ctrl+Shift+Q 停止", style="Muted.TLabel").pack(side=tk.RIGHT, padx=(0, 10))
    editor.tabs = ttk.Notebook(right)
    editor.tabs.pack(fill=tk.BOTH, expand=True)
    _build_step_form(editor)
    preview = ttk.Frame(editor.tabs, padding=14)
    editor.tabs.add(preview, text="图片预览")
    editor.recognition = RecognitionPane(editor.tabs, editor._recognition_context,
                                         editor._apply_recognition_threshold, editor._open_preflight)
    editor.tabs.add(editor.recognition, text="识别检查")
    editor.recognition.bind("<Map>", lambda _event: editor.recognition.refresh_visible_selection())
    editor.preview_label = ttk.Label(preview, text="选择一个含图片的步骤以预览", anchor=tk.CENTER, style="Card.TLabel")
    editor.preview_label.pack(fill=tk.BOTH, expand=True)
    editor.preview_info = tk.StringVar(value="")
    ttk.Label(preview, textvariable=editor.preview_info, wraplength=350, style="Muted.TLabel").pack(fill=tk.X, pady=10)
    editor.apply_button = ttk.Button(right, text="应用步骤修改", command=editor._update_step)
    editor.apply_button.pack(fill=tk.X, pady=(10, 0))

    footer = ttk.Frame(shell, padding=(0, 12, 0, 0))
    footer.grid(row=6, column=0, sticky="ew")
    editor.detail_var = tk.StringVar(value="选择步骤开始编辑。保存或运行时自动应用修改。")
    feedback = ttk.Frame(footer)
    feedback.pack(fill=tk.X)
    editor.log_button = ttk.Button(feedback, text="展开日志", command=editor._toggle_log)
    editor.log_button.pack(side=tk.RIGHT)
    editor.diagnostic_button = ttk.Button(feedback, text="查看现场…", command=editor._open_diagnostic, state="disabled")
    editor.diagnostic_button.pack(side=tk.RIGHT, padx=(8, 5))
    editor.run_summary_var = tk.StringVar(value="就绪")
    summary = ttk.Label(feedback, textvariable=editor.run_summary_var, wraplength=760)
    summary.pack(side=tk.LEFT, fill=tk.X, expand=True)
    summary.bind("<Configure>", lambda event: summary.configure(wraplength=max(120, event.width)))
    detail = ttk.Label(footer, textvariable=editor.detail_var, style="Muted.TLabel", wraplength=960)
    detail.pack(fill=tk.X, pady=(3, 0))
    detail.bind("<Configure>", lambda event: detail.configure(wraplength=max(120, event.width)))
    editor.log_frame = ttk.Frame(footer)
    editor.log_text = tk.Text(editor.log_frame, height=5, wrap="word", font=("Consolas", 9), background="#172238",
                              foreground="#d6e0f0", relief="flat", padx=12, pady=8, state="disabled")
    editor.log_text.pack(side=tk.LEFT, fill=tk.X, expand=True)
    scrollbar = ttk.Scrollbar(editor.log_frame, command=editor.log_text.yview)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    editor.log_text.configure(yscrollcommand=scrollbar.set)
    root.bind("<Control-s>", lambda event: editor._save())


def _build_step_form(editor) -> None:
    tab = ttk.Frame(editor.tabs, style="Card.TFrame")
    editor.tabs.add(tab, text="步骤设置")
    canvas = tk.Canvas(tab, background="white", highlightthickness=0, height=1, width=390)
    scrollbar = ttk.Scrollbar(tab, orient=tk.VERTICAL, command=canvas.yview)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    canvas.configure(yscrollcommand=scrollbar.set)
    content = ttk.Frame(canvas, style="Card.TFrame", padding=12)
    window = canvas.create_window((0, 0), window=content, anchor="nw")
    content.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
    content.columnconfigure(0, weight=1)

    basic = ttk.Frame(content, style="Card.TFrame")
    basic.grid(row=0, column=0, sticky="ew")
    basic.columnconfigure(0, weight=1)
    editor.form_hint_var = tk.StringVar()
    hint = ttk.Label(content, textvariable=editor.form_hint_var, style="Card.TLabel", foreground="#62718a", width=1)
    hint.grid(row=1, column=0, sticky="ew", pady=(8, 10))
    hint.bind("<Configure>", lambda event: event.widget.configure(wraplength=event.width))

    editor.advanced_panel = ttk.Frame(content, style="Card.TFrame", padding=(0, 6, 0, 0))
    editor.advanced_panel.grid(row=3, column=0, sticky="ew")
    editor.advanced_panel.columnconfigure(0, weight=1)

    def reveal_advanced() -> None:
        if not content.winfo_ismapped():
            return
        content.update_idletasks()
        bottom = editor.advanced_panel.winfo_rooty() + editor.advanced_panel.winfo_height()
        if bottom > canvas.winfo_rooty() + canvas.winfo_height():
            top = editor.advanced_toggle.winfo_rooty() - content.winfo_rooty()
            canvas.yview_moveto(top / content.winfo_height())

    editor.advanced_toggle = DisclosureButton(content, "确认与恢复", editor.advanced_panel, on_expand=reveal_advanced)
    editor.advanced_toggle.grid(row=2, column=0, sticky="ew")

    editor.form = {}
    editor.form_widgets = {}
    editor.form_rows = {}
    for parent, fields in (
        (basic, [
            ("id", "步骤 ID"), ("type", "动作类型"), ("image", "模板图片"),
            ("threshold", "匹配阈值"), ("x", "参考坐标 X"), ("y", "参考坐标 Y"),
            ("timeout", "最长等待 / 秒"), ("wait", "执行后等待 / 秒"), ("scan_interval", "识别间隔 / 秒"),
        ]),
        (editor.advanced_panel, [
            ("attempts", "最大尝试次数"), ("next", "预期下一步骤"),
            ("response", "响应等待 / 秒"), ("recover", "恢复候选 ID"), ("requires_action", "前置动作 ID"),
        ]),
    ):
        for index, (key, label) in enumerate(fields):
            row = ttk.Frame(parent, style="Card.TFrame")
            row.grid(row=index, column=0, sticky="ew", pady=3)
            editor.form_rows[key] = row
            ttk.Label(row, text=label, width=16, style="Card.TLabel").pack(side=tk.LEFT)
            var = tk.StringVar()
            editor.form[key] = var
            if key == "type":
                widget = ttk.Combobox(row, textvariable=var, values=list(TYPE_LABELS.values()), state="readonly", width=12)
            else:
                widget = ttk.Entry(row, textvariable=var, width=12)
            widget.pack(side=tk.LEFT, fill=tk.X, expand=True)
            editor.form_widgets[key] = widget
            if key == "image":
                editor.image_button = ttk.Button(row, text="浏览…", command=editor._choose_image)
                editor.image_button.pack(side=tk.LEFT, padx=(5, 0))

    recovery_hint = ttk.Label(editor.advanced_panel, text="用于顺序场景。多个恢复候选 ID 用英文逗号分隔。", style="Card.TLabel",
                              foreground="#62718a")
    recovery_hint.grid(row=5, column=0, sticky="w", pady=(5, 0))

    def wheel(event):
        canvas.yview_scroll(-int(event.delta / 120), "units")
        return "break"

    def scroll_to_focus(event):
        widget = event.widget
        top = widget.winfo_rooty() - canvas.winfo_rooty()
        bottom = top + widget.winfo_height()
        offset = min(0, top) or max(0, bottom - canvas.winfo_height())
        if offset:
            canvas.yview_moveto((canvas.canvasy(0) + offset) / content.winfo_height())

    def bind_wheel(widget):
        widget.bind("<MouseWheel>", wheel)
        for child in widget.winfo_children():
            bind_wheel(child)

    bind_wheel(canvas)
    for widget in (*editor.form_widgets.values(), editor.image_button, editor.advanced_toggle):
        widget.bind("<FocusIn>", scroll_to_focus)
