"""Core store: append-only log + in-memory index."""

from __future__ import annotations

import os
import struct
import time
import zlib
from typing import Callable, Dict, List, NamedTuple, Optional

# Record layout (big-endian):
#   crc32   u32   checksum of everything after this field
#   op      u8    1 = PUT, 2 = DELETE
#   expires f64   absolute expiry (clock seconds); 0.0 means "never"
#   klen    u32
#   vlen    u32
#   key     klen bytes (UTF-8)
#   value   vlen bytes
_HEADER = struct.Struct(">IBdII")
_HEADER_SIZE = _HEADER.size
OP_PUT = 1
OP_DELETE = 2

Clock = Callable[[], float]


class StoreClosedError(RuntimeError):
    """Raised when using a store after close()."""


class _Entry(NamedTuple):
    value_offset: int
    value_len: int
    expires: float


def _encode(op: int, key: bytes, value: bytes, expires: float) -> bytes:
    body = struct.pack(">BdII", op, expires, len(key), len(value)) + key + value
    return struct.pack(">I", zlib.crc32(body)) + body


class KVStore:
    """Persistent str -> bytes store.

    Every mutation is appended to a log file and flushed (and fsync'd when
    ``fsync=True``). An in-memory dict maps each live key to the position of
    its value in the log. ``clock`` returns the current time in seconds and can
    be replaced in tests.
    """

    def __init__(self, path: str, *, clock: Clock = time.time, fsync: bool = False) -> None:
        self.path = path
        self._clock = clock
        self._fsync = fsync
        self._index: Dict[str, _Entry] = {}
        self._garbage = 0  # bytes of log occupied by dead records
        self.recovered_truncated_bytes = 0
        self._closed = False
        self._fh = open(path, "a+b")
        self._recover()

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self) -> "KVStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            self._fh.close()
            self._closed = True

    def _check_open(self) -> None:
        if self._closed:
            raise StoreClosedError("store is closed")

    # -- recovery ----------------------------------------------------------

    def _recover(self) -> None:
        """Replay the log into the index; drop any torn or corrupt tail.

        Replay stops at the first incomplete record or checksum mismatch.
        """
        fh = self._fh
        fh.seek(0)
        good_end = 0
        while True:
            head = fh.read(_HEADER_SIZE)
            if len(head) < _HEADER_SIZE:
                break
            crc, op, expires, klen, vlen = _HEADER.unpack(head)
            payload = fh.read(klen + vlen)
            if len(payload) < klen + vlen:
                break
            if zlib.crc32(head[4:] + payload) != crc or op not in (OP_PUT, OP_DELETE):
                break
            try:
                name = payload[:klen].decode("utf-8")
            except UnicodeDecodeError:
                break
            size = _HEADER_SIZE + klen + vlen
            old = self._index.pop(name, None)
            if old is not None:
                self._garbage += _HEADER_SIZE + klen + old.value_len
            if op == OP_PUT:
                self._index[name] = _Entry(good_end + _HEADER_SIZE + klen, vlen, expires)
            else:
                self._garbage += size
            good_end += size
        fh.seek(0, os.SEEK_END)
        total = fh.tell()
        if total > good_end:
            # Remove the tail so new appends start on a clean record boundary.
            self.recovered_truncated_bytes = total - good_end
            fh.truncate(good_end)
            fh.flush()
            if self._fsync:
                os.fsync(fh.fileno())

    # -- internals ---------------------------------------------------------

    def _append(self, data: bytes) -> int:
        self._fh.seek(0, os.SEEK_END)
        start = self._fh.tell()
        self._fh.write(data)
        self._fh.flush()
        if self._fsync:
            os.fsync(self._fh.fileno())
        return start

    def _expired(self, entry: _Entry) -> bool:
        return entry.expires != 0.0 and self._clock() >= entry.expires

    # -- public API --------------------------------------------------------

    def set(self, key: str, value: bytes, ttl: Optional[float] = None) -> None:
        """Store ``value``. ``ttl`` is seconds until expiry (must be > 0)."""
        self._check_open()
        if ttl is not None and ttl <= 0:
            raise ValueError("ttl must be positive")
        expires = self._clock() + ttl if ttl is not None else 0.0
        kb = key.encode("utf-8")
        start = self._append(_encode(OP_PUT, kb, value, expires))
        old = self._index.get(key)
        if old is not None:
            self._garbage += _HEADER_SIZE + len(kb) + old.value_len
        self._index[key] = _Entry(start + _HEADER_SIZE + len(kb), len(value), expires)

    def get(self, key: str, default: Optional[bytes] = None) -> Optional[bytes]:
        self._check_open()
        entry = self._index.get(key)
        if entry is None:
            return default
        if self._expired(entry):
            self.delete(key)  # lazy expiry: persist a tombstone
            return default
        self._fh.seek(entry.value_offset)
        return self._fh.read(entry.value_len)

    def delete(self, key: str) -> bool:
        """Remove ``key``. Returns True if a live key was removed."""
        self._check_open()
        entry = self._index.get(key)
        if entry is None:
            return False
        was_live = not self._expired(entry)
        kb = key.encode("utf-8")
        data = _encode(OP_DELETE, kb, b"", 0.0)
        self._append(data)
        del self._index[key]
        self._garbage += _HEADER_SIZE + len(kb) + entry.value_len + len(data)
        return was_live

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and self.get(key) is not None

    def keys(self) -> List[str]:
        """Live (unexpired) keys, in sorted order."""
        self._check_open()
        return sorted(k for k, e in self._index.items() if not self._expired(e))

    def __len__(self) -> int:
        return len(self.keys())

    @property
    def garbage_bytes(self) -> int:
        """Approximate bytes in the log that compaction would reclaim."""
        return self._garbage

    def compact(self) -> int:
        """Rewrite the log with only live records. Returns bytes reclaimed."""
        self._check_open()
        before = os.path.getsize(self.path)
        tmp = self.path + ".compact"
        new_index: Dict[str, _Entry] = {}
        with open(tmp, "wb") as out:
            pos = 0
            for key in sorted(self._index):
                entry = self._index[key]
                if self._expired(entry):
                    continue
                self._fh.seek(entry.value_offset)
                value = self._fh.read(entry.value_len)
                kb = key.encode("utf-8")
                out.write(_encode(OP_PUT, kb, value, entry.expires))
                new_index[key] = _Entry(pos + _HEADER_SIZE + len(kb), len(value), entry.expires)
                pos += _HEADER_SIZE + len(kb) + len(value)
            out.flush()
            os.fsync(out.fileno())
        self._fh.close()
        os.replace(tmp, self.path)  # atomic: a crash leaves either the old or the new log
        self._fh = open(self.path, "a+b")
        self._index = new_index
        self._garbage = 0
        return before - os.path.getsize(self.path)
