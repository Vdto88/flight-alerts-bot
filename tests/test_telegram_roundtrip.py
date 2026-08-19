from datetime import date
import telegram_bot
from airlines.base import Flight
from alerts import RoundTripAlert


def _leg(o, d, dt, price, airline, url):
    return Flight(origin=o, destination=d, airline=airline, departure_date=dt,
                  departure_time="10h00", arrival_time="20h00", price=price,
                  is_direct=False, stops=1, booking_url=url)


def test_format_round_trip_alert_contains_both_legs():
    rt = RoundTripAlert(
        watch_name="Europa",
        ida=_leg("CNF", "CDG", date(2027, 3, 1), 1450.0, "AZUL", "http://ida"),
        volta=_leg("MXP", "CNF", date(2027, 3, 15), 1440.0, "LATAM", "http://volta"),
        stay_days=14, total=2890.0, max_total=3000.0,
    )
    msg = telegram_bot.format_round_trip_alert(rt)
    assert "IDA+VOLTA EUROPA" in msg
    assert "CNF → CDG" in msg and "MXP → CNF" in msg
    assert "01/03/2027" in msg and "15/03/2027" in msg
    assert "14 dias" in msg
    assert "R$ 2.890" in msg and "R$ 3.000" in msg
    assert "(http://ida)" in msg and "(http://volta)" in msg
