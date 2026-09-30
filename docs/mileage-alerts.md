# Milhas: Azul, LATAM e GOL

A coleta de milhas roda neste computador às 08h, 14h e 20h, no horário
local do Windows (Brasília neste PC). Reutiliza `GROUPS`, rotas CNF ↔ destino,
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

## Configuração local

Abra `Configurar-Milhas.cmd` uma vez. O token Telegram existente é reutilizado.
Preencha o ID do grupo (ou um link privado de uma mensagem `t.me/c/...`) e a
**mesma senha do painel atual**. Os valores ficam no `.env`, ignorado pelo Git.
Não envie credenciais pelo chat. A senha é verificada contra o histórico
criptografado existente antes de qualquer publicação de milhas.

O cliente instalado fica em `scripts/exploration/bin/award-http.exe`, fora do
Git. A dependência privada permanece neste computador. Nenhuma credencial de
leitura dessa dependência é necessária nos Actions. Para recompilar uma cópia
já autenticada, use `python scripts/build_miles_client.py CAMINHO_DO_CHECKOUT_PRIVADO`.
`MILES_CLIENT_BIN` permite indicar outro caminho para o executável.

O Agendador de Tarefas do Windows usa a tarefa `FlightAlert-Milhas`, com o
usuário conectado (a tela pode estar bloqueada). Não liga o computador.
`StartWhenAvailable` tenta recuperar um horário perdido e há um gatilho ao
entrar no Windows. Execuções simultâneas são bloqueadas; um gatilho automático
é dispensado quando uma coleta já terminou nos últimos 30 minutos.

Para reinstalar o agendamento:
`powershell -ExecutionPolicy Bypass -File scripts/install_local_miles.ps1`.

## Alertas e execução local

A primeira coleta em produção estabelece a referência. Depois o bot avisa
quedas para o mesmo programa, rota, datas, cabine e condição de cliente, no
tópico Telegram já configurado para o destino. Não usa os limites em reais como
limites em milhas. Referências expiram após 48h; a mesma oferta/valor só é
reenviada após 24h. Falhas de envio são tentadas novamente. Limite de 20 envios
por ciclo, com os restantes tentados no próximo ciclo enquanto válidos.

Para executar manualmente, abra `Rodar-Milhas.cmd` ou rode:

```powershell
python scripts/local_miles.py --interactive
```

A execução manual inclui também os dias mais distantes. Os resultados ficam
em `miles.json`, a referência de alertas em `data/miles-state.json` e os logs
em `logs/local-miles.log`; todos ignorados pelo Git. Sem destino Telegram,
a coleta funciona em prévia, sem enviar alertas. Sem senha do painel, os dados
ficam somente locais. `python miles_main.py` também faz prévia sem mensagens.

## Painel e publicação

`web/milhas.html` usa a mesma senha do painel. Há abas Azul, LATAM e GOL,
filtros e estados de falha ou coleta parcial. Links aparecem nos painéis
Terminal e clássico.

O processo local envia **somente `miles.enc.json`, criptografado**, para a
release `mileage-panel` deste bot, usando a autenticação existente do GitHub
CLI. O workflow de preços em reais baixa esse arquivo e inclui os dados na
**próxima publicação do site**. A coleta de milhas não roda no GitHub e seu
código de transporte privado não é enviado. Preços em reais e promoções
continuam com seus agendamentos existentes.

Teste completo via cliente local em 30/09/2026: 95 ofertas Azul, 180 LATAM e
1 GOL dentro da configuração atual. É uma amostra, sem garantia de cobertura
futura.

## Repositório privado

Privatizar o repositório não muda o funcionamento local ou os segredos dos
workflows. Porém GitHub Pages em repositório privado exige Pro/Team/Enterprise;
Pages de um repositório privado também pode continuar sendo um site público.
Actions passa a consumir a franquia de minutos da conta e pode gerar cobrança
por excedente. Verifique plano e hospedagem antes de mudar a visibilidade.

- [GitHub Pages e planos](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
- [Cobrança GitHub Actions](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
