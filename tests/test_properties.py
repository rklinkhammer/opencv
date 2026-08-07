"""Property-based tests for parsing, normalization, and output naming."""

from datetime import datetime
from pathlib import Path
import re
import tempfile

from hypothesis import given, strategies as st
import pytest

from camera_capture.validators import (
    normalize_backend,
    normalize_fourcc,
    normalize_image_extension,
)
from capture_shared.errors import ConfigurationError
from capture_shared.output import reserve_unique_path
from capture_shared.timestamps import format_filename_timestamp, format_iso_timestamp
from parallel_cli import _parse_gpio_spec


_NAMES = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), max_codepoint=127),
    min_size=1,
    max_size=20,
)


@given(
    chip=_NAMES,
    line_offset=st.integers(min_value=0, max_value=2**31 - 1),
    tag=_NAMES,
    edge=st.sampled_from(["rising", "falling", "both"]),
)
def test_gpio_spec_round_trip(chip: str, line_offset: int, tag: str, edge: str):
    job = _parse_gpio_spec(f"  {chip} : {line_offset} : {tag} : {edge.upper()}  ")

    assert (job.chip, job.line_offset, job.tag, job.edge) == (chip, line_offset, tag, edge)


@given(line_offset=st.integers(max_value=-1))
def test_gpio_spec_rejects_every_negative_offset(line_offset: int):
    with pytest.raises(ConfigurationError, match="must be >= 0"):
        _parse_gpio_spec(f"gpiochip0:{line_offset}:door:both")


@given(
    backend=st.sampled_from(["opencv", "gstreamer"]),
    padding=st.text(alphabet=" \t", max_size=5),
)
def test_backend_normalization_is_case_and_whitespace_insensitive(backend: str, padding: str):
    assert normalize_backend(f"{padding}{backend.upper()}{padding}") == backend


@given(
    extension=st.sampled_from(["jpg", "jpeg", "png", "bmp"]),
    dot_count=st.integers(min_value=0, max_value=4),
)
def test_image_extension_normalization(extension: str, dot_count: int):
    assert normalize_image_extension("." * dot_count + extension.upper()) == extension


@given(
    fourcc=st.text(
        alphabet=st.characters(min_codepoint=32, max_codepoint=126), min_size=4, max_size=4
    )
)
def test_fourcc_normalization_preserves_four_character_contract(fourcc: str):
    normalized = normalize_fourcc(fourcc)

    assert normalized == fourcc.upper()
    assert len(normalized) == 4


@given(count=st.integers(min_value=1, max_value=20))
def test_reserved_output_paths_are_unique(count: int):
    with tempfile.TemporaryDirectory() as tmp_dir:
        paths = [reserve_unique_path(Path(tmp_dir), "frame", ".jpg") for _ in range(count)]

        assert len(paths) == len(set(paths)) == count
        assert all(path.exists() for path in paths)


@given(capture_time=st.floats(min_value=0, max_value=4_000_000_000, allow_nan=False))
def test_timestamp_formats_remain_parseable(capture_time: float):
    filename_timestamp = format_filename_timestamp(capture_time)
    iso_timestamp = format_iso_timestamp(capture_time)

    assert re.fullmatch(r"\d{8}T\d{6}_\d{3}[+-]\d{4}", filename_timestamp)
    assert datetime.fromisoformat(iso_timestamp).tzinfo is not None
