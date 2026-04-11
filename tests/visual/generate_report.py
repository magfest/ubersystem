"""
Aggregate diffs.json files from all visual comparison chunk artifacts and
print a markdown PR comment body to stdout.

Usage (from repo root after downloading all visual-diff-* artifacts):
    python3 tests/visual/generate_report.py artifacts/
"""

import glob
import json
import sys
from pathlib import Path

DIFF_THRESHOLD_PCT = 0.2  # must match visual_config.DIFF_THRESHOLD * 100
MARKER = '<!-- visual-regression-report -->'


def main(artifacts_dir: str = 'artifacts') -> None:
    all_diffs: list[dict] = []

    for path in sorted(glob.glob(f'{artifacts_dir}/visual-diff-*/diffs.json')):
        chunk = Path(path).parent.name.removeprefix('visual-diff-')
        try:
            entries = json.loads(Path(path).read_text())
            for entry in entries:
                all_diffs.append({**entry, 'chunk': chunk})
        except Exception as e:
            print(f'Warning: could not read {path}: {e}', file=sys.stderr)

    all_diffs.sort(key=lambda d: d['ratio'], reverse=True)
    top5 = all_diffs[:5]
    total = len(all_diffs)

    if not top5:
        body = f'{MARKER}\n## Visual Regression\n\n✅ No significant visual changes detected.\n'
    else:
        rows = '\n'.join(
            f'| `{d["label"]}` | **{d["ratio"] * 100:.2f}%** | {d["chunk"]} |'
            for d in top5
        )
        more = f'\n\n*…and {total - 5} more.  ' if total > 5 else '\n\n*'
        body = (
            f'{MARKER}\n'
            f'## Visual Regression\n\n'
            f'**{total} route{"s" if total != 1 else ""} changed** '
            f'(threshold: {DIFF_THRESHOLD_PCT:.1f}%):\n\n'
            f'| Route | Diff | Chunk |\n'
            f'|-------|------|-------|\n'
            f'{rows}\n'
            f'{more}'
            f'Download `visual-diff-*` artifacts from this run to view screenshots.*\n'
        )

    print(body, end='')


if __name__ == '__main__':
    main(*sys.argv[1:])
