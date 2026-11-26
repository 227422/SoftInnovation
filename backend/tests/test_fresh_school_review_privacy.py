from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/quality"))


def test_readers_cannot_see_category_encoded_collection_identifiers():
    from fresh_school_review import obscure, restore
    row = dict(case_id="v3-s-37-01", title="校内通知", url="https://example.edu.cn/1",
               body_path="local/aa.txt", raw_path="local/aa.html", body_sha256="a"*64,
               raw_sha256="b"*64, reference_category="daily", reference_reason="private")
    other = dict(row, case_id="v3-s-37-19", title="学院通知", reference_category="excluded")
    a, mapping = obscure([row, other], "private-salt")
    assert a == obscure([other, row], "private-salt")[0]
    assert set(mapping.values()) == {row["case_id"], other["case_id"]}
    assert all(set(r) == {"case_id","title","url","body_path","raw_path","body_sha256","raw_sha256"} for r in a)
    assert all(r["case_id"] not in mapping.values() for r in a)
    assert set(mapping).isdisjoint(obscure([row, other], "other-salt")[1])
    reread = [dict(case_id=r["case_id"], category="daily", evidence="引文") for r in a]
    out = restore(reread, mapping)
    assert [v["case_id"] for v in out] == [mapping[r["case_id"]] for r in a]
    assert all(v["evidence"] == "引文" for v in out)
    for corrupt in (reread[:1], reread+reread[:1], [*reread[:-1], dict(reread[-1], case_id="unknown")]):
        with pytest.raises(ValueError):
            restore(corrupt, mapping)
    with pytest.raises(ValueError):
        obscure([row, row], "private-salt")
