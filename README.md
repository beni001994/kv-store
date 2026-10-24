# kv-store

A small persistent key-value store in pure Python (3.9+, standard library only).
Writes go to an append-only write-ahead log, an in-memory index serves reads,
the log can be compacted, and the store recovers on startup even if the last
record was only partly written. Keys can have a TTL.

It is a learning/portfolio project, not a database replacement. See
[Limitations](#limitations).

## Install

```bash
pip install -e ".[dev]"
pytest
```

## Usage

### Library

```python
from kv_store import KVStore

with KVStore("data.db") as db:
    db.set("user:1", b"alice")
    db.set("session", b"abc123", ttl=60)   # expires in 60 seconds
    db.get("user:1")                        # b"alice"
    db.delete("user:1")                     # True
    db.keys()                               # ["session"]
    db.compact()                            # bytes reclaimed
```

Keys are `str` (UTF-8 encoded on disk), values are `bytes`. `KVStore` accepts:

- `clock`: a zero-argument callable returning seconds (default `time.time`).
  Tests inject a fake clock to make TTL expiry deterministic.
- `fsync`: when `True`, every append is followed by `os.fsync` (durable against
  power loss, but slower). Default `False` (data is flushed to the OS only).

### CLI

```bash
kv-store --db data.db set greeting hello
kv-store --db data.db set token abc --ttl 30
kv-store --db data.db get greeting      # prints "hello"
kv-store --db data.db del greeting
kv-store --db data.db compact           # prints "reclaimed N bytes"
```

The database path defaults to `$KV_STORE_PATH`, then `./kv.db`. `get` and `del`
exit with status 1 if the key does not exist.

## Architecture

```
          set/del                      get
            |                           |
            v                           v
   +-----------------+   offset   +-------------+
   | append to log   |----------->| index (dict)|
   +-----------------+            +------+------+
            |                            |
            v                            v
        data.db  <----- seek + read value
```

### File format

The file is a sequence of records, all integers big-endian:

| field   | size  | notes                                         |
|---------|-------|-----------------------------------------------|
| crc32   | 4     | over every byte of the record after this field |
| op      | 1     | 1 = put, 2 = delete (tombstone)               |
| expires | 8     | float64 absolute expiry time, `0.0` = never   |
| klen    | 4     | key length                                    |
| vlen    | 4     | value length                                  |
| key     | klen  | UTF-8                                         |
| value   | vlen  | raw bytes (empty for deletes)                 |

There is no file header and no record framing beyond the lengths and checksum.

### In-memory index

`dict[str, (value_offset, value_len, expires)]`. Values stay on disk; a `get`
is one dictionary lookup plus one seek and read. Keys (not values) must fit in
memory. This is the same basic design as Bitcask.

### Recovery

On open, the log is replayed from the start, rebuilding the index. Replay stops
at the first record that is incomplete (short header or short body), fails its
CRC, or has an invalid op or key encoding. Everything from that point is
discarded by truncating the file to the end of the last good record, so later
appends start on a clean boundary. The number of discarded bytes is exposed as
`recovered_truncated_bytes`.

Consequences, which are tested:

- A crash mid-append loses at most the record being written; the state is
  always some prefix of the operation history.
- A delete whose tombstone was truncated is lost, so the old value reappears.
- A corrupt record in the *middle* of the file also ends replay, and the
  records after it are discarded. The CRC detects corruption; this store does
  not try to skip over it or repair it.

### TTL

`set(key, value, ttl=seconds)` stores an absolute expiry time in the record.
Expiry is lazy: expired keys are hidden from `get`, `keys`, `len` and `in`
immediately, a `get` on an expired key appends a tombstone, and compaction
drops expired entries for good. Expiry compares against the injected clock, so
a store reopened after a wall-clock change will see the new time.

### Compaction

The log only grows, so overwritten, deleted and expired records pile up.
`compact()` writes every live record to `<path>.compact`, fsyncs it, then
`os.replace`s it over the log (atomic on POSIX and Windows) and rebuilds the
index.

Trade-offs:

- Needs free disk space for a second copy of the live data while it runs.
- Blocks the caller for the duration (it is synchronous and not incremental).
- A crash before the rename leaves the old log intact and a stray
  `.compact` file, which the next compaction overwrites.
- It is manual: nothing triggers it automatically. `garbage_bytes` gives an
  estimate of how much a compaction would reclaim so callers can decide.

## Tests

`pytest` runs tests for the basic API, recovery (truncation at every byte
offset, checksum corruption, empty and garbage files), compaction correctness,
TTL behaviour with a fake clock, and the CLI.

## Limitations

- Single process, single thread. There is no file locking and no thread safety;
  two processes opening the same file will corrupt it.
- Durability is only as strong as `fsync=True`; the default does not fsync
  appends, so a power loss (not just a process crash) can lose recent writes.
- Recovery cannot skip past mid-file corruption (see above).
- The whole key set must fit in memory, and replay time grows with log size.
- Compaction is stop-the-world and manual.
- No transactions, batching, range scans or iteration over values.
- Timestamps use wall-clock time by default, which can jump.
- Each CLI call opens the file and replays the whole log.

## License

MIT
