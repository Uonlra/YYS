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

未配置状态确认的旧场景可用 `max_retries` 控制整轮尝试；只有明确设置 `retry_after_clicks: true` 才允许点击后从第一步重试。配置了 `next_step` 或恢复路径的场景采用下述步骤级有限尝试，失败后不整轮重放，避免绕过步骤尝试上限。

启动场景前会预检 YAML 结构、步骤 ID、图片可解码性，以及坐标点击是否位于参考窗口和点击白名单内。配置中布尔值必须使用 YAML 的 `true` / `false`，时间和阈值必须是有限数值。

普通识别循环使用 `config.yaml` 的 `max_clicks`。场景可在 YAML 中独立配置 `max_clicks`：`auto` 按各点击步骤的最大尝试次数之和乘以轮数计算预算；整数设置该场景的明确上限；省略时使用全局配置。dry-run 中也会按计划点击计数。`startup_delay_seconds` 在普通识别循环开始识别前等待，也支持紧急停止。`max_retries` 表示每轮场景最多尝试次数，不是额外重试次数。

## 单次领奖流程

`YYSscript/yuhun/scenario.reward-once.yaml` 执行一次 `start -> confirm -> reward -> start`：前三步匹配并点击，最后只等待开始界面重新出现，然后结束，不点击下一轮开始。它不会执行旧示例中的 victory 或重复 confirm 步骤。

```powershell
.\.venv\Scripts\python.exe -B run.py --config config.yaml --validate-scenario YYSscript/yuhun/scenario.reward-once.yaml
.\.venv\Scripts\python.exe -B run.py --config config.yaml --scenario YYSscript/yuhun/scenario.reward-once.yaml
```

运行前保持目标窗口打开，处于 start 界面；配置使用 `capture_mode: window`、`dry_run: false`。正常执行点击三次，每个动作最多尝试三次，因此自动预算预留九次，不需要修改全局 `max_clicks`。点击 start 后最多等待 confirm 180 秒，confirm 后等待 reward 60 秒，reward 后等待 start 60 秒；可按实际流程调整。用尽步骤尝试和恢复扫描仍无法确认状态才停止，不从头重放。

场景点击使用窗口消息，可能与已验证的普通鼠标点击效果不同；首次请观察按钮是否响应。看到 `Scenario completed: reward_once` 表示流程确认回到 start；存在重试或状态恢复时，实际点击数可能不同，不代表校验了奖励数量。dry-run 不会推动界面变化，可能反复模拟同一按钮，最终耗尽尝试退出。

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

重复版每轮确认返回 start 后才进入下一轮。按 Esc 或 Ctrl+Shift+Q 停止；允许的步骤尝试和恢复仍失败后退出。越界、预算不足、状态冲突或鼠标 failsafe 立即停止，不进入恢复。日志记录当前轮数、完成轮数和累计点击数。

```yaml
repeat_count: null
max_cycles: 800
```

`repeat_count: null` 表示重复至 `max_cycles` 安全上限或提前停止。未来定次运行只需将 `repeat_count` 改为 1 到 `max_cycles` 之间的整数，例如 `repeat_count: 10`。未写 `repeat_count` 的旧场景仍只执行一次。`max_retries` 仍是每轮的最大尝试次数，与轮数无关。

重复流程设置 `max_clicks: auto`，按每轮最大九次点击尝试计算，800 轮预留 7200 次；正常每步一次成功仍只点击 2400 次。预算跨轮累计，开始新一轮前必须足够覆盖该轮全部允许的点击尝试。首次建议将 `repeat_count` 临时设为 2 验证两轮，再恢复 `null`。

## 场景点击预算

| 场景字段 | 有效预算 | 与全局配置的关系 |
| --- | --- | --- |
| 不写 `max_clicks` | `config.yaml` 中的值 | 沿用已有场景行为，全局 `null` 表示不限点击数 |
| `max_clicks: auto` | 每轮点击步骤的 `max_attempts` 之和乘以计划轮数 | 覆盖全局默认值 |
| `max_clicks: 500` | 本场景最多 500 次点击 | 覆盖全局默认值 |
| `max_clicks: 0` | 禁止点击，仍可执行等待与观察步骤 | 覆盖全局默认值 |

场景里的 `null`、负数、布尔值和数字字符串均不接受；要继承全局设置请省略字段。全局值是默认值，不是与场景预算取最小值的硬上限。启动日志和 `--validate-scenario` 会显示每轮点击数、计划轮数、有效预算和来源。

例如，每轮五次点击、计划执行 100 轮的不同任务，只需设置：

```yaml
repeat_count: 100
max_cycles: 800
max_clicks: auto
```

若每步默认只尝试一次，自动预算为 500；若五个动作都设为最多三次，则预算为 1500。`wait` 和 `wait_for_image` 不计入点击数。点击发送失败可能已产生副作用，仍消耗额度；恢复扫描不点击，不消耗额度。旧式整轮重试不额外增加预算。后续引入分支或其他步骤内多次点击时，应同步扩展预算计算和测试。

## 点击确认与恢复

这些能力由每个场景独立声明，未配置的旧步骤仍只点击一次。御魂单次版和重复版均已启用：

```yaml
recovery_scans: 2
recovery_interval_seconds: 1.0
steps:
  - id: start
    type: match_and_click
    image: ../../assets/targets/start.png
    max_attempts: 3
    next_step: confirm
    response_timeout_seconds: 3
    recover_to: [confirm, reward]
    timeout_seconds: 30
```

此片段需要接上 confirm、reward 等步骤；`next_step` 必须是紧接着的下一步骤 ID。`recover_to` 只能引用后续的模板点击或图片等待步骤，不能回到前序步骤、不能恢复到固定坐标点击。步骤 ID 改名、删除或调序后需要重新校验。

执行规则：

1. 等待当前按钮，或确认预期下一状态已经出现；匹配冲突立即停止。
2. 当前按钮匹配后点击，最多 `max_attempts` 次（包含首次，范围 1 到 3）。
3. 点击后持续观察，若按钮一直存在，至少等待响应时间、执行后等待和全局冷却限制，再重新截图尝试。
4. 一旦观察到按钮消失，只等待下一状态，不再补点；即使原按钮重新出现，也不会自动当作新一轮。点击后的长等待使用下一步骤的 `timeout_seconds`，至少覆盖响应时间；每次发送尝试都重新获得这一段观察时间。
5. 下一状态出现才算当前动作完成。达到次数或等待上限后保存失败现场，再最多扫描两轮 `recover_to`；扫描自身不点击。
6. 恢复扫描只有一个候选匹配且当前状态不同时匹配，才从该步骤继续，并在实际点击前重新截图验证。恢复入口动作最多尝试两次，之后动作遵循各自配置。只允许向后恢复，因此不会无限跳转。

御魂 start 允许恢复到 confirm 或 reward；confirm 只允许恢复到 reward，看到 start 不会擅自开启下一轮；reward 允许恢复到返回 start 的观察步骤。越界、预算不足、停止、状态冲突、意外错误不执行恢复。点击发送异常可能已经送达，先观察再决定是否补点；鼠标 `FailSafeException` 则直接停止。使用新机制的场景失败后不再整轮重试。

GUI 可编辑步骤最大尝试数、下一步骤、响应等待和恢复候选，保存时保留场景级恢复扫描参数。“测试当前步骤”刻意降为一次单步操作，不执行下一状态确认或恢复；验证完整恢复逻辑请运行整个场景。

## 日志与现场

`logs/automation.log` 以追加方式写入，达到 5 MiB 自动轮转为 `.1` 到 `.5`，最多五份归档，文件总量通常约 30 MiB；超过保留数量的旧归档会自动淘汰。原有日志不清空，过大时会在下一条记录触发轮转；单条超长记录可能略超限。重复初始化日志会关闭旧处理器，避免句柄泄漏。不要让多个进程同时写入并轮转同一个日志文件；同时运行不同实例请使用不同 `log_file`。

步骤失败会尝试将归一化后的窗口画面保存到日志文件旁的 `failures/`，仅保留最新 20 张 `failure_*.png`。截图数量受限，文件大小取决于分辨率。日志记录失败原因、步骤、完成轮数、点击数、坐标变换和匹配诊断。无法获取新画面时回退到最近一次截图，并标记 `source=last_capture`；完全没有画面时只记录原因。磁盘写入失败不会阻止任务退出，用户按停止不会生成失败截图。

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
