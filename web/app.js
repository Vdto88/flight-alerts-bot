/* Painel de passagens — lê o snapshot cifrado, agrupa por destino e desenha
   cards com calendário de preços, ou uma tabela para quem prefere varrer tudo. */

const $ = (id) => document.getElementById(id);
const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let DEALS = [];
let HUB = "CNF";
let VIEW = "cards";
let OPEN = new Set();
let sortKey = "preco", sortDir = 1;

const isRT = (d) => d.tipo === "roundtrip";
const cidadeOf = (d) => (d.origem === HUB ? d.destino : d.origem);
const sentidoOf = (d) => (d.destino === HUB ? "volta" : "ida");
const hasSignal = (d) => isRT(d) || d.azul_cheapest || d.price_watch != null;
const groupKey = (d, i) => (isRT(d) ? `rt:${i}` : `${cidadeOf(d)}|${sentidoOf(d)}`);

/* ---------------- Formatting ---------------- */
const fmtBRL = (n) => "R$ " + Math.round(n).toLocaleString("pt-BR");
const fmtDate = (iso) => { const [y, m, d] = String(iso).split("-"); return `${d}/${m}/${y}`; };
const fmtDay = (iso) => { const [, m, d] = String(iso).split("-"); return `${d}/${m}`; };
const MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
const fmtMonth = (ym) => {
  const [y, m] = ym.split("-");
  const name = MONTHS[Number(m) - 1];
  return `${name[0].toUpperCase()}${name.slice(1)} de ${y}`;
};
const fmtFound = (iso) => new Date(iso).toLocaleString("pt-BR", {
  timeZone: "America/Sao_Paulo", day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
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

/* Percentage gap between this fare and its own 30-day median. Below ±3% the
   noise outweighs the signal, so it reads as "na média" instead of a number. */
function delta(d) {
  if (d.delta_pct == null) return "";
  const p = d.delta_pct;
  if (Math.abs(p) < 3) return `<span class="delta flat">na média de 30d</span>`;
  const dir = p < 0 ? "down" : "up";
  const word = p < 0 ? "abaixo" : "acima";
  return `<span class="delta ${dir}" title="${Math.abs(p)}% ${word} da média de 30 dias">
    ${icon(dir)} ${Math.abs(p)}% ${word}</span>`;
}

/* Sparkline of the daily minimum, oldest → newest, ending on today's fare so the
   line and the percentage next to it always tell the same story. */
function spark(d) {
  if (!d.spark || d.spark.length < 2) return "";
  const values = d.spark.concat(d.preco);
  const w = 84, h = 24, lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
  const x = (i) => (i / (values.length - 1)) * w;
  const y = (v) => h - ((v - lo) / span) * (h - 4) - 2;
  const path = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");
  const trend = d.delta_pct <= -3 ? "down" : d.delta_pct >= 3 ? "up" : "";
  return `<svg class="spark ${trend}" viewBox="0 0 ${w} ${h}" role="img"
    aria-label="Preço nos últimos ${d.spark.length} dias, de ${fmtBRL(values[0])} até ${fmtBRL(d.preco)} hoje">
    <path d="${path}"/><circle cx="${w}" cy="${y(d.preco).toFixed(1)}" r="2.5"/></svg>`;
}

/* ---------------- Filtering ---------------- */
function filtered() {
  const regiao = $("f-regiao").value, aeroporto = $("f-aeroporto").value, cia = $("f-cia").value;
  const tipo = $("f-tipo").value, sentido = $("f-sentido").value;
  const de = $("f-de").value, ate = $("f-ate").value;
  const direto = $("f-direto").checked;
  const precoMax = Number($("f-preco").value);
  $("f-preco-out").textContent = fmtBRL(precoMax);

  return DEALS.filter((d) =>
    (!regiao || d.regiao === regiao) &&
    (!aeroporto || cidadeOf(d) === aeroporto) &&
    (!sentido || (!isRT(d) && sentidoOf(d) === sentido)) &&
    (!cia || d.cia === cia) &&
    (!de || d.data >= de) &&
    (!ate || d.data <= ate) &&
    (!direto || d.direto) &&
    (!tipo || (
      tipo === "roundtrip" ? isRT(d) :
      tipo === "azul" ? (!isRT(d) && d.azul_cheapest) :
      tipo === "queda" ? (d.delta_pct != null && d.delta_pct <= -5) :
        (!isRT(d) && d.price_watch != null)
    )) &&
    d.preco <= precoMax
  );
}

/* ---------------- Cards view ---------------- */
function groupDeals(rows) {
  const groups = new Map();
  rows.forEach((d, i) => {
    const key = groupKey(d, i);
    if (!groups.has(key)) groups.set(key, { key, deals: [], rt: isRT(d) });
    groups.get(key).deals.push(d);
  });
  for (const g of groups.values()) {
    g.deals.sort((a, b) => (a.data < b.data ? -1 : 1));
    g.best = g.deals.reduce((a, b) => (b.preco < a.preco ? b : a));
    g.alert = g.deals.some(hasSignal);
    g.cidade = cidadeOf(g.best);
  }
  return [...groups.values()];
}

function sortGroups(groups) {
  const by = $("f-ordem").value;
  const pick = {
    preco: (g) => g.best.preco,
    delta: (g) => (g.best.delta_pct == null ? 999 : g.best.delta_pct),
    data: (g) => g.best.data,
    destino: (g) => g.cidade,
  }[by];
  return groups.sort((a, b) => (pick(a) > pick(b) ? 1 : pick(a) < pick(b) ? -1 : 0));
}

/* Four price tiers over this route's own fares, so "cheap" is relative to the
   destination and not to the whole panel. */
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
    <span><i style="background:#10352a"></i>muito barato</span>
    <span><i style="background:#1d3320"></i>barato</span>
    <span><i style="background:#33280f"></i>médio</span>
    <span><i style="background:#331a1a"></i>caro</span>
    <span>Preços arredondados; clique no dia para comprar.</span></p>`;
}

function roundTripBody(d) {
  return `<table class="dates">
    <tr><th>Trecho</th><th>Data</th><th>Cia</th><th>Preço</th></tr>
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
  return `<table class="dates"><tr><th>Data</th><th>Cia</th><th>Voo</th><th>Preço</th></tr>${rows}</table>`;
}

function cardHTML(g) {
  const d = g.best;
  const open = OPEN.has(g.key);
  // Round trips can be open-jaw, so the return leg's origin is worth spelling out
  // whenever it is not the city the outbound leg landed in.
  const openJaw = g.rt && d.volta_origem !== d.ida_destino;
  const rota = g.rt
    ? `${esc(d.ida_origem)} <span class="arrow">→</span> ${esc(d.ida_destino)}${openJaw ? ` <span class="arrow">/</span> ${esc(d.volta_origem)}` : ""} <span class="arrow">→</span> ${esc(d.volta_destino)}`
    : `${esc(d.origem)} <span class="arrow">→</span> ${esc(d.destino)}`;
  const sub = g.rt
    ? `${fmtDate(d.data_ida)} → ${fmtDate(d.data_volta)} · ${d.estadia} dias${openJaw ? " · volta de outra cidade" : ""}`
    : `${g.deals.length} data${g.deals.length > 1 ? "s" : ""} · melhor em ${fmtDay(d.data)} · ${esc(d.cia)}`;

  return `<article class="deal-card ${g.alert ? "is-alert" : ""} ${open ? "open" : ""}">
    <button class="card-head" type="button" data-key="${esc(g.key)}" aria-expanded="${open}">
      <span>
        <span class="route">${rota}</span>
        <span class="card-sub">${sub}</span>
        <span class="badges">${badges(d) || '<span class="badge reg">' + esc(d.regiao) + "</span>"}</span>
      </span>
      <span class="card-price">
        <span class="amount num">${fmtBRL(d.preco)}</span>
        ${delta(d)}
      </span>
    </button>
    <div class="card-foot">
      ${spark(d) || `<span class="muted">${esc(d.regiao)}</span>`}
      <span class="muted">${open ? "menos detalhes" : g.rt ? "ver trechos" : "ver calendário"} ${icon("chevron", "chevron")}</span>
    </div>
    ${open ? `<div class="card-body">${g.rt ? roundTripBody(d) : calendar(g) + datesTable(g)}</div>` : ""}
  </article>`;
}

/* ---------------- Table view ---------------- */
function tableRowHTML(d) {
  const cell = (label, value) => `<td data-label="${label}">${value}</td>`;
  const rota = isRT(d)
    ? `${esc(d.ida_origem)}→${esc(d.ida_destino)} + ${esc(d.volta_origem)}→${esc(d.volta_destino)}`
    : `${esc(d.origem)} → ${esc(d.destino)}`;
  const data = isRT(d)
    ? `${fmtDate(d.data_ida)} → ${fmtDate(d.data_volta)}`
    : fmtDate(d.data);
  const cia = isRT(d) ? `${esc(d.cia_ida)} + ${esc(d.cia_volta)}` : esc(d.cia);
  const link = isRT(d)
    ? `<a class="buy" href="${esc(d.url_ida)}" target="_blank" rel="noopener">ida</a> ·
       <a class="buy" href="${esc(d.url_volta)}" target="_blank" rel="noopener">volta</a>`
    : `<a class="buy" href="${esc(d.url_compra)}" target="_blank" rel="noopener">comprar</a>`;

  return `<tr class="${hasSignal(d) ? "is-alert" : ""}">
    ${cell("Rota", `${rota} <span class="muted">· ${esc(d.regiao)}</span>`)}
    ${cell("Data", `<span class="num">${data}</span>`)}
    ${cell("Cia", `${cia}${isRT(d) ? "" : ` <span class="muted">· ${d.direto ? "direto" : d.paradas + " parada(s)"}</span>`}`)}
    ${cell("Preço", `<span class="num">${fmtBRL(d.preco)}</span>`)}
    ${cell("vs. média", delta(d) || '<span class="muted">sem histórico</span>')}
    ${cell("Sinal", badges(d) || "—")}
    ${cell("", link)}
  </tr>`;
}

/* ---------------- Render ---------------- */
function render() {
  const rows = filtered();

  const menor = rows.length ? fmtBRL(Math.min(...rows.map((d) => d.preco))) : "—";
  const destinos = new Set(rows.map((d) => cidadeOf(d))).size;
  const alertas = rows.filter(hasSignal).length;
  const quedas = rows.filter((d) => d.delta_pct != null && d.delta_pct <= -5).length;
  $("summary").innerHTML = [
    ["Ofertas", rows.length, ""],
    ["Mais barata", menor, "is-deal"],
    ["Destinos", destinos, ""],
    ["Sinais", alertas, ""],
    ["Em queda", quedas, ""],
  ].map(([label, value, cls]) =>
    `<div class="stat ${cls}"><div class="label">${label}</div><div class="value num">${value}</div></div>`
  ).join("");

  $("count").textContent = `${rows.length} de ${DEALS.length} ofertas`;
  $("empty").hidden = rows.length > 0;

  if (VIEW === "cards") {
    $("cards").innerHTML = sortGroups(groupDeals(rows)).map(cardHTML).join("");
  } else {
    const sorted = [...rows].sort((a, b) => {
      const x = a[sortKey] ?? Infinity, y = b[sortKey] ?? Infinity;
      return (x > y ? 1 : x < y ? -1 : 0) * sortDir;
    });
    $("rows").innerHTML = sorted.map(tableRowHTML).join("");
  }
}

function setView(view) {
  VIEW = view;
  document.querySelectorAll(".seg").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === view)));
  $("cards").hidden = view !== "cards";
  $("tabela").hidden = view !== "tabela";
  render();
}

/* ---------------- Setup ---------------- */
function unique(arr) { return [...new Set(arr)].sort(); }

function fillSelect(el, label, values) {
  el.innerHTML = `<option value="">${label}: todos</option>` +
    values.map((v) => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
}

function setup(data) {
  DEALS = data.deals;
  $("updated").textContent = "Atualizado em " + fmtFound(data.gerado_em) + " (Brasília)";

  // The hub is whichever airport shows up in the most legs — CNF today, but the
  // panel should keep working if that ever changes in config.
  const counts = {};
  DEALS.forEach((d) => {
    counts[d.origem] = (counts[d.origem] || 0) + 1;
    counts[d.destino] = (counts[d.destino] || 0) + 1;
  });
  HUB = Object.keys(counts).reduce((a, b) => (counts[b] > counts[a] ? b : a), DEALS.length ? DEALS[0].origem : "CNF");
  $("hub-label").textContent = HUB;

  fillSelect($("f-regiao"), "Região", unique(DEALS.map((d) => d.regiao)));
  fillSelect($("f-aeroporto"), "Aeroporto", unique(DEALS.map(cidadeOf)));
  fillSelect($("f-cia"), "Cia", unique(DEALS.map((d) => d.cia)));

  const slider = $("f-preco");
  slider.max = String(Math.ceil(Math.max(1000, ...DEALS.map((d) => d.preco)) / 50) * 50);
  slider.value = slider.max;

  document.querySelectorAll("#filters select, #filters input, #f-ordem").forEach((el) =>
    el.addEventListener("input", render));

  $("clear").addEventListener("click", () => {
    document.querySelectorAll("#filters select").forEach((s) => (s.value = ""));
    $("f-de").value = $("f-ate").value = "";
    $("f-direto").checked = false;
    slider.value = slider.max;
    render();
  });

  document.querySelectorAll(".seg").forEach((b) =>
    b.addEventListener("click", () => setView(b.dataset.view)));

  $("cards").addEventListener("click", (e) => {
    const head = e.target.closest(".card-head");
    if (!head) return;
    const key = head.dataset.key;
    OPEN.has(key) ? OPEN.delete(key) : OPEN.add(key);
    render();
  });

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
  setView("cards");
}

async function unlock(event) {
  event.preventDefault();
  const btn = $("unlock"), err = $("error");
  err.hidden = true;
  btn.disabled = true;
  btn.textContent = "Abrindo…";
  try {
    setup(await loadDeals($("password").value));
  } catch (e) {
    err.hidden = false;
    btn.disabled = false;
    btn.textContent = "Entrar";
    $("password").select();
  }
}

$("gate-form").addEventListener("submit", unlock);
