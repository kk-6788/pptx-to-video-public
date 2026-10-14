# UI 主题与布局升级

完成日期：2026-09-07。新增三套即时切换的主题，默认简约浅色；没有新增第三方 UI 依赖。

## 实际窗口截图

- [简约浅色](./artifacts/ui-themes/light.png)：白色面板、蓝色主按钮。
- [柔和暖色](./artifacts/ui-themes/warm.png)：米白面板、暖棕强调色。
- [深色科技](./artifacts/ui-themes/dark.png)：蓝灰面板、青蓝强调色。
- [1000×720 窗口](./artifacts/ui-themes/small_1000x720.png)
- [画幅、声音和输出设置](./artifacts/ui-themes/sound_settings.png)

这些图片来自实际 tkinter 窗口截图，不是设计稿。

## 使用方法

在 `<项目目录>` 运行：

```powershell
python gui.py
```

右上角 **界面主题** 可选择三套外观，选择后立即生效，重新启动仍恢复上次选择。首次启动默认 **简约浅色**。偏好保存在应用旁的 `ui_preferences.json`，只包含主题名称，不包含 API Key、PPT 内容或转换参数。

**界面主题** 控制软件外观；左侧 **画面风格** 仍控制生成视频的风格，两者独立。

设置区可滚动，主操作按钮固定在左下方；中间分隔线可拖动，并限制最小宽度防止表单被挤没。标题、正文、辅助文字有独立字号，输入框和下拉框保留清楚的焦点状态。初始分镜区域增加文件选择入口及操作说明。

## 文件改动与原因

| 文件 | 改动与原因 |
|---|---|
| [ui_themes.py:12](./ui_themes.py:12) | 新增三套语义配色、字体和完整 ttk 控件样式，集中维护外观；32、37、45 行负责偏好路径、读取与原子保存；无效偏好回到浅色，保存失败不阻止使用 |
| [gui.py:286](./gui.py:286) | 主题即时应用；原地更新控件、文本标签及已打开过的下拉菜单，保留输入、焦点相关控件和场景对象，不重建窗口 |
| [gui.py:334](./gui.py:334) | 增加 PPT 到视频的示意图和空白引导；选文件后显示文件已就绪，生成分镜后自动让出内容区 |
| [gui.py:371](./gui.py:371) | 顶部增加界面主题选择，优化标题与真实流程步骤条 |
| [gui.py:486](./gui.py:486) | 原先拥挤的八列表单改为纵向字段，保留下拉变量引用，修复引擎名称空白；画面风格显示中文名称并正确映射原内部值 |
| [gui.py:526](./gui.py:526) | 画幅、字幕、TTS、转述、BGM 独立分区；滑条数值和文本读数保持同步 |
| [gui.py:603](./gui.py:603) | 分析、生成、确认、停止等按钮固定在滚动区外，滚动查看参数时仍可操作；空闲时隐藏无进度内容的进度栏 |
| [gui.py:48](./gui.py:48)、[gui.py:866](./gui.py:866) | 主窗口文本区采用可跟随主题的 ttk 滚动条；API Key 标题与输入框分行，增加可用宽度，保留显隐功能 |
| [PPT转视频工具.spec:6](./PPT转视频工具.spec:6) | 打包配置包含 `ui_themes`；后续已完成新版 EXE 构建，位于 `dist/PPT转视频工具.exe` |
| [README.md:266](./README.md:266) | 新增主题使用、偏好文件与布局说明 |
| [tests/test_ui_themes.py:1](./tests/test_ui_themes.py:1) | 新增五项测试：正文/按钮对比度、偏好往返、损坏/未知值降级、写入失败不覆盖旧偏好、未知主题不落盘 |
| [tools/check_ui_themes.py:1](./tools/check_ui_themes.py:1) | 实际桌面启动、主题和下拉菜单切换、参数保留、小窗口、滚轮、Key 显隐、截图与重启恢复验收 |

视频解析、合成、配音、SRT 和 BGM 处理模块未在本轮改动。

## 验证结果

```powershell
python -m unittest discover -s tests -v
& '<用户目录>\AppData\Local\Python\pythoncore-3.14-64\python.exe' -m unittest discover -s tests -v
& '<用户目录>\AppData\Local\Python\pythoncore-3.14-64\python.exe' tools/check_ui_themes.py
```

- Python 3.11.15：**53 项测试通过**。[日志](./artifacts/ui-themes/unittest_py311.log)
- Python 3.14.5：**53 项测试通过**。[日志](./artifacts/ui-themes/unittest_py314.log)
- 真实桌面验收：三套主题均应用；展开过的下拉菜单也正确换色；关闭并新建应用后恢复深色主题。
- 切换主题前后，输入/输出路径、9:16、TTS、转述、BGM 音量、分镜文本和原始场景对象均保留。处理中禁用的确认按钮不会因切换主题被启用。
- 1000×720 窗口下，关键表单未横向溢出，固定按钮可见，鼠标滚轮有效；API Key 显隐和中文画面风格映射正常。
- 三套主题的正文、辅助文字及主要按钮前景/背景对比度均不低于 4.5:1。
- 独立运行 `gui.py`：两个解释器均启动成功，存活 3 秒、stderr 为空，随后验收脚本主动关闭窗口。
- 本轮备份三项 SHA-256 校验通过，五个改动/新增 Python 与 spec 文件编译通过。

[GUI 验收记录](./artifacts/ui-themes/checks.json) · [最终入口与备份检查](./artifacts/ui-themes/final_checks.json)

主题持久化测试使用隔离的临时偏好文件，没有把测试用深色主题强加给实际用户。

## 备份与范围

本轮修改前保存了独立备份，上一轮原文件旁的 `.bak` 保持不变：

- `<项目目录>\backups\ui-20260907-100601\gui.py.bak`
- `<项目目录>\backups\ui-20260907-100601\README.md.bak`
- `<项目目录>\backups\ui-20260907-100601\PPT转视频工具.spec.bak`

[本轮备份清单](./backups/ui-20260907-100601/manifest.json)

后续交付已完成：`dist/PPT转视频工具.exe` 已于 2026-09-07 重新打包并实际启动通过，包含本报告的三套主题。Windows 原生文件选择框、系统消息框仍使用系统外观。桌面窗口最小尺寸为 1000×720；左侧长表单通过滚动访问。
