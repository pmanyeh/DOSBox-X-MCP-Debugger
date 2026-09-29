import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))

import pytest

from knowledge import KnowledgeStore, _canonical_address


@pytest.fixture
def store(tmp_path):
    return KnowledgeStore(path=str(tmp_path / "knowledge.json"))


def test_set_and_get_symbol(store):
    result = store.set_symbol("1234:0100", "main_loop")
    assert result == {"address": "1244:0000", "name": "main_loop"}
    assert store.get_symbol("1234:0100") == {"address": "1244:0000", "name": "main_loop"}


def test_symbol_lookup_is_canonical_across_representations(store):
    # "1234:0100" and "1244:0000" and "1000:2440" all name the same linear
    # address (0x12440 = 0x1234*16+0x100 = 0x1244*16+0 = 0x1000*16+0x2440).
    store.set_symbol("1234:0100", "main_loop")
    assert store.get_symbol("1000:2440")["name"] == "main_loop"
    assert store.get_symbol("1244:0000")["name"] == "main_loop"


def test_get_symbol_missing_returns_none(store):
    result = store.get_symbol("1234:0100")
    assert result["name"] is None


def test_delete_symbol(store):
    store.set_symbol("1234:0100", "main_loop")
    result = store.delete_symbol("1234:0100")
    assert result["deleted"] is True
    assert store.get_symbol("1234:0100")["name"] is None
    assert store.delete_symbol("1234:0100")["deleted"] is False


def test_list_symbols(store):
    store.set_symbol("1234:0100", "main_loop")
    store.set_symbol("1234:0200", "decode_string")
    result = store.list_symbols()
    assert result["symbols"] == [
        {"address": "1244:0000", "name": "main_loop"},
        {"address": "1254:0000", "name": "decode_string"},
    ]


def test_comments_round_trip(store):
    store.set_comment("1234:0100", "entry point, sets up DS")
    assert store.get_comment("1234:0100")["text"] == "entry point, sets up DS"
    assert store.get_comment("1234:0200")["text"] is None


def test_add_xref_is_idempotent(store):
    entry1 = store.add_xref("1234:0100", "1234:0200", "call")
    entry2 = store.add_xref("1234:0100", "1234:0200", "call")
    assert entry1 == entry2
    result = store.list_xrefs("1234:0200", direction="to")
    assert result["xrefs"] == [entry1]


def test_list_xrefs_directions(store):
    store.add_xref("1234:0100", "1234:0200", "call")
    store.add_xref("1234:0300", "1234:0100", "jump")

    to_result = store.list_xrefs("1234:0100", direction="to")
    assert [x["from"] for x in to_result["xrefs"]] == [_canonical_address("1234:0300")]

    from_result = store.list_xrefs("1234:0100", direction="from")
    assert [x["to"] for x in from_result["xrefs"]] == [_canonical_address("1234:0200")]

    both_result = store.list_xrefs("1234:0100", direction="both")
    assert len(both_result["xrefs"]) == 2


def test_add_xref_invalid_kind_raises(store):
    with pytest.raises(ValueError):
        store.add_xref("1234:0100", "1234:0200", "bogus")


def test_list_xrefs_invalid_direction_raises(store):
    with pytest.raises(ValueError):
        store.list_xrefs("1234:0100", direction="sideways")


def test_malformed_address_raises(store):
    with pytest.raises(ValueError):
        store.set_symbol("not-an-address", "x")


def test_persistence_round_trip(tmp_path):
    path = str(tmp_path / "knowledge.json")
    store1 = KnowledgeStore(path=path)
    store1.set_symbol("1234:0100", "main_loop")
    store1.set_comment("1234:0100", "entry point")
    store1.add_xref("1234:0100", "1234:0200", "call")

    store2 = KnowledgeStore(path=path)
    assert store2.get_symbol("1234:0100")["name"] == "main_loop"
    assert store2.get_comment("1234:0100")["text"] == "entry point"
    assert store2.list_xrefs("1234:0200", direction="to")["xrefs"]
