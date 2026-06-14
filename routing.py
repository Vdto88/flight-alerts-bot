from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from config import Group


@dataclass(frozen=True)
class Route:
    origin: str
    destination: str
    non_hub: str            # the non-hub endpoint (carries window + topic)
    topic_id: Optional[int]


def group_of(airport: str, groups: list[Group]) -> Optional[Group]:
    for g in groups:
        if airport in g.airports:
            return g
    return None


def build_routes(groups: list[Group], hub: str) -> list[Route]:
    """hub <-> each airport of each group, both directions."""
    routes: list[Route] = []
    for g in groups:
        for airport in g.airports:
            routes.append(Route(hub, airport, airport, g.topic_id))
            routes.append(Route(airport, hub, airport, g.topic_id))
    return routes
