/* Terminal CNF — lê o snapshot cifrado, monta o quadro de partidas com os
   melhores sinais, e desenha cartões de embarque por destino (com calendário)
   ou uma tabela paginada para varrer tudo. */

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const REDUCED_MOTION = matchMedia("(prefers-reduced-motion: reduce)").matches;

let DEALS = [];
let GENERATED_AT = null;
let HUB = "CNF";
let VIEW = "cards";
let OPEN = new Set();
let sortKey = "preco", sortDir = 1;
let boardBooted = false;

// The production snapshot runs to thousands of fares; the table grows a page at a time.
const TABLE_PAGE = 150;
let tableLimit = TABLE_PAGE;

// code -> {cidade, uf, pais}; shipped inside the snapshot, straight from config.AIRPORTS.
let AIRPORTS = {};
// Window behind every "vs. média" number, shipped by the snapshot (history.STATS_DAYS).
// The fallback is only for a cached snapshot written before the field existed.
let HIST_DAYS = 60;
// Near band (config.WINDOW_MAX_DAYS): beyond it, dates are searched once a day and carried.
// The fallback is only for a cached snapshot written before the field existed.
let NEAR_DAYS = 120;

// Round trips by stay (config.STAY_OPTIONS, shipped as "estadias"). STAY: "" = one-way view,
// "best" = cheapest return over the destination's stays, else a number of days as a string.
let ESTADIAS = null;
let RETURNS = new Map();          // "<origem>|<data>" -> one-way return record (X -> HUB)
let STAY = "";
let VIEW_CACHE = null;            // [STAY, rows]: pairing depends on STAY only
const STAY_KEY = "painel-estadia";
const cityOf = (code) => (AIRPORTS[code] && AIRPORTS[code].cidade) || code;

const isRT = (d) => d.tipo === "roundtrip";
const cidadeOf = (d) => (d.origem === HUB ? d.destino : d.origem);
const sentidoOf = (d) => (d.destino === HUB ? "volta" : "ida");
const hasSignal = (d) => isRT(d) || d.azul_cheapest || d.price_watch != null;
// Round trips are keyed by their itinerary so an open card survives re-filtering.
// "Florianópolis · SC" / "Lisboa · Portugal". Snapshots older than the airport table
// only know the Telegram group name, so fall back to it.
const placeOf = (d) => (d.cidade ? `${d.cidade} · ${d.uf || d.pais}` : d.regiao);
// Region filter values: "pais:Chile" or "uf:SC".
const inRegion = (d, v) => {
  if (!v) return true;
  const [kind, name] = [v.slice(0, v.indexOf(":")), v.slice(v.indexOf(":") + 1)];
  return kind === "uf" ? d.uf === name : d.pais === name;
};
const groupKey = (d) => (isRT(d)
  ? `rt:${d.ida_destino}|${d.data_ida}|${d.volta_origem}|${d.data_volta}`
  : `${cidadeOf(d)}|${sentidoOf(d)}`);

/* ---------------- Round trips by stay ---------------- */
const addDays = (iso, n) => {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
};
const staysFor = (d, estadias) => estadias.por_pais[d.pais] || estadias.padrao;

/* The cheapest return `stay` days after an outbound one-way fare. `stay` is a number, or
   "best" for every valid stay of the destination (ties keep the shorter stay, because the
   stays arrive in ascending order and only a strictly cheaper return replaces the best).
   -> {volta, total, estadia} | {motivo: "invalid-stay" | "out-of-window", validas} */
function pairReturn(ida, stay, index, estadias) {
  const validas = staysFor(ida, estadias);
  const tries = stay === "best" ? validas : validas.includes(stay) ? [stay] : null;
  if (!tries) return { motivo: "invalid-stay", validas };
  let best = null;
  for (const s of tries) {
    const volta = index.get(`${ida.destino}|${addDays(ida.data, s)}`);
    if (volta && (!best || volta.preco < best.volta.preco)) best = { volta, estadia: s };
  }
  if (!best) return { motivo: "out-of-window", validas };
  return { ...best, total: Math.round((ida.preco + best.volta.preco) * 100) / 100 };
}

/* What the panel lists. One-way view: the snapshot as is. With a stay chosen: only outbound
   one-way fares, each carrying its return (its price becomes the total) or why it has none.
   Returns and the Europe watch's round trips would duplicate the pairs, so they drop out. */
function viewDeals() {
  if (!STAY || !ESTADIAS) return DEALS;
  if (VIEW_CACHE && VIEW_CACHE[0] === STAY) return VIEW_CACHE[1];
  const stay = STAY === "best" ? "best" : Number(STAY);
  const rows = DEALS.filter((d) => !isRT(d) && sentidoOf(d) === "ida").map((d) => {
    const r = pairReturn(d, stay, RETURNS, ESTADIAS);
    return r.volta
      ? { ...d, preco: r.total, preco_ida: d.preco, par_volta: r.volta, par_estadia: r.estadia }
      : { ...d, sem_par: r.motivo, validas: r.validas };
  });
  VIEW_CACHE = [STAY, rows];
  return rows;
}

/* ---------------- Formatting ---------------- */
const fmtInt = (n) => Math.round(n).toLocaleString("pt-BR");
const fmtBRL = (n) => "R$ " + fmtInt(n);
const fmtDate = (iso) => { const [y, m, d] = String(iso).split("-"); return `${d}/${m}/${y}`; };
const MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
const MON = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"];
const fmtShort = (iso) => { const [, m, d] = String(iso).split("-"); return `${d} ${MON[Number(m) - 1]}`; };
const fmtMonth = (ym) => {
  const [y, m] = ym.split("-");
  const name = MONTHS[Number(m) - 1];
  return `${name[0].toUpperCase()}${name.slice(1)} de ${y}`;
};
const fmtFound = (date) => date.toLocaleString("pt-BR", {
  timeZone: "America/Sao_Paulo", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
});

/* Far-band dates are searched once a day; records carried from that cycle say when. */
function ageOf(iso) {
  const min = Math.max(1, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  return min < 60 ? `visto há ${min} min` : `visto há ${Math.round(min / 60)} h`;
}

/* ---------------- Decryption (shared, see switch.js) ---------------- */
let PASSWORD = "";
const loadDeals = (password) => PanelCrypto.load("deals.enc.json", password);

/* ---------------- Promotions (blog posts picked by the hourly RSS cycle) ----------------
   Optional: the file may not exist yet, and the panel must work without it. Everything in it
   was written by third parties, so it only ever reaches the page through textContent. */
const PROMO_PAGE = 8;
let PROMOS = [], PROMO_KIND = "", PROMO_SHOWN = PROMO_PAGE;

function promoAge(iso) {
  const min = Math.max(1, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (min < 60) return `há ${min} min`;
  if (min < 1440) return `há ${Math.round(min / 60)} h`;
  const days = Math.round(min / 1440);
  return days === 1 ? "ontem" : `há ${days} dias`;
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function promoRow(p) {
  const li = el("li", "promo-row" + (p.origem_bh ? " from-bh" : ""));
  li.append(el("span", "promo-age", promoAge(p.publicado_em)));
  li.append(el("span", "badge " + (p.tipo === "milhas" ? "rt" : "azul"), p.tipo === "milhas" ? "milhas" : "passagem"));

  const body = el("div", "promo-body");
  const safe = typeof p.link === "string" && p.link.startsWith("https://");
  const title = el(safe ? "a" : "span", "promo-title", p.titulo);
  if (safe) { title.href = p.link; title.target = "_blank"; title.rel = "noopener noreferrer"; }
  body.append(title);

  const tags = el("div", "promo-tags");
  if (p.origem_bh) tags.append(el("span", "badge low", "saindo de BH"));
  [...(p.programas || []), ...(p.destinos || [])].forEach((t) => tags.append(el("span", "badge reg", t)));
  if (p.origem_nao_informada) tags.append(el("span", "badge reg", "origem não informada"));
  tags.append(el("span", "promo-source", p.fonte));
  body.append(tags);

  li.append(body);
  return li;
}

function renderPromos() {
  const rows = PROMOS.filter((p) => !PROMO_KIND || p.tipo === PROMO_KIND);
  $("promo-rows").replaceChildren(...rows.slice(0, PROMO_SHOWN).map(promoRow));
  $("promo-empty").hidden = rows.length > 0;
  const left = rows.length - PROMO_SHOWN;
  $("promo-more").hidden = left <= 0;
  $("promo-more").textContent = `Ver mais ${Math.min(left, PROMO_PAGE)} de ${left}`;
}

function setupPromos(data) {
  PROMOS = Array.isArray(data && data.promos) ? data.promos : [];
  if (!PROMOS.length) return;          // nothing collected yet: keep the section out of the way
  $("promos").hidden = false;
  document.querySelectorAll(".pseg").forEach((b) => b.addEventListener("click", () => {
    PROMO_KIND = b.dataset.promo;
    PROMO_SHOWN = PROMO_PAGE;
    document.querySelectorAll(".pseg").forEach((o) => o.setAttribute("aria-pressed", String(o === b)));
    renderPromos();
  }));
  $("promo-more").addEventListener("click", () => { PROMO_SHOWN += PROMO_PAGE; renderPromos(); });
  renderPromos();
}

const loadPromos = (password) =>
  PanelCrypto.load("promos.enc.json", password)
    .then(setupPromos)
    .catch((e) => console.warn(`promoções indisponíveis (${e && e.code ? e.code : "erro"})`));

/* History is one encrypted file per route, fetched the first time a pass of that route is
   drawn open. Map value: undefined = not requested, null = loading, false = failed, object = loaded. */
const ROUTE_HISTORY = new Map();
const routeFile = (origem, destino) => `${origem}-${destino}`;

function ensureRouteHistory(origem, destino) {
  const key = routeFile(origem, destino);
  if (ROUTE_HISTORY.has(key)) return;
  ROUTE_HISTORY.set(key, null);
  PanelCrypto.load(`history/${key}.enc.json`, PASSWORD)
    .then((h) => ROUTE_HISTORY.set(key, h))
    .catch((e) => {
      console.warn(`histórico de ${key} indisponível (${e && e.code ? e.code : "erro"})`);
      ROUTE_HISTORY.set(key, false);
    })
    .then(scheduleRender);
}

/* ---------------- Small pieces of markup ---------------- */
function icon(name, cls = "") {
  return `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-${name}"/></svg>`;
}

function badges(d) {
  const out = [];
  if (isRT(d)) out.push('<span class="badge rt">ida + volta</span>');
  if (d.azul_cheapest) out.push('<span class="badge azul">Azul mais barata</span>');
  if (d.price_watch != null) out.push(`<span class="badge watch">alvo ≤ ${fmtBRL(d.price_watch)}</span>`);
  if (d.menor_hist) out.push(`<span class="badge low">${icon("star")} menor em ${HIST_DAYS}d</span>`);
  return out.join("");
}

/* Gap between this fare and its own median over the snapshot's window. Under ±3% it is noise. */
function delta(d) {
  if (d.delta_pct == null) return "";
  const p = d.delta_pct;
  if (Math.abs(p) < 3) return `<span class="delta flat">na média</span>`;
  const dir = p < 0 ? "down" : "up";
  const word = p < 0 ? "abaixo" : "acima";
  return `<span class="delta ${dir}" title="${Math.abs(p)}% ${word} da média de ${HIST_DAYS} dias">${icon(dir)}${Math.abs(p)}% ${word}</span>`;
}

/* Same ±3% dead band as delta(), but against what the route typically costs: inside
   the band this fare simply is the route's price. Signed form feeds the table column. */
function rotaDelta(d, signed = false) {
  if (d.rota_delta_pct == null) return "";
  const p = d.rota_delta_pct;
  const cls = Math.abs(p) <= 3 ? "flat" : p < 0 ? "down" : "up";
  const text = signed
    ? `${p > 0 ? "+" : ""}${p}%`
    : cls === "flat" ? "na média da rota" : `${Math.abs(p)}% ${p < 0 ? "abaixo" : "acima"} da rota`;
  return `<span class="delta ${cls}" title="Preço típico da rota: ${fmtBRL(d.rota_med)}">${text}</span>`;
}

/* Daily-minimum sparkline that ends on today's fare, coloured like the delta. */
function spark(d) {
  if (!d.spark || d.spark.length < 2) return "";
  const values = d.spark.concat(d.preco);
  const w = 96, h = 26, lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
  const x = (i) => (i / (values.length - 1)) * w;
  const y = (v) => h - ((v - lo) / span) * (h - 6) - 3;
  const path = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");
  const trend = d.delta_pct <= -3 ? "down" : d.delta_pct >= 3 ? "up" : "";
  return `<svg class="spark ${trend}" viewBox="0 0 ${w} ${h}" role="img"
    aria-label="Preço nos últimos ${d.spark.length} dias, de ${fmtBRL(values[0])} até ${fmtBRL(d.preco)} hoje">
    <path d="${path}"/><circle cx="${w}" cy="${y(d.preco).toFixed(1)}" r="3"/></svg>`;
}

/* ---------------- Filtering ---------------- */
function filterState() {
  return {
    regiao: $("f-regiao").value, aeroporto: $("f-aeroporto").value, cia: $("f-cia").value,
    tipo: $("f-tipo").value, sentido: $("f-sentido").value,
    de: $("f-de").value, ate: $("f-ate").value,
    direto: $("f-direto").checked, precoMax: Number($("f-preco").value),
  };
}

function filtered() {
  const f = filterState();
  $("f-preco-out").textContent = fmtBRL(f.precoMax);

  const active = [f.regiao, f.aeroporto, f.cia, f.tipo, f.sentido, f.de, f.ate, f.direto]
    .filter(Boolean).length + (f.precoMax < Number($("f-preco").max) ? 1 : 0);
  $("clear-label").textContent = active ? `Limpar (${active})` : "Limpar";
  $("clear").classList.toggle("is-active", active > 0);

  return viewDeals().filter((d) =>
    inRegion(d, f.regiao) &&
    (!f.aeroporto || cidadeOf(d) === f.aeroporto) &&
    (!f.sentido || (!isRT(d) && sentidoOf(d) === f.sentido)) &&
    (!f.cia || d.cia === f.cia) &&
    (!f.de || d.data >= f.de) &&
    (!f.ate || d.data <= f.ate) &&
    (!f.direto || d.direto) &&
    (!f.tipo || (
      f.tipo === "roundtrip" ? isRT(d) :
      f.tipo === "azul" ? (!isRT(d) && d.azul_cheapest) :
      f.tipo === "queda" ? (d.delta_pct != null && d.delta_pct <= -5) :
        (!isRT(d) && d.price_watch != null)
    )) &&
    // Unpaired fares have no total to compare; the slider at its maximum means no limit,
    // since totals can exceed the one-way maximum it was sized for.
    (d.sem_par || f.precoMax >= Number($("f-preco").max) || d.preco <= f.precoMax)
  );
}

/* ---------------- Grouping ---------------- */
function groupDeals(rows) {
  const groups = new Map();
  rows.forEach((d) => {
    const key = groupKey(d);
    if (!groups.has(key)) groups.set(key, { key, deals: [], rt: isRT(d) });
    groups.get(key).deals.push(d);
  });
  for (const g of groups.values()) {
    // With a stay chosen, dates without a return drop out of their pass; a pass left with
    // none stays, dimmed, to say why (wrong stay for this destination, or no return yet).
    const paired = g.deals.filter((d) => !d.sem_par);
    if (paired.length) g.deals = paired;
    else g.unpaired = g.deals[0];
    g.deals.sort((a, b) => (a.data < b.data ? -1 : 1));
    g.best = g.deals.reduce((a, b) => (b.preco < a.preco ? b : a));
    // Light the pass up only when the fare it shows carries a signal; with ~135 dates
    // per route, "any date has one" would light up nearly every card.
    g.alert = hasSignal(g.best);
    g.cidade = cidadeOf(g.best);
  }
  return [...groups.values()];
}

function sortGroups(groups) {
  const pick = {
    preco: (g) => g.best.preco,
    delta: (g) => (g.best.delta_pct == null ? 999 : g.best.delta_pct),
    data: (g) => g.best.data,
    destino: (g) => g.cidade,
  }[$("f-ordem").value];
  return groups.sort((a, b) =>
    (!!a.unpaired - !!b.unpaired) || (pick(a) > pick(b) ? 1 : pick(a) < pick(b) ? -1 : 0));
}

/* ============================================================
   Departures board
   ============================================================ */

/* How strongly a fare is worth a look. Lower is better: the gap to its own median,
   pushed further down by every independent signal it carries. */
function score(d) {
  let s = d.delta_pct ?? 0;
  if (d.price_watch != null) s -= 15;
  if (isRT(d)) s -= 12;
  if (d.menor_hist) s -= 8;
  if (d.azul_cheapest) s -= 4;
  return s;
}

function statusOf(d) {
  if (d.price_watch != null) return ["s-deal", `Alvo ≤ ${fmtInt(d.price_watch)}`];
  if (isRT(d)) return ["s-rt", `Ida+volta ${d.estadia}d`];
  if (d.delta_pct != null && d.delta_pct <= -3) return ["s-good", `▼ ${Math.abs(d.delta_pct)}% abaixo`];
  if (d.menor_hist) return ["s-good", `Menor ${HIST_DAYS} dias`];
  if (d.azul_cheapest) return ["s-azul", "Azul + barata"];
  return ["s-flat", "Na média"];
}

let flapSeq = 0;
function flaps(text) {
  return [...String(text)].map((c) => {
    const i = flapSeq++;
    return c === " "
      ? `<span class="flap sp"> </span>`
      : `<span class="flap" data-c="${esc(c)}" data-i="${i}">${esc(c)}</span>`;
  }).join("");
}

function boardRow(d) {
  flapSeq += 4; // each row starts settling a beat after the previous one
  const dest = isRT(d) ? `${d.ida_destino}` : cidadeOf(d);
  const leg = isRT(d) ? "ida+volta" : d.par_volta ? `ida+volta ${d.par_estadia}d` : sentidoOf(d);
  const when = isRT(d) ? fmtShort(d.data_ida) : fmtShort(d.data);
  const cia = (isRT(d) ? d.cia_ida : d.cia).slice(0, 7);
  const [cls, status] = statusOf(d);
  const href = isRT(d) ? d.url_ida : d.url_compra;
  const label = `${leg === "volta" ? "Volta de" : "Para"} ${cityOf(dest)}, ${when}, ${cia}, ${fmtBRL(d.preco)}, ${status}`;

  return `<li><a class="board-row" href="${esc(href)}" target="_blank" rel="noopener" aria-label="${esc(label)}">
    <span class="dest" aria-hidden="true"><span class="code">${flaps(dest)}</span><span class="city"><i>${leg}</i> ${esc(cityOf(dest))}</span></span>
    <span class="when" aria-hidden="true">${flaps(when)}</span>
    <span class="cia" aria-hidden="true">${flaps(cia.toUpperCase())}</span>
    <span class="b-fare num" aria-hidden="true">${flaps(fmtBRL(d.preco))}</span>
    <span class="status ${cls}" aria-hidden="true">${flaps(status.toUpperCase())}</span>
    <span class="meta" aria-hidden="true">${esc(when)} · ${esc(cia)}</span>
  </a></li>`;
}

function renderBoard(rows) {
  rows = rows.filter((d) => !d.sem_par);   // an unpaired fare is no highlight
  const best = new Map();
  rows.forEach((d) => {
    const k = groupKey(d);
    if (!best.has(k) || score(d) < score(best.get(k))) best.set(k, d);
  });
  const top = [...best.values()].sort((a, b) => score(a) - score(b) || a.preco - b.preco).slice(0, 8);

  flapSeq = 0;
  $("board").innerHTML = top.length
    ? top.map(boardRow).join("")
    : `<li class="board-empty">SEM PARTIDAS PARA ESSES FILTROS</li>`;

  if (!boardBooted && top.length) { boardBooted = true; spinFlaps(); }
}

/* The one theatrical moment: on first load every tile shuffles through letters
   and settles left-to-right, row by row, like a real split-flap board. */
function spinFlaps() {
  if (REDUCED_MOTION) return;
  const GLYPHS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
  const tiles = [...$("board").querySelectorAll(".flap[data-c]")];
  const last = Math.max(...tiles.map((t) => Number(t.dataset.i)));
  let tick = 0;
  const timer = setInterval(() => {
    tick++;
    let pending = 0;
    for (const t of tiles) {
      const settleAt = 5 + (Number(t.dataset.i) / last) * 34; // whole board lands in ~1.8 s
      if (tick >= settleAt) {
        if (t.classList.contains("spin")) { t.textContent = t.dataset.c; t.classList.remove("spin"); }
      } else {
        pending++;
        if (/[A-Z0-9]/i.test(t.dataset.c)) {
          t.textContent = GLYPHS[(Math.random() * GLYPHS.length) | 0];
          t.classList.add("spin");
        }
      }
    }
    if (!pending) clearInterval(timer);
  }, 45);
}

/* ============================================================
   Boarding passes
   ============================================================ */

/* Four price tiers over this route's own fares: "cheap" is relative to the destination. */
function tierer(prices) {
  const sorted = [...prices].sort((a, b) => a - b);
  const q = (f) => sorted[Math.floor((sorted.length - 1) * f)];
  const cuts = [q(0.25), q(0.5), q(0.75)];
  return (p) => (p <= cuts[0] ? 1 : p <= cuts[1] ? 2 : p <= cuts[2] ? 3 : 4);
}

const TIER_WORD = { 1: "muito barato", 2: "barato", 3: "médio", 4: "caro" };

function calendar(g) {
  const byDate = new Map(g.deals.map((d) => [d.data, d]));
  const tier = tierer(g.deals.map((d) => d.preco));
  const months = [...new Set(g.deals.map((d) => d.data.slice(0, 7)))].sort();

  const html = months.map((ym) => {
    const [y, m] = ym.split("-").map(Number);
    const first = new Date(Date.UTC(y, m - 1, 1));
    const days = new Date(Date.UTC(y, m, 0)).getUTCDate();
    const cells = [];
    for (let i = 0; i < first.getUTCDay(); i++) cells.push('<div class="day empty"></div>');
    for (let day = 1; day <= days; day++) {
      const iso = `${ym}-${String(day).padStart(2, "0")}`;
      const d = byDate.get(iso);
      if (!d) { cells.push(`<div class="day"><span class="d">${day}</span></div>`); continue; }
      const t = tier(d.preco);
      const best = d === g.best ? " best" : "";
      cells.push(`<a class="day t${t}${best}" href="${esc(d.url_compra)}" target="_blank" rel="noopener"
        title="${fmtDate(iso)} · ${fmtBRL(d.preco)} · ${TIER_WORD[t]}${best ? " · melhor preço" : ""} · ${esc(d.cia)}${d.visto_em ? " · " + ageOf(d.visto_em) : ""}">
        <span class="d">${day}</span><span class="p">${Math.round(d.preco / 10) * 10}</span></a>`);
    }
    return `<div class="month"><h3>${fmtMonth(ym)}</h3>
      <div class="dow" aria-hidden="true"><span>D</span><span>S</span><span>T</span><span>Q</span><span>Q</span><span>S</span><span>S</span></div>
      <div class="grid">${cells.join("")}</div></div>`;
  }).join("");

  return html + `<p class="legend">
    <span><i style="background:#113a2a"></i>muito barato</span>
    <span><i style="background:#1f3a1d"></i>barato</span>
    <span><i style="background:#3a2c0b"></i>médio</span>
    <span><i style="background:#3d1b15"></i>caro</span>
    <span>Contorno âmbar = melhor dia. Toque no dia para comprar.</span></p>`;
}

function roundTripBody(d) {
  return `<table class="dates">
    <tr><th>Trecho</th><th>Data</th><th>Cia</th><th>Tarifa</th></tr>
    <tr><td>${esc(d.ida_origem)} → ${esc(d.ida_destino)}</td><td class="num">${fmtDate(d.data_ida)}</td>
        <td>${esc(d.cia_ida)}</td><td class="num"><a class="buy" href="${esc(d.url_ida)}" target="_blank" rel="noopener">${fmtBRL(d.preco_ida)}</a></td></tr>
    <tr><td>${esc(d.volta_origem)} → ${esc(d.volta_destino)}</td><td class="num">${fmtDate(d.data_volta)}</td>
        <td>${esc(d.cia_volta)}</td><td class="num"><a class="buy" href="${esc(d.url_volta)}" target="_blank" rel="noopener">${fmtBRL(d.preco_volta)}</a></td></tr>
    <tr><td>Total</td><td class="num">${d.estadia} dias</td><td></td><td class="num">${fmtBRL(d.preco)}</td></tr>
  </table>`;
}

function datesTable(g) {
  const rows = g.deals.map((d) => `<tr>
    <td class="num">${fmtDate(d.data)}</td>
    <td>${esc(d.cia)}</td>
    <td>${d.direto ? "direto" : `${d.paradas} parada(s)`}</td>
    <td class="num"><a class="buy" href="${esc(d.url_compra)}" target="_blank" rel="noopener">${fmtBRL(d.preco)}</a></td>
  </tr>`).join("");
  return `<table class="dates"><tr><th>Data</th><th>Cia</th><th>Voo</th><th>Tarifa</th></tr>${rows}</table>`;
}

function iata(code, extra = "") {
  return `<span class="iata"><b>${esc(code)}</b><small>${esc(extra || cityOf(code))}</small></span>`;
}

const LEAD_LABELS = ["0–7 d", "8–14 d", "15–30 d", "31–60 d", "61–90 d", "91–120 d", "121–180 d"];
const DOW_LABELS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"];   // Python weekday(): Monday = 0
const MIN_CLOSED_DATES = 20, MIN_LEAD_BUCKETS = 4;
const MIN_ROUTE_DATES = 5;   // mirrors history.MIN_ROUTE_DATES: below it a route median means nothing

/* Daily series of one flight date: line, median rule, floor rule, today's point. */
function dateChart(d, hist) {
  const points = hist.series[`${d.origem}|${d.destino}|${d.data}`];
  if (!points || points.length < 2) return `<p class="hist-note">Ainda sem série suficiente para esta data.</p>`;
  const prices = points.map(([, p]) => p);
  const w = 560, h = 160, padL = 46, padR = 12, padT = 12, padB = 22;
  const lo = Math.min(...prices), hi = Math.max(...prices), span = hi - lo || 1;
  const x = (i) => padL + (i / (points.length - 1)) * (w - padL - padR);
  const y = (v) => padT + (1 - (v - lo) / span) * (h - padT - padB);
  const path = prices.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");
  const med = d.hist_med, rule = (v, cls, label) => (v == null || v < lo || v > hi) ? "" :
    `<line class="${cls}" x1="${padL}" x2="${w - padR}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}"/>
     <text class="rule-label" x="${w - padR}" y="${(y(v) - 4).toFixed(1)}" text-anchor="end">${label} ${fmtBRL(v)}</text>`;
  const last = points.length - 1;
  return `<figure class="hist-chart">
    <figcaption>Preço desta data · ${points.length} dias observados</figcaption>
    <svg viewBox="0 0 ${w} ${h}" role="img"
      aria-label="Preço de ${fmtDate(d.data)} ao longo de ${points.length} dias: de ${fmtBRL(prices[0])} a ${fmtBRL(prices[last])}, mínimo ${fmtBRL(lo)}, máximo ${fmtBRL(hi)}">
      <text class="axis" x="${padL - 6}" y="${y(hi) + 4}" text-anchor="end">${fmtInt(hi)}</text>
      <text class="axis" x="${padL - 6}" y="${y(lo) + 4}" text-anchor="end">${fmtInt(lo)}</text>
      <text class="axis" x="${padL}" y="${h - 4}">${fmtShort(points[0][0])}</text>
      <text class="axis" x="${w - padR}" y="${h - 4}" text-anchor="end">${fmtShort(points[last][0])}</text>
      ${rule(med, "rule-med", "mediana")}
      <path class="series" d="${path}"/>
      <circle class="today" cx="${x(last).toFixed(1)}" cy="${y(prices[last]).toFixed(1)}" r="4"/>
    </svg></figure>`;
}

function barRows(entries, fmtKey) {
  if (!entries.length) return "";
  const values = entries.map(([, v]) => v);
  const max = Math.max(...values), min = Math.min(...values);
  // Fares of one route sit in a narrow band, so a bar drawn from zero would make R$ 261 and
  // R$ 266 look identical. Spread them across the group's own range instead, keeping a 30%
  // floor so the cheapest bar is still a bar. All equal: full width, and no cheapest to mark.
  const flat = max === min;
  const width = (v) => (flat ? 100 : Math.round(30 + 70 * ((v - min) / (max - min))));
  return entries.map(([k, v]) => `<div class="bar-row${!flat && v === min ? " is-low" : ""}">
    <span class="bar-key">${esc(fmtKey(k))}</span>
    <span class="bar-track"><span class="bar-fill" style="width:${width(v)}%"></span></span>
    <span class="bar-val num">${fmtBRL(v)}</span></div>`).join("");
}

/* What the route usually costs, and (once enough flights have departed) when to buy. */
function routeSection(d, h) {
  const r = h.rota;
  // Too few flight dates for a median to mean anything — and the stub above already
  // says "sem histórico", so a confident route summary here would contradict it.
  if (!r || r.n_dates < MIN_ROUTE_DATES) return "";
  const months = Object.entries(r.by_month).sort(([a], [b]) => a.localeCompare(b));
  const dows = Object.entries(r.by_dow).sort(([a], [b]) => Number(a) - Number(b));
  const lead = r.lead_curve || [];
  const enough = r.n_closed >= MIN_CLOSED_DATES && lead.length >= MIN_LEAD_BUCKETS;
  return `<section class="hist-route" aria-label="Histórico da rota">
    <h3>Rota ${esc(d.origem)} → ${esc(d.destino)}</h3>
    <p class="hist-facts"><span>Preço típico <b class="num">${fmtBRL(r.med)}</b></span>
      <span>Piso já visto <b class="num">${fmtBRL(r.min)}</b></span>
      <span>${fmtInt(r.n_dates)} datas acompanhadas</span></p>
    <div class="hist-cols">
      <div><h4>Por mês do voo</h4>${barRows(months, (m) => MON[Number(m) - 1])}</div>
      <div><h4>Por dia da semana</h4>${barRows(dows, (k) => DOW_LABELS[Number(k)])}</div>
      <div><h4>Quando comprar</h4>${enough
        ? barRows(lead.map((b) => [b.bucket, b.med]), (k) => LEAD_LABELS[Number(k)])
        : `<p class="hist-note">Coletando dados — disponível após algumas semanas de voos encerrados (${fmtInt(r.n_closed)} de ${MIN_CLOSED_DATES}).</p>`}</div>
    </div></section>`;
}

function historyBlock(g) {
  if (g.rt) return "";
  const d = g.best;
  // Fetching while rendering is safe: ensureRouteHistory sets the Map key synchronously,
  // before the request goes out, so the re-render it triggers cannot fetch again or loop.
  ensureRouteHistory(d.origem, d.destino);          // idempotent; re-renders when it lands
  const h = ROUTE_HISTORY.get(routeFile(d.origem, d.destino));
  if (h === null || h === undefined) return `<p class="hist-note">Carregando histórico…</p>`;
  if (h === false) return `<p class="hist-note">Histórico indisponível agora para esta rota. Calendário e tabela seguem funcionando.</p>`;
  return dateChart(d, h) + routeSection(d, h);
}

const carriedNote = (g) => {
  const stamp = g.deals.map((d) => d.visto_em).filter(Boolean).sort()[0];
  return stamp ? `<p class="hist-note">Datas a mais de ${NEAR_DAYS} dias são atualizadas uma vez por dia · ${ageOf(stamp)}.</p>` : "";
};

function passHTML(g, i) {
  const d = g.best;
  const open = OPEN.has(g.key);
  // Round trips may be open-jaw: say so when the return leg leaves from another city.
  const openJaw = g.rt && d.volta_origem !== d.ida_destino;
  const from = g.rt ? d.ida_origem : d.origem;
  const to = g.rt ? d.ida_destino : d.destino;
  const toLabel = openJaw ? `volta de ${cityOf(d.volta_origem)}` : "";

  const meta = g.rt
    ? [["Ida", fmtShort(d.data_ida)], ["Volta", fmtShort(d.data_volta)], ["Estadia", `${d.estadia} dias`]]
    : [["Melhor dia", fmtShort(d.data)], ["Cia", d.cia], ["Datas", g.deals.length]];

  return `<article class="pass ${g.alert ? "is-alert" : ""} ${open ? "open" : ""}" style="--i:${Math.min(i, 12)}">
    <button class="pass-top" type="button" data-key="${esc(g.key)}" aria-expanded="${open}">
      <span class="pass-main">
        <span class="pass-route">
          ${iata(from)}
          <span class="flight-path" aria-hidden="true">${icon("plane")}</span>
          ${iata(to, toLabel)}
        </span>
        <span class="pass-meta">${meta.map(([k, v]) => `<span><i>${k}</i><em class="num">${esc(v)}</em></span>`).join("")}</span>
        <span class="badges">${badges(d) || `<span class="badge reg">${esc(placeOf(d))}</span>`}</span>
      </span>
      <span class="pass-stub">
        <span><span class="fare-label">Tarifa${g.rt ? " total" : ""}</span>
          <span class="fare"><small>R$</small>${fmtInt(d.preco)}</span></span>
        ${delta(d) || (g.rt ? "" : rotaDelta(d) || '<span class="delta flat">sem histórico</span>')}
      </span>
    </button>
    <div class="pass-foot">
      ${spark(d) || `<span class="kicker">${esc(placeOf(d))}</span>`}
      <span class="pass-toggle">${open ? "Fechar" : g.rt ? "Ver trechos" : "Ver calendário"} ${icon("chevron", "chevron")}</span>
    </div>
    ${open ? `<div class="pass-body">${g.rt ? roundTripBody(d) : historyBlock(g) + carriedNote(g) + calendar(g) + datesTable(g)}</div>` : ""}
  </article>`;
}

/* ============================================================
   Table
   ============================================================ */
function tableRowHTML(d) {
  const cell = (label, value) => `<td data-label="${label}">${value}</td>`;
  const rota = isRT(d)
    ? `${esc(d.ida_origem)}→${esc(d.ida_destino)} + ${esc(d.volta_origem)}→${esc(d.volta_destino)}`
    : `${esc(d.origem)} → ${esc(d.destino)}`;
  const data = isRT(d) ? `${fmtDate(d.data_ida)} → ${fmtDate(d.data_volta)}` : fmtDate(d.data);
  const cia = isRT(d) ? `${esc(d.cia_ida)} + ${esc(d.cia_volta)}` : esc(d.cia);
  const link = isRT(d)
    ? `<a class="buy" href="${esc(d.url_ida)}" target="_blank" rel="noopener">ida</a> ·
       <a class="buy" href="${esc(d.url_volta)}" target="_blank" rel="noopener">volta</a>`
    : `<a class="buy" href="${esc(d.url_compra)}" target="_blank" rel="noopener">comprar</a>`;

  return `<tr class="${hasSignal(d) ? "is-alert" : ""}">
    ${cell("Rota", `${rota} <span class="muted">· ${esc(placeOf(d))}</span>`)}
    ${cell("Data", `<span class="num"${d.visto_em ? ` title="${ageOf(d.visto_em)}"` : ""}>${data}</span>`)}
    ${cell("Cia", `${cia}${isRT(d) ? "" : ` <span class="muted">· ${d.direto ? "direto" : d.paradas + " parada(s)"}</span>`}`)}
    ${cell("Tarifa", `<span class="num">${fmtBRL(d.preco)}</span>`)}
    ${cell("vs. média", delta(d) || '<span class="muted">sem histórico</span>')}
    ${cell("vs. rota", rotaDelta(d, true) || '<span class="muted">—</span>')}
    ${cell("Sinal", badges(d) || "—")}
    ${cell("", link)}
  </tr>`;
}

function renderTable(rows) {
  const sorted = [...rows].sort((a, b) => {
    const x = a[sortKey] ?? Infinity, y = b[sortKey] ?? Infinity;
    return (!!a.sem_par - !!b.sem_par) || (x > y ? 1 : x < y ? -1 : 0) * sortDir;
  });
  $("rows").innerHTML = sorted.slice(0, tableLimit).map(tableRowHTML).join("");
  const rest = sorted.length - tableLimit;
  $("more").hidden = rest <= 0;
  $("more").textContent = `Mostrar mais ${Math.min(TABLE_PAGE, rest)} (faltam ${fmtInt(rest)})`;
}

/* ============================================================
   Render
   ============================================================ */
function renderCounters(rows) {
  const priced = rows.filter((d) => !d.sem_par);
  const menor = priced.length ? fmtBRL(Math.min(...priced.map((d) => d.preco))) : "—";
  const destinos = new Set(rows.map(cidadeOf)).size;
  const sinais = rows.filter(hasSignal).length;
  const quedas = rows.filter((d) => d.delta_pct != null && d.delta_pct <= -5).length;
  $("summary").innerHTML = [
    ["Tarifas", fmtInt(rows.length), ""],
    ["Mais barata", menor, "is-deal"],
    ["Destinos", destinos, ""],
    ["Com sinal", fmtInt(sinais), ""],
    ["Em queda", fmtInt(quedas), "is-good"],
  ].map(([label, value, cls]) =>
    `<div class="counter ${cls}"><span class="kicker">${label}</span><span class="value num">${value}</span></div>`
  ).join("");
}

function render() {
  const rows = filtered();
  renderBoard(rows);
  renderCounters(rows);
  $("count").textContent = `${fmtInt(rows.length)} de ${fmtInt(viewDeals().length)} tarifas`;
  $("empty").hidden = rows.length > 0;

  if (VIEW === "cards") {
    $("cards").innerHTML = sortGroups(groupDeals(rows)).map(passHTML).join("");
  } else {
    renderTable(rows);
  }
}

// Filters fire on every slider step; coalesce them into one render per frame.
let pending = false;
function scheduleRender() {
  if (pending) return;
  pending = true;
  requestAnimationFrame(() => { pending = false; render(); });
}

function setView(view) {
  VIEW = view;
  document.querySelectorAll(".seg").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === view)));
  $("cards").hidden = view !== "cards";
  $("tabela").hidden = view !== "tabela";
  render();
}

/* ---------------- Clock + freshness ---------------- */
function tickClock() {
  $("clock").textContent = new Date().toLocaleTimeString("pt-BR", { timeZone: "America/Sao_Paulo", hour12: false });
  if (!GENERATED_AT) return;
  const hours = (Date.now() - GENERATED_AT.getTime()) / 36e5;
  const span = hours < 1 ? `${Math.max(1, Math.round(hours * 60))} min` : `${Math.round(hours)} h`;
  const el = $("updated");
  // Cycles run every ~6 h; past 12 h something upstream stalled and the fares are old.
  el.classList.toggle("stale", hours > 12);
  el.textContent = hours > 12
    ? `Dados de ${span} atrás — o robô pode estar sem conseguir buscar`
    : `Tarifas encontradas há ${span} · ${fmtFound(GENERATED_AT)}`;
}

/* ---------------- Setup ---------------- */
function unique(arr) { return [...new Set(arr)].sort(); }

function fillSelect(el, label, values, fmt = (v) => v) {
  el.innerHTML = `<option value="">${label}: todos</option>` +
    values.map((v) => `<option value="${esc(v)}">${esc(fmt(v))}</option>`).join("");
}

function setup(data) {
  DEALS = data.deals;
  AIRPORTS = data.aeroportos || {};
  HIST_DAYS = data.hist_janela_dias || HIST_DAYS;
  NEAR_DAYS = data.janela_perto_dias || NEAR_DAYS;
  GENERATED_AT = new Date(data.gerado_em);

  // The hub is whichever airport shows up in the most legs.
  const counts = {};
  DEALS.forEach((d) => {
    counts[d.origem] = (counts[d.origem] || 0) + 1;
    counts[d.destino] = (counts[d.destino] || 0) + 1;
  });
  HUB = Object.keys(counts).reduce((a, b) => (counts[b] > counts[a] ? b : a), DEALS.length ? DEALS[0].origem : "CNF");
  $("hub-label").textContent = HUB;
  $("hub-city").textContent = cityOf(HUB);

  // Round trips by stay: returns are indexed once (sentidoOf needs HUB, set just above), and
  // the selector lists every stay any country uses. A snapshot without the table hides it.
  ESTADIAS = data.estadias || null;
  RETURNS = new Map(DEALS.filter((d) => !isRT(d) && sentidoOf(d) === "volta")
    .map((d) => [`${d.origem}|${d.data}`, d]));
  VIEW_CACHE = null;
  const stayEl = $("f-estadia");
  if (ESTADIAS) {
    const days = [...new Set([...Object.values(ESTADIAS.por_pais).flat(), ...ESTADIAS.padrao])]
      .sort((a, b) => a - b);
    stayEl.insertAdjacentHTML("beforeend",
      days.map((n) => `<option value="${n}">Estadia: ${n} dias</option>`).join(""));
    let saved = "";
    try { saved = localStorage.getItem(STAY_KEY) || ""; } catch (e) { /* storage blocked: one-way */ }
    if ([...stayEl.options].some((o) => o.value === saved)) { stayEl.value = saved; STAY = saved; }
    stayEl.hidden = false;
    stayEl.addEventListener("input", () => {
      STAY = stayEl.value;
      try { localStorage.setItem(STAY_KEY, STAY); } catch (e) { /* applied, just not remembered */ }
      tableLimit = TABLE_PAGE;
      scheduleRender();
    });
  }

  // Countries first, then the Brazilian states; city level is the airport filter below.
  const paises = unique(DEALS.map((d) => d.pais).filter(Boolean));
  const ufs = unique(DEALS.map((d) => d.uf).filter(Boolean));
  $("f-regiao").innerHTML = `<option value="">Região: todas</option>` +
    `<optgroup label="País">${paises.map((p) => `<option value="pais:${esc(p)}">${esc(p)}</option>`).join("")}</optgroup>` +
    (ufs.length ? `<optgroup label="Brasil · estado">${ufs.map((u) => `<option value="uf:${esc(u)}">${esc(u)}</option>`).join("")}</optgroup>` : "");
  fillSelect($("f-aeroporto"), "Aeroporto", unique(DEALS.map(cidadeOf)), (c) => `${c} · ${cityOf(c)}`);
  fillSelect($("f-cia"), "Cia", unique(DEALS.map((d) => d.cia)));

  const slider = $("f-preco");
  slider.max = String(Math.ceil(DEALS.reduce((m, d) => Math.max(m, d.preco), 1000) / 50) * 50);
  slider.value = slider.max;

  document.querySelectorAll("#filters select, #filters input, #f-ordem").forEach((el) =>
    el.addEventListener("input", () => { tableLimit = TABLE_PAGE; scheduleRender(); }));

  $("clear").addEventListener("click", () => {
    document.querySelectorAll("#filters select").forEach((s) => (s.value = ""));
    $("f-de").value = $("f-ate").value = "";
    $("f-direto").checked = false;
    slider.value = slider.max;
    tableLimit = TABLE_PAGE;
    render();
  });

  document.querySelectorAll(".seg").forEach((b) =>
    b.addEventListener("click", () => setView(b.dataset.view)));

  $("cards").addEventListener("click", (e) => {
    const head = e.target.closest(".pass-top, .pass-foot");
    if (!head) return;
    const key = head.closest(".pass").querySelector(".pass-top").dataset.key;
    OPEN.has(key) ? OPEN.delete(key) : OPEN.add(key);
    render();
  });

  $("more").addEventListener("click", () => { tableLimit += TABLE_PAGE; render(); });

  document.querySelectorAll("#table th[data-sort]").forEach((th) =>
    th.addEventListener("click", () => {
      const k = th.dataset.sort;
      sortDir = sortKey === k ? -sortDir : 1;
      sortKey = k;
      document.querySelectorAll("#table th[data-sort]").forEach((o) =>
        o.setAttribute("aria-sort", o === th ? (sortDir === 1 ? "ascending" : "descending") : "none"));
      render();
    }));

  $("gate").hidden = true;
  $("app").hidden = false;
  tickClock();
  setInterval(tickClock, 1000);
  $("cards").classList.add("booting");
  setView("cards");
  setTimeout(() => $("cards").classList.remove("booting"), 1200);
}

/* Only an OperationError from the decrypt is actually a wrong password (see switch.js);
   telling a stale deploy or an old browser apart from one saves a lot of retyping. */
const UNLOCK_MESSAGES = {
  password: "Senha incorreta. Confira e tente de novo.",
  unsupported: "Seu navegador é antigo demais para abrir o painel. Atualize o navegador e tente de novo.",
};
const UNLOCK_FALLBACK = "Não consegui carregar os dados agora. Tente de novo em alguns minutos.";

async function unlock(event) {
  event.preventDefault();
  const btn = $("unlock"), err = $("error");
  err.hidden = true;
  btn.disabled = true;
  btn.textContent = "Validando…";
  try {
    const password = $("password").value;
    const data = await loadDeals(password);
    PASSWORD = password;          // kept in memory only, to fetch history/<ROTA>.enc.json later
    setup(data);
    loadPromos(password);         // optional section; never blocks or fails the unlock
  } catch (e) {
    err.textContent = UNLOCK_MESSAGES[e && e.code] || UNLOCK_FALLBACK;
    err.hidden = false;
    btn.disabled = false;
    btn.textContent = "Embarcar";
    $("password").select();
  }
}

$("gate-form").addEventListener("submit", unlock);

document.querySelectorAll("[data-switch]").forEach((b) =>
  b.addEventListener("click", () => PanelVersion.switchTo("classica", "classic/", $("password").value)));

// Arrived here from the classic panel already unlocked: open straight away.
const handedOver = PanelVersion.takeHandoff();
if (handedOver) { $("password").value = handedOver; $("gate-form").requestSubmit(); }
