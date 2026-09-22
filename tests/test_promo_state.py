import json
from datetime import datetime, timedelta, timezone

from promos import state as promo_state
from promos.classify import Classification
from promos.feeds import FeedItem

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
FARE = Classification("fare", ("Roma",), (), from_bh=False, origin_unknown=True)
MILES = Classification("miles", (), ("Livelo",), from_bh=False, origin_unknown=False)


def item(guid: str, published: datetime = NOW) -> FeedItem:
    return FeedItem(guid=guid, title=f"Título {guid}", summary="Resumo", link=f"https://example.com/{guid}",
                    source="Teste", categories=(), published_at=published)


def test_missing_file_gives_an_empty_seeding_state(tmp_path):
    st = promo_state.load(tmp_path / "nada.json")
    assert st.seen == {} and st.promos == [] and st.seeding


def test_corrupt_file_gives_an_empty_seeding_state(tmp_path):
    path = tmp_path / "promos_state.json"
    path.write_text("{isto não é json", encoding="utf-8")
    assert promo_state.load(path).seeding
    path.write_text(json.dumps({"seen": "errado"}), encoding="utf-8")
    assert promo_state.load(path).seeding


def test_round_trip_keeps_everything_and_stops_seeding(tmp_path):
    st = promo_state.load(tmp_path / "s.json")
    st.mark_seen("a", NOW)
    st.add_promo(item("a"), FARE)
    st.record_attempt("b")
    st.record_feed_result("Teste", False)
    promo_state.save(st, NOW, tmp_path / "s.json", tmp_path / "p.json")

    back = promo_state.load(tmp_path / "s.json")
    assert back.is_seen("a") and not back.is_seen("b")
    assert back.promos[0]["guid"] == "a"
    assert back.attempts == {"b": 1} and back.feed_failures == {"Teste": 1}
    assert not back.seeding


def test_mark_seen_drops_the_attempt_counter():
    st = promo_state.PromoState()
    assert st.record_attempt("a") == 1 and st.record_attempt("a") == 2
    st.mark_seen("a", NOW)
    assert st.attempts == {}


def test_add_promo_is_idempotent_and_maps_the_fields():
    st = promo_state.PromoState()
    st.add_promo(item("a"), FARE)
    st.add_promo(item("a"), FARE)
    assert len(st.promos) == 1
    assert st.promos[0] == {
        "guid": "a", "tipo": "passagem", "titulo": "Título a", "resumo": "Resumo",
        "link": "https://example.com/a", "fonte": "Teste", "publicado_em": "2026-09-21T12:00:00Z",
        "destinos": ["Roma"], "programas": [], "origem_bh": False, "origem_nao_informada": True,
    }
    st.add_promo(item("m"), MILES)
    assert st.promos[1]["tipo"] == "milhas" and st.promos[1]["programas"] == ["Livelo"]


def test_save_prunes_old_guids_and_old_promos(tmp_path):
    st = promo_state.PromoState()
    st.mark_seen("velho", NOW - timedelta(days=31))
    st.mark_seen("novo", NOW - timedelta(days=29))
    st.add_promo(item("p-velha", NOW - timedelta(days=15)), FARE)
    st.add_promo(item("p-nova", NOW - timedelta(days=13)), FARE)
    promo_state.save(st, NOW, tmp_path / "s.json", tmp_path / "p.json")
    assert list(st.seen) == ["novo"]
    assert [p["guid"] for p in st.promos] == ["p-nova"]


def test_payload_is_newest_first_and_never_carries_guids(tmp_path):
    st = promo_state.PromoState()
    st.add_promo(item("antiga", NOW - timedelta(days=2)), FARE)
    st.add_promo(item("recente", NOW - timedelta(hours=1)), MILES)
    promo_state.save(st, NOW, tmp_path / "s.json", tmp_path / "p.json")
    payload = json.loads((tmp_path / "p.json").read_text(encoding="utf-8"))
    assert payload["gerado_em"] == "2026-09-21T12:00:00Z"
    assert [p["titulo"] for p in payload["promos"]] == ["Título recente", "Título antiga"]
    assert all("guid" not in p for p in payload["promos"])


def test_health_alert_fires_once_at_six_failures_and_rearms_after_a_recovery():
    st = promo_state.PromoState()
    fired = [st.record_feed_result("Teste", False) for _ in range(8)]
    assert fired == [False] * 5 + [True] + [False] * 2
    assert st.record_feed_result("Teste", True) is False
    assert st.feed_failures == {} and st.health_alerted == []
    fired = [st.record_feed_result("Teste", False) for _ in range(6)]
    assert fired[-1] is True


def test_save_never_raises_when_the_directory_cannot_be_created(tmp_path):
    blocker = tmp_path / "arquivo"
    blocker.write_text("x", encoding="utf-8")
    promo_state.save(promo_state.PromoState(), NOW, blocker / "s.json", blocker / "p.json")
