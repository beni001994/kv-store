from kv_store import KVStore


def test_key_expires_with_injected_clock(db, clock):
    with KVStore(db, clock=clock) as s:
        s.set("a", b"1", ttl=10)
        clock.advance(9.9)
        assert s.get("a") == b"1"
        clock.advance(0.1)  # exactly at expiry -> expired
        assert s.get("a") is None
        assert "a" not in s


def test_no_ttl_never_expires(db, clock):
    with KVStore(db, clock=clock) as s:
        s.set("a", b"1")
        clock.advance(10**9)
        assert s.get("a") == b"1"


def test_expiry_persists_across_reopen(db, clock):
    with KVStore(db, clock=clock) as s:
        s.set("a", b"1", ttl=10)
    clock.advance(5)
    with KVStore(db, clock=clock) as s:
        assert s.get("a") == b"1"
        clock.advance(6)
        assert s.get("a") is None


def test_expired_key_hidden_from_keys_and_len(db, clock):
    with KVStore(db, clock=clock) as s:
        s.set("a", b"1", ttl=1)
        s.set("b", b"2")
        clock.advance(2)
        assert s.keys() == ["b"]
        assert len(s) == 1


def test_overwrite_resets_ttl(db, clock):
    with KVStore(db, clock=clock) as s:
        s.set("a", b"1", ttl=5)
        s.set("a", b"2")  # no ttl now
        clock.advance(100)
        assert s.get("a") == b"2"


def test_delete_expired_reports_false(db, clock):
    with KVStore(db, clock=clock) as s:
        s.set("a", b"1", ttl=1)
        clock.advance(5)
        assert s.delete("a") is False


def test_lazy_expiry_writes_tombstone(db, clock):
    with KVStore(db, clock=clock) as s:
        s.set("a", b"1", ttl=1)
        clock.advance(5)
        assert s.get("a") is None
    clock.now = 0.0  # even a clock that went backwards must not resurrect it
    with KVStore(db, clock=clock) as s:
        assert s.get("a") is None
