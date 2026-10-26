/* The "you're seeing a preview" bar on Lyra Watch and the Tremor page. The limits themselves
   are enforced by the APIs (lyra/api/watch_api.py, market_api.py); this only tells visitors
   what they're missing and where to unlock it. <script src="/js/preview.js" data-product="watch|tremor"> */
(function () {
  var product = (document.currentScript && document.currentScript.getAttribute('data-product')) || 'watch';
  var KEY = 'lyra-preview-closed-' + product;
  try { if (sessionStorage.getItem(KEY)) return; } catch (e) {}
  var signedIn = !!window.lyraSignedIn;

  var probe = product === 'tremor' ? '/api/market/public/track-record' : '/api/watch/feed?limit=11';
  fetch(probe, { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
    if (!d || !('locked' in d)) return;   // a subscriber or member: nothing is held back
    if (product === 'tremor') {
      show('Tremor Index',
        'You’re seeing the public record. Members get every reading, live Tremor scores for any stock and the news behind each one.',
        signedIn ? ['/dashboard/billing.html?need=market', 'Choose a plan'] : ['/dashboard/register.html?next=/market', 'Start 14 days free'],
        'No card needed for the trial.');
      return;
    }
    fetch('/api/watch/account/pricing').then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }).then(function (p) {
      var cents = p && p.watch_pro && p.watch_pro.price_cents;
      var price = cents ? '$' + (cents / 100).toFixed(cents % 100 ? 2 : 0) + '/month' : '';
      show('Lyra Watch',
        'You’re seeing a preview: the top 5 movers, 12 people per list and the 10 latest moves, an hour late. Watch Pro unlocks the live stream, every profile and the full record.',
        signedIn ? ['/watch/account/', 'Unlock Watch Pro' + (price ? ' · ' + price : '')] : ['/dashboard/register.html?next=/watch/account/', 'Create a free account'],
        price ? 'Watch Pro is ' + price + ', cancel any time.' : 'Cancel any time.');
    });
  }).catch(function () {});

  function show(name, text, cta, small) {
    var css = document.createElement('style');
    css.textContent = '' +
      '.lp{position:fixed;left:16px;right:16px;bottom:16px;z-index:9000;max-width:980px;margin:0 auto;display:flex;gap:18px;align-items:center;' +
      'padding:16px 18px 16px 20px;border-radius:16px;color:#faf9f7;font:14px/1.5 Inter,system-ui,sans-serif;' +
      'background:radial-gradient(500px 160px at 100% 0,rgba(225,29,72,.35),transparent 70%),#14120e;box-shadow:0 24px 60px -16px rgba(0,0,0,.55),0 0 0 1px rgba(250,249,247,.08);' +
      'animation:lpin .45s cubic-bezier(.2,.7,.2,1) both}' +
      '@keyframes lpin{from{opacity:0;transform:translateY(16px)}}' +
      '.lp b{display:block;font-family:"Instrument Serif",Georgia,serif;font-weight:400;font-size:22px;line-height:1.1;margin-bottom:2px}' +
      '.lp p{margin:0;color:rgba(250,249,247,.75);font-size:13.5px}.lp small{display:block;color:rgba(250,249,247,.5);font-size:12px;margin-top:2px}' +
      '.lp a{flex:none;padding:11px 16px;border-radius:10px;background:#faf9f7;color:#14120e;font-weight:600;text-decoration:none;white-space:nowrap}' +
      '.lp a:hover{background:#fff;opacity:1}' +
      '.lp button{flex:none;background:none;border:0;color:rgba(250,249,247,.55);font-size:20px;line-height:1;cursor:pointer;padding:4px 6px;border-radius:6px}' +
      '.lp button:hover{color:#faf9f7}.lp a:focus-visible,.lp button:focus-visible{outline:2px solid #fb7185;outline-offset:2px}' +
      '.lp-copy{flex:1;min-width:0}' +
      // Phones: one short line and a full-width button, with the close button in the corner
      '@media (max-width:640px){.lp{flex-wrap:wrap;gap:12px;left:10px;right:10px;bottom:calc(10px + env(safe-area-inset-bottom));padding:14px 44px 14px 16px}' +
      '.lp-copy{flex:1 1 100%}.lp b{font-size:19px}.lp p{display:none}.lp a{flex:1 1 100%;text-align:center;padding:12px}' +
      '.lp button{position:absolute;top:8px;right:8px;font-size:22px}}' +
      '@media (prefers-reduced-motion:reduce){.lp{animation:none}}';
    document.head.appendChild(css);
    var bar = document.createElement('aside');
    bar.className = 'lp';
    bar.setAttribute('aria-label', name + ' preview');
    var copy = document.createElement('div');
    var h = document.createElement('b'); h.textContent = 'This is a preview of ' + name + '.';
    var p = document.createElement('p'); p.textContent = text;
    var s = document.createElement('small'); s.textContent = small;
    copy.className = 'lp-copy';
    copy.append(h, p, s);
    var a = document.createElement('a'); a.href = cta[0]; a.textContent = cta[1];
    var x = document.createElement('button'); x.type = 'button'; x.setAttribute('aria-label', 'Hide'); x.textContent = '×';
    x.onclick = function () { bar.remove(); try { sessionStorage.setItem(KEY, '1'); } catch (e) {} };
    bar.append(copy, a, x);
    document.body.appendChild(bar);
  }
})();
