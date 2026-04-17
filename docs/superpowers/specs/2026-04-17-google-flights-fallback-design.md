# Google Flights Fallback — Design Spec

**Date:** 2026-04-17  
**Status:** Approved

## Context

Diagnostic testing revealed all three airline scrapers are currently broken:

| Companhia | Status | Problema |
|-----------|--------|----------|
| GOL/Smiles | 406 | `api-key` placeholder inválida |
| LATAM | 404 | Endpoint `/api/v1/flights` não existe mais |
| Azul | 200 (fake) | Akamai bot challenge — requer JS |

**Decision:** Add Google Flights (via `fast-flights` library) as a fallback when individual scrapers return empty results. Keep existing scrapers intact so they can be restored when real API keys/endpoints are obtained.

## Architecture

```
scheduler.py
  └── para cada rota/data/companhia:
        1. chama searcher.search()  ← GOL, LATAM ou AZUL (sem mudança)
        2. se retornar [] → chama google_searcher.search(..., airline_filter=airline)
        3. filtra resultados do Google pelo nome da companhia esperada
        4. segue fluxo normal (cache + alertas)

airlines/
  ├── gol.py              ← sem mudança
  ├── latam.py            ← sem mudança
  ├── azul.py             ← sem mudança
  └── google_flights.py   ← NOVO
```

## Components

### `airlines/google_flights.py`

- Class `GoogleFlightsSearcher(FlightSearcher)` with `AIRLINE_NAME = "GOOGLE_FALLBACK"`
- `search(origin, destination, departure_date, airline_filter=None) -> List[Flight]`
- `fast-flights` is synchronous — runs via `asyncio.run_in_executor` to avoid blocking the event loop
- `_parse()` maps `fast-flights` result fields to `Flight` dataclass
- `airline_filter` applied after parse — keeps only flights whose `airline` field matches the expected carrier

### Airline name mapping

| Config name | Google Flights variants |
|-------------|------------------------|
| `GOL` | `"GOL"`, `"Gol"`, `"GOL Linhas Aéreas"` |
| `LATAM` | `"LATAM"`, `"Latam Airlines"`, `"LATAM Airlines"` |
| `AZUL` | `"AZUL"`, `"Azul"`, `"Azul Linhas Aéreas"` |

Matching is case-insensitive prefix check.

### `scheduler.py` change

Two lines added after the existing `search()` call:

```python
flights = await searcher.search(origin, dest, date)
if not flights:
    logger.info(f"{airline}/{origin}→{dest} {date}: usando Google Flights como fallback")
    flights = await google_searcher.search(origin, dest, date, airline_filter=airline)
```

`google_searcher` is a single `GoogleFlightsSearcher` instance created once at scheduler startup.

## Error Handling

- If `fast-flights` raises an exception, log warning and return `[]` — same pattern as existing scrapers
- If airline filter removes all results (Google didn't have that carrier), return `[]` — no alert sent
- No retry logic added for the fallback itself (keeps it simple)

## Dependencies

- Add `fast-flights` to `requirements.txt`

## Out of Scope

- Fixing GOL API key (requires real key from Smiles developer portal)
- Fixing LATAM endpoint (requires browser Network tab investigation)
- Fixing Azul bot protection (requires Playwright)
- Deduplication when native scraper eventually returns results alongside fallback
