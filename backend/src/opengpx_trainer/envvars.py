"""Environment variables of the app: ``OPENGPX_TRAINER_<NAME>``.

The app was called "Home Trainer" before 2026-11: the former ``HOMETRAINER_<NAME>`` variables
are still read when the new one is not set, so existing setups keep working.
"""

from __future__ import annotations

import os

PREFIX = "OPENGPX_TRAINER_"
FORMER_PREFIX = "HOMETRAINER_"


def env(name: str) -> str | None:
    """``OPENGPX_TRAINER_<name>``, else ``HOMETRAINER_<name>``, else None (empty = unset)."""
    return os.environ.get(PREFIX + name) or os.environ.get(FORMER_PREFIX + name) or None
