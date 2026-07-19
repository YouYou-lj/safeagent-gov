"""Unicode-aware normalization and offset-preserving safe chunking."""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from dataclasses import dataclass

from safeagent_gov.contracts import ContentChunk, SourceEnvelope

ZERO_WIDTH_AND_BIDI = {
    "\u200b",
    "\u200c",
    "\u200d",
    "\u2060",
    "\ufeff",
    "\u202a",
    "\u202b",
    "\u202c",
    "\u202d",
    "\u202e",
    "\u2066",
    "\u2067",
    "\u2068",
    "\u2069",
}
BASE64_LIKE = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{40,}={0,2}(?![A-Za-z0-9+/])")


@dataclass(frozen=True)
class NormalizationResult:
    text: str
    content_hash: str
    normalized_hash: str
    flags: tuple[str, ...]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _has_mixed_latin_cyrillic(text: str) -> bool:
    for token in re.findall(r"[^\W_]+", text, flags=re.UNICODE):
        scripts = set()
        for character in token:
            name = unicodedata.name(character, "")
            if "LATIN" in name:
                scripts.add("latin")
            elif "CYRILLIC" in name:
                scripts.add("cyrillic")
        if len(scripts) > 1:
            return True
    return False


def normalize_text(text: str, *, decode_html_entities: bool = False) -> NormalizationResult:
    """Normalize common encoding tricks while retaining deterministic evidence flags."""
    original = text or ""
    flags: list[str] = []
    normalized = original.replace("\r\n", "\n").replace("\r", "\n")
    if normalized != original:
        flags.append("line_endings_normalized")

    if decode_html_entities:
        decoded = html.unescape(normalized)
        if decoded != normalized:
            flags.append("html_entities_decoded")
        normalized = decoded

    nfkc = unicodedata.normalize("NFKC", normalized)
    if nfkc != normalized:
        flags.append("unicode_nfkc")
    normalized = nfkc

    removed = "".join(character for character in normalized if character not in ZERO_WIDTH_AND_BIDI)
    if removed != normalized:
        flags.append("zero_width_or_bidi_removed")
    normalized = removed

    cleaned_chars: list[str] = []
    control_removed = False
    for character in normalized:
        if character in {"\n", "\t"} or not unicodedata.category(character).startswith("C"):
            cleaned_chars.append(character)
        else:
            control_removed = True
    if control_removed:
        flags.append("control_characters_removed")
    normalized = "".join(cleaned_chars)

    collapsed = re.sub(r"[^\S\n]+", " ", normalized)
    collapsed = re.sub(r"\n{3,}", "\n\n", collapsed).strip()
    if collapsed != normalized.strip():
        flags.append("whitespace_collapsed")
    normalized = collapsed

    if BASE64_LIKE.search(normalized):
        flags.append("base64_like_segment")
    if _has_mixed_latin_cyrillic(normalized):
        flags.append("mixed_latin_cyrillic")

    return NormalizationResult(
        text=normalized,
        content_hash=sha256_text(original),
        normalized_hash=sha256_text(normalized),
        flags=tuple(dict.fromkeys(flags)),
    )


def chunk_source(
    source: SourceEnvelope,
    *,
    max_chars: int = 2_000,
    overlap_chars: int = 200,
) -> list[ContentChunk]:
    """Split normalized content into bounded chunks with stable source offsets."""
    if max_chars < 256:
        raise ValueError("max_chars must be at least 256")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be between 0 and max_chars")
    text = source.normalized_content
    if not text:
        return []

    chunks: list[ContentChunk] = []
    start = 0
    index = 0
    while start < len(text):
        hard_end = min(len(text), start + max_chars)
        end = hard_end
        if hard_end < len(text):
            search_from = start + max_chars // 2
            candidates = [text.rfind(separator, search_from, hard_end) for separator in ("\n", "。", "！", "？", ". ")]
            boundary = max(candidates)
            if boundary > start:
                end = boundary + 1
        fragment = text[start:end]
        chunk_hash = sha256_text(fragment)
        chunk_id = f"{source.source_id}:chunk:{index}:{chunk_hash[:12]}"
        chunks.append(
            ContentChunk(
                chunk_id=chunk_id,
                source_id=source.source_id,
                source_type=source.source_type,
                index=index,
                text=fragment,
                start_char=start,
                end_char=end,
                content_hash=chunk_hash,
                trust_score=source.trust_score,
                metadata={"origin": source.origin, "session_id": source.session_id},
            )
        )
        if end >= len(text):
            break
        next_start = end - overlap_chars
        start = next_start if next_start > start else end
        index += 1
    return chunks
