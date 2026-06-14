import config
import routing


def test_build_routes_both_directions_and_count():
    routes = routing.build_routes(config.GROUPS, config.AZUL_HUB)
    assert len(routes) == 42  # 21 airports x 2 directions
    pairs = {(r.origin, r.destination) for r in routes}
    assert ("CNF", "GIG") in pairs
    assert ("GIG", "CNF") in pairs
    assert all("CNF" in (r.origin, r.destination) for r in routes)


def test_build_routes_carries_non_hub_and_topic():
    routes = routing.build_routes(config.GROUPS, config.AZUL_HUB)
    igu = [r for r in routes if r.non_hub == "IGU"]
    assert len(igu) == 2
    assert all(r.topic_id is None for r in igu)  # Foz has no topic configured yet


def test_group_of_finds_group():
    g = routing.group_of("FTE", config.GROUPS)
    assert g is not None and g.name == "Patagônia"


def test_group_of_returns_none_for_unknown():
    assert routing.group_of("XXX", config.GROUPS) is None
