# YYS Desktop Automation

本项目是一个本地桌面自动化辅助程序 MVP：实时截屏，识别指定 UI 图片模板，命中后在受控区域内执行低频、可停止的鼠标点击。

当前处于早期开发阶段，桌面运行面向 Windows，CI 覆盖 Python 3.11–3.13。使用前请先在可观察的窗口中试运行。

## 首次使用

在项目根目录打开 PowerShell，完成安装和校验：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py --init-config
# 编辑 config.yaml 中的窗口名称、参考尺寸、点击白名单和目标图片。
.\.venv\Scripts\python.exe run.py --validate-config
.\.venv\Scripts\python.exe run.py --validate-scenario YYSscript/yuhun/scenario.match-any.yaml
.\.venv\Scripts\python.exe run.py --dry-run --scenario YYSscript/yuhun/scenario.match-any.yaml
```

`--init-config` 创建默认开启 `dry_run` 的配置，已有文件不会被覆盖。自定义路径可使用 `--config PATH --init-config`（父目录需已存在），目标图片路径会按配置所在目录调整。生成的配置引用本仓库中的示例图片；更换项目位置或分发配置时，请一起调整图片路径。

`--dry-run` 只对本次运行生效，即使配置中是 `dry_run: false` 也不发送点击；配置文件不会被改写。GUI 可用 `--dry-run --gui PATH` 打开，运行场景和测试当前步骤都继承此选项。试运行仍会截图、识别、写日志并消耗计划点击预算；界面不会被推动，因此顺序场景可能超时，不能据此证明真实流程成功。

确认识别、坐标和预算后，将配置中的 `dry_run` 改为 `false` 并省略命令行 `--dry-run` 才会发送点击。运行时按 `Esc` 或 `Ctrl+Shift+Q` 停止。

## 命令与问题排查

`python run.py --help` 显示完整参数。`--init-config`、`--validate-config`、`--validate-scenario`、`--probe-window`、`--capture-window`、`--diagnose-match`、`--scenario`、`--gui`、`--resume-gui` 每次只能选择一个。

| 现象 | 处理方式 |
| --- | --- |
| 找不到配置 | 运行 `--init-config`；已有配置通过 `--config PATH` 指定 |
| 图片缺失或无法解码 | 用 `--validate-config` 或 `--validate-scenario PATH` 检查；图片路径相对于各自 YAML 文件 |
| 找不到窗口 | 用 `--probe-window` 检查标题或句柄；重启应用后更新固定句柄和进程 ID |
| 看见按钮但不点击 | 检查 `dry_run`、识别阈值、白名单、冷却及点击预算；用 `--diagnose-match` 查看分数 |
| 消息点击没有响应 | 检查目标应用的输入支持及权限；参阅下文点击后端说明 |

退出码：`0` 表示命令或任务成功，`1` 表示场景校验失败或任务未成功完成，`2` 表示参数、配置或初始化错误。只校验不会截图、监听热键或执行点击。场景运行中的具体停止原因请查看状态文件和日志。

参与开发请阅读 [贡献指南](CONTRIBUTING.md)，后续方向见 [路线图](docs/ROADMAP.md)。仓库目前尚未声明开源许可证；正式作为开源项目发布前，需要作者选定许可证并确认代码和模板图片的分发权限。

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

建议使用 Python 3.13 和虚拟环境（项目 CI 验证 Python 3.11–3.13）：

```powershell
cd D:\projects\yys\YYS
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

项目依赖由 `pyproject.toml` 统一声明；`requirements.txt` 保留为本地源码安装入口。也可以直接运行 `pip install -e .`。

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

窗口模式下模板匹配也会使用 `allowed_region` 作为搜索 ROI，只扫描允许点击的参考区域；桌面模式的截图本身已经是该区域。每个模板的不同缩放版本会在首次创建检测器时缓存，连续扫描不会重复缩放图片。

窗口定位默认使用 `title_contains`。如果系统中有多个同名窗口，可在 `window` 下配置固定 `handle`（HWND）和/或 `process_id`：

```yaml
window:
  title_contains: "阴阳师-MuMu模拟器专版" # 可选交叉校验
  handle: 123456
  process_id: 1234
  reference_width: 1280
  reference_height: 720
```

配置 `handle` 后只接受该窗口句柄；配置 `process_id` 后还会校验句柄所属进程。建议两者同时配置，避免同名窗口误选或句柄复用。可先运行 `python run.py --config config.yaml --probe-window` 查看当前匹配窗口的句柄和进程 ID。窗口不可见、已关闭、客户区为零或身份校验失败时，程序会按窗口未找到处理。

## 运行

场景编辑器的顶部显示当前场景、目标窗口和生效的点击上限。点击上限旁会标明继承全局、由场景覆盖或按场景设置自动计算。左侧列出步骤，右侧提供步骤设置、确认与恢复、模板预览和识别检查。

- “打开场景…”会直接加载文件并选中第一步；支持另存为和 `Ctrl+S` 保存。
- 切换步骤、保存、校验或运行时会自动应用当前表单修改，无需先点“应用步骤修改”。加载其他文件或关闭前，会提示处理未保存内容。
- “校验配置”检查当前编辑内容和全局配置，不改写原场景文件；保存会先检查场景结构，成功后原子替换，非法参数不会覆盖旧文件。
- 动作类型使用中文名称，无关参数自动禁用；坐标 `0` 可正常显示和保存。参数较多或窗口较小时可用表单滚动条查看。
- 启动按钮旁会显示“真实点击”或模拟点击的来源。勾选“试运行”只影响本次会话。全局试运行可在“全局设置”中关闭。用 `--dry-run` 打开的工作台会在整个会话中保持试运行。
- 底部状态栏显示本次任务的步骤、点击数、上限和运行时长。测试单步时使用单步预算。任务停止后，同一处显示原因与“查看现场”入口。
- “展开日志”可查看本次任务最近约 16 KB 的输出。日志默认收起，展开后仍可看到已收集的内容。持久日志保存在全局配置指定的位置。

“测试选中步骤”只执行一次动作；无顺序场景会沿用原输入后端和连续确认帧数，最多点击一次。该测试不验证完整流程的转换和恢复。

“全局设置”可编辑窗口标题、参考尺寸、白名单、默认点击上限、点击间隔、识别间隔、匹配阈值和试运行。保存时校验数据并更新当前全局 YAML；已有字段会保留，注释和排版可能变化。

“场景设置”可编辑连续确认帧数和场景点击上限。无顺序场景还可设置点击方式、场景点击间隔与无目标停止条件。场景点击上限和点击间隔留空时继承全局设置。步骤里的图片阈值也可留空以继承全局默认值。场景设置应用后即可预览，保存或运行时写入场景文件。

### 识别检查与同帧调参

选中一个含图片的步骤，在“识别检查”页点击“截图识别”。修改试调阈值后点击“同帧重算”，可在原图上对比两套设置的分数、阈值和命中情况。红色十字与表格坐标表示试调结果的点击中心参考点。调试只识别当前步骤，使用对应场景的识别方式。

点击“应用阈值”会更新当前步骤，随后保存或运行时写入场景文件。阈值留空时会继承全局设置。“运行诊断”里的“用此帧调参”可把最后一张诊断截图直接带回此页，参考尺寸改变后需重新截图。

在“识别检查”点“窗口与区域…”可以选择目标窗口、框选白名单和查看所有 match-any 目标的识别结果。窗口列表显示标题、客户区大小、HWND 和进程 ID，也可按全局配置定位。截图与识别在后台进行，检查过程不发送点击。

预览沿用运行时的参考尺寸、模板缩放范围、匹配阈值、搜索白名单和快速匹配选项：

- 蓝框标记点击白名单，绿框标记达到阈值的目标，黄框标记低于阈值的候选。红色十字表示点击中心参考点。
- 在截图上拖出黄色选框，点击“应用框选…”将区域填入全局设置。保存后会按新白名单重新截图识别。白名单按参考分辨率保存，可在面板中精确修改。
- 表格显示各目标的分数、阈值、中心参考坐标与屏幕坐标；无顺序模式同时检查全部目标，并标明本帧分数最高的首选目标。
- 顺序模式只检查编辑器当前选中的步骤，不推断当前执行阶段；图片等待步骤只显示识别框，纯等待步骤不产生点击点。
- 单帧结果只用于检查图片识别。实际运行还会检查连续确认帧、冷却、执行阶段和预算。快速模式没有可复核候选时，表格不显示分数。

确认窗口后点击“使用此窗口”返回工作台，再按需运行。选择会以 HWND 和进程 ID 同时绑定本次工作台会话，适用于完整运行和单步测试，不改写 `config.yaml`。目标应用重启后请重新选择；失效的句柄不会回退到其他同名窗口。“恢复配置中的窗口”可清除本次选择。

命令行也支持临时窗口绑定，两个参数必须同时提供且为正整数：

```powershell
python run.py --config config.yaml --window-handle 123456 --window-process-id 1234 --dry-run --scenario YYSscript/yuhun/scenario.match-any-victory.yaml
```

截图依赖目标应用支持窗口捕获；若预览为黑屏或旧画面，请先恢复窗口并检查权限与捕获支持，预览命中不能替代实际界面确认。

Windows 本地环境配置完成后，双击根目录 `start.bat` 会恢复上次打开的场景及选中步骤。首次启动会打开默认的御魂无顺序场景，启动后停在“就绪”。选中的步骤已被删除或改名时，会选中第一步。启动器固定使用项目的 `.venv\Scripts\python.exe`，无需激活环境，也不依赖系统 PATH。

文件栏的“最近场景”保留最近使用的 8 份场景。场景文件被移动或删除时，界面会提示并提供“重新定位…”。成功定位后会更新记录，场景里仍存在的步骤 ID 会继续被选中。各全局配置的历史分别存放在配置旁，例如 `config.yaml` 对应 `.config.yaml.yys-workbench.json`。历史只记录文件路径和步骤 ID。

命令行的 `--resume-gui` 与双击启动相同。指定 `--gui PATH` 可以直接打开另一份场景。

启动器也支持命令行参数：

```powershell
.\start.bat --validate-scenario YYSscript/yuhun/scenario.match-any.yaml
.\start.bat --probe-window
.\start.bat --scenario YYSscript/yuhun/scenario.match-any.yaml
```

PyCharm 的项目解释器选择项目目录下的 `.venv\Scripts\python.exe`；运行文件选择 `run.py`，工作目录选择项目根目录，参数可填写 `--config config.yaml --gui YYSscript/yuhun/scenario.match-any.yaml`。

本机的便携 Python 存放在 `.runtime\python313`，虚拟环境依赖此目录，请保留它。旧 Python 3.15 环境保存在 `.venv-python315-backup`；这些本地环境目录均已从 Git 排除。复制项目到新位置后应重新创建虚拟环境。

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

如果只需要“看见配置图片就点击”，使用下面的无顺序模式；本节及后面的状态确认逻辑仅用于原顺序流程。

## 无顺序匹配点击

```powershell
.\.venv\Scripts\python.exe -B run.py --config config.yaml --validate-scenario YYSscript/yuhun/scenario.match-any.yaml
.\.venv\Scripts\python.exe -B run.py --config config.yaml --scenario YYSscript/yuhun/scenario.match-any.yaml
```

`scenario.match-any.yaml` 设置 `execution_mode: match_any`，将 start、confirm、reward、continue 作为无顺序目标列表。每次截图匹配所有目标，达到各自阈值后点击；多图同时命中时选匹配分数最高的一张，分数相同按配置顺序选择。可用场景级 `stable_frames` 要求同一组目标连续识别若干帧后才点击，降低单帧误识别；默认值为 1。每帧最多点击一次，随后等待冷却并重新截图。图片一直存在时会在冷却后再次点击，不受三次动作尝试、前后步骤或领奖阶段约束。当前场景连续 300 秒未命中任何目标时，会保存失败截图并以失败状态退出。工作台显示停止原因，直接从命令行启动时弹出错误对话框；扫描到任一目标就从该时刻重新计时。可通过 `no_target_timeout_seconds` 调整。

`scenario.match-any.yaml` 现启用 `match_any_detection_mode: coarse_to_fine`：在半分辨率彩色图上搜索全部配置缩放，每个缩放最多选取 5 个候选位置，再在原分辨率局部区域使用原彩色模板和原阈值复核。短边小于 16 像素的模板仍使用全量匹配。双帧确认、点击预算、点击白名单和冷却保持生效；扫描等待间隔缩短为 0.1 秒。点击后确认计数清零，下一次点击需要重新满足双帧确认。

这是近似搜索：缩小图片可能丢失细节，候选数量也有限，存在漏检或未选到全局最高分位置的可能。原分辨率复核保证最终分数仍经过原阈值检查，但不保证与全量搜索完全等价。将 `match_any_detection_mode` 改为 `exhaustive` 可恢复全量搜索；其他未指定该选项的场景默认仍使用全量搜索。GUI 保存会保留此设置。快速模式日志中的 `last_score` 是已复核候选的最高分，没有候选时为 0，不代表全图最高分。

日志每 5 秒输出一次扫描耗时摘要；状态文件包含 `capture_duration_seconds`（截图）、`scan_duration_seconds`（全部目标识别合计）、`detector_timings_seconds`（各目标识别）和 `confirmation_duration_seconds`（从本次连续首次观察的截图开始，到确认完成，含截图、识别及帧间等待，不含点击和点击后等待）。可用离线基准比较已有失败截图和三组不同缩放的合成正样本，不会截图或执行点击：

```powershell
.\.venv\Scripts\python.exe tools/benchmark_match_any.py --frames logs/failures --limit 5
```

输出逐帧命中、坐标、分数、平均扫描耗时及加速比。已有截图的一致结果仅代表与原算法一致，不替代真实界面验证；合成正样本也不覆盖动画、遮挡或所有缩放。`wait_after_seconds` 和 `match_any_click_interval_seconds` 仍为 1 秒，完整操作耗时还受界面动画、截图和等待影响。

点击后端由 `input_backend` 选择。`physical_mouse` 使用 PyAutoGUI 移动系统鼠标并点击，窗口必须位于桌面最前方，否则物理坐标可能点到遮挡窗口；`window_message` 使用 PostMessage 向目标窗口发消息，不移动光标，可尝试后台窗口，但应用可能忽略后台输入。当前 MuMu 配置需让脚本和模拟器以管理员身份运行；PyCharm 内置终端应由管理员权限启动的 PyCharm 打开。最小化窗口不保证能正确截图或响应点击。日志会说明所选后端；窗口消息失败时会分别记录按下和抬起消息的发送状态。

```yaml
input_backend: window_message
```

切换后端建议先用小 `max_clicks` 测试。使用 `physical_mouse` 时确认窗口位于最前方并聚焦；使用 `window_message` 时可尝试遮挡窗口并确认游戏响应。物理鼠标会移动光标；按 Esc/Ctrl+Shift+Q 可紧急停止，鼠标移到屏幕左上角也会触发 PyAutoGUI failsafe。模板必须对应实际交互按钮，而不是标题或装饰图。

没有目标命中就继续等待，期间可按 Esc 或 Ctrl+Shift+Q 停止。窗口捕获、图像处理或点击异常，以及点击越界，会停止并记录诊断。点击仍受白名单、`min_click_interval_seconds`、各目标的 `wait_after_seconds`、dry-run 和总点击上限约束。该模式不判断奖励是否领取成功，也不统计完整轮数；重新出现 start 时会按普通目标点击并继续任务。

```yaml
name: yuhun_match_any
execution_mode: match_any
no_target_timeout_seconds: 60
max_clicks: 2400
steps:
  - id: start
    type: match_and_click
    image: ../../assets/targets/start.png
    threshold: 0.86
    wait_after_seconds: 1
```

这是目标列表片段，完整配置还包括 confirm、reward 和 continue。`no_target_timeout_seconds` 从启动或最近一次命中任意目标时开始计时；到时保存截图并失败退出，工作台提供运行诊断。`max_clicks: 2400` 仅限制累计点击数，不代表保证完成 800 轮。可修改成其他非负整数；省略时使用全局配置。此模式不支持 `max_clicks: auto`、重复轮数、步骤转换确认、恢复扫描和步骤转换规则，配置了这些规则会报错，避免误以为仍受顺序约束。目标的 `timeout_seconds` 不用于退出条件。每次启动重新计数，dry-run 也计入点击上限。

GUI 打开并保存此场景会保留模式；目标的添加、删除和图片编辑沿用原界面。其他任务也可配置独立的 `match_any` YAML，普通顺序场景默认仍使用 `execution_mode: sequential`。

## 顺序领奖流程

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
| `scenario.match-any.yaml` | 无顺序匹配图片，命中即点击，按累计点击数停止 |
| `scenario.match-any-victory.yaml` | start、victory、reward 三目标无顺序匹配，最多累计点击 2400 次 |

三目标版本引用 `assets/targets/` 下同名图片，沿用现有无顺序场景的窗口消息后端、0.75 阈值、双帧确认、1 秒点击间隔和 300 秒无目标超时。列表顺序为 `start`、`victory`、`reward`，但不强制依次执行。可从工作台“打开场景…”加载，也可直接打开试运行工作台：

```powershell
.\start.bat --dry-run --gui YYSscript/yuhun/scenario.match-any-victory.yaml
```

先检查识别分数和实际界面响应，再按需要调整各图片阈值；该预设不统计完整轮数或确认领奖成功。

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

1. 在整个等待期间持续识别当前按钮、`next_step` 和 `recover_to` 中允许的后续状态，不必等当前步骤超时才发现已进入 reward 等界面。
2. 只有同一组识别结果连续达到 `stable_frames` 帧才确认状态。短暂漏识别或冲突只暂停动作，持续冲突才停止；截图异常会清空连续帧计数。
3. 当前按钮稳定匹配后点击，最多 `max_attempts` 次（包含首次，范围 1 到 3）。点击后重新累计确认帧，按钮持续存在时至少等响应时间、执行后等待和全局冷却，再重新截图尝试。
4. 连续 `stable_frames` 个有效截图都识别不到原按钮，确认进入转换阶段，只等待允许的后续状态，不再补点；原按钮后来出现也不会当作新一轮。单帧漏识别不会锁定转换阶段。点击后的长等待使用下一步骤的 `timeout_seconds`，至少覆盖响应时间；每次发送尝试都重新获得这一段观察时间。
5. 预期下一状态稳定出现时推进；更远的允许状态稳定出现时，跳过已经错过的动作并从该状态继续，入口动作最多尝试两次。进入新步骤仍重新截图确认，绝不使用旧匹配位置点击。
6. 达到次数或等待上限后保存失败现场，再最多执行两轮恢复扫描。每轮采集 `stable_frames` 帧且结果必须连续一致，扫描自身不点击；恢复同样验证阶段约束与状态冲突。只允许向后恢复，不会无限跳转。

御魂 start 允许恢复到 confirm 或 reward；confirm 只允许恢复到 reward，看到 start 不会擅自开启下一轮；reward 允许恢复到返回 start 的观察步骤。越界、预算不足、停止、状态冲突、意外错误不执行恢复。点击发送异常可能已经送达，先观察再决定是否补点；鼠标 `FailSafeException` 则直接停止。使用新机制的场景失败后不再整轮重试。

## 循环状态确认

御魂单次与重复场景使用如下配置：

```yaml
stable_frames: 3
# 最后的观察步骤：
steps:
  - id: returned_to_start
    type: wait_for_image
    image: ../../assets/targets/start.png
    requires_action: reward
    timeout_seconds: 60
    wait_after_seconds: 0
```

这是配置片段，需要保留前面的 start、confirm、reward 步骤。`stable_frames` 是场景级连续确认帧数，范围 1 到 10，未配置的旧场景默认 1。帧间使用扫描间隔，截图和模板匹配耗时也影响实际响应速度。纯观察和普通模板点击也使用此帧数；固定坐标点击没有图像确认。

`requires_action` 只能用于图片观察步骤，引用本轮之前的点击步骤。每轮开始清空已尝试动作，不能沿用上一轮的 reward。必须实际尝试过 reward 的点击并稳定识别到返回 start，才允许完成本轮；点击发送异常仍可能已送达，因此也算尝试，最终仍需画面确认。dry-run 不满足这个实际动作条件，不能误报领奖完成。

start 的两次出现虽然图片相同，但阶段不同：首次 start 只用于开始；confirm 等待中提前返回 start 会以 `phase` 原因停止，保存现场；reward 尚未尝试就看到 start 同样停止。领奖后确认返回 start，最后观察步骤再次稳定验证，完成轮数才加一。此规则只证明流程阶段和画面转换，不核对奖励数量。

上述阶段检查同时覆盖持续识别、超时后的恢复扫描和最后观察步骤。后续其他循环任务可用自己的步骤 ID、`recover_to` 和 `requires_action` 配置，不依赖御魂专用 Python 逻辑。GUI 保存会保留 `stable_frames`，步骤表单支持编辑前置动作；单步骤测试清除阶段前置条件，仅验证该单步。

GUI 可编辑步骤最大尝试数、下一步骤、响应等待和恢复候选，保存时保留场景级恢复扫描参数。“测试当前步骤”刻意降为一次单步操作，不执行下一状态确认或恢复；验证完整恢复逻辑请运行整个场景。

## 日志与现场

工作台在运行中显示未命中、确认帧进度、点击冷却和画面切换等待。无顺序模式会显示本帧首选目标和最近一次点击的结果。

任务停止后，可打开「运行诊断」查看停止原因。现场图标出白名单、已命中或未达阈值的候选框，以及尝试点击的位置。通过「调整设置」可以跳到相关参数，通过「重新检查」可以用当前参数重新截图识别。已绑定的窗口不可用时会提示重新选择。

运行状态保存在日志目录的 `automation.status.json`。它包含进程 ID、步骤、运行时长、轮数、点击预算、识别状态和停止原因。任务结束后状态会标记为 `completed` 或 `stopped`。无顺序模式达到点击预算或连续未命中上限时仍正常退出，`stop_reason` 会记录具体原因。

`logs/automation.log` 以追加方式写入，达到 5 MiB 自动轮转为 `.1` 到 `.5`，最多五份归档，文件总量通常约 30 MiB；超过保留数量的旧归档会自动淘汰。原有日志不清空，过大时会在下一条记录触发轮转；单条超长记录可能略超限。重复初始化日志会关闭旧处理器，避免句柄泄漏。不要让多个进程同时写入并轮转同一个日志文件；同时运行不同实例请使用不同 `log_file`。

失败或触及运行限制时，程序会保存本次运行最后一次成功采集的画面，并把同一帧的识别结果写入状态文件。截图保存在日志文件旁的 `failures/`，`failure_*.png` 和 `stop_*.png` 合计保留最新 20 张。如果没有成功采集或保存画面，诊断仍会显示停止原因。手动停止不生成截图。

## 多流程约定

每个流程保存在独立的 `scenario.<flow-name>.yaml` 中，按用途放在 `YYSscript/<category>/` 下，通过 `--scenario PATH` 或 GUI 打开文件切换，共用 `config.yaml` 中的窗口和安全设置；不要为了新增流程复制执行器代码。模板路径相对所在场景文件解析，御魂场景使用 `../../assets/targets/`。根目录的 `scenario.example.yaml` 保留为通用示例。

目前支持的通用步骤：

| 类型 | 行为 | 主要字段 |
| --- | --- | --- |
| `match_and_click` | 等待模板出现并点击一次 | `image`、`threshold`、`timeout_seconds` |
| `wait_for_image` | 只等待模板出现，不点击、不占点击额度 | `image`、`threshold`、`timeout_seconds` |
| `click_point` | 点击窗口参考坐标 | `x`、`y`、`timeout_seconds` |
| `wait` | 固定等待 | `timeout_seconds` |

所有步骤都可使用 `wait_after_seconds`。它表示动作后至少等待多久再继续识别；例如 start 等待战斗阶段时可设置为 10 秒。每个步骤还可使用 `scan_interval_seconds`，省略时继承全局 `scan_interval_seconds`。长等待步骤使用较大的 `wait_after_seconds` 和较长识别间隔，confirm、reward 等短阶段使用较短识别间隔。同一流程中的步骤 ID 应唯一，优先使用模板点击和界面确认，而不是固定坐标。循环和场景级点击预算适用于所有场景，GUI 保存已有场景时会保留这些参数，测试当前步骤仍只执行一次。后续有实际需求时，再扩展步骤识别区域、连续多帧确认或分支，不把业务流程写死在 Python 中。

## 测试

测试不需要启动目标窗口，使用模拟画面验证场景点击的坐标映射、白名单、点击上限和重试策略：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

GitHub Actions 会在 Windows runner 上使用 Python 3.11、3.12 和 3.13 重复执行源码编译、全量测试和正式场景校验。

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
- 增加 dry-run 模式截图标注预览

## 自动停止条件

顺序场景支持可选的无人值守停止条件：

```yaml
max_runtime_minutes: 120
max_consecutive_failures: 3
stop_when:
  - id: low_energy
    image: ../../assets/targets/low_energy.png
    threshold: 0.90
    stable_frames: 3
```

`max_runtime_minutes` 限制整次运行时长；`max_consecutive_failures` 限制连续失败的轮数；`stop_when` 中的模板连续稳定识别后立即停止。停止原因会写入日志和 `automation.status.json`，例如 `runtime_limit`、`failure_limit` 或 `stop_image:low_energy`。
