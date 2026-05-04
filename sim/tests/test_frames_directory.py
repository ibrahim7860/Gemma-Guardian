"""Asserts every `frame_file` referenced by a shipped scenario exists on disk
and is a structurally-valid, sensibly-sized JPEG.

Two failure modes the assertions guard against:

1. Scenario references a frame that's missing from sim/fixtures/frames/.
   When Thayyil swaps placeholder JPEGs for real xBD imagery, the file
   *names* must stay the same — this test enforces that. New scenario
   references without matching files fail before merge.
2. A swapped-in image is corrupt, empty, or single-pixel. Without these
   checks a broken file would only blow up at demo time when the drone
   agent passes it to Gemma 4 — the JPEG-sanity assertions surface the
   problem in CI instead.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, UnidentifiedImageError

from sim.scenario import load_scenario

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "scenarios"
FRAMES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "frames"

SHIPPED_SCENARIOS = [
    "disaster_zone_v1.yaml",
    "single_drone_smoke.yaml",
    "resilience_v1.yaml",
]

# The drone agent's perception node downsamples to 512×512 (docs/05). We
# pick 64×64 as the floor — small enough that any *intended* xBD crop
# clears it, large enough that an obviously-degenerate file (icon, single
# pixel, accidental thumbnail) trips the check.
MIN_DIMENSION_PX = 64

# JPEG SOI ("Start Of Image") marker is FF D8, immediately followed by
# another FF that introduces the next segment marker. Checking three bytes
# rules out accidentally-renamed PNG/GIF files that happen to share the
# first two bytes (PNG starts 89 50; GIF starts 47 49 — neither matches).
JPEG_SOI_PREFIX = b"\xff\xd8\xff"


def _shipped_jpegs() -> list[Path]:
    found = sorted(FRAMES_DIR.glob("*.jpg"))
    assert found, "no placeholder JPEGs found under sim/fixtures/frames/"
    return found


@pytest.mark.parametrize("scenario_name", SHIPPED_SCENARIOS)
def test_every_referenced_frame_exists(scenario_name: str):
    scenario = load_scenario(SCENARIOS_DIR / scenario_name)
    referenced: set[str] = set()
    for mappings in scenario.frame_mappings.values():
        for mapping in mappings:
            referenced.add(mapping.frame_file)

    missing = [name for name in sorted(referenced) if not (FRAMES_DIR / name).exists()]
    assert not missing, f"frames missing for {scenario_name}: {missing}"


@pytest.mark.parametrize("path", _shipped_jpegs(), ids=lambda p: p.name)
def test_frame_is_non_empty(path: Path):
    """A zero-byte file would survive the magic-byte check below if we
    only read 0 bytes — guard against the swap producing an empty file."""
    assert path.stat().st_size > 0, f"{path.name} is empty"


@pytest.mark.parametrize("path", _shipped_jpegs(), ids=lambda p: p.name)
def test_frame_starts_with_jpeg_soi(path: Path):
    """SOI marker FF D8 followed by the FF of the next segment — rules
    out renamed PNG/GIF/empty/text files."""
    with path.open("rb") as fh:
        head = fh.read(3)
    assert head == JPEG_SOI_PREFIX, (
        f"{path.name} is not a JPEG (first 3 bytes={head!r}, expected {JPEG_SOI_PREFIX!r})"
    )


@pytest.mark.parametrize("path", _shipped_jpegs(), ids=lambda p: p.name)
def test_frame_dimensions_parse_via_pillow(path: Path):
    """Pillow must be able to open the file and report finite, sensible
    dimensions. ``Image.verify()`` parses headers without decoding pixels
    — fast and catches truncation."""
    try:
        with Image.open(path) as img:
            img.verify()  # parse header / structure
    except (UnidentifiedImageError, OSError) as e:
        pytest.fail(f"{path.name} did not parse as an image: {e}")
    # verify() leaves the image in an unusable state; reopen for size.
    with Image.open(path) as img:
        width, height = img.size
    assert isinstance(width, int) and isinstance(height, int), (
        f"{path.name} has non-integer dimensions: {width!r}x{height!r}"
    )
    assert width >= MIN_DIMENSION_PX and height >= MIN_DIMENSION_PX, (
        f"{path.name} dimensions {width}x{height} below floor {MIN_DIMENSION_PX}px"
    )
