"""
Configuration and environment variable loading for pptx-to-video.

API Key resolution priority (highest first):
  1. In-memory cache (set via ``set_api_key()`` from ``--api-key`` CLI argument)
  2. ``SILICONFLOW_API_KEY`` environment variable
  3. ``~/.ppt2video_config.json`` config file

If none of the above yields a key and the caller calls ``resolve_api_key()``
with ``interactive=True``, the user will be prompted to enter one and the
result is saved to the config file.

Provider configuration
----------------------
The pipeline supports multiple generation backends:

- ``agnes`` — Agnes AI free-tier (text, image, video)
- ``siliconflow`` (default) — cloud API at ``BASE_URL``
- ``comfyui`` — local ComfyUI instance (free, GPU required)
- ``custom_api`` — any OpenAI-compatible endpoint

Set ``PROVIDER`` env var or pass ``--provider`` on the CLI to switch.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load .env — search multiple locations for EXE and dev-mode support
# ---------------------------------------------------------------------------
def _find_env_file() -> Path | None:
    """Search for .env in priority order."""

    # 1. Explicit override via env var
    explicit = os.getenv("PPTX_TO_VIDEO_ENV")
    if explicit:
        p = Path(explicit)
        if p.exists():
            return p

    # 2. Current working directory
    cwd = Path.cwd() / ".env"
    if cwd.exists():
        return cwd

    # 3. PyInstaller EXE directory (sys.executable or _MEIPASS)
    try:
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).parent
            exe_env = exe_dir / ".env"
            if exe_env.exists():
                return exe_env
    except Exception:
        pass

    # 4. Project root (parent of script location)
    try:
        script_dir = Path(__file__).resolve().parent
        project_env = script_dir / ".env"
        if project_env.exists():
            return project_env
    except Exception:
        pass

    return None


ENV_FILE = _find_env_file()
if ENV_FILE:
    load_dotenv(dotenv_path=ENV_FILE, override=True)
    logger.info("Loaded env from: %s", ENV_FILE)
else:
    load_dotenv()  # fall back to default search (PATH-based)
    logger.info("No .env found, using existing environment variables")

# ---------------------------------------------------------------------------
# Config file path  (~/.ppt2video_config.json)
# ---------------------------------------------------------------------------
CONFIG_FILE = Path.home() / ".ppt2video_config.json"

# ---------------------------------------------------------------------------
# In-memory API key cache (set via --api-key CLI argument)
# ---------------------------------------------------------------------------
_api_key_cache: str | None = None


def set_api_key(key: str) -> None:
    """Set the API key in the in-memory cache (used by the ``--api-key`` arg).

    This has the highest priority in :func:`resolve_api_key`.
    """
    global _api_key_cache
    _api_key_cache = key


def _load_from_config_file() -> str | None:
    """Read ``SILICONFLOW_API_KEY`` from ``~/.ppt2video_config.json``."""
    try:
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            key = data.get("siliconflow_api_key", "")
            if key:
                logger.debug("Loaded API key from config file: %s", CONFIG_FILE)
                return key.strip()
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read config file %s: %s", CONFIG_FILE, exc)
    return None


def _save_config_file(key: str) -> None:
    """Write the API key to ``~/.ppt2video_config.json`` with mode 0600."""
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {"siliconflow_api_key": key}
        CONFIG_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        # Set restricted permissions (POSIX; best-effort on Windows)
        try:
            CONFIG_FILE.chmod(0o600)
        except Exception:
            pass  # Windows doesn't support POSIX chmod meaningfully
        logger.info("API key saved to %s (mode 0600)", CONFIG_FILE)
    except OSError as exc:
        logger.warning("Failed to save config file %s: %s", CONFIG_FILE, exc)


def _interactive_prompt() -> str:
    """Prompt the user to enter their SiliconFlow API key interactively.

    The entered value is saved to the config file before returning.
    """
    print("=" * 60, file=sys.stderr)
    print("  SiliconFlow API Key Required", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(file=sys.stderr)
    print("  You need a SiliconFlow API key to generate videos.", file=sys.stderr)
    print("  Get one free at: https://cloud.siliconflow.cn", file=sys.stderr)
    print(file=sys.stderr)
    print("  Three ways to provide it:", file=sys.stderr)
    print("    1. --api-key SK-xxx...xxx  (command line)", file=sys.stderr)
    print("    2. set SILICONFLOW_API_KEY  (environment variable)", file=sys.stderr)
    print(file=sys.stderr)
    print("  Enter your key below, or press Ctrl+C to quit.", file=sys.stderr)
    print(file=sys.stderr)
    try:
        key = input("  API Key > ").strip()
    except (EOFError, KeyboardInterrupt):
        print(file=sys.stderr)
        print("  Aborted.", file=sys.stderr)
        sys.exit(1)
    if not key:
        print("  No key entered. Exiting.", file=sys.stderr)
        sys.exit(1)
    # Save for future runs
    _save_config_file(key)
    return key


def resolve_api_key(interactive: bool = False) -> str:
    """Resolve the SiliconFlow API key using the priority chain.

    Priority (highest first):
      1. In-memory cache (set via :func:`set_api_key`)
      2. ``SILICONFLOW_API_KEY`` environment variable
      3. ``~/.ppt2video_config.json`` config file
      4. Interactive prompt (if *interactive* is ``True``)

    Args:
        interactive: If ``True`` and no key is found, prompt the user
                     interactively and save to the config file.

    Returns:
        The resolved API key string.

    Raises:
        RuntimeError: If no key is found and *interactive* is ``False``.
    """
    # 1. In-memory cache
    if _api_key_cache:
        return _api_key_cache

    # 2. Environment variable
    env_key = os.getenv("SILICONFLOW_API_KEY", "").strip()
    if env_key:
        return env_key

    # 3. Config file
    cfg_key = _load_from_config_file()
    if cfg_key:
        return cfg_key

    # 4. Interactive prompt
    if interactive:
        return _interactive_prompt()

    raise RuntimeError(
        "No SiliconFlow API key found.\n"
        "  Provide it via:\n"
        "    python main.py --input demo.pptx --output out.mp4"
        " --api-key SK-xxx...xxx\n"
        "  Or set the environment variable:\n"
        "    export SILICONFLOW_API_KEY=SK-xxx...xxx\n"
        "  Or create a config file:\n"
        f"    {CONFIG_FILE}  (siliconflow_api_key: SK-xxx...xxx)\n"
        "\n"
        "  Get a free key at: https://cloud.siliconflow.cn\n"
    )


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------

PROVIDER: str = os.getenv("PROVIDER", "agnes")
"""Active generation provider: ``"siliconflow"``, ``"agnes"``, ``"kling"``, ``"volcengine"``, ``"comfyui"``, or ``"custom_api"``."""

# Separate image/video providers (override PROVIDER for each)
IMAGE_PROVIDER: str = os.getenv("IMAGE_PROVIDER", PROVIDER)
"""Image generation provider (overrides PROVIDER for image tasks)."""
VIDEO_PROVIDER: str = os.getenv("VIDEO_PROVIDER", PROVIDER)
"""Video generation provider (overrides PROVIDER for video tasks)."""

# New API keys for openai and gemini
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
"""OpenAI API key for DALL-E / GPT-based generation."""
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
"""Google Gemini API key for Gemini-based generation."""

# Provider-specific models — SiliconFlow
SILICONFLOW_IMAGE_MODEL: str = os.getenv("SILICONFLOW_IMAGE_MODEL", "Kwai-Kolors/Kolors")
SILICONFLOW_VIDEO_MODEL: str = os.getenv("SILICONFLOW_VIDEO_MODEL", "Wan-AI/Wan2.2-I2V-A14B")

# Provider-specific models — 可灵AI (Kling)
KLING_IMAGE_MODEL: str = os.getenv("KLING_IMAGE_MODEL", "kling-v1")
KLING_VIDEO_MODEL: str = os.getenv("KLING_VIDEO_MODEL", "kling-v1")

# Provider-specific models — 火山引擎 (Volcengine)
VOLC_IMAGE_MODEL: str = os.getenv("VOLC_IMAGE_MODEL", "doubao-vision-pro-32k")
VOLC_VIDEO_MODEL: str = os.getenv("VOLC_VIDEO_MODEL", "seed-video-v1")

COMFYUI_BASE_URL: str = os.getenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188")

CUSTOM_API_BASE_URL: str = os.getenv("CUSTOM_API_BASE_URL", "")
CUSTOM_API_IMAGE_MODEL: str = os.getenv("CUSTOM_API_IMAGE_MODEL", "")
CUSTOM_API_VIDEO_MODEL: str = os.getenv("CUSTOM_API_VIDEO_MODEL", "")

# ---------------------------------------------------------------------------
# ── Encoding config ──
VIDEO_CODEC: str = os.getenv("VIDEO_CODEC", "hevc_nvenc")
"""Video encoder codec.
   - "hevc_nvenc" → GPU (RTX 4060 NVENC, fast + good, needs NVIDIA GPU)
   - "libx265"    → CPU HEVC (slower, slightly better quality)
   - "libx264"    → CPU H.264 (most compatible, slowest)
"""
NVENC_PRESET: str = os.getenv("NVENC_PRESET", "p7")
"""NVENC quality preset: p1 (fastest) → p7 (best quality, default)."""
NVENC_CQ: int = int(os.getenv("NVENC_CQ", "20"))
"""NVENC constant quality level: 1-51, lower = better. 18-23 is good range."""
# ---------------------------------------------------------------------------

VISUAL_STYLE: str = os.getenv("VISUAL_STYLE", "auto")
"""Visual style for the Director engine.

One of: ``"auto"``, ``"modern luxury"``, ``"tech innovation"``, ``"nature organic"``,
``"fashion editorial"``, ``"corporate clean"``, ``"warm lifestyle"``.
"""

OVERALL_THEME: str = os.getenv("OVERALL_THEME", "")
"""Optional high-level theme description to guide the Director."""

# ---------------------------------------------------------------------------
# General configuration (non-secret)
# ---------------------------------------------------------------------------

BASE_URL: str = os.getenv("BASE_URL", "https://api.siliconflow.cn")
"""Base URL for the SiliconFlow API."""

# Video / generation defaults
FPS: int = int(os.getenv("FPS", "24"))
RATIO: str = os.getenv("RATIO", "16:9")
_RATIO_SIZES = {"16:9": "1280x720", "9:16": "720x1280", "1:1": "1080x1080"}
if RATIO not in _RATIO_SIZES:
    RATIO = "16:9"
# Preserve legacy custom VIDEO_SIZE when no ratio was explicitly configured.
VIDEO_SIZE: str = _RATIO_SIZES[RATIO] if "RATIO" in os.environ else os.getenv("VIDEO_SIZE", _RATIO_SIZES[RATIO])


def set_ratio(ratio: str) -> str:
    """Apply an output ratio to both composition and generation at runtime."""
    if ratio not in _RATIO_SIZES:
        raise ValueError("ratio must be '16:9', '9:16' or '1:1'")
    global RATIO, VIDEO_SIZE
    RATIO = ratio
    VIDEO_SIZE = _RATIO_SIZES[ratio]
    return VIDEO_SIZE

VIDEO_BITRATE: str = os.getenv("VIDEO_BITRATE", "5000k")
"""Video encode bitrate (e.g. '2000k', '3000k', '5000k'). Higher = better quality + larger file."""
VIDEO_DURATION: int = int(os.getenv("VIDEO_DURATION", "5"))

# Duration mode: "auto" (per-slide recommendation) or fixed int
DURATION_MODE: str = os.getenv("DURATION_MODE", "auto")
"""Duration mode: 'auto' → per-slide recommendation from summarizer, or numeric → fixed seconds."""

# Images per slide — how many keyframe images to generate per slide
IMAGES_PER_SLIDE: int = int(os.getenv("IMAGES_PER_SLIDE", "2"))
"""Number of keyframe images to generate per slide (4 = 4 angles per scene)."""

# Character & scene consistency
ENABLE_CONSISTENCY: bool = os.getenv("ENABLE_CONSISTENCY", "true").lower() in ("true", "1", "yes")
"""If True, Director maintains character/scene/style consistency across all slides."""

# Preview & feedback
ENABLE_PREVIEW: bool = os.getenv("ENABLE_PREVIEW", "true").lower() in ("true", "1", "yes")
"""If True, show preview after generation and allow feedback/edits."""

# Concurrency & retry
MAX_CONCURRENT: int = int(os.getenv("MAX_CONCURRENT", "1"))
MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
RETRY_BASE_DELAY: float = float(os.getenv("RETRY_BASE_DELAY", "1.0"))
POLL_INTERVAL: float = float(os.getenv("POLL_INTERVAL", "3.0"))
POLL_TIMEOUT: float = float(os.getenv("POLL_TIMEOUT", "3600.0"))

# Paths — use absolute path relative to script location or EXE directory
_SCRIPT_DIR = Path(__file__).resolve().parent
if getattr(sys, "frozen", False):
    # PyInstaller EXE — use EXE's own directory (persistent)
    _BASE_DIR = Path(sys.executable).resolve().parent
else:
    _BASE_DIR = _SCRIPT_DIR
TEMP_DIR: Path = Path(os.getenv("TEMP_DIR", str(_BASE_DIR / "work")))
_ASSET_DIR = Path(getattr(sys, "_MEIPASS", _BASE_DIR)) / "assets"
BGM_PATH: Path = Path(os.getenv("BGM_PATH", str(_ASSET_DIR / "bgm" / "bgm.mp3")))
BGM_VOLUME: float = max(0.0, min(0.5, float(os.getenv("BGM_VOLUME", "0.15"))))

# Legacy prompt prefixes (kept for backward compat but overridden by Director)
IMAGE_PROMPT_PREFIX: str = os.getenv(
    "IMAGE_PROMPT_PREFIX",
    "Professional product showcase, high quality, clean background: ",
)
VIDEO_PROMPT_PREFIX: str = os.getenv(
    "VIDEO_PROMPT_PREFIX",
    "Smooth cinematic motion, professional product video: ",
)

# Subtitle defaults
SUBTITLE_FONT_SIZE: int = int(os.getenv("SUBTITLE_FONT_SIZE", "36"))
SUBTITLE_COLOR: str = os.getenv("SUBTITLE_COLOR", "white")
SUBTITLE_BG_COLOR: str = os.getenv("SUBTITLE_BG_COLOR", "black@0.5")

# Fallback clip defaults
FALLBACK_BG_COLOR: tuple[int, int, int] = (245, 247, 250)
FALLBACK_TEXT_COLOR: str = os.getenv("FALLBACK_TEXT_COLOR", "#1F2937")
FALLBACK_DURATION: float = float(os.getenv("FALLBACK_DURATION", "3.0"))


def ensure_temp_dir() -> Path:
    """Create and return the temporary directory, creating parents as needed."""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    return TEMP_DIR
