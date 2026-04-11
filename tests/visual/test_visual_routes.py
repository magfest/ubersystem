"""
Visual regression tests.

Each test navigates to a route, takes a screenshot, and either:
  - Saves it as the baseline (first run, or --update-baselines)
  - Compares it against the stored baseline (subsequent runs)

Run:
  pytest tests/visual/                       # compare
  pytest tests/visual/ --update-baselines    # update baselines
  pytest tests/visual/ -k login              # single route
"""

import dataclasses
import io
import json
import re
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from tests.visual.route_manifest import ALL_ROUTES, DATA_ROUTES, RouteSpec
from tests.visual.visual_config import (
    BASELINE_DIR,
    DIFF_THRESHOLD,
    NETWORK_IDLE_TIMEOUT,
    RESULTS_DIR,
    SCREENSHOT_EXT,
    SCREENSHOT_FORMAT,
    SCREENSHOT_QUALITY,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanitize_label(label: str) -> str:
    return re.sub(r'[^\w.-]', '_', label)


def _record_diff(label: str, ratio: float) -> None:
    """Append a diff entry to RESULTS_DIR/diffs.json (sorted by ratio desc)."""
    diffs_file = RESULTS_DIR / 'diffs.json'
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    diffs: list[dict] = []
    if diffs_file.exists():
        try:
            diffs = json.loads(diffs_file.read_text())
        except Exception:
            pass
    diffs.append({'label': label, 'ratio': ratio})
    diffs.sort(key=lambda d: d['ratio'], reverse=True)
    diffs_file.write_text(json.dumps(diffs, indent=2))


def _screenshot_route(page, base_url: str, route: RouteSpec) -> bytes:
    """Navigate to a route and return a full-page PNG screenshot."""
    url = f'{base_url}{route.path}'
    if route.query:
        url += f'?{route.query}'

    page.goto(url, wait_until='domcontentloaded', timeout=NETWORK_IDLE_TIMEOUT)

    if route.wait_selector:
        try:
            page.wait_for_selector(route.wait_selector, timeout=5_000)
        except Exception:
            pass  # best-effort; screenshot anyway

    page.wait_for_load_state('networkidle', timeout=NETWORK_IDLE_TIMEOUT)

    return page.screenshot(full_page=True, type=SCREENSHOT_FORMAT, quality=SCREENSHOT_QUALITY)


def _pixel_diff_ratio(img_a_bytes: bytes, img_b_bytes: bytes) -> tuple[float, bytes]:
    """
    Compare two PNG images pixel-by-pixel.

    Returns (ratio, diff_png) where ratio is the fraction of differing pixels
    and diff_png is a highlighted diff image for debugging.
    """
    img_a = Image.open(io.BytesIO(img_a_bytes)).convert('RGBA')
    img_b = Image.open(io.BytesIO(img_b_bytes)).convert('RGBA')

    # Pad to the same size (font rendering differences can shift layout slightly)
    max_w = max(img_a.width, img_b.width)
    max_h = max(img_a.height, img_b.height)

    if img_a.size != (max_w, max_h):
        padded = Image.new('RGBA', (max_w, max_h), (255, 255, 255, 255))
        padded.paste(img_a, (0, 0))
        img_a = padded

    if img_b.size != (max_w, max_h):
        padded = Image.new('RGBA', (max_w, max_h), (255, 255, 255, 255))
        padded.paste(img_b, (0, 0))
        img_b = padded

    diff = ImageChops.difference(img_a, img_b)

    # Count pixels that differ in any channel
    diff_rgb = diff.convert('RGB')
    total_pixels = max_w * max_h
    diff_pixels = sum(
        1 for r, g, b in diff_rgb.getdata()
        if (r + g + b) > 0
    )
    ratio = diff_pixels / total_pixels if total_pixels else 0.0

    # Build a red-highlighted diff image for inspection
    diff_highlight = Image.new('RGB', (max_w, max_h), (255, 255, 255))
    for idx, (r, g, b) in enumerate(diff_rgb.getdata()):
        if (r + g + b) > 0:
            x = idx % max_w
            y = idx // max_w
            diff_highlight.putpixel((x, y), (255, 0, 0))

    buf = io.BytesIO()
    diff_highlight.save(buf, format='PNG')
    return ratio, buf.getvalue()


# ---------------------------------------------------------------------------
# Parametrized test
# ---------------------------------------------------------------------------

def _route_id(route: RouteSpec) -> str:
    return route.label


@pytest.mark.parametrize(
    'route',
    [r for r in ALL_ROUTES if r.auth == 'public'],
    ids=[_route_id(r) for r in ALL_ROUTES if r.auth == 'public'],
)
def test_public_route_visual(route, public_page, live_server, update_baselines):
    """Visual regression test for public (unauthenticated) routes."""
    _run_visual_test(route, public_page, live_server, update_baselines)


@pytest.mark.parametrize(
    'route',
    [r for r in ALL_ROUTES if r.auth == 'admin'],
    ids=[_route_id(r) for r in ALL_ROUTES if r.auth == 'admin'],
)
def test_admin_route_visual(route, admin_page, live_server, update_baselines):
    """Visual regression test for admin (authenticated) routes."""
    _run_visual_test(route, admin_page, live_server, update_baselines)


# ---------------------------------------------------------------------------
# Core comparison logic
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    'route',
    DATA_ROUTES,
    ids=[r.label for r in DATA_ROUTES],
)
def test_data_route_visual(route, admin_page, live_server, update_baselines, test_data):
    """Visual regression test for routes that require an existing database object."""
    # Resolve template placeholders in the query string (e.g. 'id={attendee_id}')
    resolved_query = route.query.format(**test_data) if route.query else ''
    resolved_route = dataclasses.replace(route, query=resolved_query)
    _run_visual_test(resolved_route, admin_page, live_server, update_baselines)


def _run_visual_test(route: RouteSpec, page, base_url: str, update_baselines: bool):
    if route.skip:
        pytest.skip(route.skip)

    label = _sanitize_label(route.label)
    baseline_path = BASELINE_DIR / f'{label}{SCREENSHOT_EXT}'
    result_path = RESULTS_DIR / f'{label}{SCREENSHOT_EXT}'
    diff_path = RESULTS_DIR / f'{label}.diff.png'  # PNG for lossless diff clarity

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    screenshot = _screenshot_route(page, base_url, route)

    # Always write the current screenshot for inspection
    result_path.write_bytes(screenshot)

    if update_baselines or not baseline_path.exists():
        BASELINE_DIR.mkdir(parents=True, exist_ok=True)
        baseline_path.write_bytes(screenshot)
        action = 'updated' if baseline_path.exists() else 'created'
        pytest.skip(f'Baseline {action}: {baseline_path.name}')
        return

    # Compare against baseline
    baseline = baseline_path.read_bytes()
    ratio, diff_png = _pixel_diff_ratio(baseline, screenshot)

    if ratio > DIFF_THRESHOLD:
        diff_path.write_bytes(diff_png)
        _record_diff(route.label, ratio)
        # Copy baseline alongside result so the diff artifact has both before/after
        baseline_copy_path = RESULTS_DIR / f'{label}.baseline{SCREENSHOT_EXT}'
        baseline_copy_path.write_bytes(baseline)
        pct = ratio * 100
        threshold_pct = DIFF_THRESHOLD * 100
        pytest.fail(
            f'{route.label}: {pct:.3f}% pixels differ (threshold {threshold_pct:.3f}%)\n'
            f'  Baseline : {baseline_path}\n'
            f'  Current  : {result_path}\n'
            f'  Diff     : {diff_path}'
        )
