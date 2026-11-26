"""Window selection and single-frame diagnostics, without sending input."""
from __future__ import annotations

import base64
import math
import queue
import threading
import tkinter as tk
from tkinter import ttk

import cv2
import yaml

from src.yys_automation.config import Region
from src.yys_automation.preflight import capture_preview, with_window_identity
from src.yys_automation.window import WindowLocator


def selection_region(start: tuple[int, int], end: tuple[int, int], displayed: Region,
                     reference_width: int, reference_height: int) -> Region | None:
    """Translate a drag on the displayed image to a half-open reference rectangle."""
    if not displayed.contains_point(*start):
        return None
    x = min(max(end[0], displayed.left), displayed.right)
    y = min(max(end[1], displayed.top), displayed.bottom)
    if abs(x - start[0]) < 3 or abs(y - start[1]) < 3:
        return None
    left, right = sorted((start[0] - displayed.left, x - displayed.left))
    top, bottom = sorted((start[1] - displayed.top, y - displayed.top))
    x0 = left * reference_width // displayed.width
    y0 = top * reference_height // displayed.height
    x1 = math.ceil(right * reference_width / displayed.width)
    y1 = math.ceil(bottom * reference_height / displayed.height)
    return Region(x0, y0, x1 - x0, y1 - y0)


class PreflightDialog:
    def __init__(self, parent, config, scenario, selected_step_id, on_apply, identity=None, *,
                 config_path=None, on_config_saved=None):
        self.config = config
        self.scenario = scenario
        self.selected_step_id = selected_step_id
        self.on_apply = on_apply
        self.config_path = config_path
        self.on_config_saved = on_config_saved
        self.result = None
        self.photo = None
        self.windows = []
        self.unavailable_identity = identity
        self.busy = False
        self.closed = False
        self.poll_id = None
        self.inbox = queue.Queue()
        self.image_bounds = None
        self.drag_start = None
        self.region = None
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("运行前检查 · 不发送点击")
        self.dialog.geometry("1120x800")
        self.dialog.minsize(960, 680)
        self.dialog.transient(parent)
        self.dialog.grab_set()
        self.dialog.protocol("WM_DELETE_WINDOW", self.close)
        shell = ttk.Frame(self.dialog, padding=18)
        shell.pack(fill=tk.BOTH, expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(3, weight=1)
        ttk.Label(shell, text="运行前检查", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        controls = ttk.Frame(shell)
        controls.grid(row=1, column=0, sticky="ew", pady=12)
        ttk.Label(controls, text="目标窗口").pack(side=tk.LEFT, padx=(0, 8))
        self.choice = ttk.Combobox(controls, state="readonly", width=65)
        self.choice.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.choice.bind("<<ComboboxSelected>>", self.invalidate)
        self.refresh_button = ttk.Button(controls, text="刷新列表", command=self.refresh)
        self.refresh_button.pack(side=tk.LEFT, padx=6)
        self.capture_button = ttk.Button(controls, text="截图并识别", style="Accent.TButton", command=self.capture)
        self.capture_button.pack(side=tk.LEFT)
        self.summary = tk.StringVar(value="选择窗口后点击“截图并识别”。图片仅在内存中预览，不会保存到磁盘。")
        ttk.Label(shell, textvariable=self.summary, wraplength=1060, style="Muted.TLabel").grid(row=2, column=0, sticky="ew", pady=(0, 10))
        self.canvas = tk.Canvas(shell, background="#172238", highlightthickness=0, height=200)
        self.canvas.grid(row=3, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda event: self.render())
        if config_path is not None:
            self.canvas.bind("<ButtonPress-1>", self.start_selection)
            self.canvas.bind("<B1-Motion>", self.drag_selection)
            self.canvas.bind("<ButtonRelease-1>", self.finish_selection)
        self.results = ttk.Treeview(shell, columns=("id", "result", "score", "point", "screen"), show="headings", height=4)
        for key, label, width in [("id", "目标", 130), ("result", "本帧观察", 210), ("score", "分数 / 阈值", 130),
                                   ("point", "参考坐标中心", 140), ("screen", "屏幕坐标中心", 140)]:
            self.results.heading(key, text=label)
            self.results.column(key, width=width, minwidth=80)
        self.results.grid(row=4, column=0, sticky="ew", pady=10)
        self.results.configure(yscrollcommand=self._scroll_results)
        self.scrollbar = ttk.Scrollbar(shell, orient="vertical", command=self.results.yview)
        self.scrollbar.grid(row=4, column=1, sticky="ns", pady=10)
        ttk.Label(shell, text="蓝框：点击白名单  ·  绿框：匹配命中  ·  黄框：未达阈值  ·  红色十字：点击中心参考点\n"
                  "此处只观察单帧，不验证连续帧、冷却或执行阶段。真实点击可能有偏移；未命中不会绘制点击点。",
                  style="Muted.TLabel", wraplength=1060).grid(row=5, column=0, sticky="w")
        bottom = ttk.Frame(shell)
        bottom.grid(row=6, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(bottom, text="恢复配置中的窗口", command=self.restore).pack(side=tk.LEFT)
        if config_path is not None:
            self.region_button = ttk.Button(bottom, text="应用框选…", command=self.edit_region, state="disabled")
            self.region_button.pack(side=tk.LEFT, padx=8)
            self.selection_hint = tk.StringVar(master=self.dialog, value="在截图上拖拽可框选白名单")
            ttk.Label(bottom, textvariable=self.selection_hint, style="Muted.TLabel").pack(side=tk.LEFT)
        ttk.Button(bottom, text="关闭", command=self.close).pack(side=tk.RIGHT)
        self.apply_button = ttk.Button(bottom, text="使用此窗口", command=self.apply, state="disabled")
        self.apply_button.pack(side=tk.RIGHT, padx=8)
        self.refresh()

    def _scroll_results(self, first, last):
        if hasattr(self, "scrollbar"):
            self.scrollbar.set(first, last)

    def invalidate(self, _event=None):
        self.result = None
        self.photo = None
        self.image_bounds = None
        self.drag_start = None
        self.region = None
        self.update_selection()
        self.canvas.delete("all")
        self.results.delete(*self.results.get_children())
        self.apply_button.configure(state="disabled")
        self.summary.set("窗口已改变，请重新截图识别。")

    def refresh(self):
        if self.busy:
            return
        previous = self.selected_identity()
        try:
            self.windows = WindowLocator().find_all()
            values = ["按全局配置定位窗口"] + [
                f"{w.title}  |  {w.client_width}×{w.client_height}  |  HWND {w.handle} / PID {w.process_id}"
                for w in self.windows
            ]
            index = next((i for i, w in enumerate(self.windows, start=1)
                          if (w.handle, w.process_id) == previous), 0)
            self.unavailable_identity = None
            if previous is not None and index == 0:
                self.unavailable_identity = previous
                index = len(values)
                values.append(f"原窗口当前不可用  |  HWND {previous[0]} / PID {previous[1]}")
            self.choice.configure(values=values)
            self.choice.current(index)
            self.invalidate()
        except Exception as exc:
            self.summary.set(f"无法枚举窗口：{exc}")

    def selected_identity(self):
        index = self.choice.current()
        if 0 < index <= len(self.windows):
            window = self.windows[index - 1]
            return window.handle, window.process_id
        if index != 0:
            return self.unavailable_identity
        return None

    def capture(self):
        if self.busy:
            return
        config = with_window_identity(self.config, self.selected_identity())
        self.invalidate()
        self.busy = True
        self.choice.configure(state="disabled")
        self.capture_button.configure(state="disabled")
        self.refresh_button.configure(state="disabled")
        self.summary.set("正在截图和识别… 可随时关闭此窗口；不会发送点击。")
        # The worker must not retain Tk objects after the dialog has been closed.
        inbox, scenario, step_id = self.inbox, self.scenario, self.selected_step_id
        def work():
            try:
                inbox.put(capture_preview(config, scenario, step_id))
            except Exception as exc:
                inbox.put(exc)
        threading.Thread(target=work, daemon=True, name="recognition-preview").start()
        self.poll_id = self.dialog.after(80, self.poll)

    def poll(self):
        self.poll_id = None
        if self.closed:
            return
        try:
            value = self.inbox.get_nowait()
        except queue.Empty:
            self.poll_id = self.dialog.after(80, self.poll)
            return
        self.busy = False
        self.choice.configure(state="readonly")
        self.capture_button.configure(state="normal")
        self.refresh_button.configure(state="normal")
        if isinstance(value, Exception):
            self.summary.set(f"预览失败：{value}")
            return
        self.result = value
        window = value.window
        budget, _ = self.scenario.click_budget(self.config)
        self.summary.set(f"{window.title}  ·  HWND {window.handle} / PID {window.process_id}  ·  "
                         f"客户区 {window.client_width}×{window.client_height} → 参考 {value.frame.image.shape[1]}×{value.frame.image.shape[0]}\n"
                         f"识别耗时 {value.duration_seconds:.2f} 秒  ·  点击预算 {budget if budget is not None else '不限'}  ·  "
                         f"本帧首选：{value.preferred_id or ('无命中' if self.scenario.execution_mode == 'match_any' else '顺序场景只检查选中步骤')}")
        for item in value.targets:
            if item.kind == "wait":
                state = "纯等待，不点击"
            elif item.kind == "wait_for_image":
                state = "已识别，只观察" if item.matched else "未达阈值 / 无候选"
            elif item.point is None:
                state = "未达阈值 / 无候选"
            else:
                state = "中心在白名单内" if item.in_bounds else "越界，运行将拒绝"
                if item.id == value.preferred_id:
                    state = "本帧首选 · " + state
            score = f"{item.score:.3f} / {item.threshold:.3f}" if item.score is not None else "—"
            self.results.insert("", "end", values=(item.id, state, score, item.point or "—", item.screen_point or "—"))
        self.apply_button.configure(state="normal")
        self.render()

    def render(self):
        if self.result is None or self.closed:
            return
        image = self.result.annotated
        width, height = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        scale = min(width / image.shape[1], height / image.shape[0], 1)
        image_width = max(1, round(image.shape[1] * scale))
        image_height = max(1, round(image.shape[0] * scale))
        resized = cv2.resize(image, (image_width, image_height))
        ok, png = cv2.imencode(".png", resized)
        if ok:
            self.photo = tk.PhotoImage(data=base64.b64encode(png).decode("ascii"), master=self.dialog)
            self.canvas.delete("all")
            self.image_bounds = Region((width - image_width) // 2, (height - image_height) // 2, image_width, image_height)
            self.drag_start = None
            self.canvas.create_image(self.image_bounds.left, self.image_bounds.top, image=self.photo, anchor="nw")
            self.update_selection()

    def start_selection(self, event):
        if self.image_bounds is not None and self.image_bounds.contains_point(event.x, event.y):
            self.drag_start = (event.x, event.y)
            self.region = None
            self.update_selection()

    def drag_selection(self, event):
        if self.drag_start is not None and self.image_bounds is not None:
            height, width = self.result.frame.image.shape[:2]
            self.region = selection_region(self.drag_start, (event.x, event.y), self.image_bounds, width, height)
            self.update_selection()

    def finish_selection(self, event):
        self.drag_selection(event)
        self.drag_start = None

    def update_selection(self):
        if self.config_path is None:
            return
        self.canvas.delete("region-draft")
        if self.region is None:
            self.region_button.configure(state="disabled")
            self.selection_hint.set("在截图上拖拽可框选白名单")
            return
        rect = self.region
        display = self.image_bounds
        height, width = self.result.frame.image.shape[:2]
        self.canvas.create_rectangle(
            display.left + rect.left * display.width / width,
            display.top + rect.top * display.height / height,
            display.left + rect.right * display.width / width,
            display.top + rect.bottom * display.height / height,
            outline="#ffca57", width=2, dash=(5, 3), tags="region-draft",
        )
        self.region_button.configure(state="normal")
        self.selection_hint.set(f"待保存  ({rect.left}, {rect.top}) · {rect.width} × {rect.height}")

    def edit_region(self):
        if self.region is None:
            return
        from src.yys_automation.settings_gui import open_global_settings

        def saved(config):
            self.config = config
            if self.on_config_saved is not None:
                self.on_config_saved(config)
            self.capture()

        height, width = self.result.frame.image.shape[:2]
        try:
            open_global_settings(self.dialog, self.config_path, saved, self.region, (width, height))
        except (OSError, ValueError, yaml.YAMLError) as exc:
            self.summary.set(f"无法应用框选：{exc}")

    def apply(self):
        if self.result is not None:
            window = self.result.window
            self.on_apply((window.handle, window.process_id), window.title)
            self.close()

    def restore(self):
        self.on_apply(None, "按全局配置定位")
        self.close()

    def close(self):
        self.closed = True
        if self.poll_id is not None:
            self.dialog.after_cancel(self.poll_id)
        self.dialog.grab_release()
        self.dialog.destroy()
