from datetime import date
import config


def test_month_expands_to_full_calendar_month():
    w = config.month(2027, 2)
    assert w.start == date(2027, 2, 1)
    assert w.end == date(2027, 2, 28)


def test_month_handles_leap_year():
    assert config.month(2024, 2).end == date(2024, 2, 29)


def test_groups_have_no_ssa():
    airports = [a for g in config.GROUPS for a in g.airports]
    assert "SSA" not in airports


def test_group_airports_have_no_duplicates():
    airports = [a for g in config.GROUPS for a in g.airports]
    assert len(airports) == len(set(airports))   # no IATA code shared across groups


def test_groups_include_europe_with_two_airports_each():
    by_name = {g.name: g for g in config.GROUPS}
    assert by_name["Portugal"].airports == ("LIS", "OPO")
    assert by_name["Espanha"].airports == ("MAD", "BCN")
    assert by_name["Itália"].airports == ("FCO", "MXP")
    assert by_name["França"].airports == ("CDG", "ORY")


def test_foz_and_patagonia_carry_windows():
    by_name = {g.name: g for g in config.GROUPS}
    assert by_name["Foz do Iguaçu"].windows == (config.month(2026, 10),)
    assert by_name["Patagônia"].windows == (config.month(2027, 2), config.month(2027, 3))


def test_every_group_has_a_unique_topic_id():
    assert all(g.topic_id is not None for g in config.GROUPS)
    ids = [g.topic_id for g in config.GROUPS]
    assert len(ids) == len(set(ids))   # no two groups share a topic
