/* The same main menu on every public page. Signed-in pages get the fuller bar from topnav.js. */
(function () {
  var LINKS = [['/news/', 'News'], ['/watch/live/', 'Live'], ['/tremor/', 'Tremor Index'], ['/watch/', 'Watch'],
    ['/watch/account/', 'Watch Pro'], ['/pricing/', 'Pricing']];

  function list() {
    var ul = document.createElement('ul');
    ul.className = 'nav-links';
    LINKS.forEach(function (l) {
      var li = document.createElement('li'), a = document.createElement('a');
      a.href = l[0]; a.textContent = l[1];
      if (location.pathname === l[0]) a.setAttribute('aria-current', 'page');
      li.append(a); ul.append(li);
    });
    return ul;
  }

  // Show as many links as fit between the logo and the page's own buttons; the rest go under "More".
  var STYLE = '.nav .nav-inner{gap:12px}.nav .nav-links.sn-fit{flex:1 1 auto;min-width:0;flex-wrap:nowrap;overflow:visible;align-items:center;justify-content:center}.sn-fit>li{display:flex;align-items:center}.sn-fit>li[hidden]{display:none}' +
    '.sn-fit>li{flex:none}.sn-fit>li>a{line-height:1.4}.sn-more{position:relative}.sn-more>button{display:inline-flex;align-items:center;gap:4px;background:none;border:0;font-family:inherit;font-size:.875rem;font-weight:450;line-height:inherit;color:rgba(250,249,247,.72);cursor:pointer;padding:6px 9px;border-radius:6px;white-space:nowrap}' +
    '.sn-more>button:hover,.sn-more>button[aria-expanded=true]{color:#faf9f7;background:rgba(250,249,247,.08)}.sn-menu{display:none;position:absolute;top:calc(100% + 8px);left:0;min-width:200px;padding:6px;border-radius:12px;' +
    'background:#14120e;border:1px solid rgba(250,249,247,.14);box-shadow:0 12px 32px rgba(0,0,0,.35);list-style:none;margin:0;z-index:300}.sn-menu.open{display:block}' +
    '.sn-menu a{display:block;padding:9px 12px;border-radius:8px;color:#faf9f7!important;text-decoration:none;white-space:nowrap}.sn-menu a:hover{background:rgba(250,249,247,.08)}';

  function fit(ul) {
    var items = [].slice.call(ul.querySelectorAll(':scope>li:not(.sn-more)'));
    var more = ul.querySelector(':scope>.sn-more'), menu = more.querySelector('.sn-menu');
    items.forEach(function (li) { li.hidden = false; });
    menu.innerHTML = '';
    more.hidden = true;
    var cta = ul.parentNode.querySelector('.nav-cta, .nav-hamburger');
    function overflowing() {
      var r = ul.getBoundingClientRect();
      var limit = cta ? cta.getBoundingClientRect().left - 8 : ul.parentNode.getBoundingClientRect().right;
      var shown = [].slice.call(ul.children).filter(function (c) { return !c.hidden; });
      if (!r.width || !shown.length) return false;
      return shown[shown.length - 1].getBoundingClientRect().right > Math.min(r.right, limit) + 0.5 || shown[0].getBoundingClientRect().left < r.left - 0.5;
    }
    for (var i = items.length - 1; i >= 0 && overflowing(); i--) {
      items[i].hidden = true;
      more.hidden = false;
      menu.prepend(items[i].firstChild.cloneNode(true));
    }
    [].slice.call(menu.children).forEach(function (a) { var li = document.createElement('li'); a.replaceWith(li); li.append(a); });
  }

  function mount() {
    if (window.lyraTopNav || window.lyraAppNav) return;
    // Signed in: the full member menu bar replaces the public one, as on the home page.
    if (window.lyraSignedIn && !document.querySelector('script[src*="topnav.js"]')) {
      var pub = document.querySelector('nav.nav');
      if (pub) pub.setAttribute('data-appnav-hide', '');
      var t = document.createElement('script');
      t.src = '/js/topnav.js?v=20261107c';
      document.head.appendChild(t);
      return;
    }
    var inner = document.querySelector('.nav .nav-inner');
    // Pages with their own menu button (the home page) keep their layout; the button holds every link.
    if (inner && inner.querySelector('.nav-hamburger')) {
      var own = inner.querySelector('.nav-links');
      if (own) own.replaceWith(list());
      return;
    }
    if (!inner) {
      // Pages without the site header (sign-in and sign-up): add the same header bar.
      var bar = document.createElement('nav');
      bar.className = 'nav sn-bar';
      bar.setAttribute('aria-label', 'Main');
      bar.innerHTML = '<div class="nav-inner"><a href="/" class="nav-logo"><img src="/img/logo-mark.svg" alt="" width="26" height="26" />Lyra AI</a>' +
        '<div class="nav-cta"><a href="/dashboard/login.html" class="sn-cta">Sign in</a></div></div>';
      if (/\/dashboard\/login\.html$/.test(location.pathname)) bar.querySelector('.sn-cta').replaceWith(Object.assign(document.createElement('a'), { href: '/dashboard/register.html', className: 'sn-cta', textContent: 'Create account' }));
      document.body.prepend(bar);
      inner = bar.querySelector('.nav-inner');
      var barStyle = document.createElement('style');
      barStyle.textContent = '.sn-bar{position:relative;z-index:200;background:#14120e;border-bottom:1px solid rgba(250,249,247,.08);font:14px/1.4 Inter,system-ui,sans-serif}' +
        '.sn-bar .nav-inner{display:flex;align-items:center;max-width:1200px;margin:0 auto;padding:10px max(16px,env(safe-area-inset-left,0px));min-height:56px;box-sizing:border-box}' +
        '.sn-bar .nav-logo{display:inline-flex;align-items:center;gap:8px;color:#faf9f7;text-decoration:none;font-weight:600;font-size:15px;flex:none}.sn-bar .nav-logo img{border-radius:6px}' +
        '.sn-bar .nav-links{display:flex!important;list-style:none;margin:0;padding:0}.sn-bar .nav-links a{display:block;padding:6px 9px;border-radius:6px;color:rgba(250,249,247,.72);text-decoration:none;font-size:.875rem;white-space:nowrap}' +
        '.sn-bar .nav-links a:hover{color:#faf9f7;background:rgba(250,249,247,.08)}.sn-bar .nav-cta{flex:none;margin-left:auto}' +
        'body>.sn-bar~* .brand,body>.sn-bar~* .mobile-brand{display:none!important}' +
        '.sn-cta{display:inline-block;padding:7px 16px;border-radius:999px;background:#faf9f7;color:#14120e!important;text-decoration:none;font-size:13px;font-weight:600;white-space:nowrap}';
      document.head.appendChild(barStyle);
    }
    if (inner) {
      var ul = list();
      ul.classList.add('sn-fit');
      var more = document.createElement('li');
      more.className = 'sn-more';
      more.hidden = true;
      more.innerHTML = '<button type="button" aria-expanded="false">More \u25BE</button><ul class="sn-menu"></ul>';
      ul.append(more);
      var old = inner.querySelector('.nav-links');
      if (old) old.replaceWith(ul);
      else inner.insertBefore(ul, inner.querySelector('.nav-cta'));
      var style = document.createElement('style');
      style.textContent = STYLE;
      document.head.appendChild(style);
      var btn = more.querySelector('button'), menu = more.querySelector('.sn-menu');
      btn.addEventListener('click', function (e) { e.stopPropagation(); var on = !menu.classList.contains('open'); menu.classList.toggle('open', on); btn.setAttribute('aria-expanded', String(on)); });
      document.addEventListener('click', function () { menu.classList.remove('open'); btn.setAttribute('aria-expanded', 'false'); });
      fit(ul);
      var tm;
      addEventListener('resize', function () { clearTimeout(tm); tm = setTimeout(function () { fit(ul); }, 80); });
      if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { fit(ul); });
      return;
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
  else mount();
})();
