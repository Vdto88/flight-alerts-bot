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


def _payload():
    return panel.build_history_payload(
        _route(),                                   # only CNF|SJK has a route summary
        {"CNF|SJK|2026-09-10": [["2026-09-01", 400.0], ["2026-09-02", 300.0]],
         "CNF|SJK|2026-09-11": [["2026-09-02", 350.0]],
         "POA|CNF|2026-10-01": [["2026-09-02", 500.0]]},
        generated_at=datetime(2026, 9, 18, 11, 0, tzinfo=timezone.utc))


def test_history_payload_shape():
    payload = _payload()
    assert payload["gerado_em"] == "2026-09-18T11:00:00Z"
    assert payload["rotas"]["CNF|SJK"]["med"] == 500.0


def test_one_history_file_per_route_holding_only_that_route(tmp_path):
    out = tmp_path / "history"
    assert panel.write_history_files(_payload(), str(out)) == 2
    sjk = json.loads((out / "CNF-SJK.json").read_text(encoding="utf-8"))
    assert sjk["gerado_em"] == "2026-09-18T11:00:00Z"
    assert sjk["rota"]["med"] == 500.0
    assert sorted(sjk["series"]) == ["CNF|SJK|2026-09-10", "CNF|SJK|2026-09-11"]


def test_a_route_first_seen_this_cycle_gets_a_file_without_a_summary(tmp_path):
    out = tmp_path / "history"
    panel.write_history_files(_payload(), str(out))
    poa = json.loads((out / "POA-CNF.json").read_text(encoding="utf-8"))
    assert poa["rota"] is None and list(poa["series"]) == ["POA|CNF|2026-10-01"]


def test_files_of_routes_that_disappeared_are_removed(tmp_path):
    out = tmp_path / "history"
    out.mkdir()
    (out / "CNF-OLD.json").write_text("{}", encoding="utf-8")
    (out / "CNF-OLD.enc.json").write_text("{}", encoding="utf-8")
    (out / "notes.txt").write_text("keep", encoding="utf-8")
    panel.write_history_files(_payload(), str(out))
    assert sorted(p.name for p in out.iterdir()) == ["CNF-SJK.json", "POA-CNF.json", "notes.txt"]


def test_a_malformed_key_costs_only_itself_and_nothing_stale_survives(tmp_path):
    out = tmp_path / "history"
    out.mkdir()
    (out / "CNF-OLD.json").write_text("{}", encoding="utf-8")
    payload = _payload()
    payload["series"]["quebrada"] = [["2026-09-02", 100.0]]
    assert panel.write_history_files(payload, str(out)) == 2
    assert sorted(p.name for p in out.iterdir()) == ["CNF-SJK.json", "POA-CNF.json"]


def test_an_entirely_unusable_payload_leaves_the_previous_files_alone(tmp_path):
    out = tmp_path / "history"
    out.mkdir()
    (out / "CNF-SJK.json").write_text('{"ontem": true}', encoding="utf-8")
    payload = panel.build_history_payload(_route(), {"quebrada": [["2026-09-02", 100.0]]})
    assert panel.write_history_files(payload, str(out)) == 0
    assert (out / "CNF-SJK.json").read_text(encoding="utf-8") == '{"ontem": true}'
