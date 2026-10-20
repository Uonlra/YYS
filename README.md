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
- 场景默认在发生点击后不自动从头重试，避免重复执行有副作用的操作

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
      config_gui.py
      detector.py
      logging_setup.py
      scenario.py
      safety.py
      screen.py
      window.py
      window_capture.py
      window_clicker.py
      window_screen.py
      workflow.py
  tests/
    test_workflow.py
```

窗口模式下，`allowed_region` 使用窗口参考坐标；桌面模式下使用屏幕绝对坐标。场景模式要求 `capture_mode: window`。场景中的模板点击和坐标点击都会经过该白名单检查，并受到场景点击预算与 `min_click_interval_seconds` 限制。

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

`allowed_region` 是点击白名单区域。桌面模式只截取该区域；窗口模式截取整个客户区，但只允许点击映射后的白名单区域。

## 运行

```powershell
python run.py --config config.yaml
```

场景模式：

```powershell
python run.py --config config.yaml --validate-scenario scenario.example.yaml
python run.py --config config.yaml --scenario scenario.example.yaml
python run.py --config config.yaml --gui scenario.example.yaml
```

场景配置中的 `max_retries` 只会重试尚未发生点击的失败尝试。只有明确设置 `retry_after_clicks: true`，才会允许点击后的场景从第一步重试；这可能重复已经执行成功的操作，应只用于幂等场景。

启动场景前会预检 YAML 结构、步骤 ID、图片可解码性，以及坐标点击是否位于参考窗口和点击白名单内。配置中布尔值必须使用 YAML 的 `true` / `false`，时间和阈值必须是有限数值。

普通识别循环使用 `config.yaml` 的 `max_clicks`。场景可在 YAML 中独立配置 `max_clicks`：`auto` 按点击步骤数和轮数计算预算；整数设置该场景的明确上限；省略时使用全局配置。dry-run 中也会按计划点击计数。`startup_delay_seconds` 在普通识别循环开始识别前等待，也支持紧急停止。`max_retries` 表示每轮场景最多尝试次数，不是额外重试次数。

## 单次领奖流程

`YYSscript/yuhun/scenario.reward-once.yaml` 执行一次 `start -> confirm -> reward -> start`：前三步匹配并点击，最后只等待开始界面重新出现，然后结束，不点击下一轮开始。它不会执行旧示例中的 victory 或重复 confirm 步骤。

```powershell
.\.venv\Scripts\python.exe -B run.py --config config.yaml --validate-scenario YYSscript/yuhun/scenario.reward-once.yaml
.\.venv\Scripts\python.exe -B run.py --config config.yaml --scenario YYSscript/yuhun/scenario.reward-once.yaml
```

运行前保持目标窗口打开，处于 start 界面；配置使用 `capture_mode: window`、`dry_run: false`。场景自动设置三次点击预算，不需要为此修改全局 `max_clicks`。confirm 最多等待 180 秒，reward 和返回 start 各等待 60 秒，可按实际流程调整。任一步超时或失败都会停止，本流程不自动重试。

场景点击使用窗口消息，可能与已验证的普通鼠标点击效果不同；首次请观察按钮是否响应。看到 `Scenario completed: reward_once` 表示已发出三次点击并重新识别到 start，不代表已校验实际奖励数量。dry-run 不会推动界面变化，因此从 start 界面运行通常会在等待 confirm 时超时。

## 御魂重复流程

御魂场景集中在 `YYSscript/yuhun/`：

| 文件 | 用途 |
| --- | --- |
| `scenario.start-only.yaml` | 单次开始按钮测试 |
| `scenario.reward-once.yaml` | 一次完整领奖流程 |
| `scenario.reward-repeat.yaml` | 重复相同完整流程，最多 800 轮 |

```powershell
.\.venv\Scripts\python.exe -B run.py --config config.yaml --validate-scenario YYSscript/yuhun/scenario.reward-repeat.yaml
.\.venv\Scripts\python.exe -B run.py --config config.yaml --scenario YYSscript/yuhun/scenario.reward-repeat.yaml
```

重复版每轮确认返回 start 后才进入下一轮。按 Esc 或 Ctrl+Shift+Q 停止；任一步失败立即退出，不忽略错误继续刷。日志记录当前轮数、完成轮数和累计点击数。

```yaml
repeat_count: null
max_cycles: 800
```

`repeat_count: null` 表示重复至 `max_cycles` 安全上限或提前停止。未来定次运行只需将 `repeat_count` 改为 1 到 `max_cycles` 之间的整数，例如 `repeat_count: 10`。未写 `repeat_count` 的旧场景仍只执行一次。`max_retries` 仍是每轮的最大尝试次数，与轮数无关。

重复流程设置 `max_clicks: auto`，预算为每轮点击步骤数乘以计划轮数，不需要更改全局配置。本流程每轮点击三次，800 轮的自动预算为 2400。预算在所有轮次之间累计，不会每轮重置；若剩余额度不足以完成下一整轮，程序会在新一轮开始前停止。首次建议将 `repeat_count` 临时设为 2 验证两轮，再恢复 `null`。dry-run 界面不会推进状态，实际重复流程要观察游戏对每次窗口消息点击的响应。

## 场景点击预算

| 场景字段 | 有效预算 | 与全局配置的关系 |
| --- | --- | --- |
| 不写 `max_clicks` | `config.yaml` 中的值 | 沿用已有场景行为，全局 `null` 表示不限点击数 |
| `max_clicks: auto` | 每轮点击步骤数乘以计划轮数 | 覆盖全局默认值 |
| `max_clicks: 500` | 本场景最多 500 次点击 | 覆盖全局默认值 |
| `max_clicks: 0` | 禁止点击，仍可执行等待与观察步骤 | 覆盖全局默认值 |

场景里的 `null`、负数、布尔值和数字字符串均不接受；要继承全局设置请省略字段。全局值是默认值，不是与场景预算取最小值的硬上限。启动日志和 `--validate-scenario` 会显示每轮点击数、计划轮数、有效预算和来源。

例如，每轮五次点击、计划执行 100 轮的不同任务，只需设置：

```yaml
repeat_count: 100
max_cycles: 800
max_clicks: auto
```

自动预算为 500；`wait` 和 `wait_for_image` 不计入点击数。点击发送失败可能已产生副作用，因此仍会消耗额度。重试共享原预算，不额外增加额度；允许点击后重试的任务如需额外额度，请显式设置整数上限。自动计算适用于当前每个点击步骤最多发送一次的顺序流程；后续引入分支或步骤内多次点击时，需要同时扩展预算计算和相应测试。

## 多流程约定

每个流程保存在独立的 `scenario.<flow-name>.yaml` 中，按用途放在 `YYSscript/<category>/` 下，通过 `--scenario PATH` 或 GUI 打开文件切换，共用 `config.yaml` 中的窗口和安全设置；不要为了新增流程复制执行器代码。模板路径相对所在场景文件解析，御魂场景使用 `../../assets/targets/`。根目录的 `scenario.example.yaml` 保留为通用示例。

目前支持的通用步骤：

| 类型 | 行为 | 主要字段 |
| --- | --- | --- |
| `match_and_click` | 等待模板出现并点击一次 | `image`、`threshold`、`timeout_seconds` |
| `wait_for_image` | 只等待模板出现，不点击、不占点击额度 | `image`、`threshold`、`timeout_seconds` |
| `click_point` | 点击窗口参考坐标 | `x`、`y`、`timeout_seconds` |
| `wait` | 固定等待 | `timeout_seconds` |

所有步骤都可使用 `wait_after_seconds`。同一流程中的步骤 ID 应唯一，优先使用模板点击和界面确认，而不是固定坐标。循环和场景级点击预算适用于所有场景，GUI 保存已有场景时会保留这些参数，测试当前步骤仍只执行一次。后续有实际需求时，再扩展步骤识别区域、连续多帧确认或分支，不把业务流程写死在 Python 中。

## 测试

测试不需要启动目标窗口，使用模拟画面验证场景点击的坐标映射、白名单、点击上限和重试策略：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
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
- 完善已有场景 GUI 的配置体验
- 支持固定窗口句柄，避免同名窗口切换
- 增加 dry-run 模式截图标注预览
