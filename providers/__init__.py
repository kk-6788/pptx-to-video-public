"""
Provider registry — pluggable image / video generation backends.

Usage::

    from providers import get_provider
    provider = get_provider("siliconflow")
    image_b64 = await provider.generate_image("A cat")
    video_path = await provider.generate_video("cat running", image_b64)

Dual-provider usage::

    from providers import get_providers
    image_prov, video_prov = get_providers(
        image_provider="openai",
        video_provider="siliconflow",
        api_keys={"openai": "sk-...", "siliconflow": "..."},
    )
    image_b64 = await image_prov.generate_image("A cat")
    video_path = await video_prov.generate_video("cat running", image_b64)
"""

from __future__ import annotations

import logging
from typing import Optional

from providers.base import (
    GenerationProvider,
    GenerationResult,
    ProviderCapabilities,
    ProviderError,
)
from providers.agnes import AgnesProvider
from providers.siliconflow import SiliconFlowProvider
from providers.kling import KlingProvider
from providers.volcengine import VolcengineProvider
from providers.gemini import GeminiProvider

logger = logging.getLogger(__name__)

# Registry of available providers
# NOTE: openai is registered as a known name but its provider module
# has not been implemented yet. Attempting to use it will raise
# a NotImplementedError with a helpful message.
_BUILTIN_PROVIDERS: dict[str, type[GenerationProvider] | None] = {
    "agnes": AgnesProvider,
    "siliconflow": SiliconFlowProvider,
    "kling": KlingProvider,
    "volcengine": VolcengineProvider,
    "openai": None,       # not yet implemented — placeholder
    "gemini": GeminiProvider,
    # "comfyui": ComfyUIProvider,
    # "custom_api": CustomApiProvider,
}


def list_providers() -> list[str]:
    """Return the list of registered provider names."""
    return list(_BUILTIN_PROVIDERS.keys())


def provider_capabilities(name: str) -> Optional[ProviderCapabilities]:
    """Return capabilities for a given provider name."""
    cls = _BUILTIN_PROVIDERS.get(name)
    if cls is None:
        return None
    return cls.capabilities()


def get_provider(
    name: str,
    api_key: str = "",
    **kwargs,
) -> GenerationProvider:
    """Factory: return a provider instance by name.

    Args:
        name: Provider name (e.g. ``"siliconflow"``).
        api_key: API key (if applicable).
        **kwargs: Additional provider-specific config (model, base_url, etc.).

    Returns:
        An initialised :class:`GenerationProvider`.

    Raises:
        ValueError: If *name* is not registered.
        NotImplementedError: If *name* is a known placeholder that has no
            implementation yet (e.g. ``"openai"``, ``"gemini"``).
    """
    cls = _BUILTIN_PROVIDERS.get(name)
    if cls is None:
        valid = ", ".join(_BUILTIN_PROVIDERS)
        if name in _BUILTIN_PROVIDERS:
            raise NotImplementedError(
                f"Provider {name!r} is a registered placeholder but has not "
                f"been implemented yet. Available: {valid}"
            )
        raise ValueError(
            f"Unknown provider {name!r}. Available: {valid}"
        )

    logger.info("Initialising provider: %s (model=%s)", name, kwargs.get("model", "default"))
    return cls(api_key=api_key, **kwargs)


def get_providers(
    image_provider: str = "",
    video_provider: str = "",
    api_keys: dict[str, str] | None = None,
    image_kwargs: dict | None = None,
    video_kwargs: dict | None = None,
) -> tuple[GenerationProvider, GenerationProvider]:
    """Factory: return a tuple of ``(image_provider, video_provider)``.

    Supports separate providers for image and video generation.
    Falls back to a single provider for both if only one is specified.

    Args:
        image_provider: Name of the provider to use for image generation.
            If empty, falls back to *video_provider*.
        video_provider: Name of the provider to use for video generation.
            If empty, falls back to *image_provider*.
        api_keys: Dict mapping provider names to their API keys.
            E.g. ``{"openai": "sk-...", "siliconflow": "..."}``.
        image_kwargs: Extra kwargs for the image provider constructor.
        video_kwargs: Extra kwargs for the video provider constructor.

    Returns:
        A tuple of ``(image_provider_instance, video_provider_instance)``.
    """
    if api_keys is None:
        api_keys = {}
    if image_kwargs is None:
        image_kwargs = {}
    if video_kwargs is None:
        video_kwargs = {}

    # Resolve provider names — if one is empty, use the other for both
    if not image_provider and not video_provider:
        from config import IMAGE_PROVIDER, VIDEO_PROVIDER, PROVIDER
        image_provider = IMAGE_PROVIDER
        video_provider = VIDEO_PROVIDER
        if not image_provider:
            image_provider = PROVIDER
        if not video_provider:
            video_provider = PROVIDER
    elif not image_provider:
        image_provider = video_provider
    elif not video_provider:
        video_provider = image_provider

    # Resolve API keys
    img_key = api_keys.get(image_provider, "")
    vid_key = api_keys.get(video_provider, "")

    # If image and video use the same provider, share the API key
    if image_provider == video_provider:
        shared_key = img_key or vid_key
        img_key = vid_key = shared_key

    logger.info(
        "Dual providers: image=%s, video=%s",
        image_provider,
        video_provider,
    )

    img_prov = get_provider(image_provider, api_key=img_key, **image_kwargs)
    vid_prov = get_provider(video_provider, api_key=vid_key, **video_kwargs)

    return img_prov, vid_prov


def register_provider(name: str, provider_cls: type[GenerationProvider]) -> None:
    """Register a custom provider at runtime.

    Args:
        name: Provider name (used to look it up later).
        provider_cls: A subclass of :class:`GenerationProvider`.
    """
    if name in _BUILTIN_PROVIDERS:
        logger.warning("Overwriting existing provider %r", name)
    _BUILTIN_PROVIDERS[name] = provider_cls
    logger.info("Registered provider: %s", name)
