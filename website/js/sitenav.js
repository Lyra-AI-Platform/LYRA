/* The same main menu on every public page. Signed-in pages get the fuller bar from topnav.js. */
(function () {
  var LINKS = [['/news/', 'News'], ['/watch/live/', 'Live'], ['/tremor/', 'Tremor Index'], ['/watch/', 'Watch'],
    ['/watch/account/', 'Watch Pro / API keys'], ['/pricing/', 'Pricing'], ['/pages/docs.html', 'Docs']];

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

  function mount() {
    if (window.lyraTopNav || window.lyraAppNav) return;
    var inner = document.querySelector('.nav .nav-inner');
    if (inner) {
      var old = inner.querySelector('.nav-links');
      if (old) old.replaceWith(list());
      else inner.insertBefore(list(), inner.querySelector('.nav-cta'));
      return;
    }
    var bar = document.createElement('nav');
    bar.setAttribute('aria-label', 'Main');
    bar.style.cssText = 'background:#14120e;padding:10px 16px;font:14px/1.4 Inter,system-ui,sans-serif';
    var ul = list();
    ul.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px 16px;list-style:none;margin:0;padding:0';
    ul.querySelectorAll('a').forEach(function (a) { a.style.cssText = 'color:#faf9f7;text-decoration:none'; });
    bar.append(ul);
    document.body.prepend(bar);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
  else mount();
})();
