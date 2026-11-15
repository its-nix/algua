import pytest

from algua.registry.db import SCHEMA_VERSION, connect, migrate
from algua.registry.inbox import add_item, list_items, mark_taken, queued_items


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "r.db")
    migrate(c)
    yield c
    c.close()


def test_add_then_list_newest_first(conn):
    a, _ = add_item(conn, kind="link", url="https://x.com/a/status/1", now="2026-11-14T10:00:00Z")
    b, _ = add_item(conn, kind="text", text="buy the dip in small caps", now="2026-11-14T11:00:00Z")
    assert [i["id"] for i in list_items(conn)] == [b["id"], a["id"]]
    assert a["status"] == "queued"


def test_same_link_while_queued_is_one_item(conn):
    a, dup1 = add_item(conn, kind="link", url="https://Example.com/p?utm_source=x", now="t1")
    b, dup2 = add_item(conn, kind="link", url="https://example.com/p", now="t2")
    assert (dup1, dup2) == (False, True) and b["id"] == a["id"]


def test_mark_taken_flips_once(conn):
    a, _ = add_item(conn, kind="text", text="x", now="t1")
    assert mark_taken(conn, a["id"], inspiration_id="2026-11-14-inbox-x-abc123", now="t2") is True
    assert mark_taken(conn, a["id"], inspiration_id="other", now="t3") is False
    assert queued_items(conn) == []


def test_taken_link_can_be_re_added(conn):
    a, _ = add_item(conn, kind="link", url="https://example.com/p", now="t1")
    mark_taken(conn, a["id"], inspiration_id="i", now="t2")
    b, dup = add_item(conn, kind="link", url="https://example.com/p", now="t3")
    assert dup is False and b["id"] != a["id"]


def test_schema_version_is_54():
    assert SCHEMA_VERSION == 54
