# PPT 内容一致性、连贯播放与三种主题交付报告

交付版本：**2.2.0**，2026-09-07。此次完成此前约定的内容重构、实际样片验收、三种 UI 主题细化及 EXE 重打包。

## 交付文件

- [新版 EXE](./dist/PPT转视频工具.exe)：111,712,576 字节；实际窗口标题 `PPT转视频工具 v2.2.0`，启动通过。
- [新版横屏 out.mp4](./out.mp4)：23.50 秒，1280×720，H.264 + AAC，逐页中文配音、字幕、BGM。
- [竖屏样片](./artifacts/content-fidelity/out_9x16.mp4)：23.50 秒，720×1280，配音、字幕、BGM。
- [复杂样例视频](./artifacts/content-fidelity/complex.mp4)：40.333 秒，1280×720，484 帧 / 12 fps，字幕和 BGM；对应[测试 PPT](./artifacts/content-fidelity/complex_source.pptx)。
- [字幕](./out.srt)与[内容来源/时间轴清单](./out.content.json)。
- [实施计划](./docs/superpowers/plans/2026-09-07-content-fidelity.md)。

EXE SHA-256：`8f0fb480f01cd6b10b32e4a1145bd8b8468e809770327b01e4b1900088441933`。

## 原因与实现

旧片第 1 页把“新品发布”表现成了 PPT 没有的手机，第 2 页把“核心功能”表现成了科幻人物。旧逻辑统一了视觉风格，但没有建立原文事实与画面之间的约束。

默认入口现在使用 **忠实讲解**：源标题、正文事实和原图直接成为画面，不调用图像/视频生成服务；逐页一一对应，保留数字与原序，不增添人物、产品外观、场景或因果关系。原来的生成链路保留为 **AI 创意演绎**。低层旧调用默认值保持兼容，CLI/GUI 默认值为 faithful。

来源核对在编码前执行：正文、标题、备注、图片摘要、页序、旁白、字幕和场景结构必须与原计划一致。编码时只用来源内容；长文本换行和分页，不用省略号抹去事实。原图按比例放入画面，数字只强调原有值，不据此虚构图表。

时间轴使用整数帧累计；每个源页的视觉、语音和字幕共用同一起点。阅读时长有下限，过长语音会延长页面。配音在忠实模式逐页重试，仍失败的页静音并记录，不把整段旁白重新分配到其他页面。内部重点与字幕时间按文本和实测语音时长估算，不声称实现逐词强制对齐。

## 文件 → 改动 → 原因

| 文件及行号 | 改动 | 原因 |
|---|---|---|
| [faithful_plan.py:43](./faithful_plan.py:43) | 新增正文事实提取、保留数字与重复事实 | 避免摘要遗漏或改写原事实 |
| [faithful_plan.py:129](./faithful_plan.py:129)、[164](./faithful_plan.py:164)、[195](./faithful_plan.py:195) | 阅读时长、逐页计划、来源摘要及完整性核对 | 拦截漏页、乱序、篡改及无依据内容 |
| [content_renderer.py:177](./content_renderer.py:177)、[199](./content_renderer.py:199) | 新增确定性信息动画、原图排版、完整分页、重点柔和切换、横竖屏及来源清单 | 用实际内容解释 PPT，保持稳定画面 |
| [prompt_engine.py:201](./prompt_engine.py:201)、[861](./prompt_engine.py:861)、[2386](./prompt_engine.py:2386) | 计划新增默认字段，Director/便捷接口增加 visual_mode | 新旧流程兼容；忠实模式不合并跨页场景 |
| [video_composer.py:262](./video_composer.py:262) | 忠实字幕优先完整短句，单行深色字幕 | 避免短句被拆成残词，提升阅读清晰度 |
| [video_composer.py:440](./video_composer.py:440) | 忠实模式逐页 TTS 重试及失败隔离 | 全局回退曾把 6 秒短页缩成约 1 秒并造成错位 |
| [video_composer.py:561](./video_composer.py:561)、[614](./video_composer.py:614) | 模式一致性校验、来源核对、拒用无依据片段、整数帧时间轴、内容 JSON | 保证逐页来源和时间可核对；避免浮点累计少一帧 |
| [video_composer.py:726](./video_composer.py:726) | 发布文件先在目标目录创建，再原子替换 | 避免私有临时目录的 Windows ACL 跟随视频，解决普通用户打不开 |
| [tts_audio.py:123](./tts_audio.py:123)、[242](./tts_audio.py:242)、[307](./tts_audio.py:307) | 可选 preserve_text，忠实文本不自动去重 | 重复数字可能属于不同试验/项目，不能擅自删掉 |
| [video_generator.py:313](./video_generator.py:313) | 忠实计划核对后直接跳过外部生成 | 防止低层调用误提交图像/视频 API |
| [main.py:92](./main.py:92)、[327](./main.py:327) | 新增 --visual-mode，默认 faithful，provider 初始化前进入本地合成 | 无生成 Key 即可使用默认流程 |
| [gui.py:351](./gui.py:351)、[845](./gui.py:845) | 分层标题区、三套主题细化、内容模式选择；忠实模式隐藏无关引擎设置 | 所有主题提升层次，并让常用画幅/声音设置更容易看到 |
| [gui.py:1629](./gui.py:1629)、[1872](./gui.py:1872) | 转换前重新解析当前文件；分镜、旁白和预览跟随忠实流程 | 避免旧文件缓存；修复无 AI clips 时被误报 0/N 失败 |
| [ui_themes.py:12](./ui_themes.py:12) | 三套调色、标题渐变、辅助金属色、面板边界与控件状态 | 提升三种 UI 的质感，保持文字对比和主题持久化 |
| [PPT转视频工具.spec:7](./PPT转视频工具.spec:7) | 收入 faithful_plan/content_renderer；保留 BGM | EXE 包含完整新流程 |
| [README.md:1](./README.md:1)、[使用说明.txt:1](./使用说明.txt:1) | 更新默认方式、使用命令与边界；同步到 dist 两份使用说明 | 防止用户误以为必须配置生成 API |
| [tests/test_faithful_plan.py:1](./tests/test_faithful_plan.py:1)、[tests/test_content_renderer.py:1](./tests/test_content_renderer.py:1) | 新增来源核对、长文完整性、数字、图像比例、阅读下限测试 | 验证源事实没有被显示逻辑丢弃 |
| [tests/test_fidelity_integration.py:1](./tests/test_fidelity_integration.py:1) | 新增离线入口、创意兼容、错模式拦截、TTS 失败隔离、整数帧测试 | 覆盖真实故障边界 |
| [tests/test_entrypoints_upgrade.py:119](./tests/test_entrypoints_upgrade.py:119) | 旧 provider 回归明确使用 creative | 默认模式更改后继续测旧流程本身 |
| [tools/check_ui_themes.py:1](./tools/check_ui_themes.py:1) | 主题测试适配隐藏的创意引擎字段 | 仍验证切换、持久化、状态保持与小窗口 |
| [tools/check_fidelity_gui.py:1](./tools/check_fidelity_gui.py:1)、[check_fidelity_media.py:1](./tools/check_fidelity_media.py:1)、[check_fidelity_release.py:1](./tools/check_fidelity_release.py:1) | 新增真实 GUI、复杂媒体、EXE 与用户权限验收脚本 | 验收可复现，结果保存在 artifacts/content-fidelity |

config.py 本轮仅备份，未更改；先前的比例、BGM 等配置继续使用。此前核心解析等升级详情见 [UPGRADE_REPORT.md](./UPGRADE_REPORT.md)。

## 实际测试

以下命令均在 `<项目目录>` 执行。`py314` 指本机 `<用户目录>\AppData\Local\Python\pythoncore-3.14-64\python.exe`；下面用完整命令保留构建方式。

| 命令 | 实际结果 |
|---|---|
| `python -X utf8 -m unittest discover -s tests -v` | Python 3.11：79 项通过；包含原核心、主题和新增忠实模式回归 |
| `& '<用户目录>\AppData\Local\Python\pythoncore-3.14-64\python.exe' -X utf8 -m unittest discover -s tests -v` | Python 3.14.5：79 项通过 |
| `python main.py -i demo.pptx -o out.mp4 --audio --subtitle --narration-style explain --ratio 16:9` | 实际使用 Python 3.14；23.50 秒，1280×720，H.264/AAC，两页 Edge TTS 完成；6 个正文事实完整进入画面 |
| `python main.py -i demo.pptx -o artifacts/content-fidelity/out_9x16.mp4 --audio --subtitle --narration-style explain --ratio 9:16` | 实际使用 Python 3.14；23.50 秒，720×1280，配音与字幕完成 |
| `python main.py -i demo.pptx -o out_9x16.mp4 --ratio 9:16 --dry-run` | 解析两页，正常退出；demo 本身无表格、图片与备注，未虚报提取增量 |
| `python main.py -i demo.pptx -o artifacts/content-fidelity/planned.srt --srt-only --ratio 9:16 --narration-style explain` | 离线导出 UTF-8 BOM 字幕；不合成视频、不调用 TTS 或生成 API |
| `python tools/check_fidelity_media.py --fixture` | 实际创建表格/备注/流程/原图测试 PPT 并合成，40.333 秒，10 个正文事实完整显示；有 BGM 音轨 |
| `python tools/check_fidelity_media.py` | 三个最终视频完整 ffmpeg 解码通过；原页次序 `[1,2]`，事实重建完全匹配；1 fps 抽样未发现 ≥2 秒黑段 |
| `python tools/check_ui_themes.py` | 实际桌面三主题、持久化、转换设置保持、1000×720 窗口检查通过；控件异常数组为空 |
| `python tools/check_fidelity_gui.py` | 实际 GUI 选择模式→规划→合成→预览通过，约 10.9 秒；预览 2/2 成功，生成 provider 调用数为 0 |
| `& '<用户目录>\AppData\Local\Python\pythoncore-3.14-64\python.exe' -X utf8 -m PyInstaller --noconfirm --distpath dist --workpath build 'PPT转视频工具.spec'` | 最终构建成功，EXE 版本 2.2.0 |
| `python tools/check_fidelity_release.py` | 实际启动新 EXE 并截图；桌面用户成功读取 out.mp4 且完整解码 |
| PyInstaller `CArchiveReader` 包检查 | 两个新增模块、合成/语音/主题模块和三首 MP3 均在包内；未打入 .env |

三片最低抽样亮度分别约 **239.20 / 239.77 / 237.13**，远高于黑帧阈值 18。来源覆盖结果是结构化内容核对结果，不是 AI 视频语义评分。

测试证据：[Python 3.11 日志](./artifacts/content-fidelity/tests-integration.log)、[Python 3.14 日志](./artifacts/content-fidelity/tests-python314.log)、[媒体核对 JSON](./artifacts/content-fidelity/media-checks.json)、[GUI 流程](./artifacts/content-fidelity/gui-workflow.json)、[构建日志](./artifacts/content-fidelity/exe-build-final.log)、[EXE/权限检查](./artifacts/content-fidelity/exe-checks.json)、[包内容检查](./artifacts/content-fidelity/exe-package.json)。

主题测试脚本在销毁临时 Tk 根窗口时可能打印 `ThemeChanged ... application has been destroyed`，发生在测试窗口销毁阶段；实际 EXE 启动和正常 GUI 工作流没有该异常。

## 使用方式

```powershell
# 默认忠实讲解，无生成 Key；配音需要联网或本地 Windows 语音
python main.py -i demo.pptx -o out.mp4 --audio --subtitle

# 竖屏、口播转述、配音、字幕
python main.py -i demo.pptx -o portrait.mp4 --ratio 9:16 --narration-style explain --audio --subtitle

# 原 AI 创意模式显式开启
python main.py -i demo.pptx -o creative.mp4 --visual-mode creative --provider agnes --subtitle

# 仅字幕／自选音乐／关闭音乐
python main.py -i demo.pptx -o captions.srt --srt-only
python main.py -i demo.pptx -o music.mp4 --bgm assets/bgm/quiet_light.mp3
python main.py -i demo.pptx -o silent.mp4 --no-bgm
```

GUI：选择文件 → 保持“忠实讲解” → 设置画幅、声音 → “规划分镜” → 核对 → “确认并生成视频”。右上角三主题可随时切换，默认仍为简约浅色；主题不会影响已选文件、比例或音频设置。

三种 UI 均已细化：简约浅色为海军蓝/香槟金，柔和暖色为鼠尾草绿/暖铜，深色科技为靛蓝/雾紫。截图：[浅色](./artifacts/ui-themes/light.png)、[暖色](./artifacts/ui-themes/warm.png)、[深色](./artifacts/ui-themes/dark.png)、[实际 EXE](./artifacts/content-fidelity/exe-v2.2.0.png)。

低层 Python 调用可用 `generate_scene_plans(slides, visual_mode='faithful')` 创建计划，再传给 `compose_video(..., plans=plans)`。旧 `Director(slides)` 与没有忠实计划的 `compose_video` 调用仍保持旧模式语义。

## 边界与风险

- 忠实模式保存**已解析的信息**，不会逐像素复刻原 PPT 的全部字体、复杂形状、版式或动画；图片中的文字未额外 OCR。复杂 SmartArt/图表受解析能力限制。
- 备注进入讲解，不冒充正文卡片；图文版式优先使用可读的主图，并非逐一播放所有装饰或附图。
- 忠实讲解的转述采用保守连接词并保留完整事实；内容密集时不为了 40–80 字或目标总时长而删事实，因此实际时长可能增加。
- 字幕与重点强调在页内按来源位置、文本权重和实测语音时长估算；尚非逐词语音强制对齐。原页边界使用统一时间轴。
- Edge TTS 依赖网络；失败页会尝试本地语音，仍失败则保留静音画面和字幕，并在日志和内容清单记录，其他页不受影响。
- 创意模式继续允许 AI 视觉演绎，不承诺与原文严格一致；本轮用离线回归验证兼容路径，没有重新消耗付费视频生成服务。
- 本机配置的 HEVC NVENC 不可用，实际样片自动回退到 H.264/libx264 并通过完整解码；信息动画码率偏低是静态画面易压缩，不等同于黑屏。
- EXE 仍需要目标机器有 ffmpeg/ffprobe；本机已有。视频发布沿用输出目录的访问权限，不会擅自放宽用户主动设置的目录权限。

## 备份

本轮修改前备份集中在 [backups/fidelity-20260907-150438](./backups/fidelity-20260907-150438)，保留逐文件 `.bak`、旧 `out.mp4.bak`、`out.srt.bak` 和旧 `PPT转视频工具.exe.bak`。后续涉及的 TTS、主题、说明、测试脚本也在修改前补充了 `.bak`。旧有项目根目录 `.bak` 和此前 UI/release 备份均保留。

旧版视频及新片对照：旧片抽帧 [第 1 页](./artifacts/content-fidelity/before_1.png)、[第 2 页](./artifacts/content-fidelity/before_7.png)；新版抽帧 [第 1 页](./artifacts/content-fidelity/out_page1_middle.png)、[第 2 页](./artifacts/content-fidelity/out_page2_middle.png)。
