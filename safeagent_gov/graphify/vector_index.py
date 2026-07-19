"""Dependency-free deterministic semantic vectors for offline Graphify recall."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

_ASCII_WORD = re.compile(r"[a-z0-9_]+")
_CJK = re.compile(r"[\u3400-\u9fff]")
DIMENSIONS = 384


def _features(text: str) -> list[str]:
    normalized = text.casefold()
    ascii_words = _ASCII_WORD.findall(normalized)
    cjk = _CJK.findall(normalized)
    features = [f"w:{word}" for word in ascii_words]
    features.extend(f"c:{item}" for item in cjk)
    features.extend(f"b:{first}{second}" for first, second in zip(cjk, cjk[1:], strict=False))
    features.extend(
        f"a:{word[index:index + 3]}"
        for word in ascii_words
        for index in range(max(0, len(word) - 2))
        if len(word) >= 3
    )
    return features


def hashed_vector(text: str, dimensions: int = DIMENSIONS) -> dict[int, float]:
    """Create a stable normalized sparse vector without network/model state."""
    counts = Counter(_features(text))
    vector: dict[int, float] = {}
    for feature, count in counts.items():
        digest = hashlib.sha256(feature.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimensions
        vector[bucket] = vector.get(bucket, 0.0) + (1.0 + math.log(float(count)))
    norm = math.sqrt(sum(value * value for value in vector.values()))
    return {bucket: value / norm for bucket, value in vector.items()} if norm else {}


def cosine_similarity(left: str, right: str) -> float:
    left_vector = hashed_vector(left)
    right_vector = hashed_vector(right)
    if not left_vector or not right_vector:
        return 0.0
    small, large = (left_vector, right_vector) if len(left_vector) <= len(right_vector) else (right_vector, left_vector)
    return max(0.0, min(1.0, sum(value * large.get(bucket, 0.0) for bucket, value in small.items())))
