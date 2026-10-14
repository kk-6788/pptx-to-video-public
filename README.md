# pptx-to-video

## 2.4：原 PPT 页面与可编辑讲稿

- 忠实讲解现在直接播放 PowerPoint 导出的原页面，保留原排版。Windows 本机需要安装 Microsoft PowerPoint；没有渲染器时明确报错，不退回卡片重排。
- 规划后点击「编辑讲稿 / 试听」：逐页编辑、自动保存、撤销、恢复初稿、锁定、静音，保存 JSON 项目和导出讲稿。创意模式也显示实际台词。
- 「讲述场景」独立于画面风格：内部培训、外部会议、对外宣讲、工作汇报、教学讲解、产品介绍。
- 内容选择显示朗读方式与理由。修改选择后点击「按选择重建预览」，核对差异再应用；AI 重写也先预览，不覆盖锁定稿。
- 可在「文字模型设置」填写独立的兼容 OpenAI 接口，或使用 `NARRATION_API_BASE`、`NARRATION_API_KEY`、`NARRATION_MODEL` 环境变量。没有模型时明确使用保守规则，语义筛选/润色能力有限；不会要求图像或视频 API Key。
- 原比例默认完整显示，隐藏页默认排除。默认导出独立 SRT；开启画面字幕会预留页外字幕区。静态页面不回放 PPT 动画、转场或嵌入音视频，字体替换仍需预览核对。
- 配音读取最终讲稿，修改台词只使对应音频失效；创意画面按来源和视觉参数缓存。配音失败会明确报错，不把失败当静音成功。
- 临时文件、自动保存和缓存存放在 `work`。项目文件不包含 API 凭据。

```powershell
python main.py -i demo.pptx -o out.mp4 --audio --presentation-style internal-training --save-project work/script.json
python main.py -i demo.pptx -o out.mp4 --audio --project work/script.json
python main.py -i demo.pptx -o planned.srt --srt-only --presentation-style external-meeting
```

`--project` 恢复保存的模式与隐藏页选择。额外选项：`--script-length concise|standard|detailed`、`--notes-policy ignore|reference|prefer`、`--voice`、`--speech-rate`、`--include-hidden`。GUI 配音默认开启；CLI 继续使用 `--audio` 显式开启。`--srt-only` 不调用文本模型或配音。

以下为历史版本说明；2.4 的原页播放和可编辑讲稿行为以本节为准。

Version **2.3.0** refreshes the desktop workbench with three coordinated themes,
rounded panels, keyboard-accessible buttons, animated toggles, segmented aspect
ratios, state-based workflow steps and a responsive file selector with subtle
pointer lighting. Enable **减弱动效** in the header to remove animated feedback.
The UI uses existing tkinter/Pillow dependencies and requires no website connection.

The reusable [UI reference skill](skills/ui-reference-library/SKILL.md) covers
Uiverse, React Bits, Aceternity and verified GitHub resources, including licenses,
fixed commit references and a source download helper. See [UI delivery and validation](UI_REFERENCE_REPORT.md).

Turn PowerPoint source content into narrated information animations. Version 2.2 defaults to **忠实讲解 / faithful**: one scene per source page, original text and images, no image/video generation API. The optional **AI 创意演绎 / creative** mode preserves the previous provider pipeline.

Faithful mode exports a same-name `.content.json` recording source facts, image hashes, page order, narration status and actual scene timing. It preserves extracted information, not the original slide's exact typography or layout. UI themes (简约浅色 / 柔和暖色 / 深色科技) change the desktop appearance independently of the video mode.

## Prerequisites

- **Python 3.11+** (tested on 3.11 and 3.14), MoviePy v2, ffmpeg/ffprobe
- A provider API key only when using `--visual-mode creative`
- A `.pptx` file to convert

## Installation

```bash
pip install -r requirements.txt
```

## Getting a SiliconFlow API Key (Free)

1. Go to [https://cloud.siliconflow.cn](https://cloud.siliconflow.cn) and register an account.
2. Once logged in, navigate to **API Keys** (usually under your profile / account settings).
3. Click **Create API Key** and copy the key (it looks like `sk-xxx...xxx`).
4. Keep it secure — never commit it to git or share it publicly.

## Quick Start

Generate a faithful video locally (Edge TTS requires network when enabled):

```bash
python main.py --input demo.pptx --output out.mp4 --audio --subtitle
```

No image/video API key is requested in faithful mode. For the former AI generation workflow, add `--visual-mode creative --provider agnes` (or another configured provider). Creative visuals can add interpretations beyond the source PPT.

## API Key Sources (Priority Order)

For creative mode, the tool looks for the API key in three places, checked in this order:

### 1. Command Line (Highest Priority)

```bash
python main.py --input deck.pptx --output out.mp4 --api-key sk-xxx...xxx
```

Use this if you want a one-off key without saving it anywhere.

### 2. Environment Variable

```bash
# Linux / macOS
export SILICONFLOW_API_KEY=sk-xxx...xxx

# Windows (CMD)
set SILICONFLOW_API_KEY=sk-xxx...xxx

# Windows (PowerShell)
$env:SILICONFLOW_API_KEY="sk-xxx...xxx"

# Or add to a .env file in the project directory:
echo SILICONFLOW_API_KEY=sk-xxx...xxx > .env
```

### 3. Config File (Persistent)

The tool automatically saves keys to `~/.ppt2video_config.json` with restricted permissions (mode 0600). You can also create or edit this file manually:

```json
{
  "siliconflow_api_key": "sk-xxx...xxx"
}
```

Creative mode may prompt for a missing provider key. Faithful mode does not initialize generation providers.

## Usage

```
python main.py --input <file.pptx> --output <out.mp4> [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--input`, `-i` | *(required)* | Path to the input `.pptx` file |
| `--output`, `-o` | *(required)* | Path for the output `.mp4` |
| `--visual-mode` | `faithful` | Source content animation, or `creative` for provider-generated interpretation |
| `--api-key` | *(none)* | SiliconFlow API key (overrides env var & config file) |
| `--fps` | `24` | Frame rate of the output video |
| `--ratio` | `16:9` | Landscape `1280x720` or portrait `9:16` / `720x1280` |
| `--subtitle` | off | Burn slide text as subtitles into the video |
| `--srt-only` | off | Export an `.srt` using the local scene plan; skip API calls, TTS and video composition |
| `--narration-style` | `direct` | `direct` reads the slide content; `explain` rewrites it as conversational narration |
| `--audio`, `--tts` | off | Enable TTS narration |
| `--bgm` | `assets/bgm/bgm.mp3` | Use a custom background music file |
| `--no-bgm` | off | Disable background music; takes priority over `--bgm` |
| `--max-concurrent` | `3` | Maximum parallel API calls |
| `--dry-run` | off | Only parse the PPTX — do not generate or compose |
| `--verbose`, `-v` | off | Enable debug logging |

### Examples

```bash
# Faithful local content animation
python main.py -i pitch_deck.pptx -o pitch_video.mp4

# Explicit creative mode with a configured provider
python main.py -i deck.pptx -o out.mp4 --visual-mode creative --provider siliconflow --api-key sk-xxx...xxx

# With subtitles and 30 fps
python main.py -i deck.pptx -o out.mp4 --subtitle --fps 30

# Preview what will be extracted (no API calls)
python main.py -i deck.pptx -o out.mp4 --dry-run

# Limit parallelism to avoid rate limits
python main.py -i deck.pptx -o out.mp4 --max-concurrent 2

# Portrait video with conversational narration and subtitles
python main.py -i deck.pptx -o portrait.mp4 --ratio 9:16 --narration-style explain --audio --subtitle

# Export subtitles quickly without an API key or TTS (writes out.srt)
python main.py -i deck.pptx -o out.mp4 --srt-only --narration-style explain

# Use your own music, or disable it completely with --no-bgm
python main.py -i deck.pptx -o out.mp4 --bgm music.mp3
python main.py -i deck.pptx -o out.mp4 --audio --no-bgm

# Open the desktop interface
python gui.py
```

The GUI keeps the existing TTS checkbox and adds a ratio selector, **口播转述**
(conversational narration), a **BGM** checkbox, and a volume slider from 0–50%
(default 15%). Changing narration style after generating prompts takes effect
when video generation starts and preserves edited visual prompts.

Explicit `--provider` overrides provider defaults from the environment.
`--image-provider` and `--video-provider` can override each channel separately.

### Narration, subtitles and music

Each source slide has one scene entry containing its text, start time and
duration. A plan that groups several slides distributes its duration across
those slides; it does not repeat the whole group's narration on every page.
Scene start times accumulate in order, and subtitle cues stay within the
matching scene. The completed video and its companion `.srt` share this
timeline. With TTS enabled, measured speech duration can extend a scene;
narration is not looped or cut off to fit a shorter planned video clip.

`--srt-only` uses **planned durations**, without generating or measuring TTS.
Its timings can therefore differ from a later video rendered with narration.
`--dry-run` still stops immediately after parsing, even when combined with
`--srt-only` or `--analyze`.

The bundled `assets/bgm/bgm.mp3` is an original, locally synthesized ambient
track created for this project; it contains no sampled commercial recording.
Background music defaults to 15% volume and is fitted to the video duration.
If the music file is unavailable, composition continues without it. Use
`--bgm` for your own track or `--no-bgm` to disable music.

## Environment Variables

All configuration can be set via environment variables or a `.env` file in the project root:

```bash
# API Key (alternatives: --api-key flag or ~/.ppt2video_config.json)
SILICONFLOW_API_KEY=sk-xxx...xxx

# Optional — sensible defaults are provided
BASE_URL=https://api.siliconflow.cn
FPS=24
VIDEO_SIZE=1280x720
RATIO=16:9
BGM_PATH=assets/bgm/bgm.mp3
BGM_VOLUME=0.15
VIDEO_DURATION=5
MAX_CONCURRENT=3
MAX_RETRIES=3
RETRY_BASE_DELAY=1.0
POLL_INTERVAL=3.0
POLL_TIMEOUT=600
TEMP_DIR=./temp
SUBTITLE_FONT_SIZE=36
SUBTITLE_COLOR=white
SUBTITLE_BG_COLOR=black@0.5
```

## Architecture

```
pptx-to-video/
├── main.py              CLI entry point (argparse + asyncio.run)
├── pptx_parser.py       Extract slides → Slide dataclasses
├── video_generator.py   SiliconFlow API client (async/await)
├── video_composer.py    moviepy concatenation + subtitles
├── config.py            .env loading + API key resolution + constants
├── requirements.txt     Python dependencies
└── README.md            This file
```

### Pipeline

```
┌──────────┐     ┌──────────────┐     ┌──────────────┐
│  Parse   │ ──▶ │   Generate   │ ──▶ │   Compose    │
│  PPTX    │     │  video clips │     │  final .mp4  │
└──────────┘     └──────────────┘     └──────────────┘
```

## How it works

### Phase 1 — Parse (`pptx_parser.py`)

Each slide is read with **python-pptx**. The parser extracts:

- **Title** from the title placeholder
- **Body text** from content placeholders (formatted as a markdown bullet list)
- **Images** saved to `./temp/images/`
- **Text boxes, grouped shapes, tables, charts and SmartArt text**, with speaker notes stored separately and included in full text

Slides without titles, body text, or images are handled gracefully.

### Phase 2 — Generate (`video_generator.py`)

For each slide, one of two paths is taken:

1. **Image → Video** (slide has images): The first image is base64-encoded and sent to the **seedance-2.0** model as an image-to-video task.
2. **Text → Image → Video** (no images): Slide text is sent to **seedream-250** to generate a product image, which is then animated by **seedance-2.0**.

Key behaviours:

- **Three API key sources** — CLI `--api-key`, `SILICONFLOW_API_KEY` env var, or `~/.ppt2video_config.json` config file (mode 0600).
- **Interactive setup** — if no key is found, the tool prompts you and saves it.
- **Retry with exponential backoff** on 429 (rate limit) and 5xx errors (max 3 retries).
- **Concurrency control** via an `asyncio.Semaphore` — configurable with `--max-concurrent`.
- **Status polling** — video tasks are submitted, then polled every few seconds until complete (or a 10-minute timeout).
- Generated clips are saved to `./temp/clips/`.

### Phase 3 — Compose (`video_composer.py`)

- All generated clips are loaded with **moviepy**.
- **Fallback clips**: failed or black generated clips become light gradient layouts with Chinese titles, progressive bullet reveals and a main image. Horizontal layouts place the image on the right; portrait layouts put it above the body.
- **Subtitles**: cues follow the shared scene timeline; `--subtitle` also burns them into the video. An `.srt` is exported alongside the completed MP4.
- Clips are **concatenated** in slide order and encoded with **H.264 / AAC**.
- Temp files are cleaned up after a successful compose.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `No SiliconFlow API key found` | Run without a key to trigger interactive setup, or use `--api-key` |
| `FileNotFoundError: PPTX file not found` | Check the `--input` path |
| API returns 429 repeatedly | Reduce `--max-concurrent` to 1 or 2 |
| Video generation times out | Increase `POLL_TIMEOUT` in `.env` |
| `moviepy` font errors | Install a system font or set a different font in `config.py` |

## License

MIT

## Upgrade verification

See [the Chinese upgrade and acceptance report](./UPGRADE_REPORT.md)
for file changes, the ten executed acceptance checks, generated examples,
CLI usage, known limitations and `.bak` backup locations.

## Desktop appearance

Run `python gui.py` and choose **界面主题** in the top-right corner:

- **简约浅色** — default; white panels and blue actions.
- **柔和暖色** — warm paper surfaces and a muted brown accent.
- **深色科技** — blue-gray surfaces and a cyan accent.

The choice applies immediately and is remembered in `ui_preferences.json`
beside the application. This file stores only appearance, never API keys.
Switching themes preserves your files, conversion settings and generated text.
The separate **画面风格** option continues to control generated video styling.

Settings scroll on the left; primary actions remain fixed at the bottom.
The desktop window supports 1000×720 and larger sizes. No new UI dependency
is required. See [UI screenshots and verification](./UI_THEMES_REPORT.md).

## Windows executable

The updated Windows GUI is available at `dist/PPT转视频工具.exe`. Double-click it to run; Python is bundled. The build includes the three UI themes, TTS modules and three BGM tracks. Existing external `.env` settings are preserved. See [release verification](./RELEASE_REPORT.md).
