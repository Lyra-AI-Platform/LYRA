/* Signed-in state on every page.
   Sign-in lives in an HttpOnly cookie the server checks (lyra/api/sessions.py); page scripts
   never see it, they just call the APIs and the browser sends it. lyra_in is a plain marker
   saying a sign-in exists.
   - window.lyraSignedIn       whether this browser is signed in
   - window.lyraToLogin()      off to sign in, coming back here afterwards
   - window.lyraSignOut(to)    end the session on the server and leave
   - Browsers signed in by the old site kept a token in localStorage: it is swapped once for
     a session and deleted.
   - When signed in, "Sign in / Create account" links become "My Lyra" and "Sign out", and a
     small "My Lyra" button stays in the corner so every product is one click away. */
(function () {
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
    if (location.pathname !== '/' && !document.getElementById('lyra-home-pill')) {
      var pill = document.createElement('a');
      pill.id = 'lyra-home-pill';
      pill.href = '/';
      pill.textContent = '✦ My Lyra';
      pill.setAttribute('aria-label', 'My Lyra: all your products');
      pill.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:9999;padding:9px 16px;border-radius:999px;' +
        'background:#14120e;color:#faf9f7;font:600 13px/1 Inter,system-ui,sans-serif;text-decoration:none;' +
        'box-shadow:0 6px 24px rgba(20,18,14,.25);opacity:1';
      document.body.appendChild(pill);
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', relabel);
  else relabel();
})();
