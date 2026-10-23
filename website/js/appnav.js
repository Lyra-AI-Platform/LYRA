/* The signed-in menu: one sidebar on every member page listing everything Lyra offers.
   Include after session.js. Wide screens get a fixed rail; narrow screens a top bar with a
   drawer. <body data-appnav="drawer"> (full-screen pages such as chat) keeps the page's own
   layout and only adds the drawer, opened by any [data-appnav-toggle] button or Ctrl/⌘+K.
   Anything marked [data-appnav-hide] (a page's old top bar) is hidden once the menu is up.
   Locks on products come from /api/billing/status and /api/watch/account; the server still
   decides access (lyra/api/page_access.py), these are only hints. */
(function () {
  if (!window.lyraSignedIn || window.lyraAppNav) return;
  window.lyraAppNav = true;

  var GROUPS = [
    ['', [
      { href: '/', ico: 'home', name: 'Overview', match: /^\/(home\/?)?$/ },
    ]],
    ['Products', [
      { href: '/market', ico: 'chart', name: 'Tremor Index', need: 'member', match: /^\/market/ },
      { href: '/dashboard/chat.html', ico: 'chat', name: 'Lyra chat', need: 'member', match: /chat\.html$/ },
      { href: '/watch/live/', ico: 'live', name: 'Watch Live', need: 'watch', match: /^\/watch\/live/ },
      { href: '/watch/', ico: 'people', name: 'Watch directory', match: /^\/watch\/?$/ },
      { href: '/news/', ico: 'book', name: 'Newswire', match: /^\/news/ },
      { href: '/dashboard/', ico: 'shield', name: 'LyraAuth sites', match: /^\/dashboard\/(index\.html)?$/ },
    ]],
    ['Developers', [
      { href: '/watch/account/', ico: 'key', name: 'API keys & credits', match: /^\/watch\/account/ },
      { href: '/pages/docs.html', ico: 'book', name: 'Documentation', match: /docs\.html$/ },
      { href: '/tremor/', ico: 'pulse', name: 'Tremor methodology', match: /^\/tremor/ },
    ]],
    ['Account', [
      { href: '/account/', ico: 'lock', name: 'Account & security', match: /^\/account/ },
      { href: '/dashboard/billing.html', ico: 'card', name: 'Billing & plan', match: /billing\.html$/ },
      { href: '/advertise/', ico: 'megaphone', name: 'Advertise', match: /^\/advertise/ },
      { href: '/feedback/', ico: 'chat', name: 'Send feedback', match: /^\/feedback/ },
      { href: 'mailto:support@lyraauth.com', ico: 'help', name: 'Help & support' },
    ]],
  ];

  var P = {
    home: 'M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z',
    chart: 'M4 19V5M4 19h16M8 15l3-4 3 2 5-6',
    chat: 'M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z',
    live: 'M12 12m-2 0a2 2 0 1 0 4 0 2 2 0 1 0-4 0M7.8 7.8a6 6 0 0 0 0 8.4M16.2 16.2a6 6 0 0 0 0-8.4M5 5a10 10 0 0 0 0 14M19 19a10 10 0 0 0 0-14',
    people: 'M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM2 21a7 7 0 0 1 14 0M17 11a3 3 0 1 0 0-6M22 21a5 5 0 0 0-4-5',
    flask: 'M9 3h6M10 3v6L4.5 18.5A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.5-2.5L14 9V3M7.5 15h9',
    shield: 'M12 3l8 3v6c0 5-3.4 8.4-8 9-4.6-.6-8-4-8-9V6zM9 12l2 2 4-4',
    key: 'M15 7a4 4 0 1 1-3.9 4.9L4 19v2h3v-2h2v-2h2l1.1-1.1A4 4 0 0 1 15 7zM16 9h.01',
    book: 'M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2zM4 21V5M8 7h7',
    pulse: 'M3 12h4l3-8 4 16 3-8h4',
    lock: 'M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0v4',
    card: 'M3 6h18v12H3zM3 10h18M7 15h3',
    megaphone: 'M3 10v4l11 5V5zM14 8a4 4 0 0 1 0 8M6 14l1 6',
    help: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .9-1 1.7M12 17h.01',
    out: 'M15 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4M10 17l5-5-5-5M15 12H3',
    globe: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18',
    menu: 'M4 7h16M4 12h16M4 17h16',
    x: 'M6 6l12 12M18 6L6 18',
    search: 'M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-4.3-4.3',
  };
  function icon(name) {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="' + P[name] + '"/></svg>';
  }
  var esc = function (s) { return String(s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };

  var CSS = '' +
    ':root{--an-w:252px;--an-ink:#14120e;--an-paper:#faf9f7;--an-rule:rgba(250,249,247,.09);--an-dim:rgba(250,249,247,.55)}' +
    '.an{position:fixed;inset:0 auto 0 0;width:var(--an-w);z-index:900;display:flex;flex-direction:column;background:var(--an-ink);color:var(--an-paper);' +
      'font:14px/1.3 Inter,system-ui,-apple-system,sans-serif;transform:translateX(-100%);transition:transform .25s cubic-bezier(.2,.7,.2,1);' +
      'background-image:radial-gradient(400px 300px at 120% -10%,rgba(225,29,72,.22),transparent 60%),radial-gradient(300px 300px at -30% 110%,rgba(180,83,9,.2),transparent 60%)}' +
    '.an.open{transform:none;box-shadow:0 0 60px rgba(0,0,0,.35)}' +
    '.an-head{display:flex;align-items:center;justify-content:space-between;padding:18px 18px 12px}' +
    '.an-brand{font-weight:600;font-size:15px;color:var(--an-paper);text-decoration:none}' +
    '.an-x{display:inline-flex;background:none;border:0;color:var(--an-dim);padding:6px;border-radius:7px;cursor:pointer}' +
    '.an-x svg,.an a svg,.an button svg{width:17px;height:17px;flex:none}' +
    '.an-find{margin:4px 12px 8px;display:flex;align-items:center;gap:8px;padding:8px 10px;border:1px solid var(--an-rule);border-radius:9px;color:var(--an-dim);background:rgba(250,249,247,.04);cursor:pointer;font:inherit;font-size:13px;text-align:left}' +
    '.an-find:hover{border-color:rgba(250,249,247,.25);color:var(--an-paper)}' +
    '.an-find kbd{margin-left:auto;font:11px "JetBrains Mono",ui-monospace,monospace;opacity:.7}' +
    '.an-scroll{flex:1;overflow-y:auto;padding:4px 10px 12px}' +
    '.an h6{font:600 10.5px/1 "JetBrains Mono",ui-monospace,monospace;letter-spacing:.14em;text-transform:uppercase;color:var(--an-dim);margin:18px 10px 8px}' +
    '.an-item{display:flex;align-items:center;gap:11px;padding:8px 10px;border-radius:8px;color:rgba(250,249,247,.82);text-decoration:none;transition:background .12s,color .12s}' +
    '.an-item:hover{background:rgba(250,249,247,.07);color:var(--an-paper);opacity:1}' +
    '.an-item[aria-current=page]{background:var(--an-paper);color:var(--an-ink)}' +
    '.an-item .an-lock{margin-left:auto;font:10.5px "JetBrains Mono",monospace;color:#fbbf24;letter-spacing:.04em}' +
    '.an-item[aria-current=page] .an-lock{color:#b45309}' +
    '.an-item:focus-visible,.an-find:focus-visible,.an-x:focus-visible,.an-bar button:focus-visible{outline:2px solid #fb7185;outline-offset:2px}' +
    '.an-foot{border-top:1px solid var(--an-rule);padding:12px}' +
    '.an-me{display:flex;align-items:center;gap:10px;padding:6px 6px 10px}' +
    '.an-av{width:32px;height:32px;border-radius:50%;background:#fb7185;color:var(--an-ink);display:grid;place-items:center;font-weight:700;font-size:13px;flex:none}' +
    '.an-me b{display:block;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:160px}' +
    '.an-me small{display:block;font-size:11.5px;color:var(--an-dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:160px}' +
    '.an-row{display:flex;gap:6px}' +
    '.an-row a,.an-row button{flex:1;display:flex;align-items:center;justify-content:center;gap:7px;padding:8px;border-radius:8px;border:1px solid var(--an-rule);background:none;color:rgba(250,249,247,.82);font:500 12.5px/1 inherit;font-family:inherit;text-decoration:none;cursor:pointer}' +
    '.an-row a:hover,.an-row button:hover{border-color:rgba(250,249,247,.3);color:var(--an-paper);opacity:1}' +
    '.an-bar{position:sticky;top:0;z-index:800;display:flex;align-items:center;gap:10px;height:54px;padding:0 12px;background:rgba(250,249,247,.92);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);border-bottom:1px solid rgba(20,18,14,.08)}' +
    '.an-bar button{display:inline-flex;align-items:center;gap:8px;background:none;border:1px solid rgba(20,18,14,.15);border-radius:8px;padding:7px 10px;font:600 13px/1 Inter,system-ui,sans-serif;color:#14120e;cursor:pointer}' +
    '.an-bar button svg{width:17px;height:17px}' +
    '.an-bar a{font:600 15px Inter,system-ui,sans-serif;color:#14120e;text-decoration:none}' +
    '.an-shade{position:fixed;inset:0;z-index:850;background:rgba(20,18,14,.4);opacity:0;pointer-events:none;transition:opacity .2s}' +
    '.an-shade.open{opacity:1;pointer-events:auto}' +
    '[data-appnav-toggle] svg{width:16px;height:16px;vertical-align:-3px}' +
    '@media (min-width:1024px){body.an-rail{padding-left:var(--an-w)}body.an-rail .an{transform:none}body.an-rail .an-x,body.an-rail .an-bar{display:none}body.an-rail .an-shade{display:none}}' +
    '.an-pal{position:fixed;inset:0;z-index:1000;display:none;align-items:flex-start;justify-content:center;padding:12vh 16px 16px;background:rgba(20,18,14,.45)}' +
    '.an-pal.open{display:flex}' +
    '.an-pal-box{width:100%;max-width:520px;background:#fff;border-radius:14px;box-shadow:0 30px 80px rgba(0,0,0,.35);overflow:hidden;font:14px Inter,system-ui,sans-serif;color:#14120e;animation:anpop .18s ease}' +
    '@keyframes anpop{from{opacity:0;transform:translateY(-6px) scale(.98)}}' +
    '.an-pal input{width:100%;border:0;border-bottom:1px solid rgba(20,18,14,.1);padding:16px 18px;font:16px Inter,system-ui,sans-serif;outline:none}' +
    '.an-pal ul{list-style:none;margin:0;padding:6px;max-height:50vh;overflow:auto}' +
    '.an-pal li a{display:flex;align-items:center;gap:12px;padding:10px 12px;border-radius:8px;color:#14120e;text-decoration:none}' +
    '.an-pal li a svg{width:17px;height:17px;color:#6e6b67}' +
    '.an-pal li a small{margin-left:auto;color:#a8a5a0;font-size:11.5px}' +
    '.an-pal li.sel a{background:#f3f1ed}' +
    '@media (prefers-reduced-motion:reduce){.an,.an-shade{transition:none}.an-pal-box{animation:none}}';

  var drawerOnly = document.body.getAttribute('data-appnav') === 'drawer';
  var path = location.pathname;
  var ITEMS = [];
  GROUPS.forEach(function (g) { g[1].forEach(function (it) { it.group = g[0] || 'Lyra'; ITEMS.push(it); }); });

  function build() {
    var style = document.createElement('style');
    style.textContent = CSS;
    document.head.appendChild(style);

    var nav = document.createElement('nav');
    nav.className = 'an';
    nav.id = 'lyra-appnav';
    nav.setAttribute('aria-label', 'Lyra menu');
    var html = '<div class="an-head"><a class="an-brand" href="/"><img src="/img/logo-mark.svg" alt="" width="24" height="24" style="vertical-align:-6px;margin-right:8px;border-radius:6px;box-shadow:0 0 0 1px rgba(250,249,247,.18)" />Lyra</a><button class="an-x" type="button" aria-label="Close menu">' + icon('x') + '</button></div>' +
      '<button class="an-find" type="button">' + icon('search') + '<span>Jump to…</span><kbd>' + (/Mac|iPhone|iPad/.test(navigator.platform) ? '⌘K' : 'Ctrl K') + '</kbd></button><div class="an-scroll">';
    GROUPS.forEach(function (g) {
      if (g[0]) html += '<h6>' + esc(g[0]) + '</h6>';
      g[1].forEach(function (it) {
        var current = it.match && it.match.test(path);
        html += '<a class="an-item" href="' + esc(it.href) + '"' + (current ? ' aria-current="page"' : '') + (it.need ? ' data-need="' + it.need + '"' : '') + '>' + icon(it.ico) + '<span>' + esc(it.name) + '</span></a>';
      });
    });
    html += '</div><div class="an-foot"><div class="an-me"><span class="an-av" id="an-av">✦</span><div><b id="an-name">Signed in</b><small id="an-email"></small></div></div>' +
      '<div class="an-row"><a href="/index.html">' + icon('globe') + 'Website</a><button type="button" id="an-out">' + icon('out') + 'Sign out</button></div></div>';
    nav.innerHTML = html;

    var shade = document.createElement('div');
    shade.className = 'an-shade';
    document.body.prepend(shade);
    document.body.prepend(nav);

    if (!drawerOnly) {
      var bar = document.createElement('div');
      bar.className = 'an-bar';
      bar.innerHTML = '<button type="button" data-appnav-toggle aria-controls="lyra-appnav" aria-expanded="false">' + icon('menu') + 'Menu</button><a href="/">✦ Lyra</a>';
      nav.after(bar);
      document.body.classList.add('an-rail');
      document.querySelectorAll('[data-appnav-hide]').forEach(function (el) { el.style.display = 'none'; });
    }

    function setOpen(on) {
      nav.classList.toggle('open', on);
      shade.classList.toggle('open', on);
      document.querySelectorAll('[data-appnav-toggle]').forEach(function (b) { b.setAttribute('aria-expanded', String(on)); });
      if (on) { var f = nav.querySelector('[aria-current=page]') || nav.querySelector('.an-item'); if (f) f.focus(); }
    }
    document.addEventListener('click', function (e) {
      if (e.target.closest('[data-appnav-toggle]')) { e.preventDefault(); setOpen(!nav.classList.contains('open')); }
    });
    shade.addEventListener('click', function () { setOpen(false); });
    nav.querySelector('.an-x').addEventListener('click', function () { setOpen(false); });
    nav.querySelector('.an-find').addEventListener('click', function () { setOpen(false); palette(true); });
    document.getElementById('an-out').addEventListener('click', function () { window.lyraSignOut('/'); });
    document.addEventListener('keydown', function (e) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); palette(true); }
      else if (e.key === 'Escape') { setOpen(false); palette(false); }
    });

    // Quick jump: type part of a name, Enter to go.
    var pal = document.createElement('div');
    pal.className = 'an-pal';
    pal.setAttribute('role', 'dialog');
    pal.setAttribute('aria-modal', 'true');
    pal.setAttribute('aria-label', 'Jump to');
    pal.innerHTML = '<div class="an-pal-box"><input type="search" placeholder="Jump to a product or page…" aria-label="Search the menu" /><ul role="listbox"></ul></div>';
    document.body.appendChild(pal);
    var input = pal.querySelector('input'), list = pal.querySelector('ul'), sel = 0, shown = [];
    function render() {
      var q = input.value.trim().toLowerCase();
      shown = ITEMS.filter(function (it) { return !q || (it.name + ' ' + it.group).toLowerCase().indexOf(q) !== -1; });
      sel = Math.min(sel, Math.max(shown.length - 1, 0));
      list.innerHTML = shown.map(function (it, i) {
        return '<li role="option"' + (i === sel ? ' class="sel" aria-selected="true"' : '') + '><a href="' + esc(it.href) + '">' + icon(it.ico) + esc(it.name) + '<small>' + esc(it.group) + '</small></a></li>';
      }).join('') || '<li style="padding:14px;color:#6e6b67">Nothing matches.</li>';
    }
    function palette(on) {
      pal.classList.toggle('open', on);
      if (on) { input.value = ''; sel = 0; render(); input.focus(); }
    }
    window.lyraPalette = palette;
    input.addEventListener('input', function () { sel = 0; render(); });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { sel = Math.min(sel + 1, shown.length - 1); render(); e.preventDefault(); }
      else if (e.key === 'ArrowUp') { sel = Math.max(sel - 1, 0); render(); e.preventDefault(); }
      else if (e.key === 'Enter' && shown[sel]) { location.href = shown[sel].href; }
    });
    pal.addEventListener('click', function (e) { if (e.target === pal) palette(false); });
  }

  function fillIn() {
    fetch('/api/users/me', { credentials: 'same-origin' }).then(function (r) {
      if (r.status === 401) { window.lyraSignOut('/dashboard/login.html'); return null; }
      return r.ok ? r.json() : null;
    }).then(function (me) {
      if (!me) return;
      document.getElementById('an-name').textContent = me.name || me.email.split('@')[0];
      document.getElementById('an-email').textContent = me.email;
      document.getElementById('an-av').textContent = (me.name || me.email).trim().charAt(0).toUpperCase();
    }).catch(function () {});
    Promise.all([
      fetch('/api/billing/status', { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }),
      fetch('/api/watch/account', { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }),
    ]).then(function (res) {
      var bill = res[0], watch = res[1];
      if (!bill) return;
      var member = bill.paid || (bill.trial && !bill.trial.expired);
      var watchOn = !!(watch && watch.watch_pro) || !!bill.paid;
      document.querySelectorAll('.an-item[data-need]').forEach(function (a) {
        var need = a.getAttribute('data-need');
        var locked = need === 'member' ? !member : need === 'watch' ? !watchOn : false;
        if (!locked) return;
        var tag = document.createElement('span');
        tag.className = 'an-lock';
        tag.textContent = 'Upgrade';
        a.appendChild(tag);
      });
    });
  }

  function go() { build(); fillIn(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', go);
  else go();
})();
