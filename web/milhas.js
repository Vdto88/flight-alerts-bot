"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const tabs = [...document.querySelectorAll("[data-airline]")];
  const number = new Intl.NumberFormat("pt-BR");
  let data, airline = "azul", password = "";
  const formatDate = value => value ? value.split("-").reverse().join("/") : "Não informada";
  const stamp = value => value ? new Date(value).toLocaleString("pt-BR", {timeZone: "America/Sao_Paulo"}) : "Não informada";
  function node(tag, text, className) {
    const el = document.createElement(tag);
    el.textContent = text;
    if (className) el.className = className;
    return el;
  }
  const conditionLabel = value => ({"Oferta pública Azul Fidelidade": "Azul Fidelidade",
    "Oferta pública LATAM Pass": "LATAM Pass"}[value] || value);
  function options(id, values) {
    const select = $(id), previous = select.value;
    select.replaceChildren(node("option", id === "destination" ? "Todos" : "Todas"));
    select.firstChild.value = "";
    [...new Set(values)].sort().forEach(value => {
      const option = node("option", id === "condition" ? conditionLabel(value) : value);
      option.value = value; select.append(option);
    });
    if (values.includes(previous)) select.value = previous;
  }
  function routes() {
    return data.searched_routes || Object.values(data.programs).flatMap(p => p.offers || []);
  }
  function destinations() {
    options("destination", routes().filter(r => !$("origin").value || r.origin === $("origin").value)
      .map(r => r.destination));
  }
  function choose(next) {
    airline = next;
    tabs.forEach(tab => {
      const active = tab.dataset.airline === next;
      tab.setAttribute("aria-selected", String(active)); tab.tabIndex = active ? 0 : -1;
    });
    $("program-panel").setAttribute("aria-labelledby", `tab-${next}`);
    const rows = data.programs[next]?.offers || [];
    options("origin", routes().map(r => r.origin));
    destinations();
    options("condition", rows.map(o => o.condition));
    render();
  }
  function render() {
    const program = data.programs[airline] || {status: "error", offers: []};
    const stale = !program.fetched_at || Date.now() - Date.parse(program.fetched_at) > 48 * 3600000;
    $("source-status").textContent = stale ? "Coleta desatualizada" : ({ok: "Fonte consultada · ofertas publicadas", partial: "Coleta parcial · algumas consultas falharam", error: "Fonte indisponível nesta coleta"}[program.status] || "Fonte indisponível");
    $("source-time").textContent = `Última tentativa: ${stamp(program.fetched_at)} · Brasília`;
    const source = {azul: ["Buscador de pontos da Azul", "https://passagens.voeazul.com.br/pt/buscador-de-pontos"],
      latam: ["Ofertas LATAM Pass", "https://www.latamairlines.com/br/pt"],
      gol: ["Ofertas Smiles", "https://www.smiles.com.br/passagens"]}[airline];
    $("source-link").textContent = source[0]; $("source-link").href = source[1];
    const invalid = $("start").value && $("end").value && $("start").value > $("end").value;
    $("filter-error").hidden = !invalid;
    const rows = invalid ? [] : program.offers.filter(o =>
      (!$("origin").value || o.origin === $("origin").value) &&
      (!$("destination").value || o.destination === $("destination").value) &&
      (!$("start").value || o.departure_date >= $("start").value) &&
      (!$("end").value || o.departure_date <= $("end").value) &&
      (!$("max").value || o.points <= Number($("max").value)) &&
      (!$("journey").value || o.journey_type === $("journey").value) &&
      (!$("condition").value || o.condition === $("condition").value)
    ).sort((a,b) => a.points - b.points || a.departure_date.localeCompare(b.departure_date));
    $("result-count").textContent = `${number.format(rows.length)} oferta${rows.length === 1 ? "" : "s"} · menor valor primeiro`;
    $("offers").replaceChildren();
    rows.forEach(o => {
      const row = node("li", "", "award-row");
      const route = node("div", `${o.origin} → ${o.destination}`, "award-route");
      route.append(node("small", `${formatDate(o.departure_date)}${o.return_date ? ` → ${formatDate(o.return_date)}` : " · só ida"}`));
      const price = node("div", number.format(o.points), "award-price");
      price.append(node("small", `${airline === "azul" ? "pontos" : "milhas"} · ${o.return_date ? "ida e volta" : "por trecho"}`));
      const details = node("div", conditionLabel(o.condition), "award-condition");
      details.append(node("small", `${o.cabin === "ECONOMY" || o.cabin === "Economy" ? "Econômica" : o.cabin} · taxas a confirmar`));
      const link = node("a", "Ver na companhia ↗");
      try {
        const url = new URL(o.url);
        if (url.protocol === "https:" && ["passagens.voeazul.com.br", "www.latamairlines.com", "www.smiles.com.br"].includes(url.hostname)) {
          link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer";
          link.setAttribute("aria-label", `Consultar ${o.origin} para ${o.destination}, ${formatDate(o.departure_date)}, na companhia`);
        }
      } catch (_) { /* Invalid source links aren't navigable. */ }
      row.append(route, price, details, link); $("offers").append(row);
    });
    $("empty").hidden = rows.length > 0 || Boolean(invalid);
    $("empty").textContent = program.status === "error" ? (program.notice || "Não foi possível consultar esta fonte. Tente após a próxima coleta; isso não significa que não há voos.") :
      $("origin").value && $("destination").value && !program.offers.some(o => o.origin === $("origin").value && o.destination === $("destination").value) ?
      `A rota ${$("origin").value} → ${$("destination").value} é monitorada, mas esta fonte não trouxe ofertas nas datas pesquisadas. Isso não significa ausência de passagens em milhas. Confira na companhia ou tente outra aba.` :
      program.offers.length ? "Nenhuma oferta corresponde a estes filtros. Experimente outra data ou limpe os filtros." :
      "Nenhuma oferta publicada foi encontrada nas rotas e datas dos seus alertas. A companhia pode ter outras datas na busca de emissão.";
  }
  tabs.forEach((tab, i) => {
    tab.addEventListener("click", () => choose(tab.dataset.airline));
    tab.addEventListener("keydown", e => {
      const target = e.key === "ArrowRight" ? (i + 1) % 3 : e.key === "ArrowLeft" ? (i + 2) % 3 : e.key === "Home" ? 0 : e.key === "End" ? 2 : null;
      if (target !== null) { e.preventDefault(); tabs[target].focus(); choose(tabs[target].dataset.airline); }
    });
  });
  $("filters").addEventListener("submit", e => e.preventDefault());
  const filterChanged = e => { if (e.target.id === "origin") destinations(); render(); };
  $("filters").addEventListener("input", filterChanged);
  $("filters").addEventListener("change", filterChanged);
  $("filters").addEventListener("reset", () => setTimeout(() => { destinations(); render(); }, 0));
  $("cash-link").addEventListener("click", e => {
    if (password) { e.preventDefault(); PanelVersion.visit("./", password); }
  });
  $("gate-form").addEventListener("submit", async e => {
    e.preventDefault(); $("error").hidden = true; $("unlock").disabled = true; $("unlock").textContent = "Abrindo…";
    try {
      const candidate = $("password").value;
      data = await PanelCrypto.load("miles.enc.json", candidate);
      if (!data.programs || !data.generated_at) throw new Error("Invalid snapshot");
      password = candidate;
      $("updated").textContent = `Atualizado em ${stamp(data.generated_at)} · Brasília`;
      choose("azul"); $("gate").hidden = true; $("miles-app").hidden = false;
      tabs[0].focus();
    } catch (error) {
      $("error").textContent = error.code === "password" ? "Senha incorreta. Confira e tente novamente." : error.code === "unsupported" ? "Atualize seu navegador para abrir o painel." : "Os dados de milhas não estão disponíveis agora. Tente após a próxima coleta.";
      $("error").hidden = false; $("unlock").disabled = false; $("unlock").textContent = "Abrir milhas";
    }
  });
  const handoff = PanelVersion.takeHandoff();
  if (handoff) { $("password").value = handoff; $("gate-form").requestSubmit(); }
})();
