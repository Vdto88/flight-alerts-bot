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

/* Fetch + decrypt (+ inflate) one encrypted JSON file. Shared by both panels.
   v1 payloads hold the JSON itself; v2 payloads hold gzip(JSON) and say enc:"gzip". */
const PanelCrypto = (() => {
  const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

  async function deriveKey(password, salt, iterations) {
    const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveKey"]);
    return crypto.subtle.deriveKey(
      { name: "PBKDF2", salt, iterations, hash: "SHA-256" },
      base, { name: "AES-GCM", length: 256 }, false, ["decrypt"]
    );
  }

  async function inflate(buffer) {
    const stream = new Blob([buffer]).stream().pipeThrough(new DecompressionStream("gzip"));
    return new Response(stream).arrayBuffer();
  }

  return {
    async load(url, password) {
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const p = await res.json();
      const key = await deriveKey(password, b64(p.salt), p.iterations);
      let clear = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64(p.iv) }, key, b64(p.ciphertext));
      if (p.enc === "gzip") clear = await inflate(clear);
      return JSON.parse(new TextDecoder().decode(clear));
    },
  };
})();
