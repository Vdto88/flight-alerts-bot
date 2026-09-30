# Milhas: Azul, LATAM e GOL

O ciclo `python miles_main.py --notify` roda após a busca em reais no mesmo
workflow (08h, 14h e 20h de Brasília). Reutiliza `GROUPS`, rotas CNF ↔ destino,
janelas extras, observações e a janela longa do ciclo da manhã. Os coletores
consultam **ofertas públicas anunciadas**, não inventário completo de emissão.
Não conseguem garantir uma tarifa para cada data da configuração.

- Azul: buscador público de pontos, com paginação por origem. As ofertas são
  tarifas coletadas pela própria companhia nas últimas 48h.
- LATAM: feed público de ofertas da página de destinos, por rota e mês. Somente
  `totalLoyaltyAmount` é usado; impostos da tarifa em reais não são impostos
  confirmados para emissão com milhas.
- GOL: campanhas atuais descobertas na página de passagens Smiles. Os arquivos
  públicos das campanhas fornecem milhas, rota e data. Parceiras são excluídas.
  Preços Clube/Diamante e Cliente Smiles ficam separados. Valores são por trecho;
  a data de volta no botão da campanha não transforma o preço em ida e volta.

Disponibilidade, taxas, horário e conexões não são confirmados. Rotas sem
ofertas publicadas ficam vazias. Falhas de fontes aparecem na UI separadamente
e não derrubam as demais fontes. Não usa servidor, proxy ou serviço de captcha
do autor. Todas as requisições do ciclo de milhas usam o cliente local,
compilado do commit fixado do projeto; não há fallback para outro
cliente HTTP. A coleta em reais existente continua com seu próprio mecanismo.

## Configuração do cliente de milhas no GitHub Actions

A dependência de transporte é privada e não é distribuída neste repositório
ou no site. O token padrão de Actions não tem acesso a outros repos privados.
Antes de ativar a coleta automática, configure no
[GitHub Secrets do bot](https://github.com/Vdto88/flight-alerts-bot/settings/secrets/actions):

- `MILES_CLIENT_SOURCE`: o repositório privado de origem, no formato organização/repo.
- `MILES_CLIENT_READ_TOKEN`: credencial autorizada pela organização, restrita
  à leitura de conteúdo desse repositório quando essa opção estiver disponível.

Não envie valores pelo chat nem grave em arquivos versionados. A origem é
resolvida em runtime, mascarada nos logs, e os diagnósticos do compilador não
são impressos nos runs públicos. O workflow compila a revisão fixada, faz as
consultas diretamente às companhias e publica apenas os arquivos do painel.
Se o acesso/build falhar, a coleta em reais segue e a área de milhas sinaliza
que está indisponível.

Localmente: `python scripts/build_miles_client.py CAMINHO_DO_CHECKOUT_PRIVADO`
compila a dependência já autenticada e instala o executável em
`scripts/exploration/bin/award-http`, fora do Git e do cache público de dados.
`MILES_CLIENT_BIN` permite indicar outro caminho para esse executável. O
processo não usa proxy herdado do ambiente nem serviço de captcha pago.

## Alertas e execução local

A primeira coleta em produção estabelece a referência. Depois o bot avisa
quedas para o mesmo programa, rota, datas, cabine e condição de cliente, no
tópico Telegram já configurado para o destino. Não usa os limites em reais como
limites em milhas. Referências expiram após 48h; a mesma oferta/valor só é
reenviada após 24h. Falhas de envio são tentadas novamente. Limite de 20 envios
por ciclo, com os restantes tentados no próximo ciclo enquanto válidos.

`python miles_main.py` faz prévia local sem enviar mensagens nem alterar a
referência de produção. Gera `miles.json` (ignorado pelo Git). `--notify` habilita
mensagens e grava `data/miles-state.json`, persistido pelo cache existente do
workflow. Não é preciso login nas companhias.

## Painel e publicação

`web/milhas.html` usa a mesma senha do painel e `miles.enc.json`. Há abas por
companhia, filtros por origem/destino/data/quantidade/viagem/condição e estado de
falha ou coleta parcial. O build publica somente o arquivo criptografado de
milhas. Links foram adicionados nos painéis Terminal e clássico.

As mudanças locais precisam ser enviadas ao GitHub para entrar nas execuções e
na publicação. Teste completo via cliente de milhas em 30/09/2026: 95 ofertas Azul, 180 LATAM e 1 GOL
dentro da configuração atual. Isso é uma amostra daquela coleta, não uma
garantia de cobertura futura.

## Repositório privado

Privatizar o repositório não muda o funcionamento local ou os segredos dos
workflows. Porém GitHub Pages em repositório privado exige Pro/Team/Enterprise;
Pages de um repositório privado também pode continuar sendo um site público.
Actions passa a consumir a franquia de minutos da conta e pode gerar cobrança
por excedente. Verifique plano e hospedagem antes de mudar a visibilidade.

- [GitHub Pages e planos](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
- [Cobrança GitHub Actions](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
