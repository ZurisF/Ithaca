"""Validate dense BGE-M3 vectors before passing them to pgvector."""

import json
import math


def checked_vector(raw: object) -> str:
    values = [float(value) for value in raw]  # type: ignore[arg-type]
    if len(values) != 1024 or not all(math.isfinite(value) for value in values):
        raise ValueError("BGE-M3 must return a finite 1024-dimensional dense vector")
    return json.dumps(values, separators=(",", ":"))
