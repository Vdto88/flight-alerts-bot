import json
from datetime import date, datetime, timedelta, timezone

import far_cache

TODAY = date(2026, 9, 20)
NOW = datetime(2026, 9, 20, 11, 30, tzinfo=timezone.utc)


def _deal(days_ahead, destino="GIG", **extra):
    return {"origem": "CNF", "destino": destino, "data": (TODAY + timedelta(days=days_ahead)).isoformat(),
            "preco": 300.0, "cia": "Azul", **extra}


def test_far_band_starts_the_day_after_the_near_limit():
    assert far_cache.is_far(_deal(120), TODAY, 120) is False
    assert far_cache.is_far(_deal(121), TODAY, 120) is True


def test_round_trips_are_never_far_band():
    assert far_cache.is_far(_deal(150, tipo="roundtrip"), TODAY, 120) is False


def test_save_keeps_only_far_band_records_and_stamps_the_time():
    assert far_cache.save([_deal(60), _deal(150), _deal(170)], TODAY, 120, now=NOW) == 2
    stored = json.loads(far_cache.FAR_PATH.read_text(encoding="utf-8"))
    assert stored["visto_em"] == "2026-09-20T11:30:00Z"
    assert [d["data"] for d in stored["deals"]] == [_deal(150)["data"], _deal(170)["data"]]


def test_load_carries_far_records_stamped_with_when_they_were_seen():
    far_cache.save([_deal(150)], TODAY, 120, now=NOW)
    carried = far_cache.load_carried([], TODAY, 120, now=NOW + timedelta(hours=9))
    assert len(carried) == 1
    assert carried[0]["visto_em"] == "2026-09-20T11:30:00Z"
    assert carried[0]["preco"] == 300.0


def test_a_date_that_slid_into_the_near_band_is_dropped():
    far_cache.save([_deal(121), _deal(150)], TODAY, 120, now=NOW)
    tomorrow = TODAY + timedelta(days=1)
    carried = far_cache.load_carried([], tomorrow, 120, now=NOW + timedelta(hours=20))
    assert [d["data"] for d in carried] == [_deal(150)["data"]]


def test_a_key_the_cycle_already_searched_wins_over_the_carried_copy():
    far_cache.save([_deal(150), _deal(150, destino="FTE")], TODAY, 120, now=NOW)
    fresh = _deal(150, destino="FTE", preco=999.0)       # explicit window searched this cycle
    carried = far_cache.load_carried([fresh], TODAY, 120, now=NOW + timedelta(hours=6))
    assert [d["destino"] for d in carried] == ["GIG"]


def test_a_file_older_than_36_hours_is_ignored():
    far_cache.save([_deal(150)], TODAY, 120, now=NOW)
    assert far_cache.load_carried([], TODAY, 120, now=NOW + timedelta(hours=35)) != []
    assert far_cache.load_carried([], TODAY, 120, now=NOW + timedelta(hours=37)) == []


def test_missing_or_corrupt_file_means_nothing_to_carry():
    assert far_cache.load_carried([], TODAY, 120, now=NOW) == []
    far_cache.FAR_PATH.parent.mkdir(parents=True, exist_ok=True)
    for junk in ("not json", '{"deals": "nope"}', '{"visto_em": "x", "deals": []}', "[]"):
        far_cache.FAR_PATH.write_text(junk, encoding="utf-8")
        assert far_cache.load_carried([], TODAY, 120, now=NOW) == []


def test_save_never_raises_when_the_path_is_unwritable(tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(far_cache, "FAR_PATH", blocker / "far_deals.json")
    assert far_cache.save([_deal(150)], TODAY, 120, now=NOW) == 0
