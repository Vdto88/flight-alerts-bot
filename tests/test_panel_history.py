import panel


def _deal(preco=300.0, **extra) -> dict:
    return {"origem": "CNF", "destino": "SJK", "data": "2026-09-10", "preco": preco, **extra}


def _stats(min_=300.0, med=400.0, spark=(400.0, 300.0)) -> dict:
    return {"CNF|SJK|2026-09-10": {"min": min_, "med": med, "spark": list(spark)}}


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
