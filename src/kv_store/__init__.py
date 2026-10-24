"""A small persistent key-value store backed by a write-ahead log."""

from .store import KVStore, StoreClosedError

__all__ = ["KVStore", "StoreClosedError"]
__version__ = "0.1.0"
