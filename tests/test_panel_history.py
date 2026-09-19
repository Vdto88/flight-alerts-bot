import json
from datetime import datetime, timezone

import panel


def _deal(preco=300.0, **extra) -> dict:
    return {"origem": "CNF", "destino": "SJK", "data": "2026-09-10", "preco": preco, **extra}


def _stats(min_=300.0, med=400.0, spark=(400.0, 300.0)) -> dict:
    return {"CNF|SJK|2026-09-10": {"min": min_, "med": med, "spark": list(spark)}}


def _route(med=500.0, min_=320.0, n_dates=40):
    return {"CNF|SJK": {"med": med, "min": min_, "n_dates": n_dates, "by_month": {"09": med},
                        "by_dow": {"3": med}, "lead_curve": [], "n_closed": 0}}


def test_enrich_adds_history_fields_from_matching_stats():
    deal = _deal(preco=352.0)
    panel.enrich_with_history([deal], _stats())
    assert deal["hist_min"] == 300.0
    assert deal["hist_med"] == 400.0
    assert deal["spark"] == [400.0, 300.0]


def test_delta_pct_is_the_rounded_gap_between_current_price_and_the_median():
    deal = _deal(preco=352.0)
    panel.enrich_with_history([deal], _stats(med=400.0))
    assert deal["delta_pct"] == -12


def test_delta_pct_is_positive_when_the_current_price_is_above_the_median():
    deal = _deal(preco=432.0)
    panel.enrich_with_history([deal], _stats(med=400.0))
    assert deal["delta_pct"] == 8


def test_menor_hist_is_true_only_when_the_price_matches_or_beats_the_window_low():
    cheap, pricey = _deal(preco=300.0), _deal(preco=301.0)
    panel.enrich_with_history([cheap, pricey], _stats(min_=300.0))
    assert cheap["menor_hist"] is True
    assert pricey["menor_hist"] is False


def test_deals_without_history_are_left_untouched():
    deal = _deal()
    panel.enrich_with_history([deal], {})
    assert "delta_pct" not in deal and "spark" not in deal


def test_a_single_observation_is_not_enough_history_to_enrich():
    deal = _deal()
    panel.enrich_with_history([deal], _stats(spark=(300.0,)))
    assert "delta_pct" not in deal


def test_round_trip_deals_are_skipped_because_their_price_is_a_two_leg_total():
    deal = _deal(tipo="roundtrip", preco=2900.0)
    panel.enrich_with_history([deal], _stats())
    assert "delta_pct" not in deal


def test_enrich_returns_the_number_of_deals_it_touched():
    deals = [_deal(), _deal(preco=500.0), {"origem": "CNF", "destino": "POA", "data": "2026-09-10", "preco": 9.0}]
    assert panel.enrich_with_history(deals, _stats()) == 2


def test_enrich_adds_observation_count_and_first_seen_day():
    deal = _deal(preco=352.0)
    stats = _stats()
    stats["CNF|SJK|2026-09-10"].update(since="2026-08-30", n=2)
    panel.enrich_with_history([deal], stats, _route())
    assert deal["hist_dias"] == 2 and deal["hist_desde"] == "2026-08-30"


def test_a_never_seen_date_still_gets_a_route_level_verdict():
    deal = _deal(preco=400.0)
    panel.enrich_with_history([deal], {}, _route(med=500.0, min_=320.0))
    assert (deal["rota_med"], deal["rota_min"], deal["rota_delta_pct"]) == (500.0, 320.0, -20)
    assert "delta_pct" not in deal and "spark" not in deal


def test_route_fields_are_withheld_while_the_route_is_thin():
    deal = _deal(preco=400.0)
    panel.enrich_with_history([deal], {}, _route(n_dates=4))
    assert "rota_med" not in deal


def test_round_trips_get_no_route_fields():
    deal = _deal(preco=2900.0, tipo="roundtrip")
    panel.enrich_with_history([deal], {}, _route())
    assert "rota_med" not in deal


def test_history_payload_and_file(tmp_path):
    payload = panel.build_history_payload(
        _route(), {"CNF|SJK|2026-09-10": [["2026-09-01", 400.0], ["2026-09-02", 300.0]]},
        generated_at=datetime(2026, 9, 18, 11, 0, tzinfo=timezone.utc))
    assert payload["gerado_em"] == "2026-09-18T11:00:00Z"
    assert payload["rotas"]["CNF|SJK"]["med"] == 500.0
    assert payload["series"]["CNF|SJK|2026-09-10"][-1] == ["2026-09-02", 300.0]

    out = tmp_path / "history.json"
    panel.write_history(payload, str(out))
    assert json.loads(out.read_text(encoding="utf-8")) == payload
