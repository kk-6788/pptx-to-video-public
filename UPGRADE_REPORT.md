# PPTX 转视频升级验收报告

完成日期：2026-09-07。项目：`<项目目录>`。

八项功能已实现，十项验收均已实际执行；Python 3.11 和 3.14 各通过 48 项自动测试。已生成真实横屏、竖屏、中文配音和 Agnes 视频，GUI 实际启动通过。全部 10 个修改过的原文件都有修改前备份，SHA-256 校验通过。

## 可直接查看的结果

- [中文口播 + 浅色动画 + 字幕 + BGM，19.79 秒](./artifacts/acceptance/out.mp4)
- [上述视频的可编辑字幕](./artifacts/acceptance/out.srt)
- [Agnes 实际生成的横屏视频，10 秒](./out.mp4)：按用户指定命令运行，包含字幕和 BGM；该命令没有 `--audio`，所以这份没有 TTS。
- [竖屏图文视频，720×1280](./artifacts/acceptance/out_9x16.mp4)：红色主图是测试图片，用于验证图片排序和布局。
- [GUI 实际窗口截图](./artifacts/acceptance/gui.png)
- [纯字幕导出](./artifacts/acceptance/subtitles_only.srt)

## 文件 → 改动点 → 原因

行号对应本次交付版本；同一文件的多个入口以文字列出。

| 文件和入口 | 改动点 | 原因 |
|---|---|---|
| [pptx_parser.py:36](./pptx_parser.py:36)，174、211、239、303、328、340、379 | `Slide.notes` 默认空串；递归组合形状及其坐标变换；标题/普通文本框；表格逐行要点；图表分类和数值；SmartArt 关系 XML；备注补充 `text_content`；源图/显示尺寸过滤和面积排序；逐页统计日志 | 修复真实 PPT 内容丢失；保留数字精度、原数据字段及旧构造方式。SmartArt 通常没有可直接读取的 `text_frame`，因此补充读取其关联 XML |
| [video_composer.py:49](./video_composer.py:49)，62、72、127、217 | 浅色微动渐变、白色半透明面板、深色中文标题与正文；要点淡入；横屏右图、竖屏上图；字符及像素双重换行；长内容分页；文字上下留白 | 避免近黑背景、截字和数字被裁掉，让图文内容可读；使用 MoviePy v2 和微软雅黑字体路径 |
| [video_composer.py:234](./video_composer.py:234)，259、295、410、428 | 按原始 PPT 页建立统一时间轴；逐段配音；最多压到原时长 80%，仍过长则延长画面；段落字幕和 BOM SRT；失败时全局仅朗读一次 | 消除配音循环、截句和页间时钟错位；字幕保留全部讲解文字 |
| [video_composer.py:320](./video_composer.py:320)，355、387、391、653 | ffmpeg 定时采样 + PIL 灰度均值；输入片段首/中/尾预检；黑片自动 fallback；最终 ≥2 秒黑段 ERROR；工具缺失时跳过 | 在输入和输出两处发现异常黑画面。采样返回所有亮度值，保留亮帧才能正确划分连续黑段 |
| [video_composer.py:470](./video_composer.py:470)，490、503、514 | BGM 循环/淡入淡出/音量；有配音默认 8%、无配音 30%；白底等比适配；重叠转场；编码器降级；临时文件和资源关闭；分组生成片段按页切分 | 无配音也能有音乐；防止转场闪黑、生成视频拉伸、整组视频只用于第一页及后续页内容丢失 |
| [tts_audio.py:24](./tts_audio.py:24)，53、123、241、276、304 | 去列表符号、保留数值；免费本地 `direct/explain` 转述；逐场景 `scene_XXX.mp3`、实测时长、独立失败返回 `None`；Edge 超时重试；旧全局接口保留 | 提供自然一些的中文讲解，避免数字/结论丢失；不依赖付费文案 API，旧调用仍可用 |
| [prompt_engine.py:38](./prompt_engine.py:38)，155、835、928、1504、1624、2361 | 横竖屏提示词；场景 `narration_style`、`narration_text`、逐页讲解映射；ScriptWriter/Director 透传；修复从 1 开始的页码索引；去掉淡到黑的转场建议 | 让提示词、音频、字幕与同一页内容关联；分组计划不再漏页/错页 |
| [config.py:292](./config.py:292)，300、345 | `RATIO` / `set_ratio()` / `VIDEO_SIZE`；`BGM_PATH` / `BGM_VOLUME`；浅色默认值；打包资源路径 | 同时支持 1280×720 和 720×1280；统一 GUI、CLI 和合成器配置 |
| [main.py:66](./main.py:66)，144、271、303、371 | 新 CLI 参数；SRT-only 提前走本地分支；合成放在线程中；图像/视频 provider 显式参数优先级修复；补齐分析分支导入 | 无需 API 即可导字幕；避免异步入口中嵌套事件循环；用户指定 provider 能准确生效 |
| [gui.py:230](./gui.py:230)，819、1603、1748、1807、1959 | 增加比例下拉、口播转述、BGM 和 0–50% 滑条；默认 16:9 / 不转述 / 开 BGM 15%；主线程读取控件后传入工作线程；编辑提示词后可刷新讲解稿 | 保留现有 GUI 布局和 TTS 勾选行为，让新选项真正进入合成流程；生成全部失败时仍可输出 fallback |
| [video_generator.py:316](./video_generator.py:316) | 通过 `Slide.index` 映射寻找源页 | 修复首图/分组场景可能引用下一页图片或越界的问题 |
| [PPT转视频工具.spec:4](./PPT转视频工具.spec:4) | 添加 BGM 资源和 TTS 隐式导入 | 后续重新打包时带上新资源；后续已于 2026-09-07 重新构建 EXE |
| [README.md:88](./README.md:88)，118、138 | 参数表、使用示例、时间轴和 BGM 说明、报告链接 | 说明新功能与现有默认行为 |

新增文件：

| 文件 | 内容及用途 |
|---|---|
| [assets/bgm/generate_bgm.py:14](./assets/bgm/generate_bgm.py:14) | 从振荡器、和弦与稀疏铃音合成音乐，无第三方录音采样 |
| [assets/bgm/README.md:1](./assets/bgm/README.md:1) | 三首曲目的来源、许可、生成与音量说明；同目录新增 `bgm.mp3`、`gentle_steps.mp3`、`quiet_light.mp3`，各 45 秒 |
| [tests/test_parser_upgrade.py:1](./tests/test_parser_upgrade.py:1) | 表格、图表数字精度、SmartArt、组内坐标、备注与图片过滤；配套 `tests/fixtures/smartart_data.xml` |
| [tests/test_narration_upgrade.py:1](./tests/test_narration_upgrade.py:1) | 讲解稿、保留数字/结论、TTS 成功与失败返回值 |
| [tests/test_composer_upgrade.py:1](./tests/test_composer_upgrade.py:1) | 亮色画面、黑段、BOM、字幕完整性、音频延时、失败降级，以及分组片段真实解码 |
| [tests/test_entrypoints_upgrade.py:1](./tests/test_entrypoints_upgrade.py:1) | CLI 新参数、纯 SRT 分支、provider 参数优先级 |
| [tests/test_generator_upgrade.py:1](./tests/test_generator_upgrade.py:1) | 真实页码对应正确源图片 |
| [tools/acceptance.py:1](./tools/acceptance.py:1) | `media / tts / full / gui / grouped` 五种可复跑验收，输出日志、JSON、MP4、MP3 和截图 |
| [实施计划](./docs/superpowers/plans/2026-09-06-pptx-video-upgrade.md:1)、本报告 | 记录实施范围、验收证据与限制 |

## 十项验收：命令和实际结果

以下命令工作目录均为 `<项目目录>`。`python` 在本机 PATH 中指向 Python 3.11.15；配音和 GUI 也用实际 Python 3.14.5 执行。PowerShell 指定 3.14 的方式：

```powershell
$py314 = '<用户目录>\AppData\Local\Python\pythoncore-3.14-64\python.exe'
```

| 验收 | 实际执行命令 | 输出摘要与证据 |
|---|---|---|
| 1. PPT 解析 | `python main.py -i demo.pptx -o out.mp4 --dry-run`；`python tools/acceptance.py media` | demo 两页标题均读出，正文由旧版 0/0 行变为 2/4 行；日志含表格、图片、备注统计。原 demo 没有表格/图片/备注，不能凭空增加。另建 7 页复杂样例：表格 1 个、备注 37 字符、过滤后图片 3 张、组合形状/图表/SmartArt 内容均提取。[日志](./artifacts/acceptance/media.log) |
| 2. Fallback | `python tools/acceptance.py media`，内部直接调用 `_make_fallback_clip(..., 5)`，并用 ffprobe/ffmpeg 验证 | `fallback_5s.mp4` 为 5 秒、1280×720、H.264；逐秒灰度均值约 241.14–243.65，明显明亮；旧背景 RGB 均值约 32.50。横竖图文均抽帧目视检查。[结果](./artifacts/acceptance/media.json) |
| 3. 三段 TTS | `& $py314 tools/acceptance.py tts` | 实际 Edge TTS 生成 `scene_001.mp3` / `002` / `003`，时长 11.52 / 12.79 / 13.25 秒，全部非空可解码。demo 只有两页，第三页使用明确新增的数据样例，未冒充原 demo 第三页。[逐段结果及文本](./artifacts/acceptance/tts_verified.json) |
| 4. 黑屏检测 | `python tools/acceptance.py media`；内部执行 `ffmpeg -y -v error -f lavfi -i color=black:s=1280x720:r=24:d=3 -c:v libx264 artifacts/acceptance/black_3s.mp4` | 0/1/2 秒亮度均为 0，识别黑段 0–3 秒；最终检测输出预期 ERROR。作为输入时出现“检测到黑片，已用 fallback 替换”。正常浅色片无误报，转场附近 17 帧均明亮；缺 ffmpeg 的降级另由测试覆盖 |
| 5. 9:16 | `python main.py -i demo.pptx -o out_9x16.mp4 --ratio 9:16 --dry-run`；`python tools/acceptance.py media` | dry-run 通过；实际图文视频 `artifacts/acceptance/out_9x16.mp4` 经 ffprobe 为 720×1280，字幕在底部，图片在文字上方。另实测普通生成片段等比适配竖屏且 `add_bgm=False` 时无音轨 |
| 6. SRT | `python main.py -i demo.pptx -o artifacts/acceptance/subtitles_only.mp4 --srt-only --ratio 9:16 --narration-style explain` | 未生成视频、未调 API/TTS，输出同名 `.srt`：UTF-8 BOM，4 条字幕 / 8 文本行，中文和 `HH:MM:SS,mmm --> HH:MM:SS,mmm` 正确；自动测试覆盖分钟进位。[日志](./artifacts/acceptance/srt_only.log) |
| 7. 口播转述 | `& $py314 tools/acceptance.py tts`，内部调用 `ScriptWriter(..., narration_style='explain').write()` | 三页均有逐页转述稿，样例均为 40–80 个汉字，不以“首先/其次/最后”开头，保留 35%、20% 等数字与后续结论。见下方抽样 |
| 8. BGM | `python assets/bgm/generate_bgm.py`；`python tools/acceptance.py media` | 三首均 45 秒、44.1 kHz 双声道、128 kbps MP3；无 TTS 的 `black_replaced_bgm.mp4` 仍有 AAC 音轨；另测 50 秒循环、第 46 秒非静音，文件不存在静默跳过 |
| 9. 全流程 | `python main.py -i demo.pptx -o out.mp4 --provider agnes --subtitle --ratio 16:9`；`& $py314 tools/acceptance.py full` | Agnes 实际生成成功，最终 10 秒、1280×720、约 6.79 MB，有 BGM 和 SRT，无 ≥2 秒黑段；429 重试后恢复。另完成不调用视频生成 API 的纯 fallback + Edge 中文转述 + 烧录字幕 + BGM 全链路：19.790998 秒，AAC 双声道，音频 RMS 0.2627。[Agnes 日志](./artifacts/acceptance/cli_agnes.log)、[配音成片结果](./artifacts/acceptance/full.json) |
| 10. GUI | `python gui.py`；`& $py314 gui.py`；`& $py314 tools/acceptance.py gui` | 两个解释器均实际启动；最终 3.14 启动后存活 4 秒、stderr 为空，随后测试主动关闭窗口。新控件存在，默认 16:9 / 转述关闭 / BGM 开启 / 15%；可切换 9:16、转述与 25% 音量，回调异常 0 个。[最终启动记录](./artifacts/acceptance/gui_entrypoint.json)、[控件记录](./artifacts/acceptance/gui.json) |

转述抽样（来自实际 TTS 输入）：

> 接下来，我们一起看一下核心功能。这一页提到的内容包括智能识别与理解、毫秒级响应速度、多语言自然交互，以及安全可靠的架构。

> 这页讲的是经营结果验收样本。转化率提升了35%，服务成本下降了20%。下一阶段继续优化服务，保持现有客户支持。

额外回归：

```powershell
python -m unittest discover -s tests -v
& $py314 -m unittest discover -s tests -v
python tools/acceptance.py grouped
```

两个解释器均为 `Ran 48 tests ... OK`：[3.11 日志](./artifacts/acceptance/unittest_py311.log)、[3.14 日志](./artifacts/acceptance/unittest_py314.log)。分组片段测试实际编码 3 秒视频，第 0.65 / 1.65 / 2.65 秒依次为红 / 绿 / 蓝，三条字幕各对应原始一页，证明后两页未丢失。最终编译检查 32 个 Python 文件全部通过，10 份原文件备份及归档副本哈希全部匹配：[检查记录](./artifacts/acceptance/final_checks.json)。

## 新功能使用

```powershell
# 竖屏 + 中文口播转述 + 烧录字幕/同名 SRT + 默认 BGM
python main.py -i demo.pptx -o portrait.mp4 --provider agnes --ratio 9:16 --audio --narration-style explain --subtitle

# 横屏直接朗读，关闭 BGM
python main.py -i demo.pptx -o direct.mp4 --provider agnes --ratio 16:9 --audio --narration-style direct --subtitle --no-bgm

# 只导字幕，后缀自动改成 .srt；无需视频生成 API
python main.py -i demo.pptx -o captions.mp4 --srt-only --narration-style explain

# 选择另一首内置音乐
python main.py -i demo.pptx -o music.mp4 --provider agnes --bgm assets/bgm/quiet_light.mp3

# 图形界面
python gui.py
```

`--ratio` 默认 `16:9`；`--narration-style` 默认 `direct`；`--audio`（别名 `--tts`）才启用朗读，仅指定 `explain` 不会自动打开声音；`--subtitle` 同时烧录并导出 SRT；默认有 BGM 文件就播放，`--no-bgm` 优先于 `--bgm`。GUI 保留原“配音 (TTS)”勾选框，并增加“口播转述”、比例、BGM 与音量滑条。基础音量默认 15%，配音时使用 8%，无配音时使用 30%；滑条为 0 时关闭音乐。

不调用视频生成 API 的生产调用也可直接使用现有 Python 接口：

```python
import config
from pptx_parser import parse_pptx
from prompt_engine import Director
from video_composer import compose_video

config.set_ratio('9:16')
slides = parse_pptx('demo.pptx')
plans = Director(slides, narration_style='explain').plan()
compose_video(slides, [], 'local.mp4', plans=plans,
              add_audio=True, add_subtitles=True, narration_style='explain')
```

## 环境与实际限制

- 本机 PATH 的 `python` 是 Python 3.11.15，指定路径的 Python 是 3.14.5。3.14 原先缺少 edge-tts，现已安装 7.2.8；MoviePy 实测为 2.1.2，Pillow 为 12.2.0，与用户描述的小版本略有差异。代码采用 v2 API，两套解释器均已测试。
- Edge TTS 免费但需要联网；逐段失败会 warning 并尝试旧全局模式，Windows 还保留 SAPI 降级。网络或语音引擎全部不可用时无法保证生成配音，视频仍可输出。没有用付费 API 实现新功能。
- `explain` 是本地规则转述，适合已有事实和要点的口语化整理，不会凭空补充业务事实。极短页面可能少于 40 字；数字/关键结论非常密集的页面会优先保留事实，可能超过 80 字，并记录警告。
- 配音最长仅压缩到原时长的 80%，之后会延长该页视频，所以实际成片可能长于计划。字幕按讲解段落字符比例分配，未实现逐字强制对齐；`--srt-only` 使用计划时长，可能与后来实际生成 TTS 的成片不同。
- 黑段检测是亮度启发式：输入只抽首/中/尾，成片默认每秒采样；无法保证发现所有极短闪黑，正常暗景也可能触发阈值。最终检测记录 ERROR，不会在编码后自动重做整个成片。
- 解析覆盖文本结构；扫描图片里的文字没有新增 OCR，特殊厂商扩展的 SmartArt/OLE 对象可能仍需人工检查。动画按提取内容重排，不复刻 PowerPoint 的原始动画效果。AI 视频的语义准确性仍取决于原 provider。
- 本机 `hevc_nvenc` 实测返回参数错误，已验证自动回退 `libx264` 输出 H.264。静态浅色画面压缩率高，可能触发低码率 WARNING，但抽帧及黑段检测正常。
- 后续发布更新：`.spec` 已添加资源，`dist/PPT转视频工具.exe` 已于 2026-09-07 重新打包并实际启动通过；详见 `RELEASE_REPORT.md`。

## 备份位置

修改前已备份以下原文件，全部在 `<项目目录>` 原文件旁边：

`config.py.bak`、`pptx_parser.py.bak`、`tts_audio.py.bak`、`prompt_engine.py.bak`、`video_composer.py.bak`、`main.py.bak`、`gui.py.bak`、`README.md.bak`、`video_generator.py.bak`、`PPT转视频工具.spec.bak`。

另有完整归档目录 [backups/20260906-162307](./backups/20260906-162307)；原有旧 `.bak` 使用 `.previous.bak` 保留。[manifest.json](./backups/20260906-162307/manifest.json) 记录原文件和备份 SHA-256，最终再次验证全部 10 项匹配。新增文件单独列在本报告中，不覆盖任何旧备份。
