# Miles Scrapers (Smiles + Azul Fidelidade) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar monitoramento de passagens com milhas para Smiles (≤15k) e Azul Fidelidade (≤20k) na rota CNF↔IGU, enviando alertas no Telegram a cada 60 minutos.

**Architecture:** Dois scrapers Playwright que interceptam respostas JSON da API interna de cada site. O dataclass `Flight` ganha campos opcionais `miles` e `taxes_brl`. Um novo ciclo `run_miles_cycle()` no scheduler roda independente do ciclo de passagens em dinheiro.

**Tech Stack:** Python 3.11, playwright>=1.44 (Chromium), pytest, aiosqlite (cache já existente), APScheduler (scheduler já existente).

---

## Mapa de Arquivos

| Arquivo | Ação | Responsabilidade |
|---------|------|-----------------|
| `airlines/base.py` | Modificar | Adicionar `miles`, `taxes_brl`, `is_miles_flight`, atualizar `cache_key()` |
| `airlines/smiles_miles.py` | Criar | Scraper Playwright para Smiles |
| `airlines/azul_miles.py` | Criar | Scraper Playwright para Azul Fidelidade |
| `tests/fixtures/smiles_sample.json` | Criar | Fixture JSON para testes do Smiles |
| `tests/fixtures/azul_miles_sample.json` | Criar | Fixture JSON para testes da Azul |
| `tests/test_smiles_miles.py` | Criar | Testes do `SmilesMilesSearcher._parse()` |
| `tests/test_azul_miles.py` | Criar | Testes do `AzulMilesSearcher._parse()` |
| `config.py` | Modificar | Adicionar `MILES_ROUTES`, `MILES_DAYS_AHEAD`, `MILES_CYCLE_MINUTES` |
| `scheduler.py` | Modificar | Adicionar `run_miles_cycle()` e registrar no scheduler |
| `telegram_bot.py` | Modificar | Detectar `is_miles_flight` e usar template alternativo |
| `tests/test_base.py` | Modificar | Testes dos novos campos do `Flight` |
| `tests/test_scheduler.py` | Modificar | Testes do `run_miles_cycle()` |
| `tests/test_telegram_bot.py` | Modificar | Testes do formato de alerta de milhas |
| `requirements.txt` | Modificar | Adicionar `playwright>=1.44` |
| `Dockerfile` | Modificar | Instalar Chromium via `playwright install chromium` |

---

## Task 1: Estender o dataclass `Flight`

**Files:**
- Modify: `airlines/base.py`
- Modify: `tests/test_base.py`

- [ ] **Step 1: Escrever os testes que vão falhar**

Adicionar ao final de `tests/test_base.py`:

```python
def test_flight_miles_field_defaults_to_none():
    flight = Flight(
        origin="CNF", destination="IGU", airline="SMILES",
        departure_date=date(2026, 6, 15), departure_time="07h40",
        arrival_time="09h10", price=0.0, is_direct=True, stops=0,
        booking_url="https://smiles.com.br",
    )
    assert flight.miles is None
    assert flight.taxes_brl is None


def test_flight_is_miles_flight_false_when_no_miles():
    flight = Flight(
        origin="CNF", destination="GRU", airline="GOL",
        departure_date=date(2026, 5, 15), departure_time="07h40",
        arrival_time="09h10", price=289.90, is_direct=True, stops=0,
        booking_url="https://example.com",
    )
    assert flight.is_miles_flight is False


def test_flight_is_miles_flight_true_when_miles_set():
    flight = Flight(
        origin="CNF", destination="IGU", airline="SMILES",
        departure_date=date(2026, 6, 15), departure_time="07h40",
        arrival_time="09h10", price=0.0, is_direct=True, stops=0,
        booking_url="https://smiles.com.br",
        miles=15000,
    )
    assert flight.is_miles_flight is True


def test_miles_cache_key_uses_miles_floor():
    flight = Flight(
        origin="CNF", destination="IGU", airline="SMILES",
        departure_date=date(2026, 6, 15), departure_time="07h40",
        arrival_time="09h10", price=0.0, is_direct=True, stops=0,
        booking_url="https://smiles.com.br",
        miles=15500,
    )
    assert flight.cache_key() == "SMILES|CNF|IGU|2026-06-15|15000mi"


def test_miles_cache_key_same_floor_for_range():
    # 15000 e 15999 → mesmo cache key
    f1 = Flight("CNF", "IGU", "SMILES", date(2026, 6, 15), "07h40", "09h10",
                0.0, True, 0, "https://smiles.com.br", miles=15000)
    f2 = Flight("CNF", "IGU", "SMILES", date(2026, 6, 15), "07h40", "09h10",
                0.0, True, 0, "https://smiles.com.br", miles=15999)
    assert f1.cache_key() == f2.cache_key()


def test_money_cache_key_unchanged_when_no_miles():
    # Voos em dinheiro continuam usando price floor — regressão
    flight = Flight(
        origin="CNF", destination="GRU", airline="GOL",
        departure_date=date(2026, 5, 15), departure_time="07h40",
        arrival_time="09h10", price=289.90, is_direct=True, stops=0,
        booking_url="https://example.com",
    )
    assert flight.cache_key() == "GOL|CNF|GRU|2026-05-15|280"
```

- [ ] **Step 2: Rodar para confirmar falha**

```
pytest tests/test_base.py -v
```

Esperado: 6 falhas começando com `AttributeError: 'Flight' object has no attribute 'miles'` ou `TypeError`.

- [ ] **Step 3: Implementar as mudanças em `airlines/base.py`**

Substituir o dataclass `Flight` e o método `cache_key()` pelo código abaixo. Não alterar nada mais no arquivo:

```python
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional
import asyncio
import logging

logger = logging.getLogger(__name__)


@dataclass
class Flight:
    origin: str           # IATA, e.g. "CNF"
    destination: str      # IATA, e.g. "IGU"
    airline: str          # "GOL" | "LATAM" | "AZUL" | "SMILES" | "AZUL_MILES"
    departure_date: date
    departure_time: str   # e.g. "07h40"
    arrival_time: str     # e.g. "09h10"
    price: float          # BRL — 0.0 para voos de milhas
    is_direct: bool
    stops: int            # 0 ou 1
    booking_url: str

    # Campos de milhas — None para voos em dinheiro
    miles: Optional[int] = None
    taxes_brl: Optional[float] = None  # reservado, sempre None por ora

    @property
    def is_miles_flight(self) -> bool:
        return self.miles is not None

    def cache_key(self) -> str:
        if self.miles is not None:
            miles_floor = (self.miles // 1000) * 1000
            return f"{self.airline}|{self.origin}|{self.destination}|{self.departure_date}|{miles_floor}mi"
        price_floor = math.floor(self.price / 10) * 10
        return f"{self.airline}|{self.origin}|{self.destination}|{self.departure_date}|{price_floor}"
```

Manter a classe `FlightSearcher` exatamente como está (não mudar `search`, `search_range` na base).

- [ ] **Step 4: Rodar os testes**

```
pytest tests/test_base.py -v
```

Esperado: todos os testes passando, incluindo os 3 testes originais de `cache_key`.

- [ ] **Step 5: Commit**

```
git add airlines/base.py tests/test_base.py
git commit -m "feat: add optional miles fields to Flight dataclass"
```

---

## Task 2: Instalar Playwright

**Files:**
- Modify: `requirements.txt`
- Modify: `Dockerfile`

- [ ] **Step 1: Adicionar dependência ao `requirements.txt`**

Adicionar na seção principal (antes do bloco `# dev / test`):

```
playwright>=1.44
```

O arquivo deve ficar:
```
httpx==0.27.0
python-telegram-bot==21.3.0
APScheduler==3.10.4
aiosqlite==0.20.0
beautifulsoup4==4.12.3
lxml==5.4.0
fast-flights==2.2
python-dotenv==1.0.1
playwright>=1.44

# dev / test
pytest==8.1.1
pytest-asyncio==0.23.6
pytest-mock==3.14.0
```

- [ ] **Step 2: Instalar o pacote e o Chromium**

```
pip install playwright>=1.44
playwright install chromium
```

Esperado: mensagem `Downloading Chromium ...` seguida de `Chromium ... downloaded to ...`.

- [ ] **Step 3: Verificar instalação**

```python
# rodar no terminal interativo (python)
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_page()
    page.goto("https://example.com")
    print(page.title())
    b.close()
```

Esperado: imprime `Example Domain`.

- [ ] **Step 4: Atualizar o `Dockerfile`**

Substituir o conteúdo do `Dockerfile` por:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Dependências do sistema necessárias para o Chromium (Playwright)
RUN apt-get update && apt-get install -y \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium

COPY . .

# Create persistent directories — data/ and logs/ are typically mounted as volumes
RUN mkdir -p data logs

CMD ["python", "main.py"]
```

- [ ] **Step 5: Commit**

```
git add requirements.txt Dockerfile
git commit -m "feat: add Playwright Chromium dependency"
```

---

## Task 3: Scraper do Smiles

**Files:**
- Create: `airlines/smiles_miles.py`
- Create: `tests/fixtures/smiles_sample.json`
- Create: `tests/test_smiles_miles.py`

### Passo de descoberta (obrigatório antes dos testes)

O JSON retornado pela API interna do Smiles não é documentado. Antes de escrever os testes, execute o script abaixo para capturar a resposta real:

- [ ] **Step 1: Executar o script de descoberta**

Criar e rodar o arquivo temporário `scripts/smiles_discover.py`:

```python
"""
Script de descoberta — executa uma vez para capturar o JSON real da API do Smiles.
Abre o browser VISÍVEL para você ver o que acontece.
Salva todas as respostas JSON em scripts/smiles_responses.json.
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

ORIGIN = "CNF"
DEST = "IGU"
DATE = "15/07/2026"

async def discover():
    captured = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # visível!
        page = await browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ))

        async def capture(response):
            if response.status == 200:
                ct = response.headers.get("content-type", "")
                if "json" in ct:
                    try:
                        data = await response.json()
                        captured.append({"url": response.url, "data": data})
                        print(f"[JSON] {response.url}")
                    except Exception:
                        pass

        page.on("response", capture)

        url = (
            f"https://www.smiles.com.br/emissao-passagem-com-milhas"
            f"?originAirportCode={ORIGIN}&destinationAirportCode={DEST}"
            f"&departureDate={DATE}&adults=1&children=0&infants=0"
            f"&tripType=2&cabinType=all"
        )
        print(f"Abrindo: {url}")
        await page.goto(url, timeout=30000)
        await asyncio.sleep(8)  # aguardar carregamento completo

        Path("scripts").mkdir(exist_ok=True)
        Path("scripts/smiles_responses.json").write_text(
            json.dumps(captured, indent=2, ensure_ascii=False)
        )
        print(f"\n{len(captured)} respostas JSON salvas em scripts/smiles_responses.json")

        await browser.close()

asyncio.run(discover())
```

```
python scripts/smiles_discover.py
```

Esperado: browser abre, navega para smiles.com.br, fecha. Arquivo `scripts/smiles_responses.json` criado. Procure no arquivo a resposta que contém dados de voos (será a maior, com campos como `flightList` ou `flights` ou similar).

- [ ] **Step 2: Criar o fixture `tests/fixtures/smiles_sample.json`**

Criar a pasta se não existir:
```
mkdir tests\fixtures
```

Com base na resposta encontrada no passo anterior, criar `tests/fixtures/smiles_sample.json`. O formato abaixo é a estrutura esperada baseada na API histórica do Smiles — **verifique os nomes dos campos no arquivo de descoberta e ajuste se necessário**:

```json
{
  "requestedFlightSegmentList": [
    {
      "flightList": [
        {
          "departure": {
            "date": "2026-07-15T07:40:00",
            "airport": {"code": "CNF"}
          },
          "arrival": {
            "date": "2026-07-15T09:10:00",
            "airport": {"code": "IGU"}
          },
          "stops": 0,
          "availabilityList": [
            {
              "type": "SMILES_CLUB",
              "quantity": 4,
              "fare": {
                "miles": 15000,
                "money": {"total": 58.90}
              }
            },
            {
              "type": "PROMO",
              "quantity": 2,
              "fare": {
                "miles": 12000,
                "money": {"total": 58.90}
              }
            }
          ]
        },
        {
          "departure": {
            "date": "2026-07-15T14:00:00",
            "airport": {"code": "CNF"}
          },
          "arrival": {
            "date": "2026-07-15T15:30:00",
            "airport": {"code": "IGU"}
          },
          "stops": 0,
          "availabilityList": [
            {
              "type": "SMILES_CLUB",
              "quantity": 0,
              "fare": {
                "miles": 20000,
                "money": {"total": 58.90}
              }
            }
          ]
        }
      ]
    }
  ]
}
```

- [ ] **Step 3: Escrever os testes que vão falhar**

Criar `tests/test_smiles_miles.py`:

```python
import json
import pytest
from datetime import date
from pathlib import Path

FIXTURE = json.loads(Path("tests/fixtures/smiles_sample.json").read_text())


def test_parse_extracts_available_fares():
    from airlines.smiles_miles import SmilesMilesSearcher
    searcher = SmilesMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    # 2 fares with quantity>0 (third has quantity=0 and is skipped)
    assert len(flights) == 2


def test_parse_miles_values():
    from airlines.smiles_miles import SmilesMilesSearcher
    searcher = SmilesMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    miles_list = sorted(f.miles for f in flights)
    assert miles_list == [12000, 15000]


def test_parse_price_is_zero():
    from airlines.smiles_miles import SmilesMilesSearcher
    searcher = SmilesMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    assert all(f.price == 0.0 for f in flights)


def test_parse_is_miles_flight():
    from airlines.smiles_miles import SmilesMilesSearcher
    searcher = SmilesMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    assert all(f.is_miles_flight for f in flights)


def test_parse_airline_name():
    from airlines.smiles_miles import SmilesMilesSearcher
    searcher = SmilesMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    assert all(f.airline == "SMILES" for f in flights)


def test_parse_skips_zero_quantity():
    from airlines.smiles_miles import SmilesMilesSearcher
    searcher = SmilesMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    miles_values = [f.miles for f in flights]
    assert 20000 not in miles_values


def test_parse_departure_time():
    from airlines.smiles_miles import SmilesMilesSearcher
    searcher = SmilesMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    # First flight departs 07:40
    first = next(f for f in flights if f.miles == 15000)
    assert first.departure_time == "07h40"


def test_parse_is_direct():
    from airlines.smiles_miles import SmilesMilesSearcher
    searcher = SmilesMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    assert all(f.is_direct for f in flights)
    assert all(f.stops == 0 for f in flights)


def test_parse_empty_response():
    from airlines.smiles_miles import SmilesMilesSearcher
    searcher = SmilesMilesSearcher()
    flights = searcher._parse({}, "CNF", "IGU", date(2026, 7, 15))
    assert flights == []


def test_parse_missing_segment_list():
    from airlines.smiles_miles import SmilesMilesSearcher
    searcher = SmilesMilesSearcher()
    flights = searcher._parse({"otherKey": []}, "CNF", "IGU", date(2026, 7, 15))
    assert flights == []


def test_parse_taxes_brl_is_none():
    from airlines.smiles_miles import SmilesMilesSearcher
    searcher = SmilesMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    assert all(f.taxes_brl is None for f in flights)
```

- [ ] **Step 4: Rodar para confirmar falha**

```
pytest tests/test_smiles_miles.py -v
```

Esperado: `ModuleNotFoundError: No module named 'airlines.smiles_miles'`

- [ ] **Step 5: Criar `airlines/smiles_miles.py`**

```python
import asyncio
import logging
import os
import random
from datetime import date, timedelta
from typing import List, Optional

from playwright.async_api import async_playwright, Browser

from airlines.base import Flight, FlightSearcher

logger = logging.getLogger(__name__)

_SEARCH_BASE = "https://www.smiles.com.br/emissao-passagem-com-milhas"
_API_HOST = "api-air-flightsearch-prd.smiles.com.br"


def _is_headless() -> bool:
    return os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() != "false"


def _parse_time(iso_str: str) -> str:
    """Extrai 'HHhMM' de '2026-07-15T07:40:00'."""
    if not iso_str or "T" not in iso_str:
        return ""
    time_part = iso_str.split("T")[1][:5]  # "07:40"
    return time_part.replace(":", "h")


class SmilesMilesSearcher(FlightSearcher):
    AIRLINE_NAME = "SMILES"

    async def search(self, origin: str, destination: str, departure_date: date) -> List[Flight]:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=_is_headless())
            try:
                return await self._search_date(browser, origin, destination, departure_date)
            except Exception as e:
                logger.warning(f"SMILES/{origin}→{destination} {departure_date}: {e}")
                return []
            finally:
                await browser.close()

    async def search_range(
        self, origin: str, destination: str, days_ahead: int = 30, batch_size: int = 1
    ) -> List[Flight]:
        """Abre um único browser e reutiliza para todas as datas (mais eficiente)."""
        today = date.today()
        dates = [today + timedelta(days=i) for i in range(1, days_ahead + 1)]
        all_flights: List[Flight] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=_is_headless())
            try:
                for d in dates:
                    flights = await self._search_date(browser, origin, destination, d)
                    all_flights.extend(flights)
                    await asyncio.sleep(random.uniform(2, 4))
            except Exception as e:
                logger.warning(f"SMILES/search_range {origin}→{destination}: {e}")
            finally:
                await browser.close()

        return all_flights

    async def _search_date(
        self, browser: Browser, origin: str, destination: str, departure_date: date
    ) -> List[Flight]:
        page = await browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        captured: list = []

        async def handle_response(response):
            if _API_HOST in response.url and response.status == 200:
                try:
                    data = await response.json()
                    captured.append(data)
                except Exception:
                    pass

        page.on("response", handle_response)

        try:
            date_str = departure_date.strftime("%d/%m/%Y")
            url = (
                f"{_SEARCH_BASE}"
                f"?originAirportCode={origin}"
                f"&destinationAirportCode={destination}"
                f"&departureDate={date_str}"
                f"&adults=1&children=0&infants=0"
                f"&tripType=2&cabinType=all"
            )
            await page.goto(url, timeout=30000)
            await page.wait_for_load_state("networkidle", timeout=20000)
            await asyncio.sleep(random.uniform(1, 2))
        except Exception as e:
            logger.warning(f"SMILES page {origin}→{destination} {departure_date}: {e}")
            return []
        finally:
            await page.close()

        if not captured:
            logger.info(f"SMILES/{origin}→{destination} {departure_date}: sem resposta JSON capturada")
            return []

        return self._parse(captured[0], origin, destination, departure_date)

    def _parse(
        self, data: dict, origin: str, destination: str, departure_date: date
    ) -> List[Flight]:
        flights: List[Flight] = []
        try:
            segments = data.get("requestedFlightSegmentList", [])
            for segment in segments:
                for flight_data in segment.get("flightList", []):
                    stops = int(flight_data.get("stops", 0))
                    if stops > 1:
                        continue

                    dep_time = _parse_time(flight_data.get("departure", {}).get("date", ""))
                    arr_time = _parse_time(flight_data.get("arrival", {}).get("date", ""))

                    booking_url = (
                        f"{_SEARCH_BASE}"
                        f"?originAirportCode={origin}"
                        f"&destinationAirportCode={destination}"
                        f"&departureDate={departure_date.strftime('%d/%m/%Y')}"
                        f"&adults=1&tripType=2"
                    )

                    for avail in flight_data.get("availabilityList", []):
                        if int(avail.get("quantity", 0)) <= 0:
                            continue
                        miles = avail.get("fare", {}).get("miles")
                        if miles is None:
                            continue

                        flights.append(Flight(
                            origin=origin,
                            destination=destination,
                            airline=self.AIRLINE_NAME,
                            departure_date=departure_date,
                            departure_time=dep_time,
                            arrival_time=arr_time,
                            price=0.0,
                            is_direct=(stops == 0),
                            stops=stops,
                            booking_url=booking_url,
                            miles=int(miles),
                        ))
        except Exception as e:
            logger.error(f"SMILES parse error: {e}", exc_info=True)
        return flights
```

- [ ] **Step 6: Rodar os testes**

```
pytest tests/test_smiles_miles.py -v
```

Esperado: todos os 11 testes passando.

> **Nota:** Se os nomes dos campos no JSON real (do script de descoberta) forem diferentes de `requestedFlightSegmentList`, `flightList`, `availabilityList`, `fare.miles` etc., atualize o fixture `tests/fixtures/smiles_sample.json` para refletir a estrutura real e ajuste os `data.get(...)` correspondentes em `_parse()`. Os testes guiarão as correções.

- [ ] **Step 7: Commit**

```
git add airlines/smiles_miles.py tests/fixtures/smiles_sample.json tests/test_smiles_miles.py
git commit -m "feat: add Smiles miles scraper with Playwright"
```

---

## Task 4: Scraper da Azul Fidelidade

**Files:**
- Create: `airlines/azul_miles.py`
- Create: `tests/fixtures/azul_miles_sample.json`
- Create: `tests/test_azul_miles.py`

### Passo de descoberta (obrigatório)

- [ ] **Step 1: Executar o script de descoberta**

Criar e rodar `scripts/azul_discover.py`:

```python
"""
Script de descoberta — executa uma vez para capturar o JSON real da Azul Fidelidade.
Abre o browser VISÍVEL. Salva todas as respostas JSON em scripts/azul_responses.json.
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

async def discover():
    captured = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ))

        async def capture(response):
            if response.status == 200:
                ct = response.headers.get("content-type", "")
                if "json" in ct:
                    try:
                        data = await response.json()
                        captured.append({"url": response.url, "data": data})
                        print(f"[JSON] {response.url}")
                    except Exception:
                        pass

        page.on("response", capture)

        # Tentar a URL de busca do Azul Fidelidade
        # Se redirecionar ou não funcionar, navegue manualmente para a busca de passagens com pontos
        await page.goto("https://www.azulfidelidade.com.br/", timeout=30000)
        print("Browser aberto. Navegue até a busca de passagens com pontos CNF → IGU e clique em Buscar.")
        print("Aguardando 30 segundos para capturar respostas...")
        await asyncio.sleep(30)

        Path("scripts").mkdir(exist_ok=True)
        Path("scripts/azul_responses.json").write_text(
            json.dumps(captured, indent=2, ensure_ascii=False)
        )
        print(f"\n{len(captured)} respostas JSON salvas em scripts/azul_responses.json")

        await browser.close()

asyncio.run(discover())
```

```
python scripts/azul_discover.py
```

Esperado: browser abre em `azulfidelidade.com.br`. Navegue manualmente até a busca de passagens com pontos, selecione CNF → IGU e clique em buscar. O script captura todas as respostas JSON. Procure em `scripts/azul_responses.json` a resposta com dados de voos.

- [ ] **Step 2: Criar o fixture `tests/fixtures/azul_miles_sample.json`**

Com base na resposta encontrada no passo anterior, criar o fixture. O formato abaixo é uma **estimativa** — substitua pelos campos reais encontrados na descoberta:

```json
{
  "flights": [
    {
      "departureTime": "07:40",
      "arrivalTime": "09:10",
      "stops": 0,
      "origin": "CNF",
      "destination": "IGU",
      "fares": [
        {
          "points": 20000,
          "available": true
        }
      ]
    },
    {
      "departureTime": "14:00",
      "arrivalTime": "15:30",
      "stops": 0,
      "origin": "CNF",
      "destination": "IGU",
      "fares": [
        {
          "points": 18000,
          "available": true
        },
        {
          "points": 25000,
          "available": false
        }
      ]
    }
  ]
}
```

**Importante:** Este JSON é apenas um template. Substitua pelos campos reais que o script de descoberta retornou antes de continuar.

- [ ] **Step 3: Escrever os testes que vão falhar**

Criar `tests/test_azul_miles.py` (ajuste os valores esperados para corresponder ao seu fixture real):

```python
import json
import pytest
from datetime import date
from pathlib import Path

FIXTURE = json.loads(Path("tests/fixtures/azul_miles_sample.json").read_text())


def test_parse_extracts_available_fares():
    from airlines.azul_miles import AzulMilesSearcher
    searcher = AzulMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    # 3 fares disponíveis (o available=false é ignorado)
    assert len(flights) == 3


def test_parse_miles_values():
    from airlines.azul_miles import AzulMilesSearcher
    searcher = AzulMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    miles_list = sorted(f.miles for f in flights)
    assert miles_list == [18000, 20000, 20000]


def test_parse_price_is_zero():
    from airlines.azul_miles import AzulMilesSearcher
    searcher = AzulMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    assert all(f.price == 0.0 for f in flights)


def test_parse_is_miles_flight():
    from airlines.azul_miles import AzulMilesSearcher
    searcher = AzulMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    assert all(f.is_miles_flight for f in flights)


def test_parse_airline_name():
    from airlines.azul_miles import AzulMilesSearcher
    searcher = AzulMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    assert all(f.airline == "AZUL_MILES" for f in flights)


def test_parse_skips_unavailable():
    from airlines.azul_miles import AzulMilesSearcher
    searcher = AzulMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    miles_values = [f.miles for f in flights]
    assert 25000 not in miles_values


def test_parse_departure_time():
    from airlines.azul_miles import AzulMilesSearcher
    searcher = AzulMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    first = next(f for f in flights if f.miles == 20000 and f.departure_time == "07h40")
    assert first.departure_time == "07h40"


def test_parse_empty_response():
    from airlines.azul_miles import AzulMilesSearcher
    searcher = AzulMilesSearcher()
    flights = searcher._parse({}, "CNF", "IGU", date(2026, 7, 15))
    assert flights == []


def test_parse_taxes_brl_is_none():
    from airlines.azul_miles import AzulMilesSearcher
    searcher = AzulMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    assert all(f.taxes_brl is None for f in flights)
```

- [ ] **Step 4: Rodar para confirmar falha**

```
pytest tests/test_azul_miles.py -v
```

Esperado: `ModuleNotFoundError: No module named 'airlines.azul_miles'`

- [ ] **Step 5: Criar `airlines/azul_miles.py`**

Este arquivo é baseado no template do scraper da Azul Fidelidade. **Os campos do `_parse()` devem ser ajustados para corresponder ao JSON real encontrado na descoberta.** O template abaixo usa os campos do fixture de exemplo:

```python
import asyncio
import logging
import os
import random
from datetime import date, timedelta
from typing import List, Optional

from playwright.async_api import async_playwright, Browser

from airlines.base import Flight, FlightSearcher

logger = logging.getLogger(__name__)

# URL da busca de passagens com pontos da Azul Fidelidade.
# Confirme a URL correta pelo script de descoberta — pode ser diferente.
_SEARCH_BASE = "https://www.azulfidelidade.com.br"
_API_HOST = "azulfidelidade.com.br"  # ajuste para o host real da API interna


def _is_headless() -> bool:
    return os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() != "false"


def _parse_time(time_str: str) -> str:
    """Converte '07:40' → '07h40'."""
    if not time_str or ":" not in time_str:
        return ""
    return time_str[:5].replace(":", "h")


class AzulMilesSearcher(FlightSearcher):
    AIRLINE_NAME = "AZUL_MILES"

    async def search(self, origin: str, destination: str, departure_date: date) -> List[Flight]:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=_is_headless())
            try:
                return await self._search_date(browser, origin, destination, departure_date)
            except Exception as e:
                logger.warning(f"AZUL_MILES/{origin}→{destination} {departure_date}: {e}")
                return []
            finally:
                await browser.close()

    async def search_range(
        self, origin: str, destination: str, days_ahead: int = 30, batch_size: int = 1
    ) -> List[Flight]:
        today = date.today()
        dates = [today + timedelta(days=i) for i in range(1, days_ahead + 1)]
        all_flights: List[Flight] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=_is_headless())
            try:
                for d in dates:
                    flights = await self._search_date(browser, origin, destination, d)
                    all_flights.extend(flights)
                    await asyncio.sleep(random.uniform(2, 4))
            except Exception as e:
                logger.warning(f"AZUL_MILES/search_range {origin}→{destination}: {e}")
            finally:
                await browser.close()

        return all_flights

    async def _search_date(
        self, browser: Browser, origin: str, destination: str, departure_date: date
    ) -> List[Flight]:
        page = await browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        captured: list = []

        async def handle_response(response):
            if _API_HOST in response.url and response.status == 200:
                try:
                    data = await response.json()
                    captured.append(data)
                except Exception:
                    pass

        page.on("response", handle_response)

        try:
            # Ajuste a URL de busca com base no que o script de descoberta mostrou
            date_str = departure_date.strftime("%Y-%m-%d")
            url = (
                f"{_SEARCH_BASE}/busca"
                f"?origin={origin}&destination={destination}"
                f"&date={date_str}&adults=1&type=points"
            )
            await page.goto(url, timeout=30000)
            await page.wait_for_load_state("networkidle", timeout=20000)
            await asyncio.sleep(random.uniform(1, 2))
        except Exception as e:
            logger.warning(f"AZUL_MILES page {origin}→{destination} {departure_date}: {e}")
            return []
        finally:
            await page.close()

        if not captured:
            logger.info(f"AZUL_MILES/{origin}→{destination} {departure_date}: sem JSON capturado")
            return []

        return self._parse(captured[0], origin, destination, departure_date)

    def _parse(
        self, data: dict, origin: str, destination: str, departure_date: date
    ) -> List[Flight]:
        """
        Converter JSON da API interna da Azul em lista de Flight.
        Os nomes dos campos abaixo são baseados no fixture de exemplo.
        Ajuste conforme o JSON real encontrado na descoberta.
        """
        flights: List[Flight] = []
        try:
            for flight_data in data.get("flights", []):
                stops = int(flight_data.get("stops", 0))
                if stops > 1:
                    continue

                dep_time = _parse_time(flight_data.get("departureTime", ""))
                arr_time = _parse_time(flight_data.get("arrivalTime", ""))

                booking_url = (
                    f"{_SEARCH_BASE}/busca"
                    f"?origin={origin}&destination={destination}"
                    f"&date={departure_date.strftime('%Y-%m-%d')}&adults=1&type=points"
                )

                for fare in flight_data.get("fares", []):
                    if not fare.get("available", False):
                        continue
                    points = fare.get("points")
                    if points is None:
                        continue

                    flights.append(Flight(
                        origin=origin,
                        destination=destination,
                        airline=self.AIRLINE_NAME,
                        departure_date=departure_date,
                        departure_time=dep_time,
                        arrival_time=arr_time,
                        price=0.0,
                        is_direct=(stops == 0),
                        stops=stops,
                        booking_url=booking_url,
                        miles=int(points),
                    ))
        except Exception as e:
            logger.error(f"AZUL_MILES parse error: {e}", exc_info=True)
        return flights
```

- [ ] **Step 6: Rodar os testes**

```
pytest tests/test_azul_miles.py -v
```

Esperado: todos os 9 testes passando.

- [ ] **Step 7: Commit**

```
git add airlines/azul_miles.py tests/fixtures/azul_miles_sample.json tests/test_azul_miles.py
git commit -m "feat: add Azul Fidelidade miles scraper with Playwright"
```

---

## Task 5: Config e Scheduler

**Files:**
- Modify: `config.py`
- Modify: `scheduler.py`
- Modify: `tests/test_scheduler.py`

- [ ] **Step 1: Escrever os testes do scheduler que vão falhar**

Adicionar ao final de `tests/test_scheduler.py`:

```python
def _miles_flight(miles: int, airline: str = "SMILES") -> Flight:
    return Flight(
        origin="CNF", destination="IGU", airline=airline,
        departure_date=date(2026, 7, 15), departure_time="07h40",
        arrival_time="09h10", price=0.0, is_direct=True, stops=0,
        booking_url="https://smiles.com.br",
        miles=miles,
    )


async def test_run_miles_cycle_sends_alert_below_threshold(monkeypatch):
    import scheduler
    import cache
    import telegram_bot

    cheap = _miles_flight(miles=14000, airline="SMILES")

    monkeypatch.setattr(scheduler, "MILES_SEARCHERS", {
        "SMILES": MagicMock(search_range=AsyncMock(return_value=[cheap]))
    })
    monkeypatch.setattr(cache, "is_cached", AsyncMock(return_value=False))
    monkeypatch.setattr(cache, "save_to_cache", AsyncMock())
    monkeypatch.setattr(telegram_bot, "send_alert", AsyncMock())
    monkeypatch.setattr(scheduler, "MILES_ROUTES", [
        {"from": "CNF", "to": "IGU", "miles_threshold": 15000, "program": "SMILES"}
    ])

    await scheduler.run_miles_cycle()

    telegram_bot.send_alert.assert_called_once_with(cheap)
    cache.save_to_cache.assert_called_once()


async def test_run_miles_cycle_sends_alert_at_exact_threshold(monkeypatch):
    import scheduler
    import cache
    import telegram_bot

    exact = _miles_flight(miles=15000, airline="SMILES")

    monkeypatch.setattr(scheduler, "MILES_SEARCHERS", {
        "SMILES": MagicMock(search_range=AsyncMock(return_value=[exact]))
    })
    monkeypatch.setattr(cache, "is_cached", AsyncMock(return_value=False))
    monkeypatch.setattr(cache, "save_to_cache", AsyncMock())
    monkeypatch.setattr(telegram_bot, "send_alert", AsyncMock())
    monkeypatch.setattr(scheduler, "MILES_ROUTES", [
        {"from": "CNF", "to": "IGU", "miles_threshold": 15000, "program": "SMILES"}
    ])

    await scheduler.run_miles_cycle()

    telegram_bot.send_alert.assert_called_once_with(exact)


async def test_run_miles_cycle_skips_above_threshold(monkeypatch):
    import scheduler
    import cache
    import telegram_bot

    expensive = _miles_flight(miles=16000, airline="SMILES")

    monkeypatch.setattr(scheduler, "MILES_SEARCHERS", {
        "SMILES": MagicMock(search_range=AsyncMock(return_value=[expensive]))
    })
    monkeypatch.setattr(cache, "is_cached", AsyncMock(return_value=False))
    monkeypatch.setattr(cache, "save_to_cache", AsyncMock())
    monkeypatch.setattr(telegram_bot, "send_alert", AsyncMock())
    monkeypatch.setattr(scheduler, "MILES_ROUTES", [
        {"from": "CNF", "to": "IGU", "miles_threshold": 15000, "program": "SMILES"}
    ])

    await scheduler.run_miles_cycle()

    telegram_bot.send_alert.assert_not_called()


async def test_run_miles_cycle_skips_cached(monkeypatch):
    import scheduler
    import cache
    import telegram_bot

    cheap = _miles_flight(miles=14000, airline="SMILES")

    monkeypatch.setattr(scheduler, "MILES_SEARCHERS", {
        "SMILES": MagicMock(search_range=AsyncMock(return_value=[cheap]))
    })
    monkeypatch.setattr(cache, "is_cached", AsyncMock(return_value=True))
    monkeypatch.setattr(cache, "save_to_cache", AsyncMock())
    monkeypatch.setattr(telegram_bot, "send_alert", AsyncMock())
    monkeypatch.setattr(scheduler, "MILES_ROUTES", [
        {"from": "CNF", "to": "IGU", "miles_threshold": 15000, "program": "SMILES"}
    ])

    await scheduler.run_miles_cycle()

    telegram_bot.send_alert.assert_not_called()
```

- [ ] **Step 2: Rodar para confirmar falha**

```
pytest tests/test_scheduler.py::test_run_miles_cycle_sends_alert_below_threshold -v
```

Esperado: `ImportError` ou `AttributeError: module 'scheduler' has no attribute 'run_miles_cycle'`

- [ ] **Step 3: Atualizar `config.py`**

Adicionar ao final do arquivo (após as constantes existentes):

```python
MILES_ROUTES = [
    {"from": "CNF", "to": "IGU", "miles_threshold": 15000, "program": "SMILES"},
    {"from": "IGU", "to": "CNF", "miles_threshold": 15000, "program": "SMILES"},
    {"from": "CNF", "to": "IGU", "miles_threshold": 20000, "program": "AZUL_MILES"},
    {"from": "IGU", "to": "CNF", "miles_threshold": 20000, "program": "AZUL_MILES"},
]

# 30 dias é suficiente — cada data requer uma sessão Playwright (~5–10s)
# 30 datas × 4 rotas × ~7s = ~14 min por ciclo, dentro do MILES_CYCLE_MINUTES
MILES_DAYS_AHEAD: int = 30
MILES_CYCLE_MINUTES: int = 60
```

- [ ] **Step 4: Atualizar `scheduler.py`**

Adicionar os imports no topo do arquivo, após os imports existentes:

```python
from airlines.smiles_miles import SmilesMilesSearcher
from airlines.azul_miles import AzulMilesSearcher
from config import ROUTES, CYCLE_MINUTES, CACHE_TTL_HOURS, SEARCH_DAYS_AHEAD, BATCH_SIZE, \
    MILES_ROUTES, MILES_DAYS_AHEAD, MILES_CYCLE_MINUTES
```

Adicionar após o bloco `SEARCHERS` existente:

```python
MILES_SEARCHERS: dict[str, FlightSearcher] = {
    "SMILES":     SmilesMilesSearcher(),
    "AZUL_MILES": AzulMilesSearcher(),
}
```

Adicionar a função `run_miles_cycle()` após `run_cycle()`:

```python
async def run_miles_cycle() -> None:
    start = time.monotonic()
    total_alerts = 0
    logger.info(f"CICLO MILHAS INICIADO — {len(MILES_ROUTES)} rotas")

    for route in MILES_ROUTES:
        origin = route["from"]
        dest = route["to"]
        threshold = route["miles_threshold"]
        program = route["program"]
        searcher = MILES_SEARCHERS[program]

        try:
            flights = await searcher.search_range(origin, dest, MILES_DAYS_AHEAD)
        except Exception as e:
            logger.warning(f"ERRO MILHAS {program}/{origin}→{dest}: {e}")
            continue

        below = [f for f in flights if f.miles is not None and f.miles <= threshold]
        logger.info(
            f"{program}/{origin}→{dest}: {len(flights)} voos, {len(below)} abaixo de {threshold} milhas"
        )

        for flight in below:
            if not await cache.is_cached(flight):
                await telegram_bot.send_alert(flight)
                await cache.save_to_cache(flight, CACHE_TTL_HOURS)
                total_alerts += 1

    elapsed = time.monotonic() - start
    logger.info(f"CICLO MILHAS CONCLUÍDO — {elapsed:.0f}s | alertas: {total_alerts}")
```

Atualizar a função `create_scheduler()` para registrar o novo ciclo:

```python
def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_cycle,
        trigger="interval",
        minutes=CYCLE_MINUTES,
        next_run_time=datetime.now(),
        id="flight_cycle",
    )
    scheduler.add_job(
        run_miles_cycle,
        trigger="interval",
        minutes=MILES_CYCLE_MINUTES,
        next_run_time=datetime.now(),
        id="miles_cycle",
    )
    return scheduler
```

- [ ] **Step 5: Rodar os testes**

```
pytest tests/test_scheduler.py -v
```

Esperado: todos os testes passando (os antigos + os 4 novos de milhas).

- [ ] **Step 6: Commit**

```
git add config.py scheduler.py tests/test_scheduler.py
git commit -m "feat: add miles cycle to scheduler (Smiles + Azul Fidelidade)"
```

---

## Task 6: Formato de Alerta de Milhas no Telegram

**Files:**
- Modify: `telegram_bot.py`
- Modify: `tests/test_telegram_bot.py`

- [ ] **Step 1: Escrever os testes que vão falhar**

Adicionar ao final de `tests/test_telegram_bot.py`:

```python
def _sample_miles_flight(miles: int = 15000, airline: str = "SMILES") -> Flight:
    return Flight(
        origin="CNF",
        destination="IGU",
        airline=airline,
        departure_date=date(2026, 7, 15),
        departure_time="07h40",
        arrival_time="09h10",
        price=0.0,
        is_direct=True,
        stops=0,
        booking_url="https://smiles.com.br/busca",
        miles=miles,
    )


def test_miles_alert_contains_miles_value():
    msg = telegram_bot.format_alert(_sample_miles_flight(15000))
    assert "15.000 milhas" in msg


def test_miles_alert_contains_route():
    msg = telegram_bot.format_alert(_sample_miles_flight())
    assert "CNF → IGU" in msg


def test_miles_alert_contains_airline():
    msg = telegram_bot.format_alert(_sample_miles_flight(airline="SMILES"))
    assert "SMILES" in msg or "Smiles" in msg


def test_miles_alert_contains_date():
    msg = telegram_bot.format_alert(_sample_miles_flight())
    assert "15/07/2026" in msg


def test_miles_alert_uses_milhas_header():
    msg = telegram_bot.format_alert(_sample_miles_flight())
    assert "MILHAS" in msg.upper()


def test_miles_alert_does_not_show_brl_price():
    msg = telegram_bot.format_alert(_sample_miles_flight())
    assert "R$" not in msg


def test_money_alert_unchanged():
    # Regressão: alerta de dinheiro não deve mudar
    money_flight = _sample_flight()
    msg = telegram_bot.format_alert(money_flight)
    assert "289,90" in msg
    assert "PASSAGEM BARATA" in msg.upper()


def test_miles_alert_direct_flight():
    msg = telegram_bot.format_alert(_sample_miles_flight())
    assert "Direto" in msg


def test_miles_alert_azul():
    msg = telegram_bot.format_alert(_sample_miles_flight(miles=20000, airline="AZUL_MILES"))
    assert "20.000 milhas" in msg
    assert "AZUL" in msg.upper()
```

- [ ] **Step 2: Rodar para confirmar falha**

```
pytest tests/test_telegram_bot.py::test_miles_alert_contains_miles_value -v
```

Esperado: `AssertionError` — o alerta atual mostra `R$ 0,00` em vez de `15.000 milhas`.

- [ ] **Step 3: Atualizar `telegram_bot.py`**

Substituir a função `format_alert` pelo código abaixo. Não alterar nada mais no arquivo:

```python
def format_alert(flight: Flight) -> str:
    if flight.is_miles_flight:
        return _format_miles_alert(flight)
    return _format_money_alert(flight)


def _format_money_alert(flight: Flight) -> str:
    dep_date = flight.departure_date.strftime("%d/%m/%Y")
    price_str = f"R$ {flight.price:_.2f}".replace("_", "X").replace(".", ",").replace("X", ".")
    stops_str = "Direto" if flight.is_direct else f"{flight.stops} parada"
    now_str = datetime.now().strftime("%H:%M")

    return (
        f"✈️ *PASSAGEM BARATA DETECTADA*\n\n"
        f"🛫 {flight.origin} → {flight.destination}\n"
        f"💰 {price_str}\n"
        f"📅 {dep_date} • {flight.departure_time} → {flight.arrival_time}\n"
        f"🏢 {flight.airline} • {stops_str}\n"
        f"🔗 [Reservar agora]({flight.booking_url})\n\n"
        f"⏰ Detectado às {now_str}"
    )


def _format_miles_alert(flight: Flight) -> str:
    dep_date = flight.departure_date.strftime("%d/%m/%Y")
    miles_str = f"{flight.miles:,}".replace(",", ".")  # 15000 → "15.000"
    stops_str = "Direto" if flight.is_direct else f"{flight.stops} parada"
    now_str = datetime.now().strftime("%H:%M")

    return (
        f"✈️ *PASSAGEM COM MILHAS DETECTADA*\n\n"
        f"🛫 {flight.origin} → {flight.destination}\n"
        f"🏆 {miles_str} milhas\n"
        f"📅 {dep_date} • {flight.departure_time} → {flight.arrival_time}\n"
        f"🏢 {flight.airline} • {stops_str}\n"
        f"🔗 [Reservar agora]({flight.booking_url})\n\n"
        f"⏰ Detectado às {now_str}"
    )
```

- [ ] **Step 4: Rodar os testes**

```
pytest tests/test_telegram_bot.py -v
```

Esperado: todos os testes passando — os 7 originais + os 9 novos de milhas.

- [ ] **Step 5: Rodar a suite completa**

```
pytest -v
```

Esperado: todos os testes passando. Nenhuma regressão.

- [ ] **Step 6: Commit final**

```
git add telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat: add miles alert format to Telegram notifications"
```

---

## Notas de Ajuste Pós-Descoberta

Após rodar os scripts de descoberta (Tasks 3 e 4), pode ser necessário ajustar:

**No Smiles (`airlines/smiles_miles.py`):**
- `_API_HOST`: substituir pelo host real da API interceptada
- `_parse()`: ajustar os `.get()` para os nomes reais dos campos
- URL de navegação: ajustar se `smiles.com.br/emissao-passagem-com-milhas` redirecionar

**Na Azul Fidelidade (`airlines/azul_miles.py`):**
- `_SEARCH_BASE` e `_API_HOST`: substituir pela URL real encontrada na descoberta
- `_parse()`: ajustar completamente para o formato JSON real
- URL de busca: o formato de parâmetros pode ser completamente diferente

Em ambos os casos, **os testes são a âncora**: quando `_parse()` estiver correto para o fixture real, todos os testes passam. Se os valores esperados nos testes precisarem mudar (ex: número de voos retornados), atualize os testes junto com o fixture.
