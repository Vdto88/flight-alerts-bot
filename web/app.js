/* Terminal CNF — lê o snapshot cifrado, monta o quadro de partidas com os
   melhores sinais, e desenha cartões de embarque por destino (com calendário)
   ou uma tabela paginada para varrer tudo. */

const $ = (id) => document.getElementById(id);
const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
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

const CITY = {
  CNF: "Belo Horizonte", GIG: "Rio · Galeão", SDU: "Rio · Santos Dumont", CGH: "São Paulo · Congonhas",
  GRU: "São Paulo · Guarulhos", SJK: "São José dos Campos", SLZ: "São Luís", FLN: "Florianópolis",
  NVT: "Navegantes", POA: "Porto Alegre", IGU: "Foz do Iguaçu", REC: "Recife", SSA: "Salvador",
  FTE: "El Calafate", PNT: "Puerto Natales", PMC: "Puerto Montt", PUQ: "Punta Arenas",
  BRC: "Bariloche", SCL: "Santiago", LIS: "Lisboa", OPO: "Porto", MAD: "Madri", BCN: "Barcelona",
  FCO: "Roma", MXP: "Milão", CDG: "Paris · CDG", ORY: "Paris · Orly",
};
const cityOf = (code) => CITY[code] || code;

const isRT = (d) => d.tipo === "roundtrip";
const cidadeOf = (d) => (d.origem === HUB ? d.destino : d.origem);
const sentidoOf = (d) => (d.destino === HUB ? "volta" : "ida");
const hasSignal = (d) => isRT(d) || d.azul_cheapest || d.price_watch != null;
// Round trips are keyed by their itinerary so an open card survives re-filtering.
const groupKey = (d) => (isRT(d)
  ? `rt:${d.ida_destino}|${d.data_ida}|${d.volta_origem}|${d.data_volta}`
  : `${cidadeOf(d)}|${sentidoOf(d)}`);

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

/* ---------------- Decryption ---------------- */
async function deriveKey(password, salt, iterations) {
  const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", salt, iterations, hash: "SHA-256" },
    base, { name: "AES-GCM", length: 256 }, false, ["decrypt"]
  );
}

async function loadDeals(password) {
  const res = await fetch("deals.enc.json", { cache: "no-store" });
  const p = await res.json();
  const key = await deriveKey(password, b64(p.salt), p.iterations);
  const clear = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64(p.iv) }, key, b64(p.ciphertext));
  return JSON.parse(new TextDecoder().decode(clear));
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
  if (d.menor_hist) out.push(`<span class="badge low">${icon("star")} menor em 30d</span>`);
  return out.join("");
}

/* Gap between this fare and its own 30-day median. Under ±3% it is noise. */
function delta(d) {
  if (d.delta_pct == null) return "";
  const p = d.delta_pct;
  if (Math.abs(p) < 3) return `<span class="delta flat">na média</span>`;
  const dir = p < 0 ? "down" : "up";
  const word = p < 0 ? "abaixo" : "acima";
  return `<span class="delta ${dir}" title="${Math.abs(p)}% ${word} da média de 30 dias">${icon(dir)}${Math.abs(p)}% ${word}</span>`;
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

  return DEALS.filter((d) =>
    (!f.regiao || d.regiao === f.regiao) &&
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
    d.preco <= f.precoMax
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
  return groups.sort((a, b) => (pick(a) > pick(b) ? 1 : pick(a) < pick(b) ? -1 : 0));
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
  if (d.menor_hist) return ["s-good", "Menor 30 dias"];
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
  const leg = isRT(d) ? "ida+volta" : sentidoOf(d);
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
        title="${fmtDate(iso)} · ${fmtBRL(d.preco)} · ${TIER_WORD[t]}${best ? " · melhor preço" : ""} · ${esc(d.cia)}">
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
        <span class="badges">${badges(d) || `<span class="badge reg">${esc(d.regiao)}</span>`}</span>
      </span>
      <span class="pass-stub">
        <span><span class="fare-label">Tarifa${g.rt ? " total" : ""}</span>
          <span class="fare"><small>R$</small>${fmtInt(d.preco)}</span></span>
        ${delta(d) || (g.rt ? "" : '<span class="delta flat">sem histórico</span>')}
      </span>
    </button>
    <div class="pass-foot">
      ${spark(d) || `<span class="kicker">${esc(d.regiao)}</span>`}
      <span class="pass-toggle">${open ? "Fechar" : g.rt ? "Ver trechos" : "Ver calendário"} ${icon("chevron", "chevron")}</span>
    </div>
    ${open ? `<div class="pass-body">${g.rt ? roundTripBody(d) : calendar(g) + datesTable(g)}</div>` : ""}
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
    ${cell("Rota", `${rota} <span class="muted">· ${esc(d.regiao)}</span>`)}
    ${cell("Data", `<span class="num">${data}</span>`)}
    ${cell("Cia", `${cia}${isRT(d) ? "" : ` <span class="muted">· ${d.direto ? "direto" : d.paradas + " parada(s)"}</span>`}`)}
    ${cell("Tarifa", `<span class="num">${fmtBRL(d.preco)}</span>`)}
    ${cell("vs. média", delta(d) || '<span class="muted">sem histórico</span>')}
    ${cell("Sinal", badges(d) || "—")}
    ${cell("", link)}
  </tr>`;
}

function renderTable(rows) {
  const sorted = [...rows].sort((a, b) => {
    const x = a[sortKey] ?? Infinity, y = b[sortKey] ?? Infinity;
    return (x > y ? 1 : x < y ? -1 : 0) * sortDir;
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
  const menor = rows.length ? fmtBRL(Math.min(...rows.map((d) => d.preco))) : "—";
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
  $("count").textContent = `${fmtInt(rows.length)} de ${fmtInt(DEALS.length)} tarifas`;
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

  fillSelect($("f-regiao"), "Região", unique(DEALS.map((d) => d.regiao)));
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

async function unlock(event) {
  event.preventDefault();
  const btn = $("unlock"), err = $("error");
  err.hidden = true;
  btn.disabled = true;
  btn.textContent = "Validando…";
  try {
    setup(await loadDeals($("password").value));
  } catch (e) {
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
