# 贡献指南

感谢帮助改进 YYS Desktop Automation。当前项目面向 Windows，推荐 Python 3.13，CI 检查 Python 3.11、3.12 和 3.13。

## 本地开发

从仓库根目录运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q run.py src tests
.\.venv\Scripts\python.exe run.py --config config.example.yaml --validate-config
```

测试使用模拟画面和输入后端，不需要启动目标应用，也不应发送真实点击。涉及真实界面的变更，先在可观察窗口中用 `--dry-run` 验证识别，再用小点击预算验证交互，并在 PR 中说明实测范围。

## 代码约定

- 配置解析和校验放在 `config.py`、`scenario.py`；场景业务通过独立 YAML 声明。
- 执行和状态转换由 `workflow.py` 管理，截图、识别、输入分属各自模块。
- 新增输入方式或重试逻辑时，保留白名单、点击预算、冷却、紧急停止和试运行约束。
- 路径相对于对应配置文件解析；避免引入本机盘符、固定 HWND 或进程 ID。
- 修复行为缺陷时添加能重现问题的测试；新增配置字段需补默认值、非法输入检查和使用说明。
- 使用标准库 `unittest`；保持模块导入不启动 GUI、截图、热键监听或自动化。

## 提交问题与变更

Bug 报告请包含 Python/Windows 版本、使用的命令、最小配置、预期与实际行为、相关日志。分享配置、日志和截图前，请移除账号、窗口私人内容和本机敏感路径。

每个 PR 聚焦一个可解释的改进，写明用户可观察到的变化、验证命令和仍未验证的部分。场景配置变更请运行 `--validate-scenario PATH`，涉及动作控制时请测试 dry-run、停止和预算边界。

请勿提交虚拟环境、便携运行时、IDE 设置或运行日志。新增模板图片需说明来源和分发权限。项目尚未声明许可证，正式接受和发布外部贡献前需由作者明确许可条款。
