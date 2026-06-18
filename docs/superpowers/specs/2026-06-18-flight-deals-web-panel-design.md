# Painel web filtrável de passagens — design

**Data:** 2026-06-18
**Status:** aprovado (aguardando revisão do spec antes do plano de implementação)

## Problema

O bot manda muitos alertas no Telegram (último run real: ~17). O usuário quer um
lugar para **consultar e filtrar** os deals quando quiser, em vez de receber um ping
por deal. O Telegram continua exatamente como está; o painel é **adicional**.

## Decisões (já fechadas com o usuário)

1. **Conteúdo:** painel completo — snapshot do último run com a **tarifa mais barata
   por rota + data** de todas as rotas/datas pesquisadas. Sem limite de linhas (~4.800,
   ~1 MB). Filtrável e ordenável.
2. **Visibilidade:** senha no front, implementada como **JSON cifrado** (AES-GCM, chave
   derivada da senha via PBKDF2). Sem a senha não há dados — nem no código-fonte.
3. **Telegram:** inalterado. O painel não mexe na lógica de envio.
4. **Hospedagem:** GitHub Pages publicado via **GitHub Actions (artifact deploy)** —
   nada é commitado no repo; o `master` continua só com código.
5. **Sem histórico:** o snapshot sobrescreve a cada run. Histórico de preço fica como
   possível fase 2 (fora de escopo).

## Arquitetura

Tudo roda no cron que já existe (`azul-alert.yml`, 3×/dia). Fluxo:

```
main.py → cycle.run_azul_cycle()
            ├─ (já existe) por rota: busca voos, evaluate (Azul), evaluate_threshold (price-watch),
            │              envia Telegram  ← INALTERADO
            └─ (novo) acumula deals por rota via panel.build_deals(...) e, ao final,
                       panel.write_deals(deals, "deals.json")
        ↓ (steps novos no workflow)
scripts/encrypt_deals.py  deals.json + $PANEL_PASSWORD → _site/deals.enc.json
montar _site/  (web/index.html, web/app.js, web/style.css + deals.enc.json)
actions/upload-pages-artifact + actions/deploy-pages  → site publicado
```

### Componentes

**`panel.py` (novo, puro + IO fino)**
- `build_deals(flights, region, watches) -> list[dict]` — **função pura, testável**.
  Para uma rota:
  - agrupa por `departure_date`, ignora `price <= 0`;
  - a linha de cada data = a **tarifa mais barata** (qualquer cia) daquela data;
  - reaproveita `alerts.evaluate(flights)` e `alerts.evaluate_threshold(flights, watches)`
    como **fonte única de verdade** dos sinais:
    - `azul_cheapest: bool` — True se a data está nos `AzulAlert`;
    - `price_watch: float | None` — o limite satisfeito (`ThresholdAlert.max_price`) ou None;
  - cada registro: `{origem, destino, regiao, cia, data (ISO), hora, preco, paradas,
    direto, url_compra, azul_cheapest, price_watch}`.
- `write_deals(deals, path, generated_at=None)` — IO fino: escreve
  `{"gerado_em": <ISO8601 UTC>, "deals": [...]}` em JSON UTF-8.

**`cycle.py` (mudança pequena)**
- Acumula em memória `all_deals += panel.build_deals(flights, region, watches)` dentro do
  loop de rotas. A `region` = `routing.group_of(route.non_hub, GROUPS).name` (a `Route` só
  carrega `non_hub` e `topic_id`, não o nome do grupo).
- Ao final do ciclo, `panel.write_deals(all_deals, "deals.json")`.
- Nenhuma query extra: usa os `flights` já buscados.

**`scripts/encrypt_deals.py` (novo)**
- Lê `deals.json`, senha em `os.environ["PANEL_PASSWORD"]`.
- PBKDF2-HMAC-SHA256 (salt 16 bytes aleatório, 200.000 iterações) → chave AES-256.
- AES-GCM (IV 12 bytes aleatório) cifra o JSON.
- Escreve `deals.enc.json`:
  `{"v":1,"kdf":"PBKDF2-SHA256","iterations":200000,"salt":b64,"iv":b64,"ciphertext":b64}`
  (ciphertext inclui a tag GCM no fim, como o WebCrypto espera).
- Dependência nova: `cryptography` em `requirements.txt`.

**`web/index.html` + `web/app.js` + `web/style.css` (novos)**
- Tela de senha → `crypto.subtle` (WebCrypto): importa a senha, deriva a chave com PBKDF2
  (mesmo salt/iterações do arquivo), baixa `deals.enc.json`, decifra com AES-GCM, faz
  `JSON.parse`.
- Renderiza: cards de resumo (deals, mais barato, rotas, alertas), barra de filtros
  (região, aeroporto, cia, tipo, mês, só diretos, preço máx via slider), tabela ordenável
  por qualquer coluna. Linhas que dispararam alerta (azul_cheapest ou price_watch)
  destacadas. "Comprar" abre `url_compra` (Google Flights).
- Vanilla JS, sem framework. Senha errada → mensagem de erro (decrypt lança).

**Workflow (`.github/workflows/azul-alert.yml`, estendido — ou `pages.yml` novo)**
- Após `python main.py` (que agora gera `deals.json`):
  `pip install` já cobre `cryptography`; roda `encrypt_deals.py`; monta `_site/`;
  `actions/upload-pages-artifact@v3`; `actions/deploy-pages@v4`.
- Permissões: `pages: write`, `id-token: write`, `contents: read`; `environment: github-pages`.
- Secret novo: `PANEL_PASSWORD` (via `gh secret set`).
- O deploy é pulado se `deals.json` não for gerado **ou** se o snapshot estiver vazio (`deals: []`) — em ambos os casos o site anterior permanece publicado.

## Modelo de dado (`deals.json`)

```json
{
  "gerado_em": "2026-06-18T11:03:00Z",
  "deals": [
    {
      "origem": "CNF", "destino": "GIG", "regiao": "Rio de Janeiro",
      "cia": "Azul", "data": "2026-07-15", "hora": "07h40",
      "preco": 289.0, "paradas": 0, "direto": true,
      "url_compra": "https://www.google.com/travel/flights/search?...",
      "azul_cheapest": true, "price_watch": null
    }
  ]
}
```

## Estratégia de testes (TDD)

- `tests/test_panel.py` (novo): `build_deals` —
  - mais barata por data escolhida corretamente; `price <= 0` ignorado;
  - `azul_cheapest`/`price_watch` batem com `evaluate`/`evaluate_threshold`;
  - campos e tipos do registro; lista vazia quando não há voos.
- `tests/test_encrypt_deals.py` (novo): round-trip em Python (cifra → decifra) garante o
  formato; valida base64 e presença de salt/iv/iterations. (A decifragem no navegador é
  validada manualmente.)
- Suíte atual (136 testes) deve seguir verde — `cycle.py` muda pouco e o Telegram não muda.
- Rodar sempre `python -m pytest -q` em `C:\FlightAlert`.

## Fora de escopo (YAGNI)

- Histórico/tendência de preço (fase 2 possível).
- Reduzir/curar o Telegram (o usuário escolheu mantê-lo igual).
- Filtro por companhia nos price-watches (já decidido: any-airline).
- Frameworks JS, build step de front (Vite etc.), backend.

## Riscos / observações

- **Volume:** ~4.800 linhas client-side. Tabela vanilla aguenta; se ficar pesado, render
  do subconjunto filtrado resolve. Trim (top-N datas por rota) fica como ajuste fácil.
- **Cifra:** segurança "boa o suficiente" — PBKDF2 200k + AES-GCM. A força depende da
  senha escolhida. Não é cofre; é para manter curiosos casuais fora.
- **Pages público:** a URL é pública (conta pessoal), mas só expõe `index.html` (tela de
  senha) + blob cifrado.
- **Churn do master:** zero — artifact deploy não commita dados.
