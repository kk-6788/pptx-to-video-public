# v2.3.0 UI 参考技能与桌面界面交付

日期：2026-09-08。延续 v2.2 的忠实讲解制作流程，本轮完成 UI 技能沉淀、三主题交互组件升级与 EXE 更新。

## 可用文件

- EXE：[./dist/PPT转视频工具.exe](./dist/PPT转视频工具.exe)。启动标题应显示 **v2.3.0**。
- 用户级技能：[<用户目录>/.agents/skills/ui-reference-library/SKILL.md](<用户目录>/.agents/skills/ui-reference-library/SKILL.md)。已安装，Codex 当前技能目录已识别。
- 技能项目副本：[skills/ui-reference-library](./skills/ui-reference-library/SKILL.md)。后续可说“使用 ui-reference-library 参考组件并优化这个界面”。
- 新版说明：[使用说明.txt](./dist/使用说明.txt)。CLI 参数、视频制作模式及已有导出能力保持兼容。

最终 EXE：111,728,326 字节；SHA256 `513d695acdd0280fbb8888419ddd2da036d0cce325a1d933dcb2fd3f5221509a`。实际启动标题为 `PPT转视频工具 v2.3.0`，[最终 EXE 截图](./artifacts/ui-library/exe-v2.3.0.png)已检查。

## 三种主题与交互

| 主题 | 色彩与层次 | 实际桌面截图 |
| --- | --- | --- |
| 简约浅色 | 雾白背景、深蓝强调、青蓝点缀与浅色渐变 | [浅色](./artifacts/ui-library/light.png) |
| 柔和暖色 | 浅砂表面、森林绿操作区、暖铜点缀 | [暖色](./artifacts/ui-library/warm.png) |
| 深色科技 | 深靛表面、雾紫强调、冷青渐变 | [深色](./artifacts/ui-library/dark.png) |

新增圆角标题栏和参数卡片、鼠标/键盘有反馈的圆角主按钮、滑动开关、横竖屏分段选择、随工作状态更新的四步指示、带局部聚光的文件入口。分镜文字增大标题并增加要点/讲解间距。更换输入会清除旧分镜，避免把另一份 PPT 的计划当成当前计划；更换模式后步骤条也会正确重置。

右上角可切换主题并记住选择；“减弱动效”停止开关插值和指针聚光。Tab 导航、空格切换开关、左右键选择画幅、回车操作按钮。生成期间文件选择及相应参数禁用。动画只在交互时运行，控件销毁会取消回调并释放变量监听。

1000×720 窗口下文件入口自动缩小，长中文文件名换行，按钮保持可见。左侧参数可滚动。[小窗口](./artifacts/ui-library/small_1000x720.png) · [长文件名](./artifacts/ui-library/long-filename-small.png) · [深色聚光](./artifacts/ui-library/dark-hover.png)

## 实际参考与许可

三个网站均已打开具体组件页并保存浏览器截图；不是仅根据首页名称推测。EXE 中的新 Tk 控件是独立实现，没有拷贝 React/CSS 组件源码，也无需联网加载界面。

| 来源 | 借鉴到本应用的方式 | 来源证据 |
| --- | --- | --- |
| Uiverse | 主按钮、开关的可见状态与交互反馈 | [按钮](https://uiverse.io/barisdogansutcu/little-penguin-13)、[开关](https://uiverse.io/Cevorob/good-wolverine-51)、[实看截图](./artifacts/ui-library/reference-uiverse.png) |
| React Bits | 指针局部聚光、完成/当前步骤的区分 | [Spotlight Card](https://reactbits.dev/components/spotlight-card)、[Stepper](https://reactbits.dev/components/stepper)、[实看截图](./artifacts/ui-library/reference-reactbits.png) |
| Aceternity | 文件选择入口、卡片分组与活动工作区 | [File Upload](https://ui.aceternity.com/components/file-upload)、[Bento Grid](https://ui.aceternity.com/components/bento-grid)、[实看截图](./artifacts/ui-library/reference-aceternity.png) |

技能记录 Uiverse UI 元素的 MIT 许可、React Bits 的 MIT + Commons Clause、Aceternity 免费/付费内容及自定义许可的差异。具体资源使用时再次核对，不把整个网站笼统认定为 MIT。完整链接和适用范围见 [站点索引](./skills/ui-reference-library/references/sites.md)。

按新增要求也核验了官方 GitHub：[Uiverse Galaxy](https://github.com/uiverse-io/galaxy)、[React Bits](https://github.com/DavidHDev/react-bits)、[Aceternity 官方组织](https://github.com/aceternity)。研究了 Pillow、Lucide 和 Sun Valley ttk 的适用性，本应用继续使用已有 Pillow，避免额外运行时。

实际按固定提交下载了一个 Lucide presentation.svg 样本及完整 ISC/Feather MIT 许可，保留在技能资源目录，供未来按需参考；没有把它冒称为本次 EXE 已使用的图标。提交 `a537cb6eb323b885f4c60baf3cec1a995982d167`，文件 SHA256 `5d15abfdfca21e40abe3b8daead5e8f6a7d38e623fb1a4dd8890448c79e75342`。[资源与 GitHub 流程](./skills/ui-reference-library/references/github-resources.md)

## 文件改动与原因

| 文件与位置 | 改动 | 原因 |
| --- | --- | --- |
| [gui.py:41](./gui.py:41) | 版本 2.3.0；接入新组件 | EXE 与源码版本一致 |
| [gui.py:344](./gui.py:344) | 圆角渐变标题栏、响应式文件入口、主题/动效切换 | 改善层次和小窗口适配 |
| [gui.py:374](./gui.py:374) | 输入变更清除旧分镜；更新空状态 | 保证计划与当前文件对应 |
| [gui.py:1190](./gui.py:1190) | 步骤状态、忙碌控件、状态栏同步更新 | 避免过期“完成”提示和生成期间改输入 |
| [ui_components.py:29](./ui_components.py:29) | 新增绘制基类、圆角按钮、开关、画幅选择、卡片、步骤、文件入口 | 统一三主题交互；合并绘制与取消无用回调 |
| [ui_themes.py:12](./ui_themes.py:12) | 三套表面/强调/渐变/阴影色 | 分别协调主题，不只更换背景 |
| [PPT转视频工具.spec:8](./PPT转视频工具.spec:8) | 包含 ui_components | 冻结 EXE 中可使用新组件 |
| [tools/check_ui_components.py:1](./tools/check_ui_components.py:1) | 新增八组真实桌面交互验收 | 检查键盘、禁用、旧状态重置、动效、长文本、销毁清理 |
| [tools/check_ui_themes.py:16](./tools/check_ui_themes.py:16) | 新结果目录；退出前处理 Tk 主题事件 | 保留历史截图；测试结束无多余 Tcl 报错 |
| [tools/check_fidelity_gui.py:17](./tools/check_fidelity_gui.py:17) | 新结果目录；截图可用性独立记录 | 保护旧样片；区分转换断言与系统截图限制 |
| [tools/check_fidelity_release.py:14](./tools/check_fidelity_release.py:14) | 新版 EXE 标题与输出路径 | 实际启动和普通用户视频读取检查 |
| [README.md:3](./README.md:3)、[使用说明.txt:1](./使用说明.txt:1) | 新界面与技能使用方式；同步 dist 两份说明 | 方便直接使用交付包 |
| [skills/ui-reference-library/SKILL.md:1](./skills/ui-reference-library/SKILL.md:1) | 技能、来源与许可索引、下载助手、9 项测试、3 个行为评估场景 | 把本次研究沉淀为可复用流程 |

## 实际验收

以下命令在 `<项目目录>` 执行；实机 GUI 使用 Windows 用户 kk。`python314` 表示 `<用户目录>\AppData\Local\Python\pythoncore-3.14-64\python.exe`。

| 命令 | 实际结果 |
| --- | --- |
| `python -X utf8 -m unittest discover -s tests -q` | Python 3.11：79 项通过；[日志](./artifacts/ui-library/tests-python311.log) |
| `python314 -X utf8 -m unittest discover -s tests -q` | Python 3.14.5：79 项通过；[日志](./artifacts/ui-library/tests-python314.log) |
| `python -X utf8 tools/check_ui_themes.py` | 三主题、偏好恢复、参数保留、1000×720 与滚动通过；errors=[]；[结果](./artifacts/ui-library/checks.json) |
| `python314 -X utf8 tools/check_ui_components.py` | 八组交互检查通过，errors=[]；[结果](./artifacts/ui-library/component-checks.json) |
| `python -X utf8 tools/check_fidelity_gui.py`，以及同命令 Python 3.14 | 实际解析→规划→合成→预览；2/2 页成功，生成 API 调用 0 次，无 GUI 异常；[结果](./artifacts/ui-library/gui-workflow.json) |
| `ffprobe -v error -show_entries stream=codec_name,width,height -show_entries format=duration -of json artifacts/ui-library/gui-faithful.mp4` | 1280×720，H.264 + AAC，23.500 秒；[视频](./artifacts/ui-library/gui-faithful.mp4) |
| `python -X utf8 -B -m unittest discover -s skills/ui-reference-library/scripts -p "test_*.py" -v`，以及 Python 3.14 | 两个运行时各 9 项下载行为测试通过；包括越界、覆盖、许可下载失败、SHA 与来源记录 |
| `python -X utf8 -B <skill-creator>/scripts/quick_validate.py <skill目录>` | 项目副本和安装副本均返回 `Skill is valid!`；Codex 技能目录已识别 |
| `python314 -X utf8 -m PyInstaller --noconfirm --distpath dist --workpath build PPT转视频工具.spec` | 最终构建成功；[exe-build.log](./artifacts/ui-library/exe-build.log) |
| `python -X utf8 tools/check_fidelity_release.py` | 启动 v2.3.0 通过，已取得最终窗口截图；out.mp4 普通用户读取及完整解码通过；[exe-checks.json](./artifacts/ui-library/exe-checks.json) |

独立代码审查发现一个旧完成状态问题，已修正并加入实机测试；未发现其它重要问题。控件测试首次发现未分配尺寸时绘图坐标无效，已在绘制入口处理初始小尺寸，后续三主题与启动测试通过。技能的 3 个行为评估场景已经编写；没有把它们冒称为额外完成的模型对照实验。

## 适用边界

- 桌面端适配上述交互原则，未移植网站的 WebGL 特效或拖放上传功能。文件入口调用本地文件对话框；UI 本身离线可用。
- “减弱动效”是当前会话选项；主题选择会持久保存。已验证键盘操作，尚未做屏幕阅读器专项验收。
- Windows 转换后窗口捕获曾返回 `screen grab failed`，验收脚本已独立记录截图状态。最终重跑转换与截图均成功，`screenshot_captured=true`、`screenshot_error=null`；该系统捕获偶发问题没有影响视频输出。[最终完成窗口](./artifacts/ui-library/gui-faithful-complete.png)
- 本轮全流程测试使用字幕和 BGM；未重新验证联网 Edge TTS 服务可用性。视频核心改造和此前完整验收见 [CONTENT_FIDELITY_REPORT.md](./CONTENT_FIDELITY_REPORT.md)。
- EXE 包含 Python 与应用依赖；复制到其他电脑仍需 ffmpeg/ffprobe 加入 PATH。

## 备份

本轮所有原有修改文件在修改前保存于 **[./backups/ui-library-20260908-112258](./backups/ui-library-20260908-112258)**，共 11 个 `.bak`。包括 gui.py、ui_themes.py、spec、README、使用说明、三个既有验收脚本、dist 两份说明及旧版 EXE（`dist_PPT转视频工具.exe.bak`）。新建文件没有被替换的旧版。此前根目录与 fidelity 备份继续保留。
