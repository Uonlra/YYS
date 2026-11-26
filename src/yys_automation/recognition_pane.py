"""Single-frame threshold tuning inside the scenario editor."""
from __future__ import annotations

import base64
from dataclasses import dataclass, replace
from queue import Empty, Queue
from threading import Thread
import tkinter as tk
from tkinter import ttk

import cv2

from src.yys_automation.config import AppConfig
from src.yys_automation.preflight import PreviewResult, capture_frame, inspect_frame
from src.yys_automation.scenario import Scenario, ScenarioStep
from src.yys_automation.screen import Frame
from src.yys_automation.window import WindowInfo


@dataclass(frozen=True)
class ThresholdComparison:
    current: PreviewResult
    draft: PreviewResult
    threshold: float | None


def compare_thresholds(config: AppConfig, scenario: Scenario, step: ScenarioStep,
                       frame: Frame, window: WindowInfo, threshold: float | None) -> ThresholdComparison:
    if frame.image.shape[:2] != (config.window.reference_height, config.window.reference_width):
        raise ValueError("截图与当前参考尺寸不同，请重新截图。")
    current = inspect_frame(config, scenario, frame, window, step.id, only_selected=True)
    if threshold == step.threshold:
        return ThresholdComparison(current, current, threshold)
    draft_step = replace(step, threshold=threshold)
    updated = replace(scenario, steps=tuple(draft_step if item.id == step.id else item for item in scenario.steps))
    draft = inspect_frame(config, updated, frame, window, step.id, only_selected=True)
    return ThresholdComparison(current, draft, threshold)


class RecognitionPane(ttk.Frame):
    def __init__(self, parent, get_context, apply_threshold, choose_window):
        super().__init__(parent, padding=10)
        self.get_context = get_context
        self.apply_threshold = apply_threshold
        self.step: ScenarioStep | None = None
        self.frame: Frame | None = None
        self.window: WindowInfo | None = None
        self.result: ThresholdComparison | None = None
        self.photo: tk.PhotoImage | None = None
        self.busy = False
        self.running = False
        self.generation = 0
        self.check_after_work = False
        self.source_label = "当前截图"

        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        self.target_label = tk.StringVar(master=self, value="选择一个图片步骤")
        ttk.Label(header, textvariable=self.target_label, width=20).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.window_button = ttk.Button(header, text="窗口与区域…", command=choose_window, padding=(6, 4))
        self.window_button.pack(side=tk.RIGHT)

        self.message = tk.StringVar(master=self, value="截图后可在同一帧试调阈值。")
        hint = ttk.Label(self, textvariable=self.message, style="Muted.TLabel", wraplength=360)
        hint.grid(row=1, column=0, sticky="ew", pady=(0, 5))
        hint.bind("<Configure>", lambda event: hint.configure(wraplength=max(100, event.width - 4)))
        self.canvas = tk.Canvas(self, background="#172238", highlightthickness=0, width=1, height=100)
        self.canvas.grid(row=2, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", self.render)

        self.comparison = ttk.Treeview(self, columns=("setting", "threshold", "score", "result"), show="headings", height=2)
        for key, label, width in [("setting", "设置", 62), ("threshold", "阈值", 76),
                                   ("score", "分数", 58), ("result", "本帧结果", 100)]:
            self.comparison.heading(key, text=label)
            self.comparison.column(key, width=width, minwidth=45, stretch=True)
        self.comparison.grid(row=3, column=0, sticky="ew", pady=(6, 5))

        settings = ttk.Frame(self)
        settings.grid(row=4, column=0, sticky="ew", pady=(0, 5))
        ttk.Label(settings, text="试调阈值").pack(side=tk.LEFT)
        self.threshold = tk.StringVar(master=self)
        self.entry = ttk.Entry(settings, textvariable=self.threshold, width=8)
        self.entry.pack(side=tk.LEFT, padx=(6, 8))
        self.entry.bind("<Return>", lambda _event: self.recalculate())
        ttk.Label(settings, text="留空继承全局值", style="Muted.TLabel").pack(side=tk.LEFT)
        self.threshold.trace_add("write", self._draft_changed)
        buttons = ttk.Frame(self)
        buttons.grid(row=5, column=0, sticky="ew")
        self.capture_button = ttk.Button(buttons, text="截图识别", command=self.capture)
        self.capture_button.pack(side=tk.LEFT, padx=(0, 4))
        self.recalculate_button = ttk.Button(buttons, text="同帧重算", command=self.recalculate)
        self.recalculate_button.pack(side=tk.LEFT, padx=(0, 4))
        self.apply_button = ttk.Button(buttons, text="应用阈值", style="Accent.TButton", command=self.apply)
        self.apply_button.pack(side=tk.LEFT)
        self._update_buttons()

    def select_step(self, step: ScenarioStep | None) -> None:
        if step == self.step:
            return
        self.step = step
        self.generation += 1
        self.result = None
        self._clear_display()
        eligible = self._has_template()
        self.target_label.set(f"正在检查 {step.id}" if eligible else "选择一个图片步骤")
        self.threshold.set(str(step.threshold) if eligible and step.threshold is not None else "")
        if eligible and self.frame is not None:
            self.message.set("已保留当前截图，可用同帧重算检查此步骤。")
            if self.winfo_ismapped() and not self.running:
                self.after_idle(self._check_selection, self.generation)
        else:
            self.message.set("截图后可在同一帧试调阈值。")
        self._update_buttons()

    def _check_selection(self, generation: int) -> None:
        if generation != self.generation or self.running or not self.winfo_ismapped():
            return
        if self.busy:
            self.check_after_work = True
        else:
            self.recalculate()

    def refresh_visible_selection(self) -> None:
        if self.result is None and self.frame is not None:
            self._check_selection(self.generation)

    def reset_frame(self, message: str = "请截图检查当前目标窗口。") -> None:
        self.generation += 1
        self.check_after_work = False
        self.frame = None
        self.window = None
        self.result = None
        self._clear_display()
        self.message.set(message)
        self._update_buttons()

    def use_saved_frame(self, frame: Frame, window: WindowInfo) -> None:
        self.reset_frame()
        self.frame, self.window = frame, window
        self.source_label = "诊断截图"
        if self.busy:
            self.check_after_work = True
        else:
            self.recalculate()

    def set_running(self, running: bool) -> None:
        self.running = running
        if running:
            self.reset_frame("场景运行中。停止后可继续检查。")
        elif self.frame is None:
            self.message.set("截图后可在同一帧试调阈值。")
        self._update_buttons()

    def capture(self) -> None:
        self._start_job(new_frame=True)

    def recalculate(self) -> None:
        self._start_job(new_frame=False)

    def _has_template(self) -> bool:
        return self.step is not None and self.step.image is not None

    def _read_threshold(self) -> float | None:
        value = self.threshold.get().strip()
        if not value:
            return None
        try:
            threshold = float(value)
            if 0 < threshold <= 1:
                return threshold
        except ValueError:
            pass
        raise ValueError("阈值须大于 0 且不超过 1，留空可继承全局值。")

    def _draft_changed(self, *_args) -> None:
        if self.result is not None and not self.busy:
            try:
                if self._read_threshold() != self.result.threshold:
                    self.message.set("阈值已修改。重算后可应用。")
                else:
                    self.message.set(f"{self.source_label}  ·  蓝框区域 / 绿框命中 / 黄框候选")
            except ValueError as exc:
                self.message.set(str(exc))
        self._update_buttons()

    def _update_buttons(self) -> None:
        ready = self._has_template() and not self.busy and not self.running
        self.capture_button.configure(state="normal" if ready else "disabled")
        self.recalculate_button.configure(state="normal" if ready and self.frame is not None else "disabled")
        self.entry.configure(state="normal" if self._has_template() and not self.running else "disabled")
        self.window_button.configure(state="disabled" if self.running else "normal")
        applicable = False
        if ready and self.result is not None:
            try:
                threshold = self._read_threshold()
                applicable = self.result.threshold == threshold and self.step.threshold != threshold
            except ValueError:
                pass
        self.apply_button.configure(state="normal" if applicable else "disabled")

    def _start_job(self, *, new_frame: bool) -> None:
        if self.busy or self.running or not self._has_template() or (not new_frame and self.frame is None):
            return
        try:
            context = self.get_context()
            if context is None:
                return
            config, scenario, step = context
            if step.image is None:
                return
            threshold = self._read_threshold()
        except Exception as exc:
            self.message.set(str(exc))
            return

        frame, window = self.frame, self.window
        inbox: Queue[ThresholdComparison | Exception] = Queue()
        self.busy = True
        self.check_after_work = False
        self.message.set("正在截图并识别…" if new_frame else "正在用同一张截图重算…")
        self._update_buttons()
        generation = self.generation

        def worker() -> None:
            try:
                sample, target = capture_frame(config) if new_frame else (frame, window)
                inbox.put(compare_thresholds(config, scenario, step, sample, target, threshold))
            except Exception as exc:
                inbox.put(exc)

        Thread(target=worker, daemon=True, name="threshold-preview").start()
        self.after(60, self._poll, inbox, generation, new_frame)

    def _poll(self, inbox, generation: int, new_frame: bool) -> None:
        try:
            value = inbox.get_nowait()
        except Empty:
            self.after(60, self._poll, inbox, generation, new_frame)
            return
        self.busy = False
        if generation == self.generation:
            self.check_after_work = False
            if isinstance(value, Exception):
                self.result = None
                self._clear_display()
                self.message.set(f"识别失败：{value}")
            else:
                self.result = value
                self.frame, self.window = value.draft.frame, value.draft.window
                if new_frame:
                    self.source_label = self.window.title
                self._show_result()
        elif self.check_after_work:
            self.check_after_work = False
            self.recalculate()
        self._update_buttons()

    def _clear_display(self) -> None:
        self.canvas.delete("all")
        self.photo = None
        self.comparison.delete(*self.comparison.get_children())

    def _show_result(self) -> None:
        self.comparison.delete(*self.comparison.get_children())
        for label, preview in (("当前设置", self.result.current), ("试调结果", self.result.draft)):
            item = preview.targets[0]
            score = "—" if item.score is None else f"{item.score:.3f}"
            if not item.matched:
                state = "未达到阈值" if item.box is not None else "无候选"
            elif item.point is None:
                state = "命中 · 只观察"
            else:
                x, y = item.point
                state = f"命中 · {x}, {y}" if item.in_bounds else f"越界 · {x}, {y}"
            self.comparison.insert("", tk.END, values=(label, f"{item.threshold:.3f}", score, state))
        self.message.set(f"{self.source_label}  ·  蓝框区域 / 绿框命中 / 黄框候选")
        self.render()

    def render(self, _event=None) -> None:
        if self.result is None:
            return
        image = self.result.draft.annotated
        width, height = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        scale = min(width / image.shape[1], height / image.shape[0], 1)
        size = (max(1, round(image.shape[1] * scale)), max(1, round(image.shape[0] * scale)))
        resized = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".png", resized)
        if ok:
            self.photo = tk.PhotoImage(data=base64.b64encode(encoded).decode("ascii"), master=self)
            self.canvas.delete("all")
            self.canvas.create_image(width // 2, height // 2, image=self.photo, anchor="center")

    def apply(self) -> None:
        if self.apply_button.instate(["disabled"]) or self.result is None:
            return
        if self.apply_threshold(self.step, self.result.threshold):
            self.message.set("阈值已应用。保存或运行时写入场景。")
