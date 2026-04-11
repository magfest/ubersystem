"""
Visual regression test configuration.

Baselines are stored in tests/visual/baselines/ so they can be committed to
version control for small sets, or mounted as a Docker volume for CI.

Run with:
  pytest tests/visual/                       # compare against baselines
  pytest tests/visual/ --update-baselines    # save new baselines
"""

from pathlib import Path

# Directory that holds golden baseline screenshots
BASELINE_DIR = Path(__file__).parent / 'baselines'

# Directory for this run's screenshots and diff images
RESULTS_DIR = Path(__file__).parent / 'results'

# Maximum fraction of pixels that may differ before a test fails (0–1)
# 0.002 = 0.2% of all pixels
DIFF_THRESHOLD = 0.002

# Viewport for all screenshots
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 900

# Milliseconds to wait for network idle before screenshotting
NETWORK_IDLE_TIMEOUT = 10_000

# Screenshot format — JPEG reduces artifact storage significantly vs PNG
SCREENSHOT_FORMAT = 'jpeg'
SCREENSHOT_EXT = '.jpg'
SCREENSHOT_QUALITY = 85
