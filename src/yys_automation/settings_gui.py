"""Editors for the settings used by the workbench and CLI."""
from __future__ import annotations

import os
import tempfile
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk

import yaml

from src.yys_automation.config import AppConfig, Region, parse_config
from src.yys_automation.scenario import Scenario


def save_global_settings(path: Path, original: bytes, updates: dict) -> AppConfig:
    previous = yaml.safe_load(original)
    if not isinstance(previous, dict):
        raise ValueError("全局配置必须是 YAML 对象。")
    raw = dict(previous)
    for key, value in updates.items():
        if isinstance(value, dict):
            raw[key] = {**raw.get(key, {}), **value}
        else:
            raw[key] = value
    config = parse_config(raw, path)
    if raw == previous:
        if path.read_bytes() != original:
            raise ValueError("配置文件已在外部修改。请关闭并重新打开设置。")
        return config

    # Keep the temporary file on the same volume for atomic replacement.
    fd, filename = tempfile.mkstemp(prefix=".yys-config-", suffix=".tmp", dir=path.parent)
    draft = Path(filename)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            yaml.safe_dump(raw, output, allow_unicode=True, sort_keys=False)
        if path.read_bytes() != original:
            raise ValueError("配置文件已在外部修改。请关闭并重新打开设置。")
        os.replace(draft, path)
    finally:
        draft.unlink(missing_ok=True)
    return config


def number(field: tk.StringVar, label: str, convert: type[int] | type[float]) -> int | float:
    try:
        return convert(field.get().strip())
    except ValueError:
        kind = "整数" if convert is int else "数字"
        raise ValueError(f"{label}须填写{kind}。") from None


class SettingsDialog:
    def __init__(self, parent: tk.Misc, title: str, button: str, on_submit: Callable):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title(title)
        self.dialog.transient(parent)
        self.dialog.resizable(True, False)
        self.dialog.minsize(540, 0)
        self.previous_grab = parent.grab_current()
        self.dialog.grab_set()
        self.dialog.protocol("WM_DELETE_WINDOW", self.close)
        self.dialog.bind("<Escape>", lambda _event: self.close())
        self.body = ttk.Frame(self.dialog, padding=18)
        self.body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(self.body, text=title, style="Title.TLabel").pack(anchor="w", pady=(0, 12))
        self.form = ttk.Frame(self.body)
        self.form.pack(fill=tk.X)
        self.form.columnconfigure(1, weight=1)
        self.error = tk.StringVar(master=self.dialog)
        self.on_submit = on_submit
        self.button_label = button

    def field(self, label: str, value: object, choices: tuple[str, ...] = ()) -> tk.StringVar:
        row = self.form.grid_size()[1]
        var = tk.StringVar(master=self.dialog, value="" if value is None else str(value))
        ttk.Label(self.form, text=label).grid(row=row, column=0, sticky="w", padx=(0, 14), pady=3)
        if choices:
            widget = ttk.Combobox(self.form, textvariable=var, values=choices, state="readonly")
        else:
            widget = ttk.Entry(self.form, textvariable=var)
        widget.grid(row=row, column=1, sticky="ew", pady=3)
        return var

    def finish(self, hint: str) -> None:
        ttk.Label(self.body, text=hint, style="Muted.TLabel", wraplength=505).pack(anchor="w", pady=(10, 0))
        ttk.Label(self.body, textvariable=self.error, foreground="#ad3541", wraplength=505).pack(anchor="w")
        buttons = ttk.Frame(self.body)
        buttons.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(buttons, text="取消", command=self.close).pack(side=tk.RIGHT)
        self.submit_button = ttk.Button(buttons, text=self.button_label, style="Accent.TButton", command=self.submit)
        self.submit_button.pack(side=tk.RIGHT, padx=8)
        self.dialog.bind("<Control-Return>", lambda _event: self.submit())

    def submit(self) -> None:
        try:
            after_close = self.on_submit()
        except (OSError, ValueError, yaml.YAMLError) as exc:
            self.error.set(str(exc))
            return
        self.close()
        after_close()

    def close(self) -> None:
        self.dialog.destroy()
        if self.previous_grab is not None:
            self.previous_grab.grab_set()


def open_global_settings(parent: tk.Misc, path: Path, on_saved: Callable[[AppConfig], None],
                         proposed_region: Region | None = None,
                         reference_size: tuple[int, int] | None = None) -> None:
    path = path.resolve()
    original = path.read_bytes()
    config = parse_config(yaml.safe_load(original), path)
    if reference_size is not None and (config.capture_mode != "window" or
            (config.window.reference_width, config.window.reference_height) != reference_size):
        raise ValueError("参考尺寸或捕获模式已改变，请重新打开运行前检查并截图。")

    def submit():
        region_values = {key: number(var, label, int) for key, label, var in region_fields}
        saved = save_global_settings(path, original, {
            "window": {
                "title_contains": title.get().strip(),
                "reference_width": number(width, "参考宽度", int),
                "reference_height": number(height, "参考高度", int),
            },
            "allowed_region": region_values,
            "max_clicks": number(clicks, "默认点击上限", int) if clicks.get().strip() else None,
            "min_click_interval_seconds": number(cooldown, "默认点击间隔", float),
            "scan_interval_seconds": number(scan, "默认识别间隔", float),
            "threshold": number(threshold, "默认匹配阈值", float),
            "dry_run": dry_run.get() == "开启",
        })
        return lambda: on_saved(saved)

    dialog = SettingsDialog(parent, "全局设置", "保存全局设置", submit)
    title = dialog.field("窗口标题包含", config.window.title_contains)
    width = dialog.field("参考宽度", config.window.reference_width)
    height = dialog.field("参考高度", config.window.reference_height)
    region = proposed_region if proposed_region is not None else config.allowed_region
    region_fields = [
        (key, label, dialog.field(label, getattr(region, key)))
        for key, label in (("left", "白名单左边 / X"), ("top", "白名单上边 / Y"),
                           ("width", "白名单宽度"), ("height", "白名单高度"))
    ]
    clicks = dialog.field("默认点击上限", config.max_clicks)
    cooldown = dialog.field("默认点击间隔 / 秒", config.min_click_interval_seconds)
    scan = dialog.field("默认识别间隔 / 秒", config.scan_interval_seconds)
    threshold = dialog.field("默认匹配阈值", config.threshold)
    dry_run = dialog.field("全局试运行", "开启" if config.dry_run else "关闭", ("开启", "关闭"))
    coordinates = "窗口参考坐标" if config.capture_mode == "window" else "屏幕绝对坐标"
    dialog.finish(f"白名单使用{coordinates}。默认点击上限留空表示不限，0 表示禁止点击。"
                  "场景参数和步骤识别间隔可覆盖相应的全局默认值。")


def open_scenario_settings(parent: tk.Misc, scenario: Scenario, on_apply: Callable[[dict], None]) -> None:
    match_any = scenario.execution_mode == "match_any"
    backends = {"窗口消息": "window_message", "物理鼠标": "physical_mouse"}

    def submit():
        value = clicks.get().strip()
        if value and value != "auto":
            try:
                value = int(value)
            except ValueError:
                raise ValueError("场景点击上限必须是非负整数或留空。顺序场景还支持 auto。") from None
        changes = {"max_clicks": value if value != "" else None, "stable_frames": frames.get().strip()}
        if match_any:
            changes.update(input_backend=backends[backend.get()],
                           no_target_timeout_seconds=timeout.get().strip() or None,
                           consecutive_miss_limit=misses.get().strip() or None,
                           match_any_click_interval_seconds=interval.get().strip() or None)
        on_apply(changes)
        return lambda: None

    dialog = SettingsDialog(parent, "场景设置", "应用到当前场景", submit)
    clicks = dialog.field("场景点击上限", scenario.max_clicks)
    frames = dialog.field("连续确认帧数（1–10）", scenario.stable_frames)
    if match_any:
        backend_label = next(label for label, value in backends.items() if value == scenario.input_backend)
        backend = dialog.field("点击方式", backend_label, tuple(backends))
        timeout = dialog.field("无目标超时 / 秒", scenario.no_target_timeout_seconds)
        misses = dialog.field("连续未命中次数上限", scenario.consecutive_miss_limit)
        interval = dialog.field("场景点击间隔 / 秒", scenario.match_any_click_interval_seconds)
        hint = "点击上限和点击间隔留空时使用全局值。无目标超时与未命中次数上限最多设置一项。"
    else:
        hint = "顺序场景使用窗口消息。点击上限留空时使用全局值，也可填写 auto 按步骤和轮数计算。"
    dialog.finish(hint + "各图片的阈值在步骤设置中调整，留空时使用全局默认阈值。")
