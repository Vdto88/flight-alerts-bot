# Design: Scrapers de Milhas — Smiles e Azul Fidelidade

**Data:** 2026-04-26
**Rotas:** CNF↔IGU (ida e volta)
**Programas:** Smiles (GOL) e Azul Fidelidade

---

## Contexto

O FlightAlert monitora passagens em dinheiro via httpx para GOL, LATAM e Azul. Este spec adiciona monitoramento de passagens com milhas para Smiles e Azul Fidelidade na rota CNF↔IGU, usando Playwright com interceptação de rede.

Não há API pública nem API interna estável disponível para esses programas:
- A API interna do Smiles (`api-air-flightsearch-prd.smiles.com.br`) começou a retornar HTTP 406 a partir de julho/2025
- A Azul Fidelidade não expõe API documentada
- Playwright com interceptação de resposta JSON é a abordagem mais robusta para ambos

---

## Thresholds

| Programa     | Rota        | Threshold |
|--------------|-------------|-----------|
| Smiles       | CNF → IGU   | ≤ 15.000 milhas |
| Smiles       | IGU → CNF   | ≤ 15.000 milhas |
| Azul Fidelidade | CNF → IGU | ≤ 20.000 milhas |
| Azul Fidelidade | IGU → CNF | ≤ 20.000 milhas |

---

## 1. Modelo de Dados (`airlines/base.py`)

Dois campos opcionais adicionados ao dataclass `Flight`:

```python
miles: int | None = None        # ex: 15000 — None para voos em dinheiro
taxes_brl: float | None = None  # reservado para uso futuro, sempre None por ora
```

- `price` permanece `0.0` em voos de milhas (evita quebrar código existente)
- Nova propriedade `is_miles_flight: bool` → `True` quando `miles is not None`
- `cache_key()` usa faixa de 1.000 milhas quando `is_miles_flight`:
  ```
  "SMILES|CNF|IGU|2026-06-15|15000mi"
  ```

Nenhuma mudança em campos existentes. Código de voos em dinheiro não é afetado.

---

## 2. Novos Scrapers

### `airlines/smiles_miles.py` — `SmilesMilesSearcher`

- `AIRLINE_NAME = "SMILES"`
- Abre `smiles.com.br` via Playwright Chromium headless
- Registra listener `page.on("response", ...)` antes de navegar
- Intercepta resposta JSON da API interna ao preencher o formulário de busca
- Extrai por voo: `miles`, `departure_time`, `arrival_time`, `stops`, `booking_url`
- `taxes_brl` não coletado (mantém `None`)

### `airlines/azul_miles.py` — `AzulMilesSearcher`

- `AIRLINE_NAME = "AZUL_MILES"`
- Abre `azulfidelidade.com.br` via Playwright Chromium headless
- Mesmo padrão de interceptação de rede
- Extrai os mesmos campos

### Comportamento comum a ambos

- `headless` configurável via env var `PLAYWRIGHT_HEADLESS` (padrão: `true`)
- Sleep aleatório de 1–3s entre ações de formulário (simula comportamento humano)
- User-Agent real do Chrome incluído no contexto do browser
- Em caso de erro (timeout, CAPTCHA, mudança de layout): loga warning e retorna `[]`
- Sem retry automático — o ciclo de 60 minutos naturalmente tenta novamente

---

## 3. Configuração (`config.py`)

Nova lista `MILES_ROUTES` separada de `ROUTES`:

```python
MILES_ROUTES = [
    {"from": "CNF", "to": "IGU", "miles_threshold": 15000, "program": "SMILES"},
    {"from": "IGU", "to": "CNF", "miles_threshold": 15000, "program": "SMILES"},
    {"from": "CNF", "to": "IGU", "miles_threshold": 20000, "program": "AZUL_MILES"},
    {"from": "IGU", "to": "CNF", "miles_threshold": 20000, "program": "AZUL_MILES"},
]

MILES_DAYS_AHEAD: int = 60
MILES_CYCLE_MINUTES: int = 60
```

`ROUTES` e todas as constantes existentes permanecem intocadas.

---

## 4. Scheduler (`scheduler.py`)

Novo ciclo `run_miles_cycle()` independente:

```python
MILES_SEARCHERS = {
    "SMILES":     SmilesMilesSearcher(),
    "AZUL_MILES": AzulMilesSearcher(),
}

async def run_miles_cycle():
    for route in MILES_ROUTES:
        searcher = MILES_SEARCHERS[route["program"]]
        flights = await searcher.search_range(
            route["from"], route["to"], MILES_DAYS_AHEAD
        )
        below = [f for f in flights if f.miles is not None and f.miles <= route["miles_threshold"]]
        for flight in below:
            if not await cache.is_cached(flight):
                await telegram_bot.send_alert(flight)
                await cache.save_to_cache(flight, CACHE_TTL_HOURS)
```

Registrado no scheduler com intervalo próprio:
```python
scheduler.add_job(run_miles_cycle, trigger="interval",
                  minutes=MILES_CYCLE_MINUTES,
                  next_run_time=datetime.now(),
                  id="miles_cycle")
```

- Sem fallback para Google Flights
- `run_cycle()` existente (voos em dinheiro) não é modificado

---

## 5. Telegram (`telegram_bot.py`)

`format_alert` detecta `is_miles_flight` e usa template alternativo:

**Voo de milhas:**
```
✈️ PASSAGEM COM MILHAS DETECTADA

🛫 CNF → IGU
🏆 15.000 milhas
📅 15/06/2026 • 07h40 → 09h10
🏢 Smiles • Direto
🔗 Reservar agora

⏰ Detectado às 08:32
```

**Voo em dinheiro (sem mudança):**
```
✈️ PASSAGEM BARATA DETECTADA

🛫 CNF → GRU
💰 R$ 289,00
...
```

---

## 6. Tratamento de Erros

| Situação | Comportamento |
|----------|---------------|
| Timeout no Playwright | Log warning, retorna `[]` |
| CAPTCHA detectado | Log warning, retorna `[]` — próximo ciclo tenta novamente |
| JSON da API mudou (campos renomeados) | Log error com detalhes, retorna `[]` |
| Nenhum voo encontrado | Retorna `[]` normalmente (sem log de erro) |
| Playwright não instalado | Erro na inicialização com mensagem clara |

---

## 7. Dependências Novas

```
playwright>=1.44
```

Instalação dos browsers:
```bash
playwright install chromium
```

Adicionado ao `requirements.txt` e documentado no `Dockerfile`.

---

## Fora do Escopo

- Outros programas de milhas (Latam Pass, Livelo, etc.)
- Outras rotas além de CNF↔IGU
- Coleta de `taxes_brl` (campo reservado, sempre `None`)
- Interface web ou dashboard
- Seats.aero API (descartada por incerteza na cobertura de rotas domésticas)
