const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let DEALS = [];

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

function unique(arr) { return [...new Set(arr)].sort(); }
function fmtBRL(n) { return "R$ " + Math.round(n).toLocaleString("pt-BR"); }

function fillSelect(el, label, values) {
  el.innerHTML = `<option value="">${label}: todos</option>` +
    values.map((v) => `<option value="${v}">${v}</option>`).join("");
}

let sortKey = "preco", sortDir = 1;

function render() {
  const regiao = document.getElementById("f-regiao").value;
  const aeroporto = document.getElementById("f-aeroporto").value;
  const cia = document.getElementById("f-cia").value;
  const tipo = document.getElementById("f-tipo").value;
  const mes = document.getElementById("f-mes").value;
  const direto = document.getElementById("f-direto").checked;
  const precoMax = Number(document.getElementById("f-preco").value);
  document.getElementById("f-preco-out").textContent = fmtBRL(precoMax);

  let rows = DEALS.filter((d) =>
    (!regiao || d.regiao === regiao) &&
    (!aeroporto || d.destino === aeroporto) &&
    (!cia || d.cia === cia) &&
    (!mes || d.data.slice(0, 7) === mes) &&
    (!direto || d.direto) &&
    (!tipo || (tipo === "azul" ? d.azul_cheapest : d.price_watch != null)) &&
    d.preco <= precoMax
  );

  rows.sort((a, b) => {
    const x = a[sortKey], y = b[sortKey];
    return (x > y ? 1 : x < y ? -1 : 0) * sortDir;
  });

  const minPreco = rows.length > 0 ? fmtBRL(Math.min(...rows.map((d) => d.preco))) : "—";
  const rotas = new Set(rows.map((d) => d.origem + "→" + d.destino)).size;
  const alertas = rows.filter((d) => d.azul_cheapest || d.price_watch != null).length;
  document.getElementById("summary").innerHTML = [
    ["Deals", rows.length],
    ["Mais barato", minPreco],
    ["Rotas", rotas],
    ["Alertas", alertas],
  ].map(([label, value]) =>
    `<div class="card"><div class="label">${label}</div><div class="value">${value}</div></div>`
  ).join("");

  document.getElementById("rows").innerHTML = rows.map((d) => {
    const badges =
      (d.azul_cheapest ? '<span class="badge azul">Azul</span>' : "") +
      (d.price_watch != null ? `<span class="badge watch">≤${Math.round(d.price_watch)}</span>` : "") || "—";
    const stops = d.direto ? "direto" : `${d.paradas} parada(s)`;
    const alert = d.azul_cheapest || d.price_watch != null ? ' class="alert"' : "";
    return `<tr${alert}>
      <td>${esc(d.origem)} → ${esc(d.destino)} <span class="muted">· ${esc(d.regiao)}</span></td>
      <td>${esc(d.data)}</td>
      <td>${esc(d.cia)} <span class="muted">· ${esc(stops)}</span></td>
      <td>${fmtBRL(d.preco)}</td>
      <td>${badges}</td>
      <td><a class="buy" href="${esc(d.url_compra)}" target="_blank" rel="noopener">comprar</a></td>
    </tr>`;
  }).join("");
  document.getElementById("count").textContent = `${rows.length} de ${DEALS.length} deals`;
}

function setup(data) {
  DEALS = data.deals;
  document.getElementById("updated").textContent = "atualizado: " + data.gerado_em;
  fillSelect(document.getElementById("f-regiao"), "Região", unique(DEALS.map((d) => d.regiao)));
  fillSelect(document.getElementById("f-aeroporto"), "Aeroporto", unique(DEALS.map((d) => d.destino)));
  fillSelect(document.getElementById("f-cia"), "Cia", unique(DEALS.map((d) => d.cia)));
  fillSelect(document.getElementById("f-mes"), "Mês", unique(DEALS.map((d) => d.data.slice(0, 7))));

  const maxPrice = Math.max(1000, ...DEALS.map((d) => d.preco));
  const slider = document.getElementById("f-preco");
  slider.max = String(Math.ceil(maxPrice / 50) * 50);
  slider.value = slider.max;

  document.querySelectorAll("#filters select, #filters input").forEach((el) =>
    el.addEventListener("input", render));
  document.querySelectorAll("th[data-sort]").forEach((th) =>
    th.addEventListener("click", () => {
      const k = th.dataset.sort;
      sortDir = sortKey === k ? -sortDir : 1;
      sortKey = k;
      render();
    }));

  document.getElementById("gate").hidden = true;
  document.getElementById("app").hidden = false;
  render();
}

async function unlock() {
  const pw = document.getElementById("password").value;
  const err = document.getElementById("error");
  const btn = document.getElementById("unlock");
  err.hidden = true;
  btn.disabled = true;
  try {
    setup(await loadDeals(pw));
  } catch (e) {
    err.hidden = false;
    btn.disabled = false;
  }
}

document.getElementById("unlock").addEventListener("click", unlock);
document.getElementById("password").addEventListener("keydown", (e) => {
  if (e.key === "Enter") unlock();
});
