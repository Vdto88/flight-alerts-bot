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


def _window_dates(start: date, end: date) -> list[date]:
    out: list[date] = []
    d = start
    while d <= end:
        out.append(d)
        d += timedelta(days=1)
    return out


def target_dates(airport: str, today: date, groups: list[Group],
                 win_min: int, win_max: int, watches=()) -> list[date]:
    """Rolling window (today+win_min .. today+win_max) UNION the airport's group windows
    UNION the windows of any PriceWatch for the airport. Deduped, sorted, past dropped."""
    dates: set[date] = {today + timedelta(days=n) for n in range(win_min, win_max + 1)}
    g = group_of(airport, groups)
    if g:
        for w in g.windows:
            dates.update(_window_dates(w.start, w.end))
    for pw in watches:
        if pw.airport == airport and pw.window is not None:
            dates.update(_window_dates(pw.window.start, pw.window.end))
    return sorted(d for d in dates if d >= today)
