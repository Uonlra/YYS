"""Present the recorded run state and the exact frame used for recognition."""
from __future__ import annotations

import base64
from pathlib import Path
import tkinter as tk
from tkinter import ttk

import cv2
import numpy as np


STOP_REASONS = {
    "completed": "场景已完成",
    "budget": "点击预算已用尽或不足以开始下一轮",
    "miss_limit": "连续未命中达到上限",
    "no_target_timeout": "等待目标超时",
    "timeout": "等待当前步骤或画面切换超时",
    "window_missing": "找不到目标窗口",
    "capture_error": "无法捕获目标窗口",
    "bounds": "点击位置超出允许区域",
    "attempts_exhausted": "点击尝试已达上限，未确认画面切换",
    "click_error": "点击发送失败",
    "failsafe": "鼠标安全保护已触发",
    "ambiguous": "同时识别到多个互斥画面",
    "phase": "当前画面不符合场景阶段",
    "runtime_limit": "达到运行时长上限",
    "failure_limit": "达到连续失败上限",
    "user_stopped": "已手动停止",
    "error": "执行过程中出错",
    "cycle_failed": "本轮执行未完成",
}

ACTIVITIES = {
    "starting": "正在启动",
    "searching": "正在查找目标",
    "no_match": "本帧未匹配到达标目标",
    "recognized": "已识别到目标",
    "cooldown": "点击间隔等待中",
    "post_click": "动作后等待",
    "transition": "等待画面切换",
    "recovering": "正在检查可恢复画面",
    "waiting": "定时等待中",
    "stopping": "正在停止",
    "window_missing": "未找到窗口，正在重试",
    "capture_error": "截图失败，正在重试",
    "click_error": "本次点击发送失败",
}


def stop_label(reason: str | None) -> str:
    if reason and reason.startswith("stop_image:"):
        return f"识别到停止图片 {reason.partition(':')[2]}"
    return STOP_REASONS.get(reason, reason or "任务已退出，请查看运行日志")


def run_progress(status: dict) -> str:
    activity = status.get("activity")
    if activity == "confirming":
        message = f"已识别，确认帧 {status.get('confirmed_frames', 0)}/{status.get('required_frames', '—')}"
    else:
        message = ACTIVITIES.get(activity, "正在执行")
    parts = [message]
    if activity == "transition" and status.get("expected_target"):
        parts.append(f"预期 {status['expected_target']}")
    if activity in {"confirming", "recognized"} and status.get("preferred_target"):
        parts.append(f"首选 {status['preferred_target']}")
    if activity in {"confirming", "recognized", "no_match"}:
        score = status.get("last_match_score")
        if score is None:
            score = status.get("best_score")
        threshold = status.get("score_threshold")
        if isinstance(score, (int, float)) and isinstance(threshold, (int, float)):
            parts.append(f"{status.get('score_target', '')} {score:.3f} / {threshold:.3f}".strip())
    if status.get("last_action_target"):
        outcome = {"sent": "已发送", "simulated": "试运行", "failed": "发送失败"}
        result = outcome.get(status.get("last_action_result"), "点击")
        parts.append(f"最近动作 {status['last_action_target']}（{result}）")
    return "  ·  ".join(parts)


def load_diagnostic_image(directory: Path, diagnostic: dict) -> np.ndarray | None:
    name = diagnostic.get("screenshot")
    if (not isinstance(name, str) or Path(name).name != name or not name.endswith(".png")
            or not name.startswith(("failure_", "stop_"))):
        return None
    try:
        path = (directory / name).resolve()
        if path.parent != directory.resolve():
            return None
        source = np.fromfile(path, dtype=np.uint8)
        if not source.size:
            return None
        return cv2.imdecode(source, cv2.IMREAD_COLOR)
    except (OSError, ValueError, cv2.error):
        return None


def draw_diagnostic_frame(canvas, frame: np.ndarray, diagnostic: dict, canvas_width: int, canvas_height: int) -> None:
    height, width = frame.shape[:2]
    scale = min(canvas_width / width, canvas_height / height, 1)
    w, h = max(1, round(width * scale)), max(1, round(height * scale))
    left, top = (canvas_width - w) // 2, (canvas_height - h) // 2
    resized = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode(".png", resized)
    if not ok:
        return
    canvas.photo = tk.PhotoImage(data=base64.b64encode(encoded).decode("ascii"), master=canvas)
    canvas.delete("all")
    canvas.create_image(left, top, anchor="nw", image=canvas.photo)

    def rectangle(box, color, dash=()):
        x, y = box["left"], box["top"]
        canvas.create_rectangle(left + x * w / width, top + y * h / height,
                                left + (x + box["width"]) * w / width,
                                top + (y + box["height"]) * h / height,
                                outline=color, width=2, dash=dash)

    if diagnostic.get("allowed_region"):
        rectangle(diagnostic["allowed_region"], "#65afff")
    for item in diagnostic.get("observations", []):
        if item.get("box"):
            rectangle(item["box"], "#52da89" if item["matched"] else "#ffca57",
                      () if item["matched"] else (4, 3))
    if diagnostic.get("screen_point") is not None:
        sx, sy = diagnostic["screen_point"]
        ox, oy = diagnostic["origin"]
        dx, dy = diagnostic["scale"]
        ref_x, ref_y = (sx - ox) / dx, (sy - oy) / dy
        if 0 <= ref_x < width and 0 <= ref_y < height:
            x, y = left + ref_x * w / width, top + ref_y * h / height
            canvas.create_line(x - 7, y, x + 7, y, fill="#ff696f", width=2)
            canvas.create_line(x, y - 7, x, y + 7, fill="#ff696f", width=2)


def show_diagnostic(parent, status: dict, directory: Path, *, on_recheck=None, on_settings=None,
                    settings_label="调整设置", on_tune=None) -> None:
    dialog = tk.Toplevel(parent)
    dialog.title("运行诊断")
    dialog.geometry("980x690")
    dialog.minsize(700, 520)
    dialog.transient(parent)
    dialog.grab_set()
    dialog.bind("<Escape>", lambda _event: dialog.destroy())
    body = ttk.Frame(dialog, padding=18)
    body.pack(fill=tk.BOTH, expand=True)
    body.columnconfigure(0, weight=1)
    body.rowconfigure(2, weight=1)
    reason = status.get("stop_reason")
    diagnostic = status.get("diagnostic") or {}
    ttk.Label(body, text=stop_label(reason), style="Title.TLabel").grid(row=0, column=0, sticky="w")
    step = status.get("current_step") or "—"
    limit = status.get("max_clicks")
    headline = f"{status.get('scenario', '当前任务')}  ·  步骤 {step}  ·  点击 {status.get('clicks', 0)} / {limit if limit is not None else '不限'}"
    if diagnostic.get("frame_step"):
        headline += f"  ·  最后一帧来自 {diagnostic['frame_step']}"
    ttk.Label(body, text=headline, style="Muted.TLabel", wraplength=900).grid(row=1, column=0, sticky="w", pady=(8, 12))

    canvas = tk.Canvas(body, background="#172238", highlightthickness=0, height=160)
    canvas.grid(row=2, column=0, sticky="nsew")
    frame = load_diagnostic_image(directory, diagnostic)
    if frame is None:
        caption = ttk.Label(body, text="此任务没有可读取的现场截图。", style="Muted.TLabel")
        caption.grid(row=2, column=0, pady=12)
    else:
        canvas.bind("<Configure>", lambda event: draw_diagnostic_frame(canvas, frame, diagnostic, event.width, event.height))

    table = ttk.Frame(body)
    table.grid(row=3, column=0, sticky="ew", pady=(10, 4))
    table.columnconfigure(0, weight=1)
    targets = ttk.Treeview(table, columns=("id", "score", "threshold", "result"), show="headings", height=4)
    for key, title in (("id", "模板"), ("score", "匹配分数"), ("threshold", "阈值"), ("result", "本帧结果")):
        targets.heading(key, text=title)
        targets.column(key, width=140)
    for item in diagnostic.get("observations", []):
        result = "命中" if item["matched"] else "低于阈值" if item.get("box") else "未找到候选框"
        score = f"{item['score']:.3f}" if item.get("box") else "—"
        targets.insert("", "end", values=(item["id"], score, f"{item['threshold']:.3f}", result))
    targets.grid(row=0, column=0, sticky="ew")
    scroll = ttk.Scrollbar(table, orient=tk.VERTICAL, command=targets.yview)
    scroll.grid(row=0, column=1, sticky="ns")
    targets.configure(yscrollcommand=scroll.set)
    legend = "蓝框：白名单   绿框：命中   黄虚线：未达阈值   红十字：尝试点击的位置"
    if diagnostic.get("screen_point") is not None:
        x, y = diagnostic["screen_point"]
        legend += f"   屏幕坐标 ({x}, {y})"
    ttk.Label(body, text=legend if frame is not None else run_progress(status),
              style="Muted.TLabel", wraplength=900).grid(row=4, column=0, sticky="w", pady=(0, 8))
    footer = ttk.Frame(body)
    footer.grid(row=5, column=0, sticky="ew")

    def open_next(action):
        dialog.destroy()
        action()

    ttk.Button(footer, text="关闭", command=dialog.destroy).pack(side=tk.RIGHT)
    if on_recheck:
        ttk.Button(footer, text="重新检查", style="Accent.TButton",
                   command=lambda: open_next(on_recheck)).pack(side=tk.RIGHT, padx=8)
    if on_tune and frame is not None:
        ttk.Button(footer, text="用此帧调参", command=lambda: open_next(on_tune)).pack(side=tk.RIGHT)
    if on_settings:
        ttk.Button(footer, text=settings_label, command=lambda: open_next(on_settings)).pack(side=tk.RIGHT)
