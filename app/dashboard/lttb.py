from __future__ import annotations

import math
from typing import Sequence


def lttb(points: Sequence[Sequence[float]], threshold: int) -> list[list[float]]:
    """Largest-Triangle-Three-Buckets downsampling for [x, y] or [x, y, ...]."""
    n = len(points)
    if threshold >= n or threshold <= 0 or threshold < 3:
        return [list(p) for p in points]
    sampled = [list(points[0])]
    every = (n - 2) / (threshold - 2)
    a = 0
    for i in range(threshold - 2):
        avg_start = int(math.floor((i + 1) * every)) + 1
        avg_end = int(math.floor((i + 2) * every)) + 1
        avg_end = min(avg_end, n)
        if avg_start >= avg_end:
            avg_x, avg_y = points[min(avg_start, n - 1)][0], points[min(avg_start, n - 1)][1]
        else:
            span = points[avg_start:avg_end]
            avg_x = sum(p[0] for p in span) / len(span)
            avg_y = sum(p[1] for p in span) / len(span)
        range_start = int(math.floor(i * every)) + 1
        range_end = int(math.floor((i + 1) * every)) + 1
        range_end = min(range_end, n - 1)
        ax, ay = points[a][0], points[a][1]
        max_area = -1.0
        max_idx = range_start
        for idx in range(range_start, max(range_start + 1, range_end)):
            px, py = points[idx][0], points[idx][1]
            area = abs((ax - avg_x) * (py - ay) - (ax - px) * (avg_y - ay)) * 0.5
            if area > max_area:
                max_area, max_idx = area, idx
        sampled.append(list(points[max_idx]))
        a = max_idx
    sampled.append(list(points[-1]))
    return sampled
