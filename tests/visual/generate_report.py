"""
Generate visual regression report.

Creates side-by-side before/after composite images for the top 5 changed
routes and writes ``composites/report_data.json`` for the GitHub Actions
workflow to turn into a PR comment with embedded images.

Usage (from repo root, after downloading all visual-diff-* artifacts):
    python3 tests/visual/generate_report.py artifacts/ composites/
"""

import glob
import json
import sys
from pathlib import Path

DIFF_THRESHOLD_PCT = 0.2   # must match visual_config.DIFF_THRESHOLD * 100
MARKER = '<!-- visual-regression-report -->'
MAX_SCREENSHOT_HEIGHT = 1500   # crop very tall pages so composites stay manageable
MAX_PANEL_WIDTH = 640          # scale each panel down to this width; keeps composite ≤ ~1.5 MB
HEADER_HEIGHT = 44             # px for the BEFORE / AFTER label bar
SEPARATOR_WIDTH = 6            # px between the two panels
COMPOSITE_QUALITY = 82         # JPEG quality for the composite (good balance of size vs clarity)


# ---------------------------------------------------------------------------
# Composite image creation
# ---------------------------------------------------------------------------

def _load_font(size: int):
    """Return a PIL font, falling back to the built-in bitmap font."""
    from PIL import ImageFont
    candidates = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf',
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _draw_header(draw, x: int, width: int, height: int, text: str,
                 bg: tuple, fg: tuple, font) -> None:
    """Fill a rectangle and center text inside it."""
    from PIL import ImageDraw  # noqa: F401 — only for type hint

    draw.rectangle([x, 0, x + width - 1, height - 1], fill=bg)
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except AttributeError:
        tw, th = draw.textsize(text, font=font)
    tx = x + max(0, (width - tw) // 2)
    ty = max(0, (height - th) // 2)
    draw.text((tx, ty), text, fill=fg, font=font)


def _resize_panel(img, max_width: int, max_height: int):
    """Crop height then scale down to max_width, preserving aspect ratio."""
    from PIL import Image

    if img.height > max_height:
        img = img.crop((0, 0, img.width, max_height))
    if img.width > max_width:
        scale = max_width / img.width
        new_h = max(1, int(img.height * scale))
        img = img.resize((max_width, new_h), Image.LANCZOS)
    return img


def create_composite(before_path: Path, after_path: Path,
                     output_path: Path, label: str, ratio: float) -> None:
    """
    Build a side-by-side JPEG with:
      - a blue  header bar (left):  "BEFORE  —  {label}  ({pct}% changed)"
      - a red   header bar (right): "AFTER"
      - both screenshots scaled to MAX_PANEL_WIDTH wide, cropped to MAX_SCREENSHOT_HEIGHT

    Saved as JPEG at COMPOSITE_QUALITY to stay well under GitHub's 10 MB upload limit.
    """
    from PIL import Image, ImageDraw

    before = _resize_panel(Image.open(before_path).convert('RGB'),
                           MAX_PANEL_WIDTH, MAX_SCREENSHOT_HEIGHT)
    after  = _resize_panel(Image.open(after_path).convert('RGB'),
                           MAX_PANEL_WIDTH, MAX_SCREENSHOT_HEIGHT)

    # Pad the shorter panel so both are the same height
    max_h = max(before.height, after.height)
    for img_ref in ('before', 'after'):
        img = before if img_ref == 'before' else after
        if img.height < max_h:
            padded = Image.new('RGB', (img.width, max_h), (245, 245, 245))
            padded.paste(img, (0, 0))
            if img_ref == 'before':
                before = padded
            else:
                after = padded

    total_w = before.width + SEPARATOR_WIDTH + after.width
    total_h = HEADER_HEIGHT + max_h

    composite = Image.new('RGB', (total_w, total_h), (30, 30, 30))
    draw = ImageDraw.Draw(composite)

    font_lg = _load_font(16)
    pct_str = f'{ratio * 100:.2f}%'
    _draw_header(draw, 0, before.width, HEADER_HEIGHT,
                 f'BEFORE  —  {label}  ({pct_str} changed)',
                 (35, 95, 145), (255, 255, 255), font_lg)
    _draw_header(draw, before.width + SEPARATOR_WIDTH, after.width, HEADER_HEIGHT,
                 'AFTER',
                 (145, 35, 35), (255, 255, 255), font_lg)

    composite.paste(before, (0, HEADER_HEIGHT))
    composite.paste(after,  (before.width + SEPARATOR_WIDTH, HEADER_HEIGHT))

    # Save as JPEG — composite is ~1286×1544 px which is well under 10 MB at this quality
    output_path.parent.mkdir(parents=True, exist_ok=True)
    composite.save(str(output_path), 'JPEG', quality=COMPOSITE_QUALITY, optimize=True)
    size_kb = output_path.stat().st_size // 1024
    print(f'  Composite: {output_path}  ({size_kb} KB)', file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(artifacts_dir: str = 'artifacts',
         composites_dir: str = 'composites') -> None:
    all_diffs: list[dict] = []

    for path in sorted(glob.glob(f'{artifacts_dir}/visual-diff-*/diffs.json')):
        chunk = Path(path).parent.name.removeprefix('visual-diff-')
        try:
            for entry in json.loads(Path(path).read_text()):
                all_diffs.append({**entry, 'chunk': chunk})
        except Exception as e:
            print(f'Warning: could not read {path}: {e}', file=sys.stderr)

    all_diffs.sort(key=lambda d: d['ratio'], reverse=True)
    significant = [d for d in all_diffs if d['ratio'] * 100 >= DIFF_THRESHOLD_PCT]
    total = len(significant)

    composites_path = Path(composites_dir)
    composites_path.mkdir(parents=True, exist_ok=True)

    composites: list[dict] = []
    if significant:
        print(f'Creating composites for top {min(5, total)} of {total} changed routes…',
              file=sys.stderr)
        for diff in significant[:5]:
            label = diff['label']
            chunk = diff['chunk']
            before = Path(artifacts_dir) / f'visual-diff-{chunk}' / f'{label}.baseline.jpg'
            after  = Path(artifacts_dir) / f'visual-diff-{chunk}' / f'{label}.jpg'

            if before.exists() and after.exists():
                filename = f'{label}.composite.jpg'
                try:
                    create_composite(before, after, composites_path / filename,
                                     label, diff['ratio'])
                    composites.append({'label': label, 'ratio': diff['ratio'],
                                       'chunk': chunk, 'filename': filename})
                except Exception as e:
                    print(f'Warning: composite failed for {label}: {e}', file=sys.stderr)
            else:
                missing = []
                if not before.exists():
                    missing.append(f'before ({before})')
                if not after.exists():
                    missing.append(f'after ({after})')
                print(f'Warning: skipping composite for {label} — missing {", ".join(missing)}',
                      file=sys.stderr)

    report_data = {
        'has_changes': total > 0,
        'total_changed': total,
        'composites': composites,
        'top_50': significant[:50],
    }

    out = composites_path / 'report_data.json'
    out.write_text(json.dumps(report_data, indent=2))
    print(f'Wrote {out}  ({total} changes, {len(composites)} composites)', file=sys.stderr)


if __name__ == '__main__':
    main(*sys.argv[1:])
