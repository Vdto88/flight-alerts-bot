import json
from datetime import date

import config
import panel
from airlines.base import Flight
from alerts import RoundTripAlert


def test_every_searched_airport_and_the_hub_has_a_place():
    codes = {a for g in config.GROUPS for a in g.airports} | {config.AZUL_HUB}
    assert codes - set(config.AIRPORTS) == set()


def test_brazilian_airports_carry_a_state_and_foreign_ones_do_not():
    for code, a in config.AIRPORTS.items():
        assert a.cidade and a.pais, code
        assert (a.uf is not None) == (a.pais == "Brasil"), code


def test_airports_that_used_to_share_a_region_are_now_told_apart():
    fln, poa = config.AIRPORTS["FLN"], config.AIRPORTS["POA"]
    assert (fln.cidade, fln.uf) == ("Florianópolis", "SC")
    assert (poa.cidade, poa.uf) == ("Porto Alegre", "RS")
    assert config.AIRPORTS["FTE"].pais == "Argentina"
    assert config.AIRPORTS["SCL"].pais == "Chile"


def _f(origin, dest, price=300.0, d=date(2026, 10, 10)):
    return Flight(origin, dest, "Azul", d, "08h00", "09h00", price, True, 0, "u")


def test_deal_carries_the_place_of_the_non_hub_end_in_both_directions():
    ida = panel.build_deals([_f("CNF", "FLN")], "Sul", [])[0]
    volta = panel.build_deals([_f("FLN", "CNF")], "Sul", [])[0]
    for d in (ida, volta):
        assert (d["cidade"], d["uf"], d["pais"]) == ("Florianópolis", "SC", "Brasil")
        assert d["regiao"] == "Sul"          # the classic panel still reads the group name


def test_foreign_deal_has_country_and_no_state():
    d = panel.build_deals([_f("CNF", "LIS")], "Portugal", [])[0]
    assert (d["cidade"], d["uf"], d["pais"]) == ("Lisboa", None, "Portugal")


def test_unknown_airport_falls_back_to_its_code():
    d = panel.build_deals([_f("CNF", "ZZZ")], "X", [])[0]
    assert (d["cidade"], d["uf"], d["pais"]) == ("ZZZ", None, "")


def test_round_trip_deal_takes_the_place_of_the_outbound_destination():
    rt = RoundTripAlert("Europa", _f("CNF", "MAD"), _f("BCN", "CNF"), 14, 2800.0, 3000.0)
    d = panel.build_round_trip_deals([rt], "Europa (ida+volta)")[0]
    assert (d["cidade"], d["uf"], d["pais"]) == ("Madri", None, "Espanha")


def test_snapshot_ships_the_airport_table(tmp_path):
    out = tmp_path / "deals.json"
    panel.write_deals([], str(out))
    table = json.loads(out.read_text(encoding="utf-8"))["aeroportos"]
    assert table["CNF"] == {"cidade": "Belo Horizonte", "uf": "MG", "pais": "Brasil"}
    assert table["BRC"] == {"cidade": "Bariloche", "uf": None, "pais": "Argentina"}
