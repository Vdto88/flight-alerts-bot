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
                 win_min: int, win_max: int, watches=(), rt_watches=(),
                 far_max: int | None = None) -> list[date]:
    """Rolling window (today+win_min .. today+win_max) UNION the airport's group windows
    UNION any PriceWatch window for the airport UNION any RoundTripWatch span
    (depart_window.start .. depart_window.end + stay_max) when the airport is in that
    watch's pool. Deduped, sorted, past dropped. `far_max` widens the rolling range to
    today+far_max for a far cycle."""
    rolling_max = far_max if far_max is not None else win_max
    dates: set[date] = {today + timedelta(days=n) for n in range(win_min, rolling_max + 1)}
    g = group_of(airport, groups)
    if g:
        for w in g.windows:
            dates.update(_window_dates(w.start, w.end))
    for pw in watches:
        if pw.airport == airport and pw.window is not None:
            dates.update(_window_dates(pw.window.start, pw.window.end))
    for rw in rt_watches:
        if airport in rw.airports:
            dates.update(_window_dates(
                rw.depart_window.start,
                rw.depart_window.end + timedelta(days=rw.stay_max),
            ))
    return sorted(d for d in dates if d >= today)
