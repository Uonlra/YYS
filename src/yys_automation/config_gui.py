from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import tkinter as tk
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, messagebox

import yaml

from src.yys_automation.config import AppConfig, load_config
from src.yys_automation.diagnostics_gui import load_diagnostic_image, run_progress, show_diagnostic, stop_label
from src.yys_automation.scenario import Scenario, ScenarioStep, load_scenario, parse_scenario, validate_scenario
from src.yys_automation.status import RunStatus
from src.yys_automation.editor_ui import TYPE_LABELS, build_editor
from src.yys_automation.preflight import with_window_identity
from src.yys_automation.recent_scenarios import RecentScenario, RecentScenarios


class ScenarioEditor:
    def __init__(self, scenario_path: Path | None = None, config_path: Path = Path("config.yaml"), *, dry_run: bool = False,
                 window_identity: tuple[int, int] | None = None, restore_recent: bool = False) -> None:
        self.root = tk.Tk()
        self.root.title("YYS 场景配置")
        self.dry_run = dry_run
        self._config_dry_run = False
        self._session_dry_run = dry_run
        self._launch_config: AppConfig | None = None
        self._window_title = ""
        if dry_run:
            self.root.title("YYS 场景配置 — 试运行（不发送点击）")
        self.scenario_path: Path | None = None
        self.config_path = config_path
        self.recent = RecentScenarios(config_path)
        self._missing_scene: RecentScenario | None = None
        self.scenario: Scenario | None = None
        self.steps: list[ScenarioStep] = []
        self.process: subprocess.Popen[str] | None = None
        self.process_cleanup_path: Path | None = None
        self._form_index: int | None = None
        self._form_snapshot: dict[str, str] = {}
        self._dirty = False
        self._loading_form = False
        self._poll_id: str | None = None
        self._stop_requested = False
        self._close_pending = False
        self._started_at: datetime | None = None
        self._output_path: Path | None = None
        self._output_content = ""
        self._window_identity = window_identity
        self._finished_run: dict | None = None
        self._diagnostic_directory: Path | None = None
        self._run_editor_path: Path | None = None
        self.status_reader = RunStatus(self.config_path.parent / "logs" / "automation.status.json")
        self._build_ui()
        self.dry_run_var.trace_add("write", self._refresh_run_mode)
        for var in (self.status_var, self.current_step_var, self.clicks_var, self.cycles_var, self.runtime_var):
            var.trace_add("write", self._refresh_run_summary)
        if window_identity:
            self._apply_window(window_identity, "命令行指定窗口")
        for var in self.form.values():
            var.trace_add("write", self._form_changed)
        self._clear_form()
        try:
            self._set_launch_config(load_config(config_path))
        except (OSError, ValueError, yaml.YAMLError):
            self._refresh_run_mode()
        restore = restore_recent and bool(self.recent.entries)
        startup_path = self.recent.entries[0].path if restore else scenario_path
        if startup_path is not None:
            self.path_var.set(str(startup_path))
            if self._load_file(startup_path) and restore:
                self.detail_var.set("已恢复上次场景，可检查设置后开始运行。")

    def _build_ui(self) -> None:
        build_editor(self)

    def _apply_window(self, identity: tuple[int, int] | None, title: str) -> None:
        if identity != self._window_identity:
            self.recognition.reset_frame("已切换目标窗口，请重新截图。")
        self._window_identity = identity
        self._window_title = title if identity else ""
        self._refresh_launch_context()

    def _set_launch_config(self, config: AppConfig) -> None:
        if not self._config_dry_run:
            self._session_dry_run = self.dry_run_var.get()
        self._launch_config = config
        self._config_dry_run = config.dry_run
        self.dry_run_var.set(self.dry_run or config.dry_run or self._session_dry_run)
        locked = self._is_running() or self.dry_run or config.dry_run
        self.dry_check.configure(state="disabled" if locked else "normal")
        self._refresh_launch_context()

    def _refresh_launch_context(self) -> None:
        config = self._launch_config
        if self._window_identity is not None:
            self.window_var.set(f"{self._window_title} · HWND {self._window_identity[0]}")
        elif config is None:
            self.window_var.set("按全局配置定位")
        else:
            window = config.window
            selector = window.title_contains or (
                f"HWND {window.handle}" if window.handle is not None else f"PID {window.process_id}"
            )
            self.window_var.set(f"按配置 · {selector}")
        if self.scenario is None and not self.steps:
            self.scene_var.set("未加载场景")
            self.budget_var.set("—")
            self.budget_source_var.set("加载场景后显示")
            return
        self.scene_var.set(self.scenario.name if self.scenario else "新场景")
        self._refresh_click_budget()

    def _refresh_click_budget(self) -> None:
        config = self._launch_config
        if config is None:
            self.budget_var.set("—")
            self.budget_source_var.set("请检查全局配置")
            return
        scenario = self.scenario or Scenario("preview", 1, False, ())
        steps = list(self.steps)
        if scenario.max_clicks == "auto" and self._form_pending():
            try:
                pending = self._read_form()
            except (TypeError, ValueError):
                self.budget_var.set("待校验")
                self.budget_source_var.set("场景自动计算")
                return
            if self._form_index is None:
                steps.append(pending)
            else:
                steps[self._form_index] = pending
        limit, source = replace(scenario, steps=tuple(steps)).click_budget(config)
        self.budget_var.set("不限" if limit is None else f"{limit} 次")
        self.budget_source_var.set({
            "config.max_clicks": "继承全局设置",
            "scenario.max_clicks": "场景覆盖全局设置",
            "scenario.auto": "场景自动计算",
        }[source])

    def _refresh_run_mode(self, *_args: object) -> None:
        dry = self.dry_run or self._config_dry_run or self.dry_run_var.get()
        if self.dry_run:
            label = "模拟点击 · 启动参数锁定"
        elif self._config_dry_run:
            label = "模拟点击 · 由全局设置开启"
        elif dry:
            label = "模拟点击 · 本次会话"
        elif self._launch_config is None:
            label = "待校验全局配置"
        else:
            label = "真实点击"
        self.mode_var.set(label)
        self.mode_label.configure(style="RunMode.TLabel" if dry or self._launch_config is None else "LiveMode.TLabel")
        self.run_button.configure(text="试运行场景" if dry else "运行场景")
        self.root.title("YYS 场景配置 — 试运行（不发送点击）" if dry else "YYS 场景配置")

    def _refresh_run_summary(self, *_args: object) -> None:
        state = self.status_var.get()
        if state == "就绪":
            self.run_summary_var.set(state)
            return
        step = self.current_step_var.get()
        summary = f"{state}  ·  {step}  ·  点击 {self.clicks_var.get()}"
        if self.cycles_var.get() != "0" or (self.scenario and self.scenario.execution_mode == "sequential"):
            summary += f"  ·  完成 {self.cycles_var.get()} 轮"
        self.run_summary_var.set(f"{summary}  ·  {self.runtime_var.get()}")

    def _global_settings_saved(self, config: AppConfig) -> None:
        self._set_launch_config(config)
        self.detail_var.set("全局设置已保存。下次预览和运行将使用新设置。")
        self.recognition.reset_frame("全局设置已更新，请重新截图。")

    def _open_global_settings(self) -> None:
        if self._is_running():
            return
        from src.yys_automation.settings_gui import open_global_settings

        try:
            open_global_settings(self.root, self.config_path, self._global_settings_saved)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            messagebox.showerror("无法打开全局设置", str(exc), parent=self.root)

    def _apply_scenario_settings(self, changes: dict) -> None:
        path = Path(self.path_var.get()).resolve()
        payload = self._payload(path)
        for key, value in changes.items():
            if value is None:
                payload.pop(key, None)
            else:
                payload[key] = value
        updated = parse_scenario(payload, path)
        if self.scenario is None or updated != replace(self.scenario, steps=tuple(self.steps)):
            self.scenario = updated
            self._mark_dirty()
            self.recognition.reset_frame("场景设置已更新，请重新截图。")
        self._refresh_launch_context()
        self.detail_var.set("场景设置已应用。预览使用当前修改，保存或运行时写入场景文件。")

    def _open_scenario_settings(self) -> None:
        if self._is_running() or not self._commit_form():
            return
        if not self.steps:
            messagebox.showwarning("场景为空", "请先打开场景或添加步骤。", parent=self.root)
            return
        from src.yys_automation.settings_gui import open_scenario_settings

        scenario = self.scenario or Scenario(Path(self.path_var.get()).stem, 1, False, tuple(self.steps))
        open_scenario_settings(self.root, scenario, self._apply_scenario_settings)

    def _open_preflight(self, *, capture_now: bool = False) -> None:
        if self._is_running() or not self._commit_form():
            return
        try:
            from src.yys_automation.preflight_gui import PreflightDialog

            config = load_config(self.config_path)
            scenario = replace(self.scenario, steps=tuple(self.steps)) if self.scenario else Scenario("preview", 1, False, tuple(self.steps))
            if not scenario.steps:
                raise ValueError("请先添加步骤或打开场景。")
            step_id = self.steps[self._form_index].id if self._form_index is not None else self.steps[0].id
            dialog = PreflightDialog(self.root, config, scenario, step_id, self._apply_window, self._window_identity,
                                     config_path=self.config_path, on_config_saved=self._global_settings_saved)
            if capture_now:
                dialog.capture()
        except Exception as exc:
            messagebox.showerror("无法打开运行前检查", str(exc), parent=self.root)

    def _show_recognition(self) -> None:
        if not self._is_running() and self._commit_form():
            self._show_editor_tab(self.recognition)

    def _show_editor_tab(self, tab: int | tk.Misc) -> None:
        self.tabs.select(tab)
        self.sidebar.expand()

    def _recognition_context(self):
        if self._is_running() or not self._commit_form() or self._form_index is None:
            return None
        config = with_window_identity(load_config(self.config_path), self._window_identity)
        scenario = self.scenario or Scenario("preview", 1, False, ())
        return config, replace(scenario, steps=tuple(self.steps)), self.steps[self._form_index]

    def _apply_recognition_threshold(self, compared_step: ScenarioStep, threshold: float | None) -> bool:
        if self._is_running() or not self._commit_form() or self._form_index is None:
            return False
        if self.steps[self._form_index] != compared_step:
            self.recognition.message.set("步骤已更新，请按当前参数重算。")
            return False
        self.form["threshold"].set("" if threshold is None else str(threshold))
        return self._commit_form()

    def _open_diagnostic(self) -> None:
        if self._is_running() or self._finished_run is None or self._diagnostic_directory is None:
            return
        status = self._finished_run
        reason = status.get("stop_reason")
        same_scenario = self.scenario_path == self._run_editor_path

        def select_step(step_id: str | None = None) -> bool:
            if not self._commit_form():
                return False
            step_id = step_id or status.get("current_step")
            for index, step in enumerate(self.steps):
                if step.id == step_id:
                    self.tree.selection_set(str(index))
                    self.tree.see(str(index))
                    self._load_form(index)
                    break
            return True

        def recheck() -> None:
            if select_step():
                self._open_preflight(capture_now=True)

        def focus_settings() -> None:
            if select_step():
                self._show_editor_tab(0)
                field = "x" if self._step_type() == "click_point" else "threshold"
                self.form_widgets[field].focus_set()

        diagnostic = status.get("diagnostic") or {}
        tune_target = next((step.id for key in ("current_step", "frame_step") for step in self.steps
                            if (status.get(key) or diagnostic.get(key)) == step.id and step.image is not None), None)

        def tune_frame() -> None:
            from src.yys_automation.screen import Frame
            from src.yys_automation.window import WindowInfo

            if not select_step(tune_target):
                return
            frame_data = load_diagnostic_image(self._diagnostic_directory, diagnostic)
            if frame_data is None:
                self.detail_var.set("诊断截图已不可用，请重新截图。")
                return
            left, top = diagnostic["origin"]
            sx, sy = diagnostic["scale"]
            height, width = frame_data.shape[:2]
            frame = Frame(frame_data, left, top, sx, sy)
            description = WindowInfo(0, "诊断截图", left, top, round(width * sx), round(height * sy))
            self._show_editor_tab(self.recognition)
            self.recognition.use_saved_frame(frame, description)

        settings_label = "调整步骤参数"
        settings = focus_settings
        if reason in {"budget", "miss_limit", "no_target_timeout"}:
            settings_label = "调整场景设置"
            settings = self._open_scenario_settings
        elif reason == "capture_error" or reason == "window_missing":
            settings_label = "调整全局设置"
            settings = self._open_global_settings
        show_diagnostic(
            self.root, status, self._diagnostic_directory,
            on_recheck=recheck if same_scenario else None,
            on_settings=settings if same_scenario else None,
            settings_label=settings_label,
            on_tune=tune_frame if same_scenario and tune_target and diagnostic.get("screenshot") else None,
        )

    def _form_changed(self, *_args: object) -> None:
        if self._loading_form:
            return
        self.saved_var.set("有未保存修改")
        self._sync_field_states()
        if self.scenario and self.scenario.max_clicks == "auto":
            self._refresh_click_budget()

    def _form_pending(self) -> bool:
        return {key: var.get() for key, var in self.form.items()} != self._form_snapshot

    def _mark_dirty(self) -> None:
        self._dirty = True
        self.saved_var.set("有未保存修改")

    def _clear_form(self) -> None:
        self._loading_form = True
        defaults = {"type": TYPE_LABELS["match_and_click"], "timeout": "30",
                    "wait": "0.5", "attempts": "1", "response": "3"}
        for key, var in self.form.items():
            var.set(defaults.get(key, ""))
        self._loading_form = False
        self._form_index = None
        self._form_snapshot = {key: var.get() for key, var in self.form.items()}
        self._sync_field_states()
        self.recognition.select_step(None)
        self._preview_image()

    def _sync_field_states(self) -> None:
        kind = self._step_type()
        editable = not self._is_running()
        uses_template = kind in {"match_and_click", "wait_for_image"}
        uses_coordinates = kind == "click_point"
        conditional_fields = {"image": uses_template, "threshold": uses_template,
                              "x": uses_coordinates, "y": uses_coordinates}
        for key, visible in conditional_fields.items():
            row = self.form_rows[key]
            if visible:
                row.grid()
            else:
                row.grid_remove()
        for key, widget in self.form_widgets.items():
            enabled = editable and conditional_fields.get(key, True)
            widget.configure(state=("readonly" if key == "type" else "normal") if enabled else "disabled")
        self.image_button.configure(state="normal" if uses_template and editable else "disabled")
        hints = {"match_and_click": "等待模板稳定出现后点击。阈值留空时使用全局默认值。",
                 "wait_for_image": "只观察图片。阈值留空时使用全局默认值。",
                 "click_point": "使用窗口参考坐标；运行前会检查点击白名单。",
                 "wait": "等待指定秒数，不识别图片，也不发送点击。"}
        self.form_hint_var.set(hints.get(kind, ""))

    def _step_type(self) -> str:
        value = self.form["type"].get()
        return next((key for key, label in TYPE_LABELS.items() if value == label), value)

    def _is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def _set_running(self, running: bool) -> None:
        for widget in [self.run_button, self.test_button, self.validate_button, self.open_button,
                       self.preflight_button,
                       self.global_settings_button, self.scenario_settings_button,
                       self.recent_button, self.relocate_button,
                       self.load_button, self.save_button, self.save_as_button, self.path_entry,
                       self.apply_button, *self.edit_buttons]:
            widget.configure(state="disabled" if running else "normal")
        self.stop_button.configure(state="normal" if running else "disabled")
        self.dry_check.configure(state="disabled" if running or self.dry_run or self._config_dry_run else "normal")
        self._sync_field_states()
        self.recognition.set_running(running)

    def _commit_form(self) -> bool:
        if not self._form_pending():
            return True
        try:
            step = self._read_form()
            if not step.id:
                raise ValueError("步骤 ID 不能为空")
            if any(item.id == step.id for index, item in enumerate(self.steps) if index != self._form_index):
                raise ValueError(f"步骤 ID 已存在：{step.id}")
            if self._form_index is None:
                self.steps.append(step)
                self._form_index = len(self.steps) - 1
            else:
                self.steps[self._form_index] = step
            self._form_snapshot = {key: var.get() for key, var in self.form.items()}
            self._mark_dirty()
            self._refresh_tree(self._form_index)
            return True
        except (ValueError, TypeError) as exc:
            messagebox.showerror("步骤无效", str(exc), parent=self.root)
            return False

    def _confirm_discard(self) -> bool:
        if not self._dirty and not self._form_pending():
            return True
        answer = messagebox.askyesnocancel("未保存修改", "是否先保存当前场景的修改？", parent=self.root)
        return self._save_silently(destination=self.scenario_path) if answer is True else answer is False

    def _new_step(self) -> None:
        if self._is_running() or not self._commit_form():
            return
        self.tree.selection_remove(*self.tree.selection())
        self._clear_form()
        number = len(self.steps) + 1
        while any(step.id == f"step_{number}" for step in self.steps):
            number += 1
        self.form["id"].set(f"step_{number}")
        self._show_editor_tab(0)
        self.form_widgets["id"].focus_set()

    def _preview_image(self) -> None:
        self._preview_photo = None
        image_value = self.form["image"].get().strip()
        if not image_value or self._step_type() not in {"match_and_click", "wait_for_image"}:
            self.preview_label.configure(image="", text="此步骤不含模板图片")
            self.preview_info.set("")
            return
        path = Path(image_value)
        if not path.is_absolute():
            path = (self.scenario_path.parent if self.scenario_path else Path.cwd()) / path
        try:
            import base64
            import cv2
            import numpy as np

            image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError("图片无法解码")
            height, width = image.shape[:2]
            scale = min(340 / width, 240 / height, 1)
            image = cv2.resize(image, (max(1, round(width * scale)), max(1, round(height * scale))))
            ok, data = cv2.imencode(".png", image)
            if not ok:
                raise ValueError("图片预览转换失败")
            self._preview_photo = tk.PhotoImage(data=base64.b64encode(data).decode("ascii"), master=self.root)
            self.preview_label.configure(image=self._preview_photo, text="")
            self.preview_info.set(f"{path.name}  ·  {width} × {height} 像素\n按比例预览，识别仍使用原图。")
        except (OSError, ValueError, tk.TclError, cv2.error) as exc:
            self.preview_label.configure(image="", text="无法预览图片")
            self.preview_info.set(str(exc))

    def _save_as(self) -> None:
        if self._is_running():
            return
        path = filedialog.asksaveasfilename(defaultextension=".yaml", filetypes=[("YAML", "*.yaml *.yml")], parent=self.root)
        if path and self._save_silently(destination=Path(path)):
            self.detail_var.set(f"已另存为：{self.scenario_path}")

    def run(self) -> None:
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _run_scenario(self) -> None:
        if self.process is not None and self.process.poll() is None:
            messagebox.showinfo("任务运行中", "当前已有一个场景在运行")
            return
        if not self._save_silently():
            return
        self._start_process(self.scenario_path)

    def _test_current_step(self) -> None:
        if self.process is not None and self.process.poll() is None:
            messagebox.showinfo("任务运行中", "请先停止当前任务")
            return
        if not self._commit_form():
            return
        index = self._selected_index()
        if index is None:
            messagebox.showwarning("未选择步骤", "请先选择一个步骤")
            return
        if not self._save_silently():
            return
        fd, temp_name = tempfile.mkstemp(prefix="yys_step_", suffix=".yaml", dir=str(self.scenario_path.parent))
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            step = replace(self.steps[index], next_step=None, max_attempts=1, recover_to=(), requires_action=None)
            payload = {
                "name": f"gui_test_{step.id}",
                "max_retries": 1,
                "max_clicks": "auto",
                "steps": [self._step_to_yaml(step, temp_path.parent)],
            }
            if self.scenario and self.scenario.execution_mode == "match_any":
                payload.update(execution_mode="match_any", input_backend=self.scenario.input_backend,
                               max_clicks=1, stable_frames=self.scenario.stable_frames,
                               no_target_timeout_seconds=step.timeout_seconds)
            with temp_path.open("w", encoding="utf-8") as file:
                yaml.safe_dump(payload, file, allow_unicode=True, sort_keys=False)
        except Exception as exc:
            temp_path.unlink(missing_ok=True)
            messagebox.showerror("步骤测试准备失败", str(exc))
            return
        self._start_process(temp_path, cleanup_path=temp_path)

    def _start_process(self, scenario_path: Path | None, cleanup_path: Path | None = None) -> None:
        if scenario_path is None or self._is_running():
            return
        try:
            config = load_config(self.config_path)
            self._set_launch_config(config)
            config = with_window_identity(config, self._window_identity)
            errors = validate_scenario(scenario_path, config)
            if errors:
                raise ValueError("\n".join(errors))
            self.status_reader = RunStatus(config.log_file.parent / "automation.status.json")
            limit, _ = load_scenario(scenario_path).click_budget(config)
        except Exception as exc:
            self._cleanup_process_file(cleanup_path)
            messagebox.showerror("无法启动", str(exc), parent=self.root)
            return
        command = [sys.executable, "-u", str(Path(__file__).resolve().parents[2] / "run.py"),
                   "--config", str(self.config_path.resolve()), "--scenario", str(scenario_path.resolve())]
        if self._window_identity is not None:
            command.extend(["--window-handle", str(self._window_identity[0]),
                            "--window-process-id", str(self._window_identity[1])])
        if self.dry_run or self.dry_run_var.get():
            command.append("--dry-run")
        self._started_at = datetime.now(timezone.utc)
        self._stop_requested = False
        self._last_status = None
        try:
            fd, name = tempfile.mkstemp(prefix="yys_output_", suffix=".log")
            self._output_path = Path(name)
            with os.fdopen(fd, "wb") as output:
                self.process = subprocess.Popen(
                    command, cwd=str(Path(__file__).resolve().parents[2]),
                    stdout=output, stderr=subprocess.STDOUT,
                    env={**os.environ, "PYTHONIOENCODING": "utf-8", "YYS_WORKBENCH_RUN": "1"},
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
        except OSError as exc:
            self._remove_output()
            self._cleanup_process_file(cleanup_path)
            messagebox.showerror("启动失败", str(exc), parent=self.root)
            return
        self.process_cleanup_path = cleanup_path
        self._output_content = ""
        if self.log_frame.winfo_manager():
            self._render_log()
        self._run_editor_path = self.scenario_path
        self._finished_run = None
        self.diagnostic_button.configure(state="disabled")
        self._set_running(True)
        self.status_var.set("试运行中" if self.dry_run_var.get() or config.dry_run else "运行中")
        self.current_step_var.set("等待截图")
        self.clicks_var.set(f"0 / {limit if limit is not None else '不限'}")
        self.cycles_var.set("0")
        self.runtime_var.set("00:00")
        self.detail_var.set("正在启动…")
        self._poll_process(cleanup_path)

    def _fresh_status(self) -> dict | None:
        status = self.status_reader.read()
        if not status:
            return None
        pid = getattr(self.process, "pid", None)
        if isinstance(pid, int) and status.get("pid") not in (None, pid):
            return None
        try:
            updated = datetime.fromisoformat(status["updated_at"])
            if self._started_at is None or updated < self._started_at:
                return None
        except (KeyError, ValueError, TypeError):
            return None
        return status

    def _poll_status(self) -> None:
        status = self._fresh_status()
        if not status:
            return
        self._last_status = status
        step = status.get("current_step") or "等待截图"
        self.current_step_var.set(str(step))
        limit = status.get("max_clicks")
        self.clicks_var.set(f"{status.get('clicks', 0)} / {limit if limit is not None else '不限'}")
        self.cycles_var.set(str(status.get("cycle", 0)))
        seconds = max(0, int(status.get("runtime_seconds", 0)))
        self.runtime_var.set(f"{seconds // 60:02}:{seconds % 60:02}")
        if not self._stop_requested:
            self.detail_var.set(run_progress(status))
        for index, item in enumerate(self.steps):
            self.tree.item(str(index), tags=("active",) if item.id == step else ("even",) if index % 2 == 0 else ())
        self.tree.tag_configure("active", background="#e0f2e8", foreground="#246744")

    def _poll_output(self) -> None:
        if self._output_path is None:
            return
        try:
            with self._output_path.open("rb") as output:
                output.seek(max(0, self._output_path.stat().st_size - 16000))
                content = output.read(16000).decode("utf-8", errors="replace").replace("\r\n", "\n")
            if content != self._output_content:
                self._output_content = content
                if self.log_frame.winfo_manager():
                    self._render_log()
        except OSError:
            pass

    def _render_log(self, *, follow_tail: bool = False) -> None:
        position, end = self.log_text.yview()
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.insert("1.0", self._output_content)
        self.log_text.configure(state="disabled")
        self.log_text.yview_moveto(1 if follow_tail or end >= 0.98 else position)

    def _toggle_log(self) -> None:
        if self.log_frame.winfo_manager():
            self.log_frame.pack_forget()
            self.log_button.configure(text="展开日志")
        else:
            self.log_frame.pack(fill=tk.X, pady=(7, 0))
            self._render_log(follow_tail=True)
            self.log_button.configure(text="收起日志")

    def _poll_process(self, cleanup_path: Path | None = None) -> None:
        self._poll_id = None
        if self.process is None:
            return
        self._poll_status()
        self._poll_output()
        code = self.process.poll()
        if code is None:
            self._poll_id = self.root.after(300, lambda: self._poll_process(cleanup_path))
            return
        # The process may publish its terminal state between the first read and poll().
        self._poll_status()
        status = self._last_status or {}
        reason = status.get("stop_reason") or status.get("failure_reason")
        if self._stop_requested:
            self.status_var.set("已停止")
            self.detail_var.set("已手动停止任务。")
            reason = "user_stopped"
        elif code == 0 and reason in (None, "completed"):
            self.status_var.set("已完成")
            self.detail_var.set("任务已完成。")
        else:
            self.status_var.set("已停止" if code == 0 or reason == "user_stopped" else "运行未完成")
            self.detail_var.set(stop_label(reason))
        if code != 0 or reason not in (None, "completed"):
            self._finished_run = {**status, "stop_reason": reason, "exit_code": code}
            self._diagnostic_directory = self.status_reader.path.parent / "failures"
            self.diagnostic_button.configure(state="normal")
        self.process = None
        self._set_running(False)
        self._cleanup_process_file(cleanup_path)
        self._remove_output()
        if self._close_pending:
            self.root.destroy()

    def _stop_process(self) -> None:
        if not self._is_running() or self._stop_requested:
            return
        self._stop_requested = True
        self.status_var.set("正在停止")
        self.detail_var.set("正在结束任务，界面仍可响应。")
        self.stop_button.configure(state="disabled")
        process = self.process
        try:
            process.terminate()
        except OSError:
            pass
        def force_stop() -> None:
            if self.process is process and process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass
        self.root.after(2000, force_stop)

    def _remove_output(self) -> None:
        if self._output_path is not None:
            try:
                self._output_path.unlink(missing_ok=True)
            except OSError:
                pass
            self._output_path = None

    def _cleanup_process_file(self, path: Path | None) -> None:
        if path is not None:
            path.unlink(missing_ok=True)
        if path == self.process_cleanup_path:
            self.process_cleanup_path = None

    def _on_close(self) -> None:
        if self._is_running():
            if not messagebox.askyesno("任务运行中", "停止当前任务并关闭工作台？", parent=self.root):
                return
            self._close_pending = True
            self._stop_process()
        elif self._confirm_discard():
            self.root.destroy()

    def _choose_file(self) -> None:
        path = filedialog.askopenfilename(parent=self.root, filetypes=[("YAML", "*.yaml *.yml"), ("All files", "*.*")])
        if path:
            self._load_file(Path(path))

    def _load_from_entry(self) -> None:
        self._load_file(Path(self.path_var.get()))

    def _refresh_recent_menu(self) -> None:
        self.recent_menu.delete(0, "end")
        if not self.recent.entries:
            self.recent_menu.add_command(label="尚无最近场景", state="disabled")
            return
        base_dir = self.recent.path.parent
        for entry in self.recent.entries:
            try:
                label = str(entry.path.relative_to(base_dir))
            except ValueError:
                label = str(entry.path)
            self.recent_menu.add_command(label=label, command=lambda path=entry.path: self._load_file(path))

    def _show_missing_scene(self, path: Path) -> None:
        self._missing_scene = RecentScenario(path, self.recent.selected_step(path))
        if self.scenario_path is None:
            self.path_var.set(str(path))
        self.file_notice_var.set(f"找不到场景 {path.name}。文件移动后可重新定位。")
        self.file_notice.pack(fill=tk.X)

    def _clear_missing_scene(self) -> None:
        self._missing_scene = None
        self.file_notice.pack_forget()

    def _relocate_scene(self) -> None:
        old = self._missing_scene
        if old is None or self._is_running():
            return
        folder = old.path.parent
        path = filedialog.askopenfilename(
            parent=self.root, title="重新定位场景", initialfile=old.path.name,
            initialdir=str(folder if folder.is_dir() else self.config_path.resolve().parent),
            filetypes=[("YAML", "*.yaml *.yml"), ("All files", "*.*")],
        )
        if path and self._load_file(Path(path), replaces=old):
            self.detail_var.set("已更新场景位置。")

    def _remember_scene(self, *, replaced_path: Path | None = None) -> None:
        if self.scenario_path is None:
            return
        step = self.steps[self._form_index].id if self._form_index is not None else None
        self.recent.remember(self.scenario_path, step, replaced_path=replaced_path)

    def _load_file(self, path: Path, *, replaces: RecentScenario | None = None) -> bool:
        if self._is_running():
            return False
        try:
            path = path.resolve()
            if not path.is_file():
                self._show_missing_scene(path)
                return False
            if not self._confirm_discard():
                return False
            scenario = load_scenario(path)
        except FileNotFoundError:
            self._show_missing_scene(path)
            return False
        except Exception as exc:
            messagebox.showerror("加载失败", str(exc), parent=self.root)
            return False
        self.scenario_path = path
        self.path_var.set(str(path))
        self.scenario = scenario
        self.steps = list(scenario.steps)
        self.recognition.reset_frame()
        self._dirty = False
        self.saved_var.set("已加载")
        self._clear_form()
        preferred_step = replaces.step_id if replaces else self.recent.selected_step(path)
        selected = next((i for i, step in enumerate(self.steps) if step.id == preferred_step), 0)
        self._refresh_tree(selected if self.steps else None)
        self._clear_missing_scene()
        self._remember_scene(replaced_path=replaces.path if replaces else None)
        return True

    def _payload(self, path: Path) -> dict[str, object]:
        from dataclasses import asdict

        scenario = self.scenario or Scenario(path.stem, 1, False, ())
        payload = {key: value for key, value in asdict(scenario).items()
                   if value is not None or key == "repeat_count"}
        payload["steps"] = [self._step_to_yaml(step, path.parent) for step in self.steps]
        payload["stop_when"] = [
            {"id": item.id, "image": self._relative_image(item.image, path.parent),
             "threshold": item.threshold, "stable_frames": item.stable_frames}
            for item in scenario.stop_when
        ]
        return payload

    def _draft_file(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="yys_step_", suffix=".yaml", dir=path.parent)
        draft = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                yaml.safe_dump(self._payload(path), output, allow_unicode=True, sort_keys=False)
            return draft
        except Exception:
            draft.unlink(missing_ok=True)
            raise

    def _save(self) -> None:
        if not self._is_running() and self._save_silently():
            self.detail_var.set(f"已保存：{self.scenario_path}")

    def _save_silently(self, *, destination: Path | None = None) -> bool:
        if not self._commit_form():
            return False
        draft = None
        try:
            if destination is None:
                value = self.path_var.get().strip()
                if not value:
                    raise ValueError("请选择场景保存路径")
                destination = Path(value)
            path = destination.resolve()
            if path.exists() and path != self.scenario_path:
                if not messagebox.askyesno("覆盖场景", f"文件已存在，是否覆盖？\n{path}", parent=self.root):
                    return False
            draft = self._draft_file(path)
            load_scenario(draft)  # Reject invalid edits before replacing the original.
            os.replace(draft, path)
            self.scenario_path = path
            self.scenario = load_scenario(path)
            self.steps = list(self.scenario.steps)
            self.path_var.set(str(path))
            self._dirty = False
            self.saved_var.set("已保存")
            self._refresh_tree(self._form_index)
            self._clear_missing_scene()
            self._remember_scene()
            return True
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc), parent=self.root)
            return False
        finally:
            if draft is not None:
                draft.unlink(missing_ok=True)

    def _validate(self) -> None:
        if self._is_running() or not self._commit_form():
            return
        draft = None
        try:
            config = load_config(self.config_path)
            draft = self._draft_file(Path(self.path_var.get()).resolve())
            errors = validate_scenario(draft, config)
            if errors:
                messagebox.showwarning("校验未通过", "\n".join(errors), parent=self.root)
                self.detail_var.set("校验未通过，请检查步骤参数和模板图片。")
            else:
                self.detail_var.set("当前编辑内容校验通过，可以运行；校验未改写场景文件。")
                messagebox.showinfo("校验通过", "当前编辑内容和全局配置有效。", parent=self.root)
        except Exception as exc:
            messagebox.showerror("校验失败", str(exc), parent=self.root)
        finally:
            if draft is not None:
                draft.unlink(missing_ok=True)

    def _choose_image(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Images", "*.png *.jpg *.jpeg"), ("All files", "*.*")])
        if path:
            self.form["image"].set(path)
            self._preview_image()

    def _selected_index(self) -> int | None:
        selected = self.tree.selection()
        if not selected:
            return None
        return int(selected[0])

    def _read_form(self) -> ScenarioStep:
        step_type = self._step_type()
        image_value = self.form["image"].get().strip()
        x_value = self.form["x"].get().strip()
        y_value = self.form["y"].get().strip()
        threshold = self.form["threshold"].get().strip()
        image = Path(image_value) if image_value else None
        if image is not None and not image.is_absolute():
            image = (self.scenario_path.parent if self.scenario_path else Path.cwd()) / image
        step = ScenarioStep(
            id=self.form["id"].get().strip(),
            type=step_type,
            image=image if step_type in {"match_and_click", "wait_for_image"} else None,
            threshold=float(threshold) if threshold and step_type in {"match_and_click", "wait_for_image"} else None,
            timeout_seconds=float(self.form["timeout"].get() or 30),
            x=int(x_value) if x_value and step_type == "click_point" else None,
            y=int(y_value) if y_value and step_type == "click_point" else None,
            wait_after_seconds=float(self.form["wait"].get() or 0.5),
            scan_interval_seconds=float(self.form["scan_interval"].get()) if self.form["scan_interval"].get().strip() else None,
            max_attempts=int(self.form["attempts"].get() or 1),
            next_step=self.form["next"].get().strip() or None,
            response_timeout_seconds=float(self.form["response"].get() or 3),
            recover_to=tuple(value.strip() for value in self.form["recover"].get().split(",") if value.strip()),
            requires_action=self.form["requires_action"].get().strip() or None,
        )
        import math

        if not all(math.isfinite(value) and value >= 0 for value in
                   (step.timeout_seconds, step.wait_after_seconds, step.response_timeout_seconds)):
            raise ValueError("等待时间必须是非负有限数值")
        if step.timeout_seconds <= 0:
            raise ValueError("最长等待时间必须大于 0")
        if step.threshold is not None and not 0 < step.threshold <= 1:
            raise ValueError("匹配阈值必须大于 0 且不超过 1")
        if not 1 <= step.max_attempts <= 3:
            raise ValueError("最大尝试次数须为 1 到 3")
        if step_type == "click_point" and (step.x is None or step.y is None):
            raise ValueError("请填写参考坐标 X 和 Y（允许 0）")
        if step_type in {"match_and_click", "wait_for_image"} and step.image is None:
            raise ValueError("请选择模板图片")
        return step

    def _update_step(self) -> None:
        if not self._is_running() and self._commit_form():
            self.detail_var.set("步骤修改已应用；保存或运行场景时写入文件。")

    def _delete_step(self) -> None:
        index = self._selected_index()
        if index is not None:
            if self._is_running() or not messagebox.askyesno("删除步骤", f"删除步骤 {self.steps[index].id}？", parent=self.root):
                return
            self.steps.pop(index)
            self._mark_dirty()
            self._clear_form()
            self._refresh_tree(max(0, index - 1))
            self._remember_scene()

    def _move_step(self, direction: int) -> None:
        if self._is_running() or not self._commit_form():
            return
        index = self._selected_index()
        if index is None:
            return
        target = index + direction
        if 0 <= target < len(self.steps):
            self.steps[index], self.steps[target] = self.steps[target], self.steps[index]
            self._mark_dirty()
            self._refresh_tree(target)

    def _refresh_tree(self, select_index: int | None = None) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for index, step in enumerate(self.steps):
            self.tree.insert("", tk.END, iid=str(index), values=self._step_values(step), tags=("even",) if index % 2 == 0 else ())
        mode = "无顺序匹配" if self.scenario and self.scenario.execution_mode == "match_any" else "顺序执行"
        self.summary_var.set(f"{mode}  ·  {len(self.steps)} 个步骤")
        if select_index is not None and self.steps:
            selected = str(min(select_index, len(self.steps) - 1))
            self.tree.selection_set(selected)
            self.tree.focus(selected)
            self.tree.see(selected)
            self._load_form(int(selected))
        self._refresh_launch_context()

    def _select_step(self, _event: object) -> None:
        if self._loading_form or self._is_running():
            return
        index = self._selected_index()
        if index is None:
            return
        if index == self._form_index:
            return
        if index != self._form_index and not self._commit_form():
            if self._form_index is not None:
                self.tree.selection_set(str(self._form_index))
            return
        self.tree.selection_set(str(index))
        self._load_form(index)
        self._remember_scene()

    def _load_form(self, index: int) -> None:
        self._loading_form = True
        self._form_index = index
        step = self.steps[index]
        self.form["id"].set(step.id)
        self.form["type"].set(TYPE_LABELS.get(step.type, step.type))
        self.form["image"].set(str(step.image or ""))
        self.form["threshold"].set(str(step.threshold) if step.threshold is not None else "")
        self.form["timeout"].set(str(step.timeout_seconds))
        self.form["x"].set(str(step.x) if step.x is not None else "")
        self.form["y"].set(str(step.y) if step.y is not None else "")
        self.form["wait"].set(str(step.wait_after_seconds))
        self.form["scan_interval"].set(str(step.scan_interval_seconds or ""))
        self.form["attempts"].set(str(step.max_attempts))
        self.form["next"].set(step.next_step or "")
        self.form["response"].set(str(step.response_timeout_seconds))
        self.form["recover"].set(",".join(step.recover_to))
        self.form["requires_action"].set(step.requires_action or "")
        self._loading_form = False
        self._form_snapshot = {key: var.get() for key, var in self.form.items()}
        self._sync_field_states()
        self.recognition.select_step(step)
        self._preview_image()

    @staticmethod
    def _step_values(step: ScenarioStep) -> tuple[str, ...]:
        return (
            step.id,
            TYPE_LABELS.get(step.type, step.type),
            step.image.name if step.image else "—",
            f"{step.timeout_seconds:g}",
            f"{step.threshold:g}" if step.threshold is not None else "",
            str(step.x) if step.x is not None else "",
            str(step.y) if step.y is not None else "",
            f"{step.wait_after_seconds:g}",
        )

    @staticmethod
    def _relative_image(image: Path, base_dir: Path) -> str:
        try:
            return os.path.relpath(image, base_dir).replace(os.sep, "/")
        except ValueError:
            return str(image.resolve()).replace(os.sep, "/")

    @staticmethod
    def _step_to_yaml(step: ScenarioStep, base_dir: Path) -> dict[str, object]:
        data: dict[str, object] = {
            "id": step.id,
            "type": step.type,
            "timeout_seconds": step.timeout_seconds,
            "wait_after_seconds": step.wait_after_seconds,
            "max_attempts": step.max_attempts,
            "response_timeout_seconds": step.response_timeout_seconds,
            "recover_to": list(step.recover_to),
        }
        if step.scan_interval_seconds is not None:
            data["scan_interval_seconds"] = step.scan_interval_seconds
        if step.next_step is not None:
            data["next_step"] = step.next_step
        if step.requires_action is not None:
            data["requires_action"] = step.requires_action
        if step.image is not None:
            data["image"] = ScenarioEditor._relative_image(step.image, base_dir)
        if step.threshold is not None:
            data["threshold"] = step.threshold
        if step.x is not None:
            data["x"] = step.x
        if step.y is not None:
            data["y"] = step.y
        return data


def launch_gui(scenario_path: Path | None = None, config_path: Path = Path("config.yaml"), *, dry_run: bool = False,
               window_identity: tuple[int, int] | None = None, restore_recent: bool = False) -> None:
    ScenarioEditor(scenario_path, config_path, dry_run=dry_run, window_identity=window_identity,
                   restore_recent=restore_recent).run()
