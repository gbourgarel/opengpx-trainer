"""Crash-safe checkpoint of the ride in progress.

Samples live in memory until the ride is saved; a crash, a kill or the computer dying while
asleep used to lose the whole ride. The engine appends the new samples every
``CHECKPOINT_EVERY_S`` to a JSON-lines file (one per session), which is deleted once the ride
is saved or discarded. At startup, any file left over is turned into a ride in the history.

File format: a header line ``{"type": "header", ...}`` then one ``Sample`` per line. Append-only
(no rewrite of what is already on disk); a line cut short by the crash is ignored on reading.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, fields
from pathlib import Path

from .recording import Sample

log = logging.getLogger(__name__)

CHECKPOINT_EVERY_S = 30.0
_SAMPLE_FIELDS = {f.name for f in fields(Sample)}


class RideCheckpoint:
    def __init__(self, path: Path, every_s: float = CHECKPOINT_EVERY_S):
        self.path = path
        self.every_s = every_s
        self._written = 0  # samples already on disk
        self._last_write: float | None = None

    def update(self, header: dict, samples: list[Sample], now: float, final: bool = False) -> None:
        """Append the samples recorded since the last write, at most every ``every_s``.

        The last sample is left out unless ``final``: the recorder may still replace it with
        a later tick of the same second.
        """
        if not final and self._last_write is not None and now - self._last_write < self.every_s:
            return
        self._last_write = now
        n = len(samples) if final else len(samples) - 1
        if n <= self._written:
            return
        lines = []
        if self._written == 0:
            lines.append(json.dumps({"type": "header", **header}))
        lines += [json.dumps(asdict(s)) for s in samples[self._written : n]]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
            f.flush()
            os.fsync(f.fileno())  # survive a power loss / a dead battery, not only a crash
        self._written = n

    def discard(self) -> None:
        self.path.unlink(missing_ok=True)


def load_checkpoint(path: Path) -> tuple[dict, list[Sample]]:
    """Read a checkpoint file; raises ValueError when it has no valid header."""
    header: dict | None = None
    samples: list[Sample] = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            try:
                d = json.loads(line)
                if i == 0:
                    if d.get("type") != "header":
                        raise ValueError("no header")
                    header = d
                    continue
                samples.append(Sample(**{k: v for k, v in d.items() if k in _SAMPLE_FIELDS}))
            except (json.JSONDecodeError, TypeError, AttributeError):
                log.warning("%s: line %d unreadable (cut short?), skipped", path.name, i + 1)
    if header is None:
        raise ValueError("empty file")
    return header, samples
