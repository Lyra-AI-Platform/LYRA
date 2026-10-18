/* COSHH AI Database — page logic.
   Substance data comes from /api/coshh (PubChem, HSE EH40, NIST). Everything the
   visitor adds (register entries, supplier SDS PDFs, their own spectra) is kept in
   this browser's IndexedDB and never leaves the device unless they export it. */
(() => {
  'use strict';
  const API = '/api/coshh';
  const $ = s => document.querySelector(s);
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const safeUrl = u => (/^https?:\/\//i.test(u || '') ? u : '#');
  const today = () => new Date().toISOString().slice(0, 10);
  const addMonths = (d, m) => { const x = new Date(d); x.setMonth(x.getMonth() + m); return x.toISOString().slice(0, 10); };
  let current = null;
  let usedRefs = new Set();

  // ---------------------------------------------------------------- storage
  const DB = (() => {
    let dbp = null;
    const open = () => dbp || (dbp = new Promise((res, rej) => {
      let r;
      try { r = indexedDB.open('lyra-coshh', 1); } catch (e) { rej(e); return; }
      r.onupgradeneeded = () => {
        const db = r.result;
        db.createObjectStore('substances', { keyPath: 'cid' });
        const ds = db.createObjectStore('datasets', { keyPath: 'id', autoIncrement: true });
        ds.createIndex('cid', 'cid');
        db.createObjectStore('files', { keyPath: 'id', autoIncrement: true });
      };
      r.onsuccess = () => res(r.result);
      r.onerror = () => rej(r.error);
    }));
    const run = (store, mode, fn) => open().then(db => new Promise((res, rej) => {
      const tx = db.transaction(store, mode), st = tx.objectStore(store);
      const req = fn(st);
      tx.oncomplete = () => res(req && req.result);
      tx.onerror = () => rej(tx.error);
    }));
    return {
      all: s => run(s, 'readonly', st => st.getAll()).catch(() => []),
      get: (s, k) => run(s, 'readonly', st => st.get(k)).catch(() => undefined),
      put: (s, v) => run(s, 'readwrite', st => st.put(v)),
      del: (s, k) => run(s, 'readwrite', st => st.delete(k)),
      byCid: cid => run('datasets', 'readonly', st => st.index('cid').getAll(cid)).catch(() => []),
    };
  })();

  // ---------------------------------------------------------------- helpers
  function setStatus(msg, err) { const s = $('#status'); s.textContent = msg || ''; s.className = 'status' + (err ? ' err' : ''); }
  function cite(ref) {
    if (ref == null || !current || !current.references[ref]) return '';
    usedRefs.add(ref);
    return `<sup><a href="#ref-${ref}" title="${esc(current.references[ref].source)}">[${ref}]</a></sup>`;
  }
  function list(items, show = 4) {
    return `<ul>${items.map((it, i) => `<li class="${i >= show ? 'hidden' : ''}">${it}</li>`).join('')}</ul>` +
      (items.length > show ? `<button class="more" type="button">Show all ${items.length}</button>` : '');
  }
  function block(label, items, show) { return `<div class="blk"><h4>${esc(label)}</h4>${list(items, show)}</div>`; }
  async function getJSON(url) {
    const r = await fetch(url);
    if (!r.ok) {
      let msg = `Request failed (${r.status}).`;
      try { msg = (await r.json()).detail || msg; } catch (e) { /* not JSON */ }
      throw new Error(msg);
    }
    return r.json();
  }
  function download(name, text, type) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], { type: type || 'text/plain' }));
    a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }
  document.addEventListener('click', e => {
    if (e.target.classList.contains('more')) {
      const blk = e.target.closest('.blk, .card, .spec') || e.target.parentElement;
      blk.classList.add('open'); blk.querySelectorAll('li.hidden').forEach(li => li.classList.remove('hidden'));
      e.target.remove();
    }
  });

  // ---------------------------------------------------------------- search
  const input = $('#q'), sug = $('#suggest');
  let sugTimer = null, sugIdx = -1;
  input.addEventListener('input', () => {
    clearTimeout(sugTimer);
    const q = input.value.trim();
    if (q.length < 3 || /^\d+-\d+/.test(q)) { sug.style.display = 'none'; return; }
    sugTimer = setTimeout(async () => {
      try {
        const d = await getJSON(`${API}/search?q=${encodeURIComponent(q)}`);
        if (input.value.trim() !== q) return;
        sugIdx = -1;
        sug.innerHTML = d.suggestions.map(s => `<button type="button" role="option" data-q="${esc(s)}">${esc(s)}</button>`).join('');
        sug.style.display = d.suggestions.length ? 'block' : 'none';
      } catch (e) { sug.style.display = 'none'; }
    }, 220);
  });
  input.addEventListener('keydown', e => {
    const opts = [...sug.querySelectorAll('button')];
    if (!opts.length || sug.style.display === 'none') return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      sugIdx = (sugIdx + (e.key === 'ArrowDown' ? 1 : -1) + opts.length) % opts.length;
      opts.forEach((o, i) => o.classList.toggle('active', i === sugIdx));
      input.value = opts[sugIdx].dataset.q;
    } else if (e.key === 'Escape') sug.style.display = 'none';
  });
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-q]');
    if (b && (b.closest('#suggest') || b.closest('.examples') || b.closest('#libraryHome'))) {
      e.preventDefault(); input.value = b.dataset.q; lookup(b.dataset.q); window.scrollTo({ top: 0, behavior: 'smooth' });
    }
    if (!e.target.closest('.search')) sug.style.display = 'none';
  });
  $('#searchForm').addEventListener('submit', e => { e.preventDefault(); sug.style.display = 'none'; if (input.value.trim()) lookup(input.value.trim()); });
  window.addEventListener('popstate', () => { const q = new URLSearchParams(location.search).get('q'); if (q) lookup(q, true); });

  async function lookup(q, fromHistory) {
    setStatus(`Compiling the safety data sheet for “${q}”… (first lookup takes a few seconds)`);
    $('#result').innerHTML = '';
    try {
      const sheet = await getJSON(`${API}/sheet?q=${encodeURIComponent(q)}`);
      current = sheet;
      if (!fromHistory) history.pushState(null, '', `?q=${encodeURIComponent(q)}`);
      document.title = `${sheet.identity.name} — COSHH AI Database`;
      setStatus(sheet.incomplete && sheet.incomplete.length
        ? `Some PubChem sections were busy and are missing (${sheet.incomplete.join(', ')}). Reload in a minute for the full sheet.` : '');
      render(sheet);
    } catch (e) {
      // Offline or API down: fall back to a copy saved in the register.
      const saved = (await DB.all('substances')).find(s => s.name.toLowerCase() === q.toLowerCase() || s.cas === q || String(s.cid) === q);
      if (saved && saved.sheet) {
        current = saved.sheet; render(saved.sheet);
        setStatus(`Showing your saved copy from ${saved.savedAt} (live lookup failed: ${e.message})`, true);
      } else setStatus(e.message, true);
    }
  }

  // ---------------------------------------------------------------- render
  function render(s) {
    usedRefs = new Set();
    const id = s.identity, g = s.ghs, flags = s.guidance.flags;
    const pics = g.pictograms.map(p => `<img src="${esc(safeUrl(p.url))}" alt="${esc(p.code + ' ' + p.name)}" title="${esc(p.code + ': ' + p.name)}">`).join('');
    $('#result').innerHTML = `
      <div class="head">
        <img class="struct" src="${esc(safeUrl(id.structure_image))}" alt="Structure of ${esc(id.name)}" loading="lazy">
        <div>
          <h2>${esc(id.name)}</h2>
          <div class="ids">
            ${id.cas ? `<span>CAS <b>${esc(id.cas)}</b></span>` : ''}${id.ec ? `<span>EC <b>${esc(id.ec)}</b></span>` : ''}
            ${id.un && id.un.length ? `<span>UN <b>${id.un.map(esc).join(', ')}</b></span>` : ''}
            ${id.formula ? `<span>Formula <b>${esc(id.formula)}</b></span>` : ''}${id.molecular_weight ? `<span>MW <b>${esc(id.molecular_weight)}</b> g/mol</span>` : ''}
            <span>PubChem CID <a href="${esc(id.pubchem_url)}" target="_blank" rel="noopener"><b>${esc(id.cid)}</b></a></span>
          </div>
          <div class="picto">${pics}${g.signal ? `<span class="signal ${esc(g.signal)}">${esc(g.signal)}</span>` : ''}</div>
          <div class="flags">${flags.map(f => `<span class="flag ${esc(f.level)}">${esc(f.label)}</span>`).join('')}</div>
          <div class="actions">
            <button class="btn btn-primary" id="printBtn" type="button">Print / save as PDF</button>
            <button class="btn btn-outline" id="saveBtn" type="button">Add to my COSHH register</button>
            <button class="btn btn-outline" id="jsonBtn" type="button">Download data (JSON)</button>
          </div>
          <p class="print-only" style="font-size:12px;margin-top:8px;">Compiled ${esc(s.retrieved)} from PubChem, HSE EH40/2005 and NIST. Not a supplier SDS.</p>
        </div>
      </div>
      <div class="tabs" role="tablist">
        <button role="tab" aria-selected="true" data-tab="sds">Safety data sheet (16 sections)</button>
        <button role="tab" aria-selected="false" data-tab="officer">H&amp;S officer view</button>
        <button role="tab" aria-selected="false" data-tab="spectra">Spectra &amp; lab data</button>
        <button role="tab" aria-selected="false" data-tab="register">My register</button>
      </div>
      <section class="panel on" id="p-sds"></section>
      <section class="panel" id="p-officer"></section>
      <section class="panel" id="p-spectra"></section>
      <section class="panel noprint" id="p-register"></section>`;
    $('#p-officer').innerHTML = renderOfficer(s);
    $('#p-sds').innerHTML = renderSds(s); // last, so section 16 lists every citation used above
    $('#printBtn').onclick = () => { document.querySelectorAll('details.sec').forEach(d => { d.open = true; }); window.print(); };
    $('#jsonBtn').onclick = () => download(`${id.name.replace(/\W+/g, '_')}_coshh.json`, JSON.stringify(s, null, 1), 'application/json');
    $('#saveBtn').onclick = () => saveToRegister(s);
    document.querySelectorAll('.tabs button').forEach(b => b.onclick = () => showTab(b.dataset.tab));
    renderSpectra(s);
    renderRegister();
  }

  function showTab(name) {
    document.querySelectorAll('.tabs button').forEach(b => b.setAttribute('aria-selected', String(b.dataset.tab === name)));
    document.querySelectorAll('.panel').forEach(p => p.classList.toggle('on', p.id === 'p-' + name));
  }

  function itemsOf(b) { return b.items.map(it => esc(it.text) + cite(it.ref)); }

  function renderSds(s) {
    const id = s.identity, g = s.ghs, w = s.wel;
    const extra = {
      1: () => `<table class="t"><tbody>
          <tr><th>Product identifier</th><td>${esc(id.name)}</td></tr>
          ${id.iupac ? `<tr><th>IUPAC name</th><td>${esc(id.iupac)}</td></tr>` : ''}
          <tr><th>CAS number</th><td>${esc(id.cas || 'Not found')}</td></tr>
          <tr><th>EC number</th><td>${esc(id.ec || 'Not found')}</td></tr>
          <tr><th>Supplier / emergency phone</th><td>Use the supplier's SDS for the product you buy. UK emergency services: 999. NHS 111 for non-emergency medical advice.</td></tr>
        </tbody></table>`,
      2: () => {
        if (!g.classified) return '<p class="none">No GHS classification was found in PubChem for this substance. Check the supplier SDS.</p>';
        const groups = { P1: 'General', P2: 'Prevention', P3: 'Response', P4: 'Storage', P5: 'Disposal' };
        const byGroup = {};
        g.precautions.forEach(p => { (byGroup[p.code.slice(0, 2)] = byGroup[p.code.slice(0, 2)] || []).push(p); });
        return `<div class="blk"><h4>GHS / CLP label elements${cite(g.ref)}</h4>
            <div class="picto">${g.pictograms.map(p => `<img src="${esc(safeUrl(p.url))}" alt="${esc(p.name)}" title="${esc(p.code + ': ' + p.name)}">`).join('')}
            ${g.signal ? `<span class="signal ${esc(g.signal)}">${esc(g.signal)}</span>` : ''}</div></div>
          <div class="blk"><h4>Hazard statements</h4><div class="tw"><table class="t"><tbody>
            ${g.hazards.map(h => { const m = h.match(/^([^:]+):\s*(.*)$/); return `<tr><td class="hcode">${esc(m ? m[1] : '')}</td><td>${esc(m ? m[2] : h)}</td></tr>`; }).join('')}
          </tbody></table></div></div>
          <div class="blk"><h4>Precautionary statements</h4>
            ${Object.keys(groups).filter(k => byGroup[k]).map(k => `<p style="margin:6px 0 2px;font-weight:600;color:var(--text);font-size:13px;">${groups[k]}</p>
              <div class="tw"><table class="t"><tbody>${byGroup[k].map(p => `<tr><td class="hcode">${esc(p.code)}</td><td>${esc(p.text || '')}</td></tr>`).join('')}</tbody></table></div>`).join('')}
          </div>
          <div class="callout">${g.notes.map(esc).join(' ')} ${g.other_sources ? `PubChem holds ${g.other_sources} other classification reports for this substance.` : ''}
            The aggregated data can leave out EU-only EUH statements and differ from the GB mandatory classification list.
            <b>The supplier's label and SDS for your product take precedence.</b></div>`;
      },
      3: () => `<div class="tw"><table class="t"><thead><tr><th>Substance</th><th>CAS</th><th>EC</th><th>Formula</th><th>MW</th><th>Concentration</th></tr></thead>
          <tbody><tr><td>${esc(id.name)}</td><td>${esc(id.cas || '–')}</td><td>${esc(id.ec || '–')}</td><td>${esc(id.formula || '–')}</td><td>${esc(id.molecular_weight || '–')}</td><td>Pure substance</td></tr></tbody></table></div>
          ${id.other_cas && id.other_cas.length ? `<p class="muted" style="font-size:13px;">Other CAS numbers used for this substance: ${id.other_cas.map(esc).join(', ')}</p>` : ''}
          <div class="callout">For a mixture or a diluted product, use section 3 of the supplier's SDS: the components and concentrations decide the classification.</div>`,
      8: () => {
        if (!w) return `<div class="blk"><h4>UK workplace exposure limit (EH40/2005)</h4><p class="none">Not listed in EH40 Table 1. That does not mean it is safe (EH40 para 6):
          control exposure to a level that nearly all workers could be exposed to, day after day, without adverse health effects.</p></div>`;
        return `<div class="blk"><h4>UK workplace exposure limit — HSE EH40/2005 (legally binding)</h4><div class="tw"><table class="t">
          <thead><tr><th>EH40 entry</th><th>8-hr TWA ppm</th><th>8-hr TWA mg/m³</th><th>15-min STEL ppm</th><th>15-min STEL mg/m³</th></tr></thead><tbody>
          ${w.limits.map(l => `<tr><td>${esc(w.substance)}${l.fraction ? ` — ${esc(l.fraction)}` : ''}</td><td>${esc(l.twa_ppm || '–')}</td><td>${esc(l.twa_mg_m3 || '–')}</td><td>${esc(l.stel_ppm || '–')}</td><td>${esc(l.stel_mg_m3 || '–')}</td></tr>`).join('')}
          </tbody></table></div>
          ${w.notations.length ? `<p style="font-size:14px;"><b>Notations:</b> ${w.notations.map(n => ({ Carc: 'Carc — capable of causing cancer and/or heritable genetic damage', Sen: 'Sen — capable of causing occupational asthma', Sk: 'Sk — can be absorbed through the skin' }[n])).map(esc).join('; ')}</p>` : ''}
          ${w.comments ? `<p class="muted" style="font-size:13px;">EH40 comments: ${esc(w.comments)}</p>` : ''}
          ${w.group_entry ? `<p class="muted" style="font-size:13px;">Matched to the EH40 group entry “${esc(w.group_entry)}”.</p>` : ''}
          ${w.bmgv ? `<p style="font-size:14px;"><b>Biological monitoring guidance value (EH40 Table 2):</b> ${esc(w.bmgv.bmgv)} — sample ${esc(w.bmgv.sampling.toLowerCase())}</p>` : ''}
          <p class="muted" style="font-size:12px;">${esc(w.source)}</p></div>`;
      },
      14: () => id.un && id.un.length ? `<div class="blk"><h4>UN numbers reported</h4><p style="font-size:14px;color:var(--text)">${id.un.map(u => 'UN ' + esc(u)).join(', ')}. The correct entry depends on the form shipped (gas, solution, concentration).</p></div>` : '',
      16: () => '',
    };
    let html = '';
    for (const sec of s.sections) {
      const pre = extra[sec.number] ? extra[sec.number]() : '';
      const blocks = sec.blocks.map(b => block(b.label, itemsOf(b))).join('');
      const count = sec.blocks.reduce((n, b) => n + b.items.length, 0);
      const body = sec.number === 16 ? '' : (pre + blocks) || '<p class="none">No data found in the sources for this section. Check the supplier SDS.</p>';
      html += `<details class="sec" ${sec.number <= 2 || sec.number === 8 ? 'open' : ''} id="sec-${sec.number}"><summary><span class="n">${sec.number}</span>${esc(sec.title)}<span class="c">${count ? count + ' entries' : ''}</span></summary><div class="body">${body}${sec.number === 16 ? '<div id="sec16"></div>' : ''}</div></details>`;
    }
    setTimeout(() => {
      const refs = [...usedRefs].sort((a, b) => a - b).map(r => {
        const x = s.references[r];
        return `<li id="ref-${r}">[${r}] ${esc(x.source)}${x.name ? ' — ' + esc(x.name) : ''} ${x.url ? `<a href="${esc(safeUrl(x.url))}" target="_blank" rel="noopener">source</a>` : ''}</li>`;
      });
      const el = $('#sec16');
      if (el) el.innerHTML = `
        <div class="blk"><h4>Compiled</h4><p style="font-size:14px;color:var(--text)">${esc(s.retrieved)} from live public sources. Each line above carries the number of its source.</p></div>
        <div class="blk"><h4>Sources</h4><ul><li>${esc(s.sources.pubchem)}</li><li>${esc(s.sources.eh40)}</li><li>${esc(s.sources.ghs_codes)}</li></ul></div>
        <div class="blk"><h4>References cited</h4>${list(refs, 8)}</div>
        <div class="callout"><b>Important.</b> This sheet is compiled from authoritative public data for the pure substance. It is not the supplier's SDS
          (UK REACH Article 31 requires the supplier to give you one) and it is not a COSHH assessment. A competent person must assess the actual work
          (COSHH Regulation 6) using the supplier SDS for the product used.</div>`;
    }, 0);
    return html;
  }

  function renderOfficer(s) {
    const cats = ['Key risks', 'Controls', 'PPE', 'Storage', 'Health surveillance', 'Emergency', 'Waste & environment'];
    const cards = [...s.guidance.cards].sort((a, b) => cats.indexOf(a.category) - cats.indexOf(b.category));
    const ppeText = (s.sections.find(x => x.number === 8).blocks.find(b => b.heading === 'Personal Protective Equipment (PPE)') || { items: [] }).items;
    const firstAid = (s.sections.find(x => x.number === 4).blocks.find(b => b.heading === 'First Aid') || { items: [] }).items;
    const fire = (s.sections.find(x => x.number === 5).blocks.find(b => b.heading === 'Fire Fighting Procedures') || { items: [] }).items;
    const spill = s.sections.find(x => x.number === 6).blocks.flatMap(b => b.items).slice(0, 4);
    const quick = (title, its) => its.length ? `<div class="card"><div class="cat">From the sources</div><h3>${esc(title)}</h3>${list(its.map(it => esc(it.text) + cite(it.ref)), 3)}</div>` : '';
    return `
      <div class="callout">What a classic SDS doesn't tell you: the <b>UK legal duties</b> and <b>practical controls</b> that follow from this substance's hazards.
        Each card names the regulation or HSE guidance it comes from. The cards are generated by fixed rules from the hazard codes
        (${s.guidance.codes.map(esc).join(', ') || 'none'}) and the EH40 entry.</div>
      <div class="cards">${cards.map(c => `<div class="card ${esc(c.level)}"><div class="cat">${esc(c.category)}</div><h3>${esc(c.title)}</h3>
        <ul>${c.points.map(p => `<li>${esc(p)}</li>`).join('')}</ul><div class="basis">${esc(c.basis)}</div></div>`).join('')}</div>
      <h3 style="margin:22px 0 8px;">Quick reference from the sources</h3>
      <div class="cards">${quick('First aid', firstAid)}${quick('Firefighting', fire)}${quick('Spills and release', spill)}${quick('PPE (as published)', ppeText)}</div>
      <h3 style="margin:22px 0 8px;">Assessment checklist</h3>
      <div class="card"><ul>
        <li>Who could be exposed (including cleaners, contractors, maintenance staff and visitors), and are any of them vulnerable (pregnant, young, sensitised)?</li>
        <li>Task, quantity, frequency and duration; form (liquid, dust, vapour, aerosol); temperature; the routes of exposure.</li>
        <li>Can you eliminate or substitute the substance, or a less hazardous form such as pellets, a paste or a weaker solution?</li>
        <li>Engineering controls in place and working (LEV test date, enclosure, ventilation)?</li>
        <li>PPE: correct type, and fit-tested where needed? Gloves checked against breakthrough time?</li>
        <li>Monitoring: air sampling against the WEL, plus health surveillance where needed?</li>
        <li>Storage, segregation, labelling, spill kit, first aid and emergency plan in place?</li>
        <li>Training given and recorded; review date set?</li>
      </ul></div>`;
  }

  // ---------------------------------------------------------------- spectra
  const TECH = { FTIR: 'FTIR / IR', 'NMR 1H': '¹H NMR', 'NMR 13C': '¹³C NMR', 'NMR other': 'NMR (other)', GC: 'GC chromatogram', 'GC-MS': 'GC-MS / MS', Raman: 'Raman', 'UV-Vis': 'UV-Vis', Other: 'Other' };
  const reverseFor = t => /FTIR|NMR|Raman/.test(t);
  const sticksFor = t => /GC-MS/.test(t);

  function axisLabels(sp, technique) {
    const x = sp.xUnits || ({ FTIR: 'Wavenumber (cm⁻¹)', GC: 'Retention time (min)', 'GC-MS': 'm/z' }[technique] || (/NMR/.test(technique) ? 'Chemical shift (ppm)' : 'x'));
    return { xLabel: x, yLabel: sp.yUnits || 'Intensity' };
  }

  function peakTable(sp, technique, peaks) {
    const isIR = /FTIR/.test(technique) || /INFRARED/i.test(sp.dataType || '');
    return `<div class="tw"><table class="t"><thead><tr><th>${/NMR/.test(technique) ? 'Shift (ppm)' : /GC-MS|MASS/i.test(technique + sp.dataType) ? 'm/z' : /GC/.test(technique) ? 'Retention' : 'Position'}</th><th>Intensity</th>${isIR ? '<th>Possible assignment (condensed phase; gas-phase bands shift)</th>' : ''}</tr></thead><tbody>
      ${peaks.map(p => `<tr><td>${+p.x.toFixed(2)}</td><td>${+p.y.toPrecision(4)}</td>${isIR ? `<td>${esc(Spectra.irAssign(p.x).slice(0, 3).join(' · ') || '–')}</td>` : ''}</tr>`).join('')}</tbody></table></div>`;
  }

  async function nistBlock(s, kind, index, el) {
    el.innerHTML = `<p class="muted">Loading NIST ${kind === 'IR' ? 'IR' : 'mass'} spectrum…</p>`;
    try {
      const r = await fetch(`${API}/spectrum?cas=${encodeURIComponent(s.identity.cas)}&kind=${kind}&index=${index}`);
      if (r.status === 404) { el.innerHTML = index ? '<p class="muted">No more NIST spectra of this kind.</p>' : `<p class="none">NIST has no ${kind === 'IR' ? 'IR' : 'mass'} spectrum for this CAS number.</p>`; return; }
      if (!r.ok) throw new Error('NIST did not answer.');
      const sp = Spectra.parse(await r.text(), 'nist.jdx');
      const isIR = kind === 'IR';
      const peaks = Spectra.pickPeaks(sp, { max: isIR ? 12 : 10 });
      el._spectrum = sp;
      el.innerHTML = `<h3>${isIR ? 'Infrared spectrum' : 'Mass spectrum (electron ionisation)'} — NIST${index ? ` #${index + 1}` : ''}</h3>
        <div class="src">${esc(sp.origin)} · ${esc(sp.owner.split('\n')[0])}${sp.state ? ' · state: ' + esc(sp.state) : ''} · <a href="https://webbook.nist.gov/cgi/cbook.cgi?ID=C${esc(s.identity.cas.replace(/-/g, ''))}&Units=SI" target="_blank" rel="noopener">NIST WebBook</a></div>
        ${Spectra.plot([{ x: sp.x, y: sp.y, sticks: sp.sticks }], { reverseX: isIR, xLabel: isIR ? 'Wavenumber (cm⁻¹)' : 'm/z', yLabel: sp.yUnits || 'Intensity',
          peaks: peaks.map(p => ({ x: p.x, y: p.y, label: String(Math.round(p.x)) })) })}
        <details><summary class="muted" style="cursor:pointer;font-size:14px;margin-top:6px;">Peak list</summary>${peakTable(sp, isIR ? 'FTIR' : 'GC-MS', peaks)}</details>
        <div class="row"><button class="btn btn-outline" type="button" data-next>Next NIST spectrum</button>
        <button class="btn btn-outline" type="button" data-csv>Download CSV</button></div>`;
      el.querySelector('[data-next]').onclick = () => nistBlock(s, kind, index + 1, el);
      el.querySelector('[data-csv]').onclick = () => download(`${s.identity.name}_NIST_${kind}_${index + 1}.csv`, 'x,y\n' + sp.x.map((x, i) => `${x},${sp.y[i]}`).join('\n'), 'text/csv');
    } catch (e) { el.innerHTML = `<p class="none">${esc(e.message)}</p>`; }
  }

  function pubchemSpectra(s) {
    const recs = s.spectra.records;
    if (!recs.length && !s.spectra.kovats.length) return '<p class="none">PubChem holds no spectral records for this substance.</p>';
    const groups = {};
    recs.forEach(r => { (groups[r.technique] = groups[r.technique] || []).push(r); });
    let html = '';
    for (const [tech, rs] of Object.entries(groups)) {
      const withPeaks = rs.filter(r => r.peaks.length).slice(0, 4);
      const isNmr = /NMR/.test(tech);
      const plots = withPeaks.map(r => {
        const sp = { x: r.peaks.map(p => p[0]), y: r.peaks.map(p => p[1] !== undefined ? p[1] : 100), sticks: true };
        const meta = Object.entries(r.fields).filter(([k, v]) => typeof v === 'string' && !/^Shifts|Spectra ID|Top 5/.test(k) && v).slice(0, 5).map(([k, v]) => `${esc(k)}: ${esc(v)}`).join(' · ');
        const link = r.links['Spectra ID'] || Object.values(r.links)[0];
        const peakText = r.peaks.map(p => p.map(n => +n.toFixed(2)).join(isNmr ? ' ppm (' : ' (') + ')').join(', ');
        const twoD = r.kind === 'nmr2d';
        return `<div class="spec"><h3>${esc(tech)}${cite(r.ref)}</h3><div class="src">${meta}${link ? ` · <a href="${esc(safeUrl(link))}" target="_blank" rel="noopener">source record</a>` : ''}</div>
          ${twoD ? '' : Spectra.plot([sp], { reverseX: /NMR/.test(tech), xLabel: /NMR/.test(tech) ? 'Chemical shift (ppm)' : 'm/z', yLabel: 'Relative intensity', height: 200,
            peaks: r.peaks.slice(0, 12).map(p => ({ x: p[0], y: p[1] !== undefined ? p[1] : 100, label: String(+p[0].toFixed(/NMR/.test(tech) ? 2 : 0)) })) })}
          <p style="font-size:13px;color:var(--text);margin-top:4px;"><b>Peaks:</b> ${esc(peakText)}</p></div>`;
      }).join('');
      const others = rs.filter(r => !withPeaks.includes(r)).map(r => {
        const meta = Object.entries(r.fields).filter(([, v]) => typeof v === 'string' && v).slice(0, 4).map(([k, v]) => `${esc(k)}: ${esc(v)}`).join(' · ');
        const link = r.links['Spectra ID'] || r.links.Thumbnail || Object.values(r.links)[0];
        return `${meta || 'Record'}${cite(r.ref)}${link ? ` — <a href="${esc(safeUrl(link))}" target="_blank" rel="noopener">view</a>` : ''}`;
      });
      html += plots + (others.length ? `<div class="spec blk"><h3>${esc(tech)} — more records (${others.length})</h3>${list(others, 3)}</div>` : '');
    }
    if (s.spectra.kovats.length) {
      html += `<div class="spec"><h3>GC retention indices (Kovats)${cite(s.spectra.kovats[0].ref)}</h3>
        <div class="src">Use these to confirm a GC peak's identity on the same column type.</div>
        <div class="tw"><table class="t"><thead><tr><th>Column type</th><th>Median RI</th><th>Range</th><th>Measurements</th></tr></thead><tbody>
        ${s.spectra.kovats.map(k => `<tr><td>${esc(k.column)}</td><td>${k.median}</td><td>${k.min}–${k.max}</td><td>${k.n}</td></tr>`).join('')}</tbody></table></div></div>`;
    }
    return html;
  }

  async function renderSpectra(s) {
    const el = $('#p-spectra');
    el.innerHTML = `
      <div class="callout">Reference data: full IR and mass spectra from the <b>NIST Chemistry WebBook</b>, plus NMR shifts, GC-MS peaks and GC retention indices
        from <b>PubChem</b>. Below that, attach <b>your own collected data</b> (FTIR, NMR, GC, GC-MS…). It is stored only in this browser.</div>
      <h3 style="margin:16px 0 4px;">Your lab data for ${esc(s.identity.name)}</h3>
      <div class="spec noprint">
        <div class="drop" id="drop">Drop JCAMP-DX (.jdx, .dx) or two-column CSV / TXT files here, or <label style="color:var(--teal);cursor:pointer;text-decoration:underline;">choose files<input type="file" id="file" multiple accept=".jdx,.dx,.jcamp,.csv,.txt,.tsv,.asc,.prn" hidden></label></div>
        <div class="row"><label>Technique <select id="tech">${Object.entries(TECH).map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join('')}</select></label>
          <input type="text" id="dsLabel" placeholder="Label (sample, batch, instrument)" style="flex:1;min-width:180px;">
          <input type="date" id="dsDate" value="${today()}" aria-label="Date collected"></div>
        <textarea id="dsNotes" rows="2" placeholder="Notes (method, solvent, column, conditions)" style="width:100%;"></textarea>
      </div>
      <div id="myData"></div>
      <h3 style="margin:22px 0 4px;">Reference spectra</h3>
      ${s.identity.cas ? '<div class="grid2"><div class="spec" id="nistIR"></div><div class="spec" id="nistMS"></div></div>' : '<p class="none">No CAS number, so NIST spectra can\'t be looked up.</p>'}
      <h3 style="margin:22px 0 4px;">Stored NMR, MS, IR and GC data (PubChem)</h3>
      ${pubchemSpectra(s)}`;
    if (s.identity.cas) { nistBlock(s, 'IR', 0, $('#nistIR')); nistBlock(s, 'Mass', 0, $('#nistMS')); }
    const drop = $('#drop');
    drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('over'); });
    drop.addEventListener('dragleave', () => drop.classList.remove('over'));
    drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('over'); addFiles(s, e.dataTransfer.files); });
    $('#file').addEventListener('change', e => addFiles(s, e.target.files));
    renderMyData(s);
  }

  async function addFiles(s, files) {
    for (const f of files) {
      if (f.size > 20e6) { setStatus(`${f.name} is over 20 MB, so it was skipped.`, true); continue; }
      try {
        const text = await f.text();
        const sp = Spectra.parse(text, f.name);
        let tech = $('#tech').value;
        if (/INFRARED/i.test(sp.dataType)) tech = 'FTIR';
        else if (/NMR/i.test(sp.dataType)) tech = /13C/.test(sp.meta['.OBSERVENUCLEUS'] || sp.meta.OBSERVENUCLEUS || '') ? 'NMR 13C' : 'NMR 1H';
        else if (/MASS/i.test(sp.dataType)) tech = 'GC-MS';
        await DB.put('datasets', {
          cid: s.identity.cid, substance: s.identity.name, cas: s.identity.cas, technique: tech,
          label: $('#dsLabel').value.trim() || f.name, filename: f.name, collected: $('#dsDate').value || today(),
          notes: $('#dsNotes').value.trim(), added: new Date().toISOString(), x: sp.x, y: sp.y,
          xUnits: sp.xUnits, yUnits: sp.yUnits, sticks: sp.sticks || sticksFor(tech), dataType: sp.dataType || '',
        });
        setStatus(`Saved ${f.name} (${sp.x.length} points) to this browser.`);
      } catch (e) { setStatus(`${f.name}: ${e.message}`, true); }
    }
    renderMyData(s); renderRegister(); renderLibraryHome();
  }

  async function renderMyData(s) {
    const el = $('#myData');
    const sets = await DB.byCid(s.identity.cid);
    if (!sets.length) { el.innerHTML = '<p class="muted" style="font-size:14px;">No data of yours stored for this substance yet.</p>'; return; }
    el.innerHTML = sets.map(d => `<div class="spec" data-id="${d.id}">
        <h3>${esc(TECH[d.technique] || d.technique)} — ${esc(d.label)}</h3>
        <div class="src">${esc(d.filename)} · collected ${esc(d.collected)} · ${d.x.length} points${d.notes ? ' · ' + esc(d.notes) : ''}</div>
        <div class="plotHere"></div>
        <div class="row noprint">
          ${/FTIR|GC-MS/.test(d.technique) && s.identity.cas ? '<label style="font-size:14px;"><input type="checkbox" data-overlay> Overlay the NIST reference</label>' : ''}
          <button class="btn btn-outline" type="button" data-csv>Download CSV</button>
          <button class="btn btn-outline" type="button" data-del>Delete</button></div>
        <details><summary class="muted" style="cursor:pointer;font-size:14px;">Peak list</summary><div class="peaks"></div></details></div>`).join('');
    sets.forEach(d => {
      const card = el.querySelector(`[data-id="${d.id}"]`);
      const sp = { x: d.x, y: d.y, sticks: d.sticks, yUnits: d.yUnits, xUnits: d.xUnits, dataType: d.dataType };
      const peaks = Spectra.pickPeaks(sp, { max: 15 });
      const labels = axisLabels(sp, d.technique);
      const draw = overlay => {
        const series = [{ x: d.x, y: d.y, sticks: d.sticks, normalise: !!overlay, color: 'var(--plot2)' }];
        if (overlay) series.unshift({ ...overlay, normalise: true, color: 'var(--plot1)' });
        card.querySelector('.plotHere').innerHTML = Spectra.plot(series, { reverseX: reverseFor(d.technique), ...labels,
          yLabel: overlay ? 'Normalised (0–100)' : labels.yLabel,
          peaks: overlay ? [] : peaks.map(p => ({ x: p.x, y: p.y, label: String(+p.x.toFixed(/NMR/.test(d.technique) ? 2 : 0)) })) });
      };
      draw(null);
      card.querySelector('.plotHere').insertAdjacentHTML('afterend', '<div class="legend muted" style="font-size:12px;display:none"><i style="background:var(--plot2)"></i>Your data<i style="background:var(--plot1)"></i>NIST reference</div>');
      card.querySelector('.peaks').innerHTML = peakTable(sp, d.technique, peaks);
      const ov = card.querySelector('[data-overlay]');
      if (ov) ov.onchange = () => {
        const ref = $(d.technique === 'FTIR' ? '#nistIR' : '#nistMS');
        draw(ov.checked && ref && ref._spectrum ? ref._spectrum : null);
        card.querySelector('.legend').style.display = ov.checked && ref && ref._spectrum ? 'block' : 'none';
        if (ov.checked && !(ref && ref._spectrum)) setStatus('The NIST reference spectrum is not available for overlay.', true);
      };
      card.querySelector('[data-csv]').onclick = () => download(`${d.label.replace(/\W+/g, '_')}.csv`, `x,y\n${d.x.map((x, i) => `${x},${d.y[i]}`).join('\n')}`, 'text/csv');
      card.querySelector('[data-del]').onclick = async () => { await DB.del('datasets', d.id); renderMyData(s); renderLibraryHome(); };
    });
  }

  // ---------------------------------------------------------------- register
  async function saveToRegister(s) {
    const existing = await DB.get('substances', s.identity.cid);
    await DB.put('substances', {
      ...(existing || { location: '', quantity: '', reviewDue: addMonths(today(), 12), notes: '', sds: [] }),
      cid: s.identity.cid, name: s.identity.name, cas: s.identity.cas, savedAt: today(), sheet: s,
      flags: s.guidance.flags.map(f => f.label), signal: s.ghs.signal, wel: !!s.wel,
    });
    setStatus(`${s.identity.name} saved to your register (in this browser), with an offline copy of the sheet.`);
    renderRegister(); renderLibraryHome(); showTab('register');
  }

  async function renderRegister() {
    const el = $('#p-register');
    if (!el || !current) return;
    const rec = await DB.get('substances', current.identity.cid);
    if (!rec) {
      el.innerHTML = `<div class="callout">Add this substance to your COSHH register to record where it's kept, its review date, and the supplier's SDS PDF. Everything stays in this browser.</div>
        <button class="btn btn-primary" type="button" id="saveBtn2">Add ${esc(current.identity.name)} to my register</button>`;
      $('#saveBtn2').onclick = () => saveToRegister(current);
      return;
    }
    const files = (await DB.all('files')).filter(f => f.cid === rec.cid);
    el.innerHTML = `<div class="spec">
      <h3>${esc(rec.name)} in your register</h3>
      <div class="row"><label>Location <input type="text" id="rLoc" value="${esc(rec.location)}" placeholder="e.g. Lab 2, flammables cabinet"></label>
        <label>Quantity held <input type="text" id="rQty" value="${esc(rec.quantity)}" placeholder="e.g. 4 × 2.5 L"></label>
        <label>Review due <input type="date" id="rDue" value="${esc(rec.reviewDue)}"></label></div>
      <textarea id="rNotes" rows="2" style="width:100%;" placeholder="Tasks it's used for, assessment reference, responsible person">${esc(rec.notes)}</textarea>
      <div class="row"><button class="btn btn-primary" type="button" id="rSave">Save</button>
        <button class="btn btn-outline" type="button" id="rRefresh">Refresh the offline copy</button>
        <button class="btn btn-outline" type="button" id="rDel">Remove from register</button></div>
      <h3 style="margin-top:14px;">Supplier SDS documents</h3>
      <div class="row"><input type="text" id="fSupplier" placeholder="Supplier"><label>Revision date <input type="date" id="fRev"></label>
        <label class="btn btn-outline" style="cursor:pointer;">Attach PDF<input type="file" id="fPdf" accept="application/pdf,.pdf" hidden></label></div>
      ${files.length ? `<div class="tw"><table class="t"><thead><tr><th>File</th><th>Supplier</th><th>Revision</th><th>Age</th><th></th></tr></thead><tbody>
        ${files.map(f => { const age = f.revision ? Math.floor((Date.now() - new Date(f.revision)) / 3.156e10 * 10) / 10 : null;
          return `<tr><td><a href="#" data-open="${f.id}">${esc(f.name)}</a></td><td>${esc(f.supplier)}</td><td>${esc(f.revision || '–')}</td>
          <td class="${age !== null && age >= 3 ? 'overdue' : ''}">${age !== null ? age + ' yrs' : '–'}</td><td><button class="more" data-fdel="${f.id}" type="button">delete</button></td></tr>`; }).join('')}
        </tbody></table></div><p class="muted" style="font-size:12px;">Ask the supplier for the current revision whenever an SDS is more than about 3 years old, or when you buy again. Suppliers must send an updated SDS when the hazard information changes.</p>` : '<p class="muted" style="font-size:14px;">No supplier SDS attached yet.</p>'}
    </div>`;
    $('#rSave').onclick = async () => {
      Object.assign(rec, { location: $('#rLoc').value, quantity: $('#rQty').value, reviewDue: $('#rDue').value, notes: $('#rNotes').value });
      await DB.put('substances', rec); setStatus('Register entry saved.'); renderLibraryHome();
    };
    $('#rRefresh').onclick = async () => { rec.sheet = current; rec.savedAt = today(); await DB.put('substances', rec); setStatus('Offline copy refreshed.'); renderLibraryHome(); };
    $('#rDel').onclick = async () => { await DB.del('substances', rec.cid); renderRegister(); renderLibraryHome(); setStatus('Removed from your register.'); };
    $('#fPdf').onchange = async e => {
      const f = e.target.files[0];
      if (!f) return;
      if (f.size > 30e6) { setStatus('That PDF is over 30 MB.', true); return; }
      await DB.put('files', { cid: rec.cid, name: f.name, supplier: $('#fSupplier').value.trim(), revision: $('#fRev').value, blob: f, added: today() });
      setStatus(`${f.name} attached.`); renderRegister();
    };
    el.querySelectorAll('[data-open]').forEach(a => a.onclick = async e => {
      e.preventDefault();
      const f = (await DB.all('files')).find(x => x.id === Number(a.dataset.open));
      if (f) window.open(URL.createObjectURL(f.blob), '_blank', 'noopener');
    });
    el.querySelectorAll('[data-fdel]').forEach(b => b.onclick = async () => { await DB.del('files', Number(b.dataset.fdel)); renderRegister(); });
  }

  async function renderLibraryHome() {
    const el = $('#libraryHome');
    const subs = await DB.all('substances'), sets = await DB.all('datasets');
    if (!subs.length && !sets.length) { el.innerHTML = ''; return; }
    const now = today();
    el.innerHTML = `<h2 style="font-size:1.4rem;margin-bottom:6px;">My COSHH register</h2>
      <p style="font-size:14px;">Kept in this browser only. Export a backup, or move it to another device with Import.</p>
      <div class="tw"><table class="t"><thead><tr><th>Substance</th><th>CAS</th><th>Signal</th><th>Key flags</th><th>Location</th><th>Review due</th><th>Lab data</th></tr></thead><tbody>
      ${subs.sort((a, b) => (a.reviewDue || '').localeCompare(b.reviewDue || '')).map(r => `<tr>
        <td><a href="#" data-q="${esc(r.cas || r.name)}">${esc(r.name)}</a></td><td>${esc(r.cas || '–')}</td><td>${esc(r.signal || '–')}</td>
        <td>${(r.flags || []).slice(0, 3).map(f => `<span class="chip">${esc(f)}</span>`).join('')}</td><td>${esc(r.location || '–')}</td>
        <td class="${r.reviewDue && r.reviewDue < now ? 'overdue' : ''}">${esc(r.reviewDue || '–')}${r.reviewDue && r.reviewDue < now ? ' (overdue)' : ''}</td>
        <td>${sets.filter(d => d.cid === r.cid).length}</td></tr>`).join('')}
      </tbody></table></div>
      ${sets.filter(d => !subs.some(r => r.cid === d.cid)).length ? `<p class="muted" style="font-size:13px;">Plus lab data for substances not in the register: ${[...new Set(sets.filter(d => !subs.some(r => r.cid === d.cid)).map(d => d.substance))].map(n => `<a href="#" data-q="${esc(n)}">${esc(n)}</a>`).join(', ')}</p>` : ''}
      <div class="row"><button class="btn btn-outline" type="button" id="exp">Export backup (JSON)</button>
        <button class="btn btn-outline" type="button" id="expCsv">Export register (CSV)</button>
        <label class="btn btn-outline" style="cursor:pointer;">Import backup<input type="file" id="imp" accept=".json,application/json" hidden></label></div>`;
    $('#exp').onclick = () => download(`coshh-register-${now}.json`, JSON.stringify({ format: 'lyra-coshh-1', exported: now, substances: subs, datasets: sets }), 'application/json');
    $('#expCsv').onclick = () => {
      const q = v => `"${String(v == null ? '' : v).replace(/"/g, '""')}"`;
      download(`coshh-register-${now}.csv`, ['Substance,CAS,Signal word,Flags,Location,Quantity,Review due,Notes',
        ...subs.map(r => [r.name, r.cas, r.signal, (r.flags || []).join('; '), r.location, r.quantity, r.reviewDue, r.notes].map(q).join(','))].join('\n'), 'text/csv');
    };
    $('#imp').onchange = async e => {
      try {
        const d = JSON.parse(await e.target.files[0].text());
        if (d.format !== 'lyra-coshh-1') throw new Error('Not a COSHH AI backup file.');
        for (const r of d.substances || []) if (r && typeof r.cid === 'number') await DB.put('substances', r);
        for (const ds of d.datasets || []) if (ds && Array.isArray(ds.x) && Array.isArray(ds.y)) await DB.put('datasets', ds);
        setStatus(`Imported ${(d.substances || []).length} substances and ${(d.datasets || []).length} datasets.`);
        renderLibraryHome(); if (current) { renderRegister(); renderMyData(current); }
      } catch (err) { setStatus(err.message, true); }
    };
  }

  // ---------------------------------------------------------------- start
  renderLibraryHome();
  const q0 = new URLSearchParams(location.search).get('q');
  if (q0) { input.value = q0; lookup(q0, true); }
})();
