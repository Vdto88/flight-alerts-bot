/* Troca entre o painel novo (raiz) e o clássico (/classic/), lembrando a escolha.
   Carregado pelas duas versões; é o único lugar que conhece as chaves de storage. */
const PanelVersion = (() => {
  const PREF = "painel-versao";
  const HANDOFF = "painel-handoff";
  // Storage can be blocked (private mode, site data off): then we simply don't remember.
  const safe = (fn) => { try { return fn(); } catch (e) { return null; } };

  return {
    // Runs in the root page's <head>, so whoever picked the classic panel never sees the new one flash.
    redirectIfClassic() {
      if (safe(() => localStorage.getItem(PREF)) === "classica") location.replace("classic/");
    },

    switchTo(version, url, password) {
      safe(() => localStorage.setItem(PREF, version));
      if (password) safe(() => sessionStorage.setItem(HANDOFF, password));
      location.href = url;
    },

    // The password crosses the switch exactly once, inside the same tab, and is erased on read.
    takeHandoff() {
      const pw = safe(() => sessionStorage.getItem(HANDOFF));
      safe(() => sessionStorage.removeItem(HANDOFF));
      return pw;
    },
  };
})();
