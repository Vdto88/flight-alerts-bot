from datetime import date

import panel
from airlines.base import Flight
from config import PriceWatch, month


def _f(airline, price, d=date(2026, 9, 10), dest="SJK", stops=0):
    return Flight("CNF", dest, airline, d, "08h00", "09h00", price, stops == 0, stops, "http://buy")


def test_build_deals_cheapest_per_date():
    deals = panel.build_deals([_f("GOL", 420.0), _f("Azul", 380.0), _f("LATAM", 500.0)], "São Paulo", [])
    assert len(deals) == 1
    d = deals[0]
    assert d["cia"] == "Azul" and d["preco"] == 380.0
    assert d["regiao"] == "São Paulo"
    assert d["origem"] == "CNF" and d["destino"] == "SJK"
    assert d["data"] == "2026-09-10" and d["hora"] == "08h00"
    assert d["direto"] is True and d["paradas"] == 0
    assert d["url_compra"] == "http://buy"


def test_build_deals_ignores_nonpositive_price():
    deals = panel.build_deals([_f("Azul", 0.0), _f("GOL", 420.0)], "SP", [])
    assert len(deals) == 1
    assert deals[0]["cia"] == "GOL" and deals[0]["preco"] == 420.0


def test_build_deals_azul_cheapest_flag_true():
    deals = panel.build_deals([_f("Azul", 300.0), _f("LATAM", 450.0)], "SP", [])
    assert deals[0]["azul_cheapest"] is True


def test_build_deals_azul_cheapest_flag_false_when_not_cheapest():
    deals = panel.build_deals([_f("Azul", 500.0), _f("GOL", 300.0)], "SP", [])
    assert deals[0]["azul_cheapest"] is False
    assert deals[0]["cia"] == "GOL"


def test_build_deals_price_watch_flag():
    watches = [PriceWatch("SJK", month(2026, 9), 400.0)]
    deals = panel.build_deals([_f("GOL", 380.0)], "SP", watches)
    assert deals[0]["price_watch"] == 400.0
    assert panel.build_deals([_f("GOL", 380.0)], "SP", [])[0]["price_watch"] is None


def test_build_deals_empty():
    assert panel.build_deals([], "SP", []) == []
