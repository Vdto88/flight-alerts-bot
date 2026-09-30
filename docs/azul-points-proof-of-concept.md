# Prova de conceito: pontos Azul

Verificado em 30/09/2026, com consultas públicas a partir deste computador.

## Resultado

O coletor `scripts/azul_points_probe.py` obtém ofertas anunciadas em pontos do
buscador público da Azul, com origem, destino, datas, tipo de viagem e valor.
Usa HTTP comum, sem login, sem enviar alertas e sem comprar passagens.

Consultas verificadas:

| Origem → destino | Data de ida | Pontos anunciados | Tipo |
| --- | --- | ---: | --- |
| CNF → CGH | 20/10/2026 | 20.000 | Só ida |
| CNF → CGH | 01/11/2026 | 12.000 | Só ida |
| CNF → CGH | 11/11/2026 | 12.000 | Só ida |
| CNF → BPS | 07/11/2026 | 10.000 | Só ida |

A consulta CNF → CGH retornou 44 ofertas em três páginas. CNF → BPS retornou
21 ofertas em duas páginas. Os arquivos em `data/` ficam fora do Git.

**Não são tarifas confirmadas de inventário ao vivo.** A página informa que
os valores foram coletados nas últimas 48 horas e podem não estar mais disponíveis.
Os registros observados não informam horário, escalas nem taxas em reais.
O coletor preserva esses campos como nulos e marca `availability_confirmed: false`.
Uma consulta sem ofertas nesta fonte não prova ausência de voos na Azul.

## Executar

Na raiz do FlightAlert, com as dependências de `requirements.txt` instaladas:

```powershell
python scripts/azul_points_probe.py --origin CNF --destination CGH
python scripts/azul_points_probe.py --origin CNF --destination CGH --date 2026-10-20 --output data/azul-points-cnf-cgh-2026-10-20.json
python scripts/azul_points_probe.py --origin CNF --destination BPS --output data/azul-points-cnf-bps.json
```

Sem `--destination`, consulta ofertas saindo da origem. `--date` filtra a
data anunciada; não dispara uma busca nova no inventário da companhia.
`--max-pages` limita o trabalho; o JSON informa `pagination_complete`.

O script lê o identificador do módulo e o token temporário da própria página
a cada execução, resolve os aeroportos publicados, pagina a mesma API GraphQL
usada pelo site e extrai exclusivamente `redemption.unit == POINTS`.
Não grava o token. Não interpreta `totalPrice`/`currencyCode` como reais, pois
nesses registros esses campos também acompanham preços em pontos.

## Testes de acesso

As ofertas públicas em pontos responderam às consultas. A busca de emissão
retornou bloqueios ou desafios, sem confirmar inventário. HTTP 200 com uma
página de desafio não é uma tarifa válida. Não foram usados serviços pagos
de captcha ou proxies.

## Integração possível

Esta fonte já permite acompanhar ofertas anunciadas em pontos por rota/data.
Para integrar, os resultados devem aparecer como ofertas em cache, com aviso
de confirmação no site. Não devem virar objetos `Flight` com horários ou
escalas inventados. A confirmação de inventário precisa de outra etapa de
acesso a uma sessão funcional da Azul.

O ciclo de milhas e sua integração atual estão descritos em `mileage-alerts.md`.

Fonte: https://passagens.voeazul.com.br/pt/buscador-de-pontos
