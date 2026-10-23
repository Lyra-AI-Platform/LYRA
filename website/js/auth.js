/* Shared by the sign-in and sign-up pages: provider buttons, show/hide password, messages
   from the server (?error= after a Google/Apple/GitHub round trip), and where to go next. */
(function () {
  var ICONS = {
    google: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.4h6.5a5.6 5.6 0 0 1-2.4 3.6v3h3.9c2.2-2.1 3.5-5.1 3.5-8.7z"/><path fill="#34A853" d="M12 24c3.2 0 6-1.1 8-2.9l-3.9-3c-1.1.7-2.5 1.2-4.1 1.2-3.1 0-5.8-2.1-6.7-5H1.3v3.1A12 12 0 0 0 12 24z"/><path fill="#FBBC05" d="M5.3 14.3a7.2 7.2 0 0 1 0-4.6V6.6H1.3a12 12 0 0 0 0 10.8l4-3.1z"/><path fill="#EA4335" d="M12 4.8c1.8 0 3.3.6 4.6 1.8l3.4-3.4A12 12 0 0 0 1.3 6.6l4 3.1c.9-2.9 3.6-4.9 6.7-4.9z"/></svg>',
    apple: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M16.4 12.7c0-2.6 2.1-3.8 2.2-3.9a4.8 4.8 0 0 0-3.8-2c-1.6-.2-3.1.9-3.9.9-.8 0-2-.9-3.4-.9a5 5 0 0 0-4.2 2.6c-1.8 3.1-.5 7.7 1.3 10.2.8 1.2 1.8 2.6 3.1 2.6s1.7-.8 3.3-.8 2 .8 3.4.8 2.2-1.3 3-2.5a10 10 0 0 0 1.4-2.8 4.4 4.4 0 0 1-2.4-4.2zM13.9 5.1A4.4 4.4 0 0 0 15 1.9a4.5 4.5 0 0 0-3 1.5 4.2 4.2 0 0 0-1 3.1c1.1.1 2.2-.6 2.9-1.4z"/></svg>',
    github: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 .5a11.5 11.5 0 0 0-3.6 22.4c.6.1.8-.3.8-.6v-2c-3.2.7-3.9-1.5-3.9-1.5-.5-1.3-1.3-1.7-1.3-1.7-1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.7-1.6-2.6-.3-5.3-1.3-5.3-5.7 0-1.3.5-2.3 1.2-3.1-.1-.3-.5-1.5.1-3.1 0 0 1-.3 3.2 1.2a11 11 0 0 1 5.8 0c2.2-1.5 3.2-1.2 3.2-1.2.6 1.6.2 2.8.1 3.1.8.8 1.2 1.9 1.2 3.1 0 4.4-2.7 5.4-5.3 5.7.4.4.8 1.1.8 2.2v3.2c0 .3.2.7.8.6A11.5 11.5 0 0 0 12 .5z"/></svg>'
  };
  var NAMES = { google: 'Google', apple: 'Apple', github: 'GitHub' };

  var ERRORS = {
    cancelled: 'Sign-in was cancelled. Pick a way to continue whenever you’re ready.',
    expired: 'That sign-in took too long or was started in another tab. Please try again.',
    provider_error: '{p} didn’t complete the sign-in. Please try again in a moment.',
    unavailable: 'Sign in with {p} is being set up and isn’t available yet. Use your email for now.',
    no_email: '{p} didn’t share a verified email address. Verify an email with {p}, or sign up with your email here.',
    link_required: 'An account with that email already has a password. Sign in with it below, then connect {p} from Account → Connected accounts.',
    disabled: 'This account has been disabled. Contact support@lyraauth.com.',
    signin_first: 'Please sign in first.',
    linked_elsewhere: 'That {p} account is already connected to a different Lyra account.'
  };

  window.lyraAuth = {
    safeNext: function (next) {
      return typeof next === 'string' && /^\/(?![\/\\])[A-Za-z0-9\-._~\/?=&#%+]*$/.test(next) ? next : '/';
    },
    takeNext: function () {
      var fromUrl = new URLSearchParams(location.search).get('next');
      var stored = null;
      try { stored = localStorage.getItem('lyra_next'); } catch (e) {}
      return lyraAuth.safeNext(fromUrl || stored);
    },
    clearNext: function () { try { localStorage.removeItem('lyra_next'); } catch (e) {} },
    show: function (msg, kind) {
      var box = document.getElementById('alert');
      box.className = 'alert show ' + (kind || 'error');
      box.textContent = msg;
      box.setAttribute('role', kind === 'info' ? 'status' : 'alert');
    },
    hide: function () { document.getElementById('alert').className = 'alert'; },
    errorText: function (data, fallback) {
      if (!data) return fallback;
      if (typeof data.detail === 'string') return data.detail;
      if (Array.isArray(data.detail) && data.detail[0]) return data.detail[0].msg || fallback;
      return fallback;
    },
    post: function (url, body) {
      return fetch(url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
        .then(function (res) {
          return res.json().catch(function () { return null; }).then(function (data) {
            if (res.status === 429) throw new Error(lyraAuth.errorText(data, 'Too many attempts. Please wait a few minutes.'));
            if (!res.ok) throw new Error(lyraAuth.errorText(data, res.status >= 500 ? 'Lyra is busy right now. Please try again in a moment.' : 'Something went wrong. Please try again.'));
            return data;
          });
        }, function () { throw new Error('Can’t reach Lyra. Check your connection and try again.'); });
    },
    busy: function (btn, on, label) {
      btn.disabled = on;
      btn.querySelector('.label').textContent = label;
    }
  };

  function providers(verb) {
    var box = document.getElementById('providers');
    if (!box) return;
    var next = window.lyraAuthNext || lyraAuth.takeNext();
    ['google', 'apple', 'github'].forEach(function (p) {
      var a = document.createElement('a');
      a.className = 'provider ' + p;
      a.href = '/api/oauth/' + p + '/start?next=' + encodeURIComponent(next);
      a.innerHTML = ICONS[p] + '<span>' + verb + ' ' + NAMES[p] + '</span>';
      a.addEventListener('click', lyraAuth.clearNext);
      box.appendChild(a);
    });
    // Grey out any provider this server hasn't been set up with, rather than sending people off to fail.
    fetch('/api/oauth/providers').then(function (r) { return r.ok ? r.json() : null; }).then(function (on) {
      if (!on) return;
      box.querySelectorAll('.provider').forEach(function (a) {
        var p = a.className.split(' ')[1];
        if (on[p]) return;
        a.setAttribute('aria-disabled', 'true');
        a.title = 'Coming soon';
        a.addEventListener('click', function (e) {
          e.preventDefault();
          lyraAuth.show(ERRORS.unavailable.replace(/\{p\}/g, NAMES[p]));
        });
      });
    }).catch(function () {});
  }

  function reveal() {
    document.querySelectorAll('.reveal').forEach(function (b) {
      b.addEventListener('click', function () {
        var input = document.getElementById(b.getAttribute('aria-controls'));
        var showing = input.type === 'text';
        input.type = showing ? 'password' : 'text';
        b.textContent = showing ? 'Show' : 'Hide';
        b.setAttribute('aria-pressed', String(!showing));
        input.focus();
      });
    });
  }

  function fromServer() {
    var q = new URLSearchParams(location.search);
    var err = q.get('error');
    if (!err) return;
    var p = NAMES[q.get('provider')] || 'The provider';
    lyraAuth.show((ERRORS[err] || ERRORS.provider_error).replace(/\{p\}/g, p), 'error');
  }

  document.addEventListener('DOMContentLoaded', function () {
    providers(document.body.getAttribute('data-verb') || 'Continue with');
    reveal();
    fromServer();
    // Keep the ?next= on the link to the other form.
    var swap = document.getElementById('swap');
    var next = new URLSearchParams(location.search).get('next');
    if (swap && next) swap.href += '?next=' + encodeURIComponent(lyraAuth.safeNext(next));
  });
})();
