from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import yaml

from src.yys_automation.config import load_config
from src.yys_automation.scenario import STEP_TYPES, Scenario, ScenarioStep, load_scenario, validate_scenario


class ScenarioEditor:
    def __init__(self, scenario_path: Path | None = None, config_path: Path = Path("config.yaml")) -> None:
        self.root = tk.Tk()
        self.root.title("YYS 场景配置")
        self.root.geometry("1050x650")
        self.scenario_path = scenario_path
        self.config_path = config_path
        self.scenario: Scenario | None = None
        self.steps: list[ScenarioStep] = []
        self.process: subprocess.Popen[str] | None = None
        self.process_cleanup_path: Path | None = None
        self._build_ui()
        if scenario_path is not None and scenario_path.exists():
            self._load_file(scenario_path)

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill=tk.X)
        ttk.Label(top, text="场景文件").pack(side=tk.LEFT)
        self.path_var = tk.StringVar(value=str(self.scenario_path or "scenario.yaml"))
        ttk.Entry(top, textvariable=self.path_var, width=75).pack(side=tk.LEFT, padx=6, fill=tk.X, expand=True)
        ttk.Button(top, text="打开", command=self._choose_file).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="加载", command=self._load_from_entry).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="保存", command=self._save).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="校验", command=self._validate).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="测试当前步骤", command=self._test_current_step).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="运行场景", command=self._run_scenario).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="停止", command=self._stop_process).pack(side=tk.LEFT, padx=2)
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(top, textvariable=self.status_var, width=16).pack(side=tk.LEFT, padx=8)

        body = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        left = ttk.Frame(body, padding=4)
        body.add(left, weight=3)
        columns = ("id", "type", "image", "timeout", "threshold", "x", "y", "wait")
        self.tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="browse")
        headers = {
            "id": "步骤",
            "type": "类型",
            "image": "模板",
            "timeout": "超时",
            "threshold": "阈值",
            "x": "X",
            "y": "Y",
            "wait": "执行后等待",
        }
        widths = {"id": 110, "type": 120, "image": 220, "timeout": 70, "threshold": 70, "x": 55, "y": 55, "wait": 90}
        for column in columns:
            self.tree.heading(column, text=headers[column])
            self.tree.column(column, width=widths[column], anchor=tk.W)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._select_step)

        tree_buttons = ttk.Frame(left, padding=(0, 6, 0, 0))
        tree_buttons.pack(fill=tk.X)
        ttk.Button(tree_buttons, text="添加", command=self._add_step).pack(side=tk.LEFT, padx=2)
        ttk.Button(tree_buttons, text="更新", command=self._update_step).pack(side=tk.LEFT, padx=2)
        ttk.Button(tree_buttons, text="删除", command=self._delete_step).pack(side=tk.LEFT, padx=2)
        ttk.Button(tree_buttons, text="上移", command=lambda: self._move_step(-1)).pack(side=tk.LEFT, padx=2)
        ttk.Button(tree_buttons, text="下移", command=lambda: self._move_step(1)).pack(side=tk.LEFT, padx=2)

        right = ttk.Frame(body, padding=12)
        body.add(right, weight=2)
        self.form: dict[str, tk.StringVar] = {}
        fields = [
            ("id", "步骤 ID"),
            ("type", "类型"),
            ("image", "模板路径"),
            ("threshold", "匹配阈值"),
            ("timeout", "超时秒数"),
            ("x", "参考 X"),
            ("y", "参考 Y"),
            ("wait", "执行后等待"),
            ("attempts", "最多点击次数"),
            ("next", "预期下一步骤"),
            ("response", "点击响应等待"),
            ("recover", "恢复步骤(逗号)"),
            ("requires_action", "requires_action"),
        ]
        for key, label in fields:
            row = ttk.Frame(right)
            row.pack(fill=tk.X, pady=4)
            ttk.Label(row, text=label, width=12).pack(side=tk.LEFT)
            var = tk.StringVar()
            self.form[key] = var
            if key == "type":
                ttk.Combobox(row, textvariable=var, values=sorted(STEP_TYPES), state="readonly").pack(side=tk.LEFT, fill=tk.X, expand=True)
            else:
                ttk.Entry(row, textvariable=var).pack(side=tk.LEFT, fill=tk.X, expand=True)
            if key == "image":
                ttk.Button(row, text="选择", command=self._choose_image).pack(side=tk.LEFT, padx=3)

        ttk.Label(
            right,
            text="match_and_click 匹配并点击；wait_for_image 只等待模板；click_point 使用参考坐标；wait 使用超时秒数。",
            wraplength=300,
        ).pack(anchor=tk.W, pady=(16, 0))

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
            with temp_path.open("w", encoding="utf-8") as file:
                yaml.safe_dump(payload, file, allow_unicode=True, sort_keys=False)
        except Exception as exc:
            temp_path.unlink(missing_ok=True)
            messagebox.showerror("步骤测试准备失败", str(exc))
            return
        self._start_process(temp_path, cleanup_path=temp_path)

    def _start_process(self, scenario_path: Path | None, cleanup_path: Path | None = None) -> None:
        if scenario_path is None:
            messagebox.showwarning("未加载场景", "请先加载或保存一个场景文件")
            return
        command = [
            sys.executable,
            str(Path(__file__).resolve().parents[2] / "run.py"),
            "--config",
            str(self.config_path.resolve()),
            "--scenario",
            str(scenario_path.resolve()),
        ]
        try:
            self.process = subprocess.Popen(command, cwd=str(Path(__file__).resolve().parents[2]))
        except OSError as exc:
            if cleanup_path is not None:
                cleanup_path.unlink(missing_ok=True)
            messagebox.showerror("启动失败", str(exc))
            return
        self.process_cleanup_path = cleanup_path
        self.status_var.set("运行中")
        self._poll_process(cleanup_path)

    def _poll_process(self, cleanup_path: Path | None = None) -> None:
        if self.process is None:
            return
        code = self.process.poll()
        if code is None:
            self.root.after(300, lambda: self._poll_process(cleanup_path))
            return
        self.status_var.set(f"已结束 ({code})")
        self.process = None
        self._cleanup_process_file(cleanup_path)

    def _stop_process(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
            self.status_var.set("已停止")
        self.process = None
        self._cleanup_process_file(self.process_cleanup_path)

    def _cleanup_process_file(self, path: Path | None) -> None:
        if path is not None:
            path.unlink(missing_ok=True)
        if path == self.process_cleanup_path:
            self.process_cleanup_path = None

    def _on_close(self) -> None:
        self._stop_process()
        self.root.destroy()

    def _choose_file(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("YAML", "*.yaml *.yml"), ("All files", "*.*")])
        if path:
            self.path_var.set(path)

    def _load_from_entry(self) -> None:
        self._load_file(Path(self.path_var.get()))

    def _load_file(self, path: Path) -> None:
        try:
            scenario = load_scenario(path)
        except Exception as exc:
            messagebox.showerror("加载失败", str(exc))
            return
        self.scenario_path = path
        self.path_var.set(str(path))
        self.scenario = scenario
        self.steps = list(scenario.steps)
        self._refresh_tree()

    def _save(self) -> None:
        path = Path(self.path_var.get())
        if not path.is_absolute():
            path = Path.cwd() / path
        try:
            payload = {
                "name": self.scenario.name if self.scenario else path.stem,
                "execution_mode": self.scenario.execution_mode if self.scenario else "sequential",
                "input_backend": self.scenario.input_backend if self.scenario else "physical_mouse",
                **({"consecutive_miss_limit": self.scenario.consecutive_miss_limit} if self.scenario and self.scenario.consecutive_miss_limit is not None else {}),
                **({"no_target_timeout_seconds": self.scenario.no_target_timeout_seconds} if self.scenario and self.scenario.no_target_timeout_seconds is not None else {}),
                **({"match_any_click_interval_seconds": self.scenario.match_any_click_interval_seconds} if self.scenario and self.scenario.match_any_click_interval_seconds is not None else {}),
                "max_retries": self.scenario.max_retries if self.scenario else 3,
                "retry_after_clicks": self.scenario.retry_after_clicks if self.scenario else False,
                "repeat_count": self.scenario.repeat_count if self.scenario else 1,
                "max_cycles": self.scenario.max_cycles if self.scenario else 800,
                "recovery_scans": self.scenario.recovery_scans if self.scenario else 0,
                "recovery_interval_seconds": self.scenario.recovery_interval_seconds if self.scenario else 1,
                "stable_frames": self.scenario.stable_frames if self.scenario else 1,
                **({"max_clicks": self.scenario.max_clicks} if self.scenario and self.scenario.max_clicks is not None else {}),
                "steps": [self._step_to_yaml(step, path.parent) for step in self.steps],
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8") as file:
                yaml.safe_dump(payload, file, allow_unicode=True, sort_keys=False)
            self.scenario_path = path
            self.scenario = load_scenario(path)
            messagebox.showinfo("保存完成", str(path))
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))

    def _save_silently(self) -> bool:
        path = Path(self.path_var.get())
        if not path.is_absolute():
            path = Path.cwd() / path
        try:
            payload = {
                "name": self.scenario.name if self.scenario else path.stem,
                "execution_mode": self.scenario.execution_mode if self.scenario else "sequential",
                "input_backend": self.scenario.input_backend if self.scenario else "physical_mouse",
                **({"consecutive_miss_limit": self.scenario.consecutive_miss_limit} if self.scenario and self.scenario.consecutive_miss_limit is not None else {}),
                **({"no_target_timeout_seconds": self.scenario.no_target_timeout_seconds} if self.scenario and self.scenario.no_target_timeout_seconds is not None else {}),
                **({"match_any_click_interval_seconds": self.scenario.match_any_click_interval_seconds} if self.scenario and self.scenario.match_any_click_interval_seconds is not None else {}),
                "max_retries": self.scenario.max_retries if self.scenario else 3,
                "retry_after_clicks": self.scenario.retry_after_clicks if self.scenario else False,
                "repeat_count": self.scenario.repeat_count if self.scenario else 1,
                "max_cycles": self.scenario.max_cycles if self.scenario else 800,
                "recovery_scans": self.scenario.recovery_scans if self.scenario else 0,
                "recovery_interval_seconds": self.scenario.recovery_interval_seconds if self.scenario else 1,
                "stable_frames": self.scenario.stable_frames if self.scenario else 1,
                **({"max_clicks": self.scenario.max_clicks} if self.scenario and self.scenario.max_clicks is not None else {}),
                "steps": [self._step_to_yaml(step, path.parent) for step in self.steps],
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8") as file:
                yaml.safe_dump(payload, file, allow_unicode=True, sort_keys=False)
            self.scenario_path = path
            self.scenario = load_scenario(path)
            return True
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))
            return False

    def _validate(self) -> None:
        path = Path(self.path_var.get())
        try:
            config = load_config(self.config_path)
        except Exception as exc:
            messagebox.showwarning("校验结果", f"配置无效：{exc}")
            return
        errors = validate_scenario(path, config)
        if errors:
            messagebox.showwarning("校验结果", "\n".join(errors))
        else:
            messagebox.showinfo("校验结果", "场景配置有效")

    def _choose_image(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Images", "*.png *.jpg *.jpeg"), ("All files", "*.*")])
        if path:
            self.form["image"].set(path)

    def _selected_index(self) -> int | None:
        selected = self.tree.selection()
        if not selected:
            return None
        return int(selected[0])

    def _read_form(self) -> ScenarioStep:
        step_type = self.form["type"].get().strip()
        image_value = self.form["image"].get().strip()
        x_value = self.form["x"].get().strip()
        y_value = self.form["y"].get().strip()
        return ScenarioStep(
            id=self.form["id"].get().strip(),
            type=step_type,
            image=Path(image_value) if image_value else None,
            threshold=float(self.form["threshold"].get() or 0.86) if step_type in {"match_and_click", "wait_for_image"} else None,
            timeout_seconds=float(self.form["timeout"].get() or 30),
            x=int(x_value) if x_value else None,
            y=int(y_value) if y_value else None,
            wait_after_seconds=float(self.form["wait"].get() or 0.5),
            max_attempts=int(self.form["attempts"].get() or 1),
            next_step=self.form["next"].get().strip() or None,
            response_timeout_seconds=float(self.form["response"].get() or 3),
            recover_to=tuple(value.strip() for value in self.form["recover"].get().split(",") if value.strip()),
            requires_action=self.form["requires_action"].get().strip() or None,
        )

    def _add_step(self) -> None:
        try:
            step = self._read_form()
            if not step.id:
                raise ValueError("步骤 ID 不能为空")
            self.steps.append(step)
            self._refresh_tree()
        except Exception as exc:
            messagebox.showerror("步骤无效", str(exc))

    def _update_step(self) -> None:
        index = self._selected_index()
        if index is None:
            messagebox.showwarning("未选择步骤", "请先选择一个步骤")
            return
        try:
            self.steps[index] = self._read_form()
            self._refresh_tree(index)
        except Exception as exc:
            messagebox.showerror("步骤无效", str(exc))

    def _delete_step(self) -> None:
        index = self._selected_index()
        if index is not None:
            self.steps.pop(index)
            self._refresh_tree(max(0, index - 1))

    def _move_step(self, direction: int) -> None:
        index = self._selected_index()
        if index is None:
            return
        target = index + direction
        if 0 <= target < len(self.steps):
            self.steps[index], self.steps[target] = self.steps[target], self.steps[index]
            self._refresh_tree(target)

    def _refresh_tree(self, select_index: int | None = None) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for index, step in enumerate(self.steps):
            self.tree.insert("", tk.END, iid=str(index), values=self._step_values(step))
        if select_index is not None and self.steps:
            selected = str(min(select_index, len(self.steps) - 1))
            self.tree.selection_set(selected)
            self.tree.focus(selected)

    def _select_step(self, _event: object) -> None:
        index = self._selected_index()
        if index is None:
            return
        step = self.steps[index]
        self.form["id"].set(step.id)
        self.form["type"].set(step.type)
        self.form["image"].set(str(step.image or ""))
        self.form["threshold"].set(str(step.threshold or 0.86))
        self.form["timeout"].set(str(step.timeout_seconds))
        self.form["x"].set(str(step.x or ""))
        self.form["y"].set(str(step.y or ""))
        self.form["wait"].set(str(step.wait_after_seconds))
        self.form["attempts"].set(str(step.max_attempts))
        self.form["next"].set(step.next_step or "")
        self.form["response"].set(str(step.response_timeout_seconds))
        self.form["recover"].set(",".join(step.recover_to))
        self.form["requires_action"].set(step.requires_action or "")

    @staticmethod
    def _step_values(step: ScenarioStep) -> tuple[str, ...]:
        return (
            step.id,
            step.type,
            str(step.image or ""),
            f"{step.timeout_seconds:g}",
            f"{step.threshold:g}" if step.threshold is not None else "",
            str(step.x or ""),
            str(step.y or ""),
            f"{step.wait_after_seconds:g}",
        )

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
        if step.next_step is not None:
            data["next_step"] = step.next_step
        if step.requires_action is not None:
            data["requires_action"] = step.requires_action
        if step.image is not None:
            image_path = Path(os.path.relpath(step.image, base_dir))
            data["image"] = str(image_path).replace(os.sep, "/")
        if step.threshold is not None:
            data["threshold"] = step.threshold
        if step.x is not None:
            data["x"] = step.x
        if step.y is not None:
            data["y"] = step.y
        return data


def launch_gui(scenario_path: Path | None = None, config_path: Path = Path("config.yaml")) -> None:
    ScenarioEditor(scenario_path, config_path).run()
