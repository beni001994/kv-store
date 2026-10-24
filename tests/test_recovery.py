import os

from kv_store import KVStore


def _populate(db):
    with KVStore(db) as s:
        s.set("a", b"alpha")
        s.set("b", b"bravo")
        s.set("c", b"charlie")


def test_truncated_last_record_is_dropped(db):
    _populate(db)
    full = os.path.getsize(db)
    with open(db, "r+b") as f:
        f.truncate(full - 3)  # cut into the last record's value
    with KVStore(db) as s:
        assert s.keys() == ["a", "b"]
        assert s.get("b") == b"bravo"
        assert s.get("c") is None
        assert s.recovered_truncated_bytes > 0


def test_file_is_repaired_and_writable_after_recovery(db):
    _populate(db)
    with open(db, "r+b") as f:
        f.truncate(os.path.getsize(db) - 2)
    with KVStore(db) as s:
        s.set("z", b"zulu")
    with KVStore(db) as s:
        assert s.recovered_truncated_bytes == 0  # tail was removed on first recovery
        assert s.keys() == ["a", "b", "z"]
        assert s.get("z") == b"zulu"


def test_corrupt_checksum_stops_replay(db):
    _populate(db)
    with open(db, "r+b") as f:
        f.seek(-1, os.SEEK_END)
        last = f.read(1)
        f.seek(-1, os.SEEK_END)
        f.write(bytes([last[0] ^ 0xFF]))
    with KVStore(db) as s:
        assert s.keys() == ["a", "b"]


def test_empty_and_garbage_files(db):
    open(db, "wb").close()
    with KVStore(db) as s:
        assert s.keys() == []
    with open(db, "wb") as f:
        f.write(b"\x00\x01\x02")
    with KVStore(db) as s:
        assert s.keys() == []
        s.set("a", b"1")
    with KVStore(db) as s:
        assert s.get("a") == b"1"


def test_delete_survives_recovery(db):
    _populate(db)
    with KVStore(db) as s:
        s.delete("b")
    with KVStore(db) as s:
        assert s.keys() == ["a", "c"]


def test_truncated_tombstone_resurrects_old_value(db):
    # Documents the semantics: a delete that never fully reached disk is lost.
    _populate(db)
    with KVStore(db) as s:
        s.delete("c")
    with open(db, "r+b") as f:
        f.truncate(os.path.getsize(db) - 1)
    with KVStore(db) as s:
        assert s.get("c") == b"charlie"


def test_every_truncation_point_recovers_a_prefix(db):
    _populate(db)
    with open(db, "rb") as f:
        data = f.read()
    valid_states = [[], ["a"], ["a", "b"], ["a", "b", "c"]]
    for n in range(len(data) + 1):
        with open(db, "wb") as f:
            f.write(data[:n])
        with KVStore(db) as s:
            assert s.keys() in valid_states
