#!/usr/bin/env python3
"""Convenience wrapper for `python -m qreviews review <Dxxxx>`.

Useful when you want to test the bot's pipeline against a single revision from
your editor or a quick shell command:

    ./scripts/review_one.py D302110             # dry run (no Phabricator write)
    ./scripts/review_one.py D302110 --post      # actually post the comment
    ./scripts/review_one.py D302110 --group home-newtab-reviewers
"""

from __future__ import annotations

import sys

from qreviews.__main__ import main


if __name__ == "__main__":
    sys.exit(main(["review", *sys.argv[1:]]))
