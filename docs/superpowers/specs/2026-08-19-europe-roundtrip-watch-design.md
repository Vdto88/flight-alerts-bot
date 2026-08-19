# Design — Alerta de ida+volta Europa (< R$3.000)

Data: 2026-08-19
Status: aprovado

## Objetivo

Emitir um sinal novo quando existir uma viagem **ida+volta** para a Europa
(França, Espanha, Itália ou Portugal) somando **menos de R$3.000 por pessoa**,
com partida em **fev–mai/2027** e **estadia de 13 a 15 dias**. O alerta vai para
o Telegram (tópico Geral) e para o painel web.

## Requisitos (fechados com o usuário)

- **Pool de destinos:** os 8 aeroportos dos 4 países, tratados como um bloco único —
  `LIS, OPO` (Portugal), `MAD, BCN` (Espanha), `FCO, MXP` (Itália), `CDG, ORY` (França).
- **Ida:** `CNF → qualquer um dos 8`, partida em **fev, mar, abr ou mai/2027**
  (01/02/2027 a 31/05/2027, inclusive).
- **Volta:** `qualquer um dos 8 → CNF`, saindo **13, 14 ou 15 dias** após a ida
  (nunca mais que 15). Portanto a volta cai entre 14/02/2027 e 15/06/2027.
- **Open-jaw liberado:** a volta pode partir de um aeroporto/país diferente do da ida.
- **Gatilho:** para cada data de partida `D`,
  `menor_ida(D) + menor_volta(D + s)` para `s ∈ {13, 14, 15}` `≤ R$3.000` → alerta.
  Como as pernas são independentes, o mínimo de cada lado já produz o open-jaw mais barato.
- **Frequência:** **uma alerta por data de partida `D`** que tenha um round-trip
  qualificado (a combinação mais barata daquela data). Sem teto de quantidade;
  dedup de 24h evita repetir a mesma combinação entre ciclos.
- **Telegram:** tópico **Geral** (`topic_id = None`). Mensagem com as duas pernas,
  dias de estadia, total e dois links de reserva.
- **Painel:** round-trips aparecem como linhas próprias, com filtro de tipo
  "Ida+volta Europa".
- **Preço por pessoa** (as tarifas do Google Flights já são por passageiro).

## Contexto atual (o que já existe)

- `routing.build_routes` já gera as **duas direções** de cada aeroporto de cada grupo
  (`CNF→A` e `A→CNF`). Os 4 países europeus já são `Group`s em `config.py`.
- Todo sinal atual é **por perna** (one-way): `evaluate` (Azul mais barata) e
  `evaluate_threshold` (tarifa ≤ limite). Não existe pareamento de ida+volta no bot.
- A busca hoje cobre só a **janela rolante** (hoje+30 a hoje+120 dias ≈ set–dez/2026),
  mais janelas extras de grupos específicos (Patagônia fev+mar/2027, Foz out/2026).
  **Fev–mai/2027 dos aeroportos europeus está fora da janela atual** e precisa ser
  adicionado à busca.
- `deals.json` → `panel.build_deals` → snapshot → `scripts/encrypt_deals.py` →
  `deals.enc.json` → GitHub Pages. O painel (`web/app.js`) decripta client-side.

## Arquitetura da solução

### 1. `config.py` — novo tipo `RoundTripWatch` + lista de watches

```python
@dataclass(frozen=True)
class RoundTripWatch:
    name: str                    # rótulo p/ display e painel, ex. "Europa"
    airports: tuple[str, ...]    # pool de aeroportos (ida-destino e volta-origem)
    depart_window: SearchWindow  # datas de partida da ida permitidas
    stay_min: int                # estadia mínima em dias
    stay_max: int                # estadia máxima em dias
    max_total: float             # BRL; alerta quando ida+volta <= isto
    topic_id: int | None         # tópico Telegram (None = Geral)

ROUND_TRIP_WATCHES: list[RoundTripWatch] = [
    RoundTripWatch(
        name="Europa",
        airports=("LIS", "OPO", "MAD", "BCN", "FCO", "MXP", "CDG", "ORY"),
        depart_window=SearchWindow(date(2027, 2, 1), date(2027, 5, 31)),
        stay_min=13, stay_max=15,
        max_total=3000.0,
        topic_id=None,   # Geral
    ),
]
```

### 2. `routing.py` — `target_dates` também une as janelas dos round-trip watches

`target_dates(airport, today, groups, win_min, win_max, watches, rt_watches)`:
para qualquer aeroporto membro de um `RoundTripWatch`, unir o intervalo
`[depart_window.start, depart_window.end + stay_max]` (i.e. 01/02/2027 a 15/06/2027).

Como `target_dates` é chamado por `route.non_hub` (o mesmo aeroporto nas duas
direções), **ambas as direções** passam a buscar esse intervalo — garantindo dados
de ida (partidas até 31/05) e de volta (partidas até 15/06). Buscar alguns dias a
mais em cada direção é inofensivo.

### 3. `alerts.py` — `evaluate_round_trip`

```python
@dataclass
class RoundTripAlert:
    watch_name: str
    ida: Flight          # perna de ida escolhida (CNF -> A)
    volta: Flight        # perna de volta escolhida (B -> CNF)
    stay_days: int       # volta.departure_date - ida.departure_date
    total: float         # ida.price + volta.price
    max_total: float     # o teto satisfeito

def evaluate_round_trip(
    ida_legs: list[Flight],      # todas as pernas CNF->A (A no pool)
    volta_legs: list[Flight],    # todas as pernas B->CNF (B no pool)
    watch: RoundTripWatch,
) -> list[RoundTripAlert]:
    ...
```

Algoritmo:
1. `ida_by_date[D]` = perna de ida mais barata que **parte em D** (mín. sobre os 8 aeroportos),
   considerando só `price > 0` e `D` dentro de `depart_window`.
2. `volta_by_date[R]` = perna de volta mais barata que **parte em R** (mín. sobre os 8 aeroportos),
   `price > 0`.
3. Para cada `D` em `ida_by_date`: para `s ∈ [stay_min, stay_max]`, olhar `R = D + s`;
   escolher o `R` que dá menor `ida_by_date[D].price + volta_by_date[R].price`.
4. Se esse menor total `≤ watch.max_total`, emitir um `RoundTripAlert` (um por `D`).

Determinístico e sem I/O — testável isoladamente.

### 4. `cycle.py` — acumular pernas europeias e avaliar após o loop

- Dentro do loop de rotas, quando `route.non_hub` pertence a algum `RoundTripWatch`,
  acumular os `flights` em `rt_ida_legs` (se `route.origin == AZUL_HUB`) ou
  `rt_volta_legs` (se `route.destination == AZUL_HUB`), agrupados por watch.
- **Depois** do loop: para cada `RoundTripWatch`, chamar `evaluate_round_trip`.
  Para cada `RoundTripAlert` não cacheado, enviar via Telegram e cachear (TTL 24h).
- Gerar os deals de round-trip do painel (ver §6) e concatenar em `all_deals`
  antes de `panel.write_deals`.

### 5. `cache.py` — dedup por chave composta

Round-trip não é um `Flight` único. Adicionar dois helpers que operam sobre uma
chave string crua:

```python
async def is_key_cached(key: str) -> bool: ...
async def save_key(key: str, ttl_hours: int = 24) -> None: ...
```

Chave do round-trip:
`rt:{watch}|{ida.origin}-{ida.destination}|{ida.date}|{volta.origin}-{volta.destination}|{volta.date}|{floor(total/10)*10}`

`is_cached`/`save_to_cache` atuais (que recebem `Flight`) permanecem intactos.

### 6. `panel.py` — deals de round-trip

Nova função `build_round_trip_deals(rt_alerts, watch) -> list[dict]` que emite, por
alerta, um registro com **shape distinto** marcado por `tipo: "roundtrip"`:

```json
{
  "tipo": "roundtrip",
  "regiao": "Europa (ida+volta)",
  "origem": "CNF",              // origem da ida (mantém cidadeOf/sentidoOf funcionando)
  "destino": "CDG",            // destino da ida
  "data": "2027-03-12",        // data da ida (usada por ordenação e filtro de datas)
  "cia": "AZUL",               // cia da ida (para o filtro de cia)
  "preco": 2890.0,             // TOTAL ida+volta
  "paradas": 1,                // paradas da ida
  "direto": false,
  "url_compra": "…ida…",       // link da ida (compat. com campo existente)
  "azul_cheapest": false,
  "price_watch": null,
  // extras de round-trip:
  "ida_origem": "CNF", "ida_destino": "CDG", "data_ida": "2027-03-12",
  "cia_ida": "AZUL", "preco_ida": 1450.0, "url_ida": "…",
  "volta_origem": "MXP", "volta_destino": "CNF", "data_volta": "2027-03-26",
  "cia_volta": "LATAM", "preco_volta": 1440.0, "url_volta": "…",
  "estadia": 14, "max_total": 3000.0
}
```

Os deals de round-trip mostrados no painel são os **mesmos que qualificam** para o
alerta (`total ≤ max_total`), para manter Telegram e painel consistentes.

### 7. `web/app.js` + `web/index.html` — render de round-trip

- `index.html`: adicionar `<option value="roundtrip">Ida+volta Europa</option>` ao
  `<select id="f-tipo">`.
- `app.js`:
  - Filtro de tipo: `tipo === "roundtrip"` → `d.tipo === "roundtrip"`; os tipos
    `azul`/`watch` passam a exigir `d.tipo !== "roundtrip"` (round-trips não têm esses sinais).
  - Filtro de sentido: linhas round-trip só passam quando `sentido` está vazio.
  - `render()`: quando `d.tipo === "roundtrip"`, renderizar a linha em formato de duas pernas:
    - Rota: `CNF→CDG + MXP→CNF · Europa`
    - Data: `12/03 → 26/03 (14 dias)`
    - Cia: `AZUL + LATAM`
    - Preço: total (`fmtBRL(d.preco)`)
    - Sinal: selo `ida+volta`
    - Ação: dois links — `ida` e `volta`
  - Contagem de "Alertas" no resumo inclui round-trips.

### 8. `telegram_bot.py` — mensagem de round-trip

`format_round_trip_alert(rt) -> str` e
`send_round_trip_alert(rt, topic_id=None) -> bool` (mesmo padrão de retorno/retry
dos outros senders). Formato:

```
🌍 *IDA+VOLTA EUROPA < R$3.000*

🛫 Ida:   CNF → CDG · 12/03/2027 · AZUL · R$ 1.450
🛬 Volta: MXP → CNF · 26/03/2027 · LATAM · R$ 1.440
🧳 Estadia: 14 dias
💰 Total: R$ 2.890  (teto R$ 3.000)
🔗 [Reservar ida](url_ida) · [Reservar volta](url_volta)

⏰ Detectado às HH:MM
```

## Testes (`tests/test_round_trip_watches.py`)

- Pareia ida+volta com estadia dentro de 13–15; **rejeita** estadias de 12 e 16.
- Escolhe o **open-jaw mais barato** (ida de um aeroporto, volta de outro).
- Não dispara quando o total > `max_total`; dispara no limite exato.
- Um alerta por data de partida; escolhe o `stay` que minimiza o total.
- Ignora `price <= 0`.
- `routing.target_dates` inclui 01/02/2027–15/06/2027 para aeroporto do pool e
  **não** para aeroporto fora do pool.
- Chave de cache composta é estável e distingue combinações diferentes.

## Fora de escopo (por ora)

- Teto de quantidade de alertas por ciclo (só se virar spam).
- Card/aba dedicada de round-trip no painel (usamos linhas na tabela existente).
- Restrição de conexões/paradas ou duração de voo.
- Outros continentes ou outras janelas de data.

## Custo

Adiciona ~4,5 meses (01/02–15/06/2027) de busca em 8 aeroportos × 2 direções.
Estimativa: +~2.000 date-queries, ~+8–10 min por ciclo (hoje ~20 min), dentro do
timeout de 60 min do workflow.
