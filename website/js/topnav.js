/* The signed-in tab menu: a dark bar across the top of member pages with every place Lyra
   offers (Products, How it works, Integrate, Pricing, Tremor Index, Watch, Live, Docs) and a
   Settings menu for the account. Include after session.js and put data-appnav="drawer" on
   <body>, so appnav.js still adds the Ctrl/⌘+K quick jump. Elements marked
   [data-appnav-hide] (a page's old header) are hidden once the bar is up. */
(function () {
  if (!window.lyraSignedIn || window.lyraTopNav) return;
  window.lyraTopNav = true;

  var PRODUCTS = [
    ['/market', 'Tremor Index', 'Market-stress readings and the news behind them', 'M4 19V5M4 19h16M8 15l3-4 3 2 5-6'],
    ['/dashboard/chat.html', 'Lyra chat', 'Ask anything; it searches the web when needed', 'M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z'],
    ['/watch/live/', 'Watch Live', 'Real-time stream of who is moving markets', 'M12 12m-2 0a2 2 0 1 0 4 0 2 2 0 1 0-4 0M7.8 7.8a6 6 0 0 0 0 8.4M16.2 16.2a6 6 0 0 0 0-8.4'],
    ['/watch/', 'Watch directory', 'Every public figure we track', 'M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM2 21a7 7 0 0 1 14 0M17 11a3 3 0 1 0 0-6M22 21a5 5 0 0 0-4-5'],
    ['/labs/', 'Lyra Labs', 'Your AI and ours: co-scientist, agents, translator', 'M9 3h6M10 3v6L4.5 18.5A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.5-2.5L14 9V3M7.5 15h9'],
    ['/news/', 'Newswire', 'Global news and new research, with filters', 'M4 5h13v14H6a2 2 0 0 1-2-2zM17 9h3v8a2 2 0 0 1-2 2M8 9h5M8 13h5'],
    ['/dashboard/', 'LyraAuth sites', 'Your sites, keys, usage and training data', 'M12 3l8 3v6c0 5-3.4 8.4-8 9-4.6-.6-8-4-8-9V6zM9 12l2 2 4-4'],
  ];
  var TABS = [
    ['/', 'Overview', /^\/(home\/?)?$/],
    ['#products', 'Products', null],
    ['/index.html#how-it-works', 'How it works', null],
    ['/index.html#integrate', 'Integrate', null],
    ['/news/', 'News', /^\/news/],
    ['/dashboard/billing.html', 'Pricing', /billing\.html$/],
    ['/tremor/', 'Tremor Index', /^\/(tremor|market)/],
    ['/watch/', 'Watch', /^\/watch\/?$/],
    ['/watch/live/', 'Live', /^\/watch\/live/],
    ['/pages/docs.html', 'Docs', /docs\.html$/],
  ];
  var SETTINGS = [
    ['/account/', 'Account & security', 'Profile, password, signed-in browsers'],
    ['/account/#links', 'Connected accounts', 'Google, Apple and GitHub sign-in'],
    ['/labs/', 'Lyra Labs', 'Plug in your AI, pair it with ours'],
    ['/dashboard/billing.html', 'Billing & plan', 'Change plan, invoices, cancel'],
    ['/watch/account/', 'API keys & credits', 'Watch Pro, keys for agents'],
    ['/feedback/', 'Send feedback', 'Ideas, bugs, praise'],
    ['mailto:support@lyraauth.com', 'Help & support', 'support@lyraauth.com'],
  ];
  var esc = function (s) { return String(s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };
  var svg = function (d, w) { return '<svg viewBox="0 0 24 24" width="' + (w || 18) + '" height="' + (w || 18) + '" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="' + d + '"/></svg>'; };
  var CHEV = 'M6 9l6 6 6-6';

  var CSS = '' +
    '.tn{position:sticky;top:0;z-index:950;background:#14120e;color:#faf9f7;font:14px/1.2 Inter,system-ui,-apple-system,sans-serif;' +
      'background-image:radial-gradient(600px 120px at 100% 0,rgba(225,29,72,.28),transparent 70%),radial-gradient(500px 120px at 0 100%,rgba(180,83,9,.18),transparent 70%);border-bottom:1px solid rgba(250,249,247,.08)}' +
    '.tn-in{max-width:1240px;margin:0 auto;height:60px;padding:0 20px;display:flex;align-items:center;gap:18px}' +
    '.tn-brand{display:flex;align-items:center;gap:9px;font-weight:600;font-size:15px;color:#faf9f7;text-decoration:none;flex:none}' +
    '.tn-brand img{width:26px;height:26px;border-radius:7px;box-shadow:0 0 0 1px rgba(250,249,247,.16)}' +
    '.tn-tabs{display:flex;align-items:center;gap:2px;flex:1;min-width:0}' +
    '.tn-tab{position:relative;display:inline-flex;align-items:center;gap:5px;padding:8px 11px;border-radius:8px;color:rgba(250,249,247,.72);text-decoration:none;background:none;border:0;font:inherit;cursor:pointer;white-space:nowrap;transition:color .15s,background .15s}' +
    '.tn-tab:hover,.tn-tab[aria-expanded=true]{color:#faf9f7;background:rgba(250,249,247,.07);opacity:1}' +
    '.tn-tab[aria-current=page]{color:#14120e;background:#faf9f7}' +
    '.tn-tab svg{opacity:.7;transition:transform .2s}.tn-tab[aria-expanded=true] svg{transform:rotate(180deg)}' +
    '.tn-live{display:inline-block;width:7px;height:7px;border-radius:50%;background:#fb7185;box-shadow:0 0 0 0 rgba(251,113,133,.6);animation:tnp 1.8s infinite}' +
    '@keyframes tnp{70%{box-shadow:0 0 0 7px rgba(251,113,133,0)}100%{box-shadow:0 0 0 0 rgba(251,113,133,0)}}' +
    '.tn-right{display:flex;align-items:center;gap:8px;flex:none}' +
    '.tn-find{display:inline-flex;align-items:center;gap:8px;padding:7px 10px;border:1px solid rgba(250,249,247,.14);border-radius:9px;background:rgba(250,249,247,.04);color:rgba(250,249,247,.6);font:inherit;font-size:13px;cursor:pointer}' +
    '.tn-find:hover{color:#faf9f7;border-color:rgba(250,249,247,.3)}' +
    '.tn-find kbd{font:11px "JetBrains Mono",ui-monospace,monospace;opacity:.75}' +
    '.tn-me{display:inline-flex;align-items:center;gap:8px;padding:4px 8px 4px 4px;border-radius:999px;border:1px solid rgba(250,249,247,.14);background:none;color:#faf9f7;font:inherit;font-size:13px;cursor:pointer}' +
    '.tn-me:hover,.tn-me[aria-expanded=true]{border-color:rgba(250,249,247,.35)}' +
    '.tn-av{width:28px;height:28px;border-radius:50%;background:#fb7185;color:#14120e;display:grid;place-items:center;font-weight:700;font-size:12.5px}' +
    '.tn-pop{position:absolute;top:calc(100% + 8px);background:#fff;color:#14120e;border-radius:14px;box-shadow:0 24px 60px -12px rgba(20,18,14,.45),0 0 0 1px rgba(20,18,14,.06);padding:8px;display:none;animation:tnin .16s ease}' +
    '.tn-pop.open{display:block}@keyframes tnin{from{opacity:0;transform:translateY(-4px)}}' +
    '.tn-mega{left:0;width:min(640px,92vw);display:none;grid-template-columns:1fr 1fr;gap:4px}.tn-mega.open{display:grid}' +
    '.tn-set{right:0;width:300px}' +
    '.tn-pop a{display:flex;gap:12px;align-items:flex-start;padding:11px 12px;border-radius:10px;text-decoration:none;color:#14120e}' +
    '.tn-pop a:hover,.tn-pop a:focus-visible{background:#f3f1ed;opacity:1;outline:none}' +
    '.tn-pop a .ic{flex:none;width:34px;height:34px;border-radius:9px;background:#14120e;color:#faf9f7;display:grid;place-items:center}' +
    '.tn-pop b{display:block;font-size:14px;font-weight:600}.tn-pop small{display:block;color:#6e6b67;font-size:12.5px;margin-top:2px;line-height:1.4}' +
    '.tn-who{padding:12px 12px 10px;border-bottom:1px solid rgba(20,18,14,.08);margin-bottom:6px}' +
    '.tn-who b{font-size:14px}.tn-who small{word-break:break-all}' +
    '.tn-out{width:100%;margin-top:6px;padding:10px 12px;border:0;border-top:1px solid rgba(20,18,14,.08);background:none;text-align:left;font:600 13.5px Inter,system-ui,sans-serif;color:#be123c;cursor:pointer;border-radius:0 0 8px 8px}' +
    '.tn-out:hover{background:#fff1f2}' +
    '.tn-burger{display:none;background:none;border:1px solid rgba(250,249,247,.18);color:#faf9f7;border-radius:8px;padding:7px;cursor:pointer}' +
    '.tn-sheet{display:none;position:fixed;inset:60px 0 0;z-index:949;background:#14120e;color:#faf9f7;overflow:auto;padding:12px 16px 40px}' +
    '.tn-sheet.open{display:block}' +
    '.tn-sheet h6{font:600 10.5px "JetBrains Mono",monospace;letter-spacing:.14em;text-transform:uppercase;color:rgba(250,249,247,.5);margin:18px 4px 8px}' +
    '.tn-sheet a{display:block;padding:12px 8px;border-bottom:1px solid rgba(250,249,247,.08);color:#faf9f7;text-decoration:none;font-size:15px}' +
    '.tn a:focus-visible,.tn button:focus-visible{outline:2px solid #fb7185;outline-offset:2px}' +
    '@media (max-width:1180px){.tn-tab.tn-opt{display:none}}' +
    '@media (max-width:860px){.tn-tabs,.tn-find{display:none}.tn-burger{display:inline-flex}.tn-in{justify-content:space-between}}' +
    '@media (prefers-reduced-motion:reduce){.tn-live,.tn-pop{animation:none}}';

  function build() {
    var style = document.createElement('style');
    style.textContent = CSS;
    document.head.appendChild(style);
    var path = location.pathname;
    var mac = /Mac|iPhone|iPad/.test(navigator.platform);

    var tabs = TABS.map(function (t, i) {
      if (t[1] === 'Products') {
        return '<div style="position:relative"><button class="tn-tab" type="button" aria-expanded="false" aria-controls="tn-products" data-pop="tn-products">Products' + svg(CHEV, 14) + '</button>' +
          '<div class="tn-pop tn-mega" id="tn-products" role="menu">' + PRODUCTS.map(function (p) {
            return '<a role="menuitem" href="' + p[0] + '"><span class="ic">' + svg(p[3]) + '</span><span><b>' + esc(p[1]) + '</b><small>' + esc(p[2]) + '</small></span></a>';
          }).join('') + '</div></div>';
      }
      var current = t[2] && t[2].test(path);
      var optional = i >= 2 && i <= 3 ? ' tn-opt' : '';
      var label = t[1] === 'Live' ? '<span class="tn-live"></span>Live' : esc(t[1]);
      return '<a class="tn-tab' + optional + '" href="' + t[0] + '"' + (current ? ' aria-current="page"' : '') + '>' + label + '</a>';
    }).join('');

    var nav = document.createElement('header');
    nav.className = 'tn';
    nav.innerHTML = '<div class="tn-in">' +
      '<a class="tn-brand" href="/"><img src="/img/logo-mark.svg" alt="" />Lyra</a>' +
      '<nav class="tn-tabs" aria-label="Lyra">' + tabs + '</nav>' +
      '<div class="tn-right">' +
        '<button class="tn-find" type="button" id="tn-find">' + svg('M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-4.3-4.3', 15) + 'Jump to<kbd>' + (mac ? '⌘K' : 'Ctrl K') + '</kbd></button>' +
        '<div style="position:relative"><button class="tn-me" type="button" aria-expanded="false" aria-controls="tn-settings" data-pop="tn-settings" aria-label="Settings and account"><span class="tn-av" id="tn-av">✦</span><span>Settings</span>' + svg(CHEV, 14) + '</button>' +
          '<div class="tn-pop tn-set" id="tn-settings" role="menu"><div class="tn-who"><b id="tn-name">Your account</b><small id="tn-email"></small></div>' +
          SETTINGS.map(function (s) { return '<a role="menuitem" href="' + s[0] + '"><span><b>' + esc(s[1]) + '</b><small>' + esc(s[2]) + '</small></span></a>'; }).join('') +
          '<button class="tn-out" type="button" id="tn-out">Sign out</button></div></div>' +
        '<button class="tn-burger" type="button" aria-label="Open menu" aria-expanded="false" id="tn-burger">' + svg('M4 7h16M4 12h16M4 17h16', 20) + '</button>' +
      '</div></div>';

    var sheet = document.createElement('div');
    sheet.className = 'tn-sheet';
    sheet.innerHTML = '<h6>Explore</h6>' + TABS.filter(function (t) { return t[1] !== 'Products'; }).map(function (t) { return '<a href="' + t[0] + '">' + esc(t[1]) + '</a>'; }).join('') +
      '<h6>Products</h6>' + PRODUCTS.map(function (p) { return '<a href="' + p[0] + '">' + esc(p[1]) + '</a>'; }).join('') +
      '<h6>Settings</h6>' + SETTINGS.map(function (s) { return '<a href="' + s[0] + '">' + esc(s[1]) + '</a>'; }).join('') +
      '<a href="#" id="tn-out2" style="color:#fb7185">Sign out</a>';

    document.body.prepend(sheet);
    document.body.prepend(nav);
    document.querySelectorAll('[data-appnav-hide]').forEach(function (el) { el.style.display = 'none'; });
    var pill = document.getElementById('lyra-home-pill');
    if (pill) pill.remove();

    function closeAll(except) {
      nav.querySelectorAll('[data-pop]').forEach(function (b) {
        if (b === except) return;
        b.setAttribute('aria-expanded', 'false');
        document.getElementById(b.getAttribute('data-pop')).classList.remove('open');
      });
    }
    nav.querySelectorAll('[data-pop]').forEach(function (b) {
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        var pop = document.getElementById(b.getAttribute('data-pop'));
        var open = !pop.classList.contains('open');
        closeAll(b);
        pop.classList.toggle('open', open);
        b.setAttribute('aria-expanded', String(open));
        if (open) { var first = pop.querySelector('a'); if (first) first.focus(); }
      });
    });
    document.addEventListener('click', function (e) { if (!e.target.closest('.tn-pop')) closeAll(); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') { closeAll(); sheet.classList.remove('open'); } });
    document.getElementById('tn-find').addEventListener('click', function () { if (window.lyraPalette) window.lyraPalette(true); });
    var burger = document.getElementById('tn-burger');
    burger.addEventListener('click', function () { var on = !sheet.classList.contains('open'); sheet.classList.toggle('open', on); burger.setAttribute('aria-expanded', String(on)); });
    function out(e) { e.preventDefault(); window.lyraSignOut('/'); }
    document.getElementById('tn-out').addEventListener('click', out);
    document.getElementById('tn-out2').addEventListener('click', out);

    fetch('/api/users/me', { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : null; }).then(function (me) {
      if (!me) return;
      document.getElementById('tn-name').textContent = me.name || me.email.split('@')[0];
      document.getElementById('tn-email').textContent = me.email;
      document.getElementById('tn-av').textContent = (me.name || me.email).trim().charAt(0).toUpperCase();
      // The owner's own menu entry.
      fetch('/api/admin/overview', { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : null; }).then(function (o) {
        if (!o) return;
        var link = document.createElement('a');
        link.setAttribute('role', 'menuitem');
        link.href = '/admin/';
        link.innerHTML = '<span><b>Admin' + (o.ads.waiting_for_approval ? ' \u00b7 ' + o.ads.waiting_for_approval + ' ad' + (o.ads.waiting_for_approval === 1 ? '' : 's') + ' to approve' : '') + '</b><small>Ads, feedback, accounts, systems</small></span>';
        var who = document.querySelector('#tn-settings .tn-who');
        who.after(link);
      }).catch(function () {});
    }).catch(function () {});
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', build);
  else build();
})();
