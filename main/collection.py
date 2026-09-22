"""Bounded, lightweight collection metadata returned by playlist extractors."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True, slots=True)
class CollectionEntry:
    """Metadata needed to queue an item; never contains a resolved stream."""

    source_url: str
    content_id: Optional[str] = None
    title: str = "Video"
    thumbnail_url: Optional[str] = None
    duration_ms: Optional[int] = None
    source_name: Optional[str] = None


@dataclass(frozen=True, slots=True)
class ResolvedCollection:
    """A bounded listing.  Entries are intentionally not direct streams."""

    source_url: str
    title: str
    entries: tuple[CollectionEntry, ...] = field(default_factory=tuple)
    is_partial: bool = False
    has_more: bool = False

