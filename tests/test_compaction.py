import os

from kv_store import KVStore


def test_compaction_preserves_live_data_and_shrinks(db):
    with KVStore(db) as s:
        for i in range(50):
            s.set("hot", f"v{i}".encode())
        s.set("keep", b"me")
        s.set("gone", b"x" * 100)
        s.delete("gone")
        before = os.path.getsize(db)
        reclaimed = s.compact()
        after = os.path.getsize(db)
        assert after < before
        assert reclaimed == before - after
        assert s.get("hot") == b"v49"
        assert s.get("keep") == b"me"
        assert s.get("gone") is None
        assert s.garbage_bytes == 0


def test_writes_after_compaction_and_reopen(db):
    with KVStore(db) as s:
        s.set("a", b"1")
        s.set("a", b"2")
        s.compact()
        s.set("b", b"3")
        s.delete("a")
    with KVStore(db) as s:
        assert s.keys() == ["b"]
        assert s.get("b") == b"3"


def test_compaction_drops_expired_and_keeps_ttl(db, clock):
    with KVStore(db, clock=clock) as s:
        s.set("short", b"1", ttl=5)
        s.set("long", b"2", ttl=100)
        clock.advance(10)
        s.compact()
        assert s.keys() == ["long"]
        clock.advance(100)
        assert s.get("long") is None


def test_compaction_leaves_no_temp_file_and_is_idempotent(db):
    with KVStore(db) as s:
        s.set("a", b"1")
        s.compact()
        size = os.path.getsize(db)
        assert s.compact() == 0
        assert os.path.getsize(db) == size
    assert not os.path.exists(db + ".compact")


def test_compact_empty_store(db):
    with KVStore(db) as s:
        s.compact()
        assert s.keys() == []


def test_garbage_accounting_grows_on_overwrite(db):
    with KVStore(db) as s:
        s.set("a", b"1")
        assert s.garbage_bytes == 0
        s.set("a", b"2")
        assert s.garbage_bytes > 0
