from constrictor.graph.id_factory import create_id


def test_format():
    id_ = create_id("func", "app.utils", "greet")
    prefix, hash_part = id_.split(":")
    assert prefix == "func"
    assert len(hash_part) == 16
    assert all(c in "0123456789abcdef" for c in hash_part)


def test_determinism():
    a = create_id("mod", "app.main", "run")
    b = create_id("mod", "app.main", "run")
    assert a == b


def test_uniqueness():
    ids = {create_id("func", f"mod_{i}", "fn") for i in range(50)}
    assert len(ids) == 50


def test_different_prefixes_different_ids():
    a = create_id("func", "app.utils", "greet")
    b = create_id("mod", "app.utils", "greet")
    assert a != b


def test_different_parts_different_ids():
    a = create_id("func", "app.utils", "greet")
    b = create_id("func", "app.utils", "helper")
    assert a != b


def test_single_part():
    id_ = create_id("mod", "app.main")
    assert id_.startswith("mod:")
    assert len(id_.split(":")[1]) == 16


def test_many_parts():
    id_ = create_id("edge", "source", "target", "CALLS")
    assert id_.startswith("edge:")
    assert len(id_.split(":")[1]) == 16
