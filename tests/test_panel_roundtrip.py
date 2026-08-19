from datetime import date
import panel
from airlines.base import Flight
from alerts import RoundTripAlert


def _leg(o, d, dt, price, airline, url):
    return Flight(origin=o, destination=d, airline=airline, departure_date=dt,
                  departure_time="10h00", arrival_time="20h00", price=price,
                  is_direct=False, stops=1, booking_url=url)


def test_build_round_trip_deal_shape():
    rt = RoundTripAlert(
        watch_name="Europa",
        ida=_leg("CNF", "CDG", date(2027, 3, 1), 1450.0, "AZUL", "http://ida"),
        volta=_leg("MXP", "CNF", date(2027, 3, 15), 1440.0, "LATAM", "http://volta"),
        stay_days=14, total=2890.0, max_total=3000.0,
    )
    [deal] = panel.build_round_trip_deals([rt], "Europa (ida+volta)")
    assert deal["tipo"] == "roundtrip"
    assert deal["regiao"] == "Europa (ida+volta)"
    assert deal["origem"] == "CNF" and deal["destino"] == "CDG"
    assert deal["data"] == "2027-03-01"
    assert deal["preco"] == 2890.0
    assert deal["url_compra"] == "http://ida"
    assert deal["azul_cheapest"] is False and deal["price_watch"] is None
    assert deal["volta_origem"] == "MXP" and deal["volta_destino"] == "CNF"
    assert deal["data_volta"] == "2027-03-15"
    assert deal["cia_ida"] == "AZUL" and deal["cia_volta"] == "LATAM"
    assert deal["preco_ida"] == 1450.0 and deal["preco_volta"] == 1440.0
    assert deal["url_ida"] == "http://ida" and deal["url_volta"] == "http://volta"
    assert deal["estadia"] == 14 and deal["max_total"] == 3000.0
    assert deal["cia"] == "AZUL"
    assert deal["paradas"] == 1
    assert deal["direto"] is False
