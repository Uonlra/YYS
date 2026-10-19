# YYS Desktop Automation MVP

本项目是一个本地桌面自动化辅助程序 MVP：实时截屏，识别指定 UI 图片模板，命中后在受控区域内执行低频、可停止的鼠标点击。

它面向你自己的本地软件辅助操作和测试，不用于绕过网站、游戏、广告平台或任何反自动化检测。

## 功能

- 实时截取屏幕画面
- 使用 OpenCV 模板匹配识别目标图片
- 支持点击区域白名单
- 支持识别阈值、点击冷却时间、最大点击次数
- 鼠标移动时间、点击点偏移可配置
- `Esc` 或 `Ctrl+Shift+Q` 紧急停止
- 日志记录识别结果、点击坐标、点击时间

## 项目结构

```text
YYS/
  README.md
  requirements.txt
  config.example.yaml
  run.py
  assets/
    targets/
      .gitkeep
  logs/
    .gitkeep
  src/
    yys_automation/
      __init__.py
      clicker.py
      config.py
      detector.py
      logging_setup.py
      safety.py
      screen.py
```

## 安装

建议使用虚拟环境：

```powershell
cd D:\Studys\Projects\YYS
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 配置

复制示例配置：

```powershell
Copy-Item config.example.yaml config.yaml
```

把你要识别的按钮或图标截图放到：

```text
assets/targets/
```

然后修改 `config.yaml`：

```yaml
target_image: "assets/targets/button.png"
threshold: 0.86
allowed_region:
  left: 0
  top: 0
  width: 1920
  height: 1080
```

`allowed_region` 是点击白名单区域。程序只截取和点击这个区域内的内容。

## 运行

```powershell
python run.py --config config.yaml
```

运行后：

- 目标图片出现并且匹配度超过阈值时，程序会点击目标中心附近
- 按 `Esc` 或 `Ctrl+Shift+Q` 立即停止
- 日志输出到控制台和 `logs/automation.log`

## 测试建议

1. 先用一个无风险窗口测试，例如记事本、计算器、你自己写的测试页面。
2. 截取一个按钮小图，保存为 `assets/targets/button.png`。
3. 把 `allowed_region` 限制到测试窗口附近，不要先用全屏。
4. 设置较大的冷却时间，例如 `min_click_interval_seconds: 3.0`。
5. 设置较小的最大点击次数，例如 `max_clicks: 3`。
6. 启动程序后把目标按钮显示在白名单区域内。
7. 确认日志中有识别分数、点击坐标、停止原因。

## 后续可扩展

- 增加 OCR 文字识别
- 增加多目标模板
- 增加 GUI 配置面板
- 增加窗口句柄绑定，只识别指定窗口
- 增加 dry-run 模式截图标注预览
