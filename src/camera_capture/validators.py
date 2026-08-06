"""Shared validation and normalization helpers for camera workflows."""

from __future__ import annotations

from capture_shared.errors import ConfigurationError

from .models import CaptureConfig

_ALLOWED_BACKENDS = {"opencv", "gstreamer"}
_ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "bmp"}


def validate_positive_duration(duration_seconds: float) -> None:
    if duration_seconds <= 0:
        raise ConfigurationError("duration_seconds must be greater than 0")


def validate_camera_index(camera_index: int) -> None:
    if camera_index < 0:
        raise ConfigurationError("camera_index must be >= 0")


def normalize_backend(capture_backend: str) -> str:
    backend = capture_backend.lower().strip()
    if backend not in _ALLOWED_BACKENDS:
        raise ConfigurationError("capture_backend must be one of: opencv, gstreamer")
    return backend


def normalize_image_extension(image_extension: str) -> str:
    normalized_extension = image_extension.lower().lstrip(".")
    if normalized_extension not in _ALLOWED_IMAGE_EXTENSIONS:
        raise ConfigurationError(
            f"image_extension must be one of: {', '.join(sorted(_ALLOWED_IMAGE_EXTENSIONS))}"
        )
    return normalized_extension


def normalize_fourcc(fourcc: str | None) -> str | None:
    if fourcc is None:
        return None
    normalized_fourcc = fourcc.upper()
    if len(normalized_fourcc) != 4:
        raise ConfigurationError("fourcc must be exactly 4 characters")
    return normalized_fourcc


def camera_open_error(camera_index: int) -> str:
    return (
        f"Unable to open camera at index {camera_index}. "
        "Check USB connection and camera permissions."
    )


def validate_capture_config(config: CaptureConfig) -> tuple[str, str]:
    validate_positive_duration(config.duration_seconds)

    if config.fps <= 0:
        raise ConfigurationError("fps must be greater than 0")
    validate_camera_index(config.camera_index)
    if config.warmup_frames < 0:
        raise ConfigurationError("warmup_frames must be >= 0")
    if config.write_queue_size <= 0:
        raise ConfigurationError("write_queue_size must be greater than 0")
    if config.frame_width is not None and config.frame_width <= 0:
        raise ConfigurationError("frame_width must be greater than 0 when provided")
    if config.frame_height is not None and config.frame_height <= 0:
        raise ConfigurationError("frame_height must be greater than 0 when provided")

    backend = normalize_backend(config.capture_backend)
    normalized_extension = normalize_image_extension(config.image_extension)
    normalize_fourcc(config.fourcc)
    return backend, normalized_extension
