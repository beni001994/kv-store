from kv_store.cli import main


def run(db, *args):
    return main(["--db", db, *args])


def test_set_get_del(db, capfd):
    assert run(db, "set", "name", "beni") == 0
    assert run(db, "get", "name") == 0
    assert capfd.readouterr().out == "beni\n"
    assert run(db, "del", "name") == 0
    assert run(db, "get", "name") == 1
    assert "not found" in capfd.readouterr().err


def test_del_missing_returns_1(db):
    assert run(db, "del", "nope") == 1


def test_compact_command(db, capfd):
    for i in range(10):
        run(db, "set", "k", "v" * (i + 1))
    capfd.readouterr()
    assert run(db, "compact") == 0
    assert capfd.readouterr().out.startswith("reclaimed ")
    run(db, "get", "k")
    assert capfd.readouterr().out == "v" * 10 + "\n"


def test_ttl_flag_validation(db, capfd):
    assert run(db, "set", "k", "v", "--ttl", "0") == 2
    assert "ttl" in capfd.readouterr().err
    assert run(db, "set", "k", "v", "--ttl", "60") == 0
