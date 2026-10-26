/* Signed-in state on every page.
   Sign-in lives in an HttpOnly cookie the server checks (lyra/api/sessions.py); page scripts
   never see it, they just call the APIs and the browser sends it. lyra_in is a plain marker
   saying a sign-in exists.
   - window.lyraSignedIn       whether this browser is signed in
   - window.lyraToLogin()      off to sign in, coming back here afterwards
   - window.lyraSignOut(to)    end the session on the server and leave
   - Browsers signed in by the old site kept a token in localStorage: it is swapped once for
     a session and deleted.
   - When signed in, "Sign in / Create account" links become "My Lyra" and "Sign out", and the
     Lyra menu (appnav.js) is on every page: built in on member pages, a corner "Menu" button
     elsewhere. */
(function () {
  // Smoother moves between pages, for everyone: a short cross-fade (browsers with cross-document
  // view transitions) and pages fetched as soon as a link is hovered or pressed, so the next one
  // is usually ready by the time the click lands. Sign-out and API links are never prefetched.
  try {
    var vt = document.createElement('style');
    vt.textContent = '@view-transition{navigation:auto}' +
      '::view-transition-old(root){animation:lyra-out .18s ease both}' +
      '::view-transition-new(root){animation:lyra-in .26s cubic-bezier(.2,.7,.2,1) both}' +
      '@keyframes lyra-out{to{opacity:0}}@keyframes lyra-in{from{opacity:0;transform:translateY(6px)}}' +
      '@media (prefers-reduced-motion:reduce){::view-transition-old(root),::view-transition-new(root){animation:none}}';
    document.head.appendChild(vt);
    if (HTMLScriptElement.supports && HTMLScriptElement.supports('speculationrules')) {
      var rules = document.createElement('script');
      rules.type = 'speculationrules';
      rules.textContent = JSON.stringify({ prefetch: [{ source: 'document', eagerness: 'moderate', where: { and: [
        { href_matches: '/*' }, { not: { href_matches: '/api/*' } }, { not: { selector_matches: '[data-no-prefetch], [href^="mailto:"]' } }
      ] } }] });
      document.head.appendChild(rules);
    }
  } catch (e) {}

  var marker = /(?:^|;\s*)lyra_in=1/.test(document.cookie);
  window.lyraSignedIn = marker;

  window.lyraToLogin = function () {
    location.href = '/dashboard/login.html?next=' + encodeURIComponent(location.pathname + location.search);
  };
  window.lyraSignOut = function (to) {
    fetch('/api/users/logout', { method: 'POST', credentials: 'same-origin' })
      .catch(function () {})
      .then(function () { location.href = to || '/'; });
  };

  var legacy = null;
  try {
    legacy = localStorage.getItem('lyra_token');
    localStorage.removeItem('lyra_token');
    localStorage.removeItem('lyra_user');
  } catch (e) {}
  if (legacy && !marker) {
    fetch('/api/users/session', { method: 'POST', credentials: 'same-origin', headers: { Authorization: 'Bearer ' + legacy } })
      .then(function (r) { if (r.ok) location.reload(); })
      .catch(function () {});
  }

  if (!marker) return;

  function relabel() {
    var links = document.querySelectorAll('a[href$="login.html"], a[href*="login.html?"]');
    for (var i = 0; i < links.length; i++) {
      links[i].setAttribute('href', '/');
      links[i].textContent = 'My Lyra';
    }
    var signups = document.querySelectorAll('a[href$="register.html"], a[href*="register.html?"]');
    for (var j = 0; j < signups.length; j++) {
      var a = signups[j], plan = /[?&]plan=(\w+)/.exec(a.getAttribute('href'));
      // Plan buttons go straight to billing; plain sign-up buttons become sign-out in the nav.
      if (plan) { a.setAttribute('href', '/dashboard/billing.html?plan=' + plan[1]); continue; }
      if (a.closest('.nav-cta, .nav-mobile, nav')) {
        a.setAttribute('href', '#');
        a.textContent = 'Sign out';
        a.addEventListener('click', function (e) { e.preventDefault(); window.lyraSignOut(); });
      } else {
        a.setAttribute('href', '/');
        a.textContent = 'Open My Lyra →';
      }
    }
    // Pages without the menu built in (marketing pages, the product apps) get it as a drawer,
    // opened from a corner button, so every product is one click away from anywhere.
    if (!document.querySelector('script[src^="/js/appnav.js"]')) {
      if (!document.body.hasAttribute('data-appnav')) document.body.setAttribute('data-appnav', 'drawer');
      var nav = document.createElement('script');
      nav.src = '/js/appnav.js';
      document.head.appendChild(nav);
    }
    if (document.body.getAttribute('data-appnav') === 'drawer' && !document.querySelector('[data-appnav-toggle]') && !document.getElementById('lyra-home-pill')) {
      var pill = document.createElement('button');
      pill.type = 'button';
      pill.id = 'lyra-home-pill';
      pill.setAttribute('data-appnav-toggle', '');
      pill.setAttribute('aria-controls', 'lyra-appnav');
      pill.textContent = '✦ Menu';
      pill.setAttribute('aria-label', 'Open the Lyra menu: all your products');
      pill.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:9999;padding:9px 16px;border-radius:999px;' +
        'background:#14120e;color:#faf9f7;font:600 13px/1 Inter,system-ui,sans-serif;text-decoration:none;' +
        'box-shadow:0 6px 24px rgba(20,18,14,.25);opacity:1;border:0;cursor:pointer';
      document.body.appendChild(pill);
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', relabel);
  else relabel();
})();

// Installable app: the service worker only caches static files (see /sw.js)
if ('serviceWorker' in navigator) window.addEventListener('load', function () { navigator.serviceWorker.register('/sw.js').catch(function () {}); });
