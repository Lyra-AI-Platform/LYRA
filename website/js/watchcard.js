/* A tracked person's Watch card with their recent trades, for any page that shows a story.
   window.lyraWatchCards(names) gives { name: card element } for the ones Lyra tracks. */
(function () {
  var cache = {};
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function card(p) {
    var box = el('div', 'watchcard');
    var a = el('a', '', p.name);
    a.href = p.page;
    box.append(a, el('span', 'wc-job', p.job ? ' · ' + p.job : ''));
    if (p.trades.length) {
      var ul = el('ul');
      p.trades.forEach(function (t) { ul.append(el('li', '', (t.date ? t.date + ': ' : '') + t.title)); });
      box.append(ul);
    }
    return box;
  }
  window.lyraWatchCards = async function (names) {
    var want = names.filter(function (n) { return !(n in cache); }).slice(0, 25);
    if (want.length) {
      var d = await fetch('/api/pulse/people?names=' + encodeURIComponent(want.join('|'))).then(function (r) { return r.json(); }).catch(function () { return { people: [] }; });
      want.forEach(function (n) { cache[n] = null; });
      d.people.forEach(function (p) { cache[p.name] = p; });
    }
    var out = {};
    names.forEach(function (n) { if (cache[n]) out[n] = card(cache[n]); });
    return out;
  };
  var style = document.createElement('style');
  style.textContent = '.watchcard{margin:8px 0 0;padding:9px 12px;border:1px solid rgba(127,127,127,.3);border-radius:9px;font-size:13px;line-height:1.45}' +
    '.watchcard a{font-weight:600}.watchcard .wc-job{opacity:.75}.watchcard ul{margin:5px 0 0;padding-left:16px}';
  document.head.append(style);
})();
