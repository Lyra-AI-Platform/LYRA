/* Signed-in state on every page.
   - Accounts that signed in before pages were guarded on the server have a token but no
     page cookie: swap one for the other once, so members-only pages open for them.
   - When signed in, "Sign in / Create account" links become "My Lyra" and "Sign out",
     and a small "My Lyra" button stays in the corner so every product is one click away.
   - lyraSignOut() clears both the token and the cookie. */
(function () {
  var token = null;
  try { token = localStorage.getItem('lyra_token'); } catch (e) {}
  var marker = /(?:^|;\s*)lyra_in=1/.test(document.cookie);

  window.lyraSignOut = function (to) {
    try { localStorage.removeItem('lyra_token'); localStorage.removeItem('lyra_user'); localStorage.removeItem('lyra_next'); } catch (e) {}
    fetch('/api/users/logout', { method: 'POST', credentials: 'same-origin' })
      .catch(function () {})
      .then(function () { location.href = to || '/'; });
  };

  if (token && !marker) {
    fetch('/api/users/session', { method: 'POST', credentials: 'same-origin', headers: { Authorization: 'Bearer ' + token } })
      .then(function (r) {
        if (r.status === 401) { try { localStorage.removeItem('lyra_token'); } catch (e) {} return; }
        // A members-only page may have sent us to sign in; now the cookie exists, go back.
        if (r.ok && /\/dashboard\/(login|register)\.html$/.test(location.pathname)) location.replace('/');
      })
      .catch(function () {});
  } else if (!token && marker) {
    // Cookie without a token (storage cleared): sign out fully so the two can't disagree.
    fetch('/api/users/logout', { method: 'POST', credentials: 'same-origin' }).catch(function () {});
  }

  if (!token) return;

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
