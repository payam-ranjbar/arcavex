"""Derived-asset cache (spec §4.7): downscaled image variants under an LRU byte budget."""

from arcavex.services.cache.derived import DerivedImageCache, cache_root

__all__ = ["DerivedImageCache", "cache_root"]
