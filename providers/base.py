"""
Base classes and data models for the provider abstraction layer.

All image / video generation backends inherit from :class:`GenerationProvider`.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums & Data models
# ---------------------------------------------------------------------------


class ProviderCapability(str, Enum):
    """Capabilities a provider may support."""

    TEXT_TO_IMAGE = "text_to_image"
    """Can generate images from text prompts."""

    IMAGE_TO_VIDEO = "image_to_video"
    """Can generate videos from an image (+ optional text prompt)."""

    TEXT_TO_VIDEO = "text_to_video"
    """Can generate videos directly from text (no input image needed)."""

    POLLING_STATUS = "polling_status"
    """Generation is async — requires polling for completion."""

    SYNCHRONOUS = "synchronous"
    """Generation returns immediately (no polling needed)."""


@dataclass
class ProviderCapabilities:
    """Describes what a provider can do and its defaults."""

    name: str
    display_name: str = ""
    capabilities: set[ProviderCapability] = field(default_factory=lambda: {
        ProviderCapability.TEXT_TO_IMAGE,
        ProviderCapability.IMAGE_TO_VIDEO,
        ProviderCapability.POLLING_STATUS,
    })
    default_image_model: str = ""
    default_video_model: str = ""
    supported_image_models: list[str] = field(default_factory=list)
    supported_video_models: list[str] = field(default_factory=list)
    """Max prompt length in characters (0 = unlimited)."""
    max_prompt_length: int = 1024
    """Whether an API key is required."""
    requires_api_key: bool = True
    """Whether a base URL is configurable."""
    configurable_base_url: bool = False
    """Human-readable description."""
    description: str = ""

    def __post_init__(self) -> None:
        if not self.display_name:
            self.display_name = self.name.title()


@dataclass
class GenerationResult:
    """Result of a successful generation."""

    data: bytes
    """Raw binary data of the generated media."""

    mime_type: str = "image/png"
    """MIME type of the data."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional metadata (duration, dimensions, etc.)."""


class ProviderError(Exception):
    """Raised when a provider fails during generation."""

    def __init__(self, message: str, provider: str = "") -> None:
        self.provider = provider
        super().__init__(f"[{provider}] {message}" if provider else message)


class AcceptedTaskError(ProviderError):
    """Generation was accepted: callers must not submit a replacement task."""

    def __init__(self, message: str, provider: str, *, request_id: str,
                 model: str = "", result_url: str = "") -> None:
        self.request_id = request_id
        self.model = model
        self.result_url = result_url
        super().__init__(message, provider)


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------


class GenerationProvider(ABC):
    """Abstract base for all image/video generation backends.

    Subclasses must implement :meth:`generate_image` and at least one
    video-generation method.
    """

    def __init__(self, api_key: str = "", **kwargs: Any) -> None:
        self._api_key = api_key

    def cache_identity(self) -> dict:
        """Credential-free identity of the resolved generation configuration.

        Built-in providers store resolved model/endpoint values in these fields.
        Custom providers with other output settings should extend this contract.
        """
        identity = {'class': f'{type(self).__module__}.{type(self).__qualname__}'}
        for name in ('image_model', 'video_model', 'model'):
            value = getattr(self, '_' + name, getattr(self, name, ''))
            if isinstance(value, (str, int, float, bool)):
                identity[name] = value
        endpoint = getattr(self, '_base_url', getattr(self, 'base_url', ''))
        if not endpoint:
            endpoint = getattr(getattr(self, '_client', None), 'base_url', '')
        if endpoint:
            parts = urlsplit(str(endpoint))
            identity['endpoint'] = [parts.scheme, parts.hostname, parts.port, parts.path]
        return identity

    # ── Capabilities ─────────────────────────────────────────────────────

    @classmethod
    @abstractmethod
    def capabilities(cls) -> ProviderCapabilities:
        """Return the capabilities descriptor for this provider."""
        ...

    # ── Image generation ────────────────────────────────────────────────

    @abstractmethod
    async def generate_image(
        self,
        prompt: str,
        *,
        model: str = "",
        size: str = "1280x720",
        **kwargs: Any,
    ) -> GenerationResult:
        """Generate an image from a text prompt.

        Args:
            prompt: Text description of the desired image.
            model: Model name (provider default if empty).
            size: Desired output size (e.g. ``"1280x720"``).
            **kwargs: Provider-specific options.

        Returns:
            A :class:`GenerationResult` with the image bytes.

        Raises:
            ProviderError: On generation failure.
        """
        ...

    # ── Video generation ────────────────────────────────────────────────

    async def generate_video(
        self,
        prompt: str,
        image_data: Optional[bytes] = None,
        *,
        model: str = "",
        size: str = "1280x720",
        duration: int = 5,
        **kwargs: Any,
    ) -> GenerationResult:
        """Generate a video from a prompt (and optionally an input image).

        The base implementation checks which capability is available and
        dispatches accordingly.  Subclasses may override this directly.

        Args:
            prompt: Text description of the desired video.
            image_data: Optional input image bytes (for image→video).
            model: Model name (provider default if empty).
            size: Desired output size (e.g. ``"1280x720"``).
            duration: Desired video duration in seconds.
            **kwargs: Provider-specific options.

        Returns:
            A :class:`GenerationResult` with the video bytes.

        Raises:
            ProviderError: On generation failure.
        """
        caps = self.capabilities()

        if image_data and ProviderCapability.IMAGE_TO_VIDEO in caps.capabilities:
            return await self._image_to_video(prompt, image_data, model=model, size=size, duration=duration, **kwargs)
        elif ProviderCapability.TEXT_TO_VIDEO in caps.capabilities:
            return await self._text_to_video(prompt, model=model, size=size, duration=duration, **kwargs)
        elif image_data:
            # Fallback: image → video via text-to-image-to-video bridge
            # (some providers only do text→image + image→video separately)
            return await self._image_to_video(prompt, image_data, model=model, size=size, duration=duration, **kwargs)
        else:
            raise ProviderError("No suitable video capability available", self.__class__.__name__)

    @abstractmethod
    async def _image_to_video(
        self,
        prompt: str,
        image_data: bytes,
        *,
        model: str = "",
        size: str = "1280x720",
        duration: int = 5,
        **kwargs: Any,
    ) -> GenerationResult:
        """Image → video (subclasses must implement)."""
        ...

    @abstractmethod
    async def _text_to_video(
        self,
        prompt: str,
        *,
        model: str = "",
        size: str = "1280x720",
        duration: int = 5,
        **kwargs: Any,
    ) -> GenerationResult:
        """Text → video (subclasses must implement)."""
        ...

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Clean up provider resources (HTTP clients, etc.)."""
        pass
