/* One calm ad box per page: <div data-lyra-ad="news"></div>.
   Asks /api/ads/slot what to show there: a paid sponsor, one labelled Google unit (only on
   Watch, Newswire and Tremor, only when switched on), Lyra's own offer, or nothing. Never a
   pop-up, never sticky, never inside text. Watch Pro and paid plans get nothing. */
(function () {
  const CSS = `
  .lyra-ad { margin: 18px 0; }
  .lyra-ad a.lyra-ad-card { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 10px; text-decoration: none;
    color: var(--text); border: 1px solid var(--border); border-radius: var(--radius, 10px); padding: 12px 16px;
    background: var(--surface, transparent); transition: border-color .15s ease; }
  .lyra-ad a.lyra-ad-card:hover { border-color: var(--border-hi, var(--text)); }
  .lyra-ad small { flex-basis: 100%; font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .08em; }
  .lyra-ad b { font-weight: 600; }
  .lyra-ad span { color: var(--muted); font-size: 14px; }
  .lyra-ad .cta { color: var(--text); font-weight: 600; white-space: nowrap; }
  .lyra-ad .net { border: 1px solid var(--border); border-radius: var(--radius, 10px); padding: 8px 10px 10px; overflow: hidden; }
  .lyra-ad .net small { display: block; margin-bottom: 6px; }
  .lyra-ad:has(ins[data-ad-status="unfilled"]) { display: none; }`;

  const el = (tag, attrs, ...kids) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) if (v != null && v !== "") n.setAttribute(k, v);
    for (const c of kids) n.append(c);
    return n;
  };
  const text = (tag, attrs, t) => { const n = el(tag, attrs); n.textContent = t; return n; };

  function card(ad) {
    const sponsor = ad.kind === "sponsor";
    return el("a", { class: "lyra-ad-card", href: ad.url, rel: sponsor ? "sponsored noopener" : null, target: sponsor ? "_blank" : null },
      text("small", {}, ad.label), text("b", {}, ad.headline), text("span", {}, ad.body), text("span", { class: "cta" }, `${ad.cta} →`));
  }

  function network(ad, box) {
    const ins = el("ins", { class: "adsbygoogle", style: "display:block", "data-ad-client": ad.client,
      "data-ad-slot": ad.slot, "data-ad-format": "auto", "data-full-width-responsive": "true" });
    box.append(el("div", { class: "net" }, text("small", {}, ad.label), ins));
    if (!document.querySelector('script[src*="adsbygoogle.js"]')) {
      document.head.append(el("script", { async: "", crossorigin: "anonymous",
        src: `https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${encodeURIComponent(ad.client)}` }));
    }
    try { (window.adsbygoogle = window.adsbygoogle || []).push({}); } catch { box.hidden = true; }
  }

  async function fill(box) {
    try {
      const r = await fetch(`/api/ads/slot?place=${encodeURIComponent(box.dataset.lyraAd || "watch")}`, { credentials: "same-origin" });
      if (!r.ok) return;
      const ad = await r.json();
      if (!ad || ad.kind === "none") return;
      box.classList.add("lyra-ad");
      box.setAttribute("aria-label", ad.label);
      if (ad.kind === "network") network(ad, box); else box.replaceChildren(card(ad));
      box.hidden = false;
    } catch {}
  }

  function start() {
    const boxes = document.querySelectorAll("[data-lyra-ad]");
    if (!boxes.length) return;
    document.head.append(text("style", {}, CSS));
    boxes.forEach(fill);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
