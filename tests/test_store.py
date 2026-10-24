import pytest

from kv_store import KVStore, StoreClosedError


def test_set_get_roundtrip(db):
    with KVStore(db) as s:
        s.set("a", b"1")
        assert s.get("a") == b"1"
        assert s.get("missing") is None
        assert s.get("missing", b"x") == b"x"


def test_overwrite_returns_latest(db):
    with KVStore(db) as s:
        s.set("a", b"1")
        s.set("a", b"22")
        assert s.get("a") == b"22"
        assert len(s) == 1


def test_delete(db):
    with KVStore(db) as s:
        s.set("a", b"1")
        assert s.delete("a") is True
        assert s.delete("a") is False
        assert s.get("a") is None
        assert "a" not in s


def test_persistence_across_reopen(db):
    with KVStore(db) as s:
        s.set("a", b"1")
        s.set("b", b"2")
        s.delete("a")
        s.set("c", b"3")
    with KVStore(db) as s:
        assert s.keys() == ["b", "c"]
        assert s.get("b") == b"2"
        assert s.get("a") is None


def test_binary_and_unicode(db):
    with KVStore(db) as s:
        s.set("ключ-é", bytes(range(256)))
        s.set("empty", b"")
    with KVStore(db) as s:
        assert s.get("ключ-é") == bytes(range(256))
        assert s.get("empty") == b""


def test_use_after_close(db):
    s = KVStore(db)
    s.close()
    s.close()  # idempotent
    with pytest.raises(StoreClosedError):
        s.get("a")


def test_invalid_ttl(db):
    with KVStore(db) as s:
        with pytest.raises(ValueError):
            s.set("a", b"1", ttl=0)
