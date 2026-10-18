/* COSHH AI — spectrum parsing, peak picking and plotting.
   Reads JCAMP-DX (AFFN and the compressed SQZ / DIF / DUP forms, XYDATA, XYPOINTS
   and PEAK TABLE) and two-column CSV / TXT exports from FTIR, NMR and GC software.
   Works in the browser (window.Spectra) and in Node (module.exports) for tests. */
(function (root) {
  'use strict';

  const SQZ = { '@': 0, A: 1, B: 2, C: 3, D: 4, E: 5, F: 6, G: 7, H: 8, I: 9,
                a: -1, b: -2, c: -3, d: -4, e: -5, f: -6, g: -7, h: -8, i: -9 };
  const DIF = { '%': 0, J: 1, K: 2, L: 3, M: 4, N: 5, O: 6, P: 7, Q: 8, R: 9,
                j: -1, k: -2, l: -3, m: -4, n: -5, o: -6, p: -7, q: -8, r: -9 };
  const DUP = { S: 1, T: 2, U: 3, V: 4, W: 5, X: 6, Y: 7, Z: 8, s: 9 };
  const COMPRESSED = /[@A-DF-Ia-df-i%J-Rj-rS-Zs]/;

  function signed(digit, rest) {
    const mag = Number(String(Math.abs(digit)) + rest);
    return digit < 0 ? -mag : mag;
  }

  // One data line -> { values, endsWithDif }. The first value is the line's X.
  function decodeLine(line) {
    line = line.replace(/\$\$.*$/, '').trim();
    if (!line) return { values: [], endsWithDif: false };
    if (!COMPRESSED.test(line)) {
      const nums = line.match(/[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?/g) || [];
      return { values: nums.map(Number), endsWithDif: false };
    }
    const tokens = line.match(/[@A-Ia-i%J-Rj-rS-Zs][0-9.]*|[+-]?[0-9.]+/g) || [];
    const values = [];
    let lastDif = false, lastDelta = 0;
    for (const t of tokens) {
      const c = t[0], rest = t.slice(1);
      if (c in SQZ) { values.push(signed(SQZ[c], rest)); lastDif = false; }
      else if (c in DIF) {
        lastDelta = signed(DIF[c], rest);
        values.push(values[values.length - 1] + lastDelta); lastDif = true;
      } else if (c in DUP) {
        const count = Number(String(DUP[c]) + rest);
        for (let k = 1; k < count; k++) {
          values.push(lastDif ? values[values.length - 1] + lastDelta : values[values.length - 1]);
        }
      } else { values.push(Number(t)); lastDif = false; }
    }
    return { values, endsWithDif: lastDif };
  }

  function parseJcamp(text) {
    const meta = {};
    const lines = text.split(/\r?\n/);
    let mode = null; const data = [];
    for (const raw of lines) {
      const m = raw.match(/^##([^=]+)=(.*)$/);
      if (m) {
        const key = m[1].trim().toUpperCase().replace(/[\s_-]/g, '');
        const val = m[2].trim();
        if (key === 'XYDATA') mode = /\(X\+\+\(Y\.\.Y\)\)/i.test(val) ? 'xy++' : 'pairs';
        else if (key === 'XYPOINTS' || key === 'PEAKTABLE') mode = 'pairs';
        else if (key === 'END') { if (mode) break; }
        else { mode = mode && key.startsWith('$') ? mode : null; meta[key] = val; }
        continue;
      }
      if (mode) data.push(raw);
    }
    const num = (k, d) => (meta[k] !== undefined && meta[k] !== '' && !isNaN(Number(meta[k])) ? Number(meta[k]) : d);
    const xf = num('XFACTOR', 1), yf = num('YFACTOR', 1);
    let x = [], y = [];
    if (!data.length) throw new Error('No XYDATA, XYPOINTS or PEAK TABLE found in this JCAMP file.');
    // Decide the layout from the header that introduced the data.
    const header = (text.match(/##(XYDATA|XYPOINTS|PEAK\s*TABLE)=([^\r\n]*)/i) || [])[0] || '';
    if (/\(X\+\+\(Y\.\.Y\)\)/i.test(header)) {
      let prevDif = false; const ys = []; const lineX = [];
      for (const line of data) {
        const { values, endsWithDif } = decodeLine(line);
        if (values.length < 1) continue;
        let yv = values.slice(1);
        if (prevDif && yv.length) yv = yv.slice(1); // DIF Y-check value repeats the previous line's last Y
        lineX.push([values[0], ys.length]);
        ys.push(...yv);
        prevDif = endsWithDif;
      }
      const n = ys.length;
      const first = num('FIRSTX', lineX.length ? lineX[0][0] * xf : 0);
      const last = num('LASTX', NaN);
      const step = n > 1 && !isNaN(last) ? (last - first) / (n - 1)
        : num('DELTAX', lineX.length > 1 ? ((lineX[1][0] - lineX[0][0]) * xf) / (lineX[1][1] - lineX[0][1]) : 1);
      x = ys.map((_, i) => first + i * step);
      y = ys.map(v => v * yf);
    } else {
      for (const line of data) {
        const clean = line.replace(/\$\$.*$/, '');
        const nums = clean.match(/[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?/g) || [];
        for (let i = 0; i + 1 < nums.length; i += 2) { x.push(Number(nums[i]) * xf); y.push(Number(nums[i + 1]) * yf); }
      }
    }
    const dataType = (meta.DATATYPE || '').toUpperCase();
    const sticks = /MASS|PEAK/.test(dataType) || /PEAK\s*TABLE/i.test(header);
    return {
      title: meta.TITLE || '', dataType, xUnits: meta.XUNITS || '', yUnits: meta.YUNITS || '',
      cas: meta.CASREGISTRYNO || '', origin: meta.ORIGIN || '', owner: meta.OWNER || '', state: meta.STATE || '',
      meta, x, y, sticks,
    };
  }

  // Two-column text: CSV, TSV, semicolon or space separated; header lines are skipped.
  function parseColumns(text) {
    const x = [], y = [];
    let header = null;
    for (const raw of text.split(/\r?\n/)) {
      const line = raw.trim();
      if (!line || line.startsWith('#')) continue;
      const parts = line.split(/[,;\t ]+/).filter(Boolean);
      const nums = parts.map(p => Number(p.replace(/^"|"$/g, '')));
      if (nums.length >= 2 && !isNaN(nums[0]) && !isNaN(nums[1])) { x.push(nums[0]); y.push(nums[1]); }
      else if (!x.length && !header) header = parts;
    }
    if (x.length < 2) throw new Error('Could not find two numeric columns (x, y) in this file.');
    return { title: '', xUnits: header ? header[0] : '', yUnits: header && header[1] ? header[1] : '', x, y, sticks: false };
  }

  function parse(text, filename) {
    if (/^\s*##TITLE/m.test(text) || /\.(jdx|dx|jcamp)$/i.test(filename || '')) return parseJcamp(text);
    return parseColumns(text);
  }

  const isTransmittance = s => /TRANSMITTANCE/i.test(s.yUnits || '');

  // Local maxima (or minima for % transmittance) that stand out by `prominence` of the range.
  function pickPeaks(s, { max = 15, prominence = 0.05 } = {}) {
    const n = s.y.length;
    if (!n) return [];
    if (s.sticks) {
      return s.x.map((x, i) => ({ x, y: s.y[i] })).sort((a, b) => b.y - a.y).slice(0, max);
    }
    const flip = isTransmittance(s) ? -1 : 1;
    const v = s.y.map(t => t * flip);
    const lo = Math.min(...v), hi = Math.max(...v), range = hi - lo || 1;
    const w = Math.max(2, Math.round(n / 300));
    const peaks = [];
    for (let i = w; i < n - w; i++) {
      let isMax = true;
      for (let k = i - w; k <= i + w; k++) if (v[k] > v[i] || (v[k] === v[i] && k < i)) { isMax = false; break; }
      if (!isMax) continue;
      // Prominence against the lowest point on each side within a wide window.
      const span = Math.max(w * 10, Math.round(n / 40));
      let left = v[i], right = v[i];
      for (let k = Math.max(0, i - span); k < i; k++) left = Math.min(left, v[k]);
      for (let k = i + 1; k <= Math.min(n - 1, i + span); k++) right = Math.min(right, v[k]);
      const prom = v[i] - Math.max(left, right);
      if (prom / range >= prominence) peaks.push({ x: s.x[i], y: s.y[i], prom });
    }
    return peaks.sort((a, b) => b.prom - a.prom).slice(0, max).sort((a, b) => a.x - b.x);
  }

  // Textbook IR correlation ranges (cm-1). Shown as "possible" assignments only.
  const IR_BANDS = [
    [3584, 3700, 'O–H (free alcohol / phenol)'], [3200, 3550, 'O–H (H-bonded alcohol / water)'],
    [3300, 3500, 'N–H stretch (amine / amide)'], [3267, 3333, '≡C–H stretch (alkyne)'],
    [2500, 3300, 'O–H (carboxylic acid, broad)'], [3000, 3100, '=C–H stretch (alkene / aromatic)'],
    [2840, 3000, 'C–H stretch (alkane)'], [2695, 2830, 'C–H (aldehyde)'], [2550, 2600, 'S–H stretch (thiol)'],
    [2349, 2349, 'CO₂ (atmospheric)'], [2210, 2260, 'C≡N stretch (nitrile)'], [2100, 2260, 'C≡C stretch (alkyne)'],
    [2250, 2275, 'N=C=O stretch (isocyanate)'], [1735, 1750, 'C=O (ester)'], [1720, 1740, 'C=O (aldehyde)'],
    [1705, 1725, 'C=O (ketone)'], [1700, 1725, 'C=O (carboxylic acid)'], [1630, 1690, 'C=O (amide)'],
    [1800, 1830, 'C=O (anhydride / acid halide)'], [1620, 1680, 'C=C stretch (alkene)'],
    [1450, 1600, 'C=C (aromatic ring)'], [1500, 1570, 'N–O (nitro, asym.)'], [1300, 1390, 'N–O (nitro, sym.)'],
    [1350, 1480, 'C–H bend (alkane)'], [1000, 1300, 'C–O stretch (alcohol / ether / ester)'],
    [1020, 1250, 'C–N stretch (amine)'], [1000, 1400, 'C–F stretch'], [600, 800, 'C–Cl stretch'],
    [500, 600, 'C–Br stretch'], [675, 900, '=C–H bend (aromatic out-of-plane)'],
  ];

  function irAssign(wavenumber) {
    return IR_BANDS.filter(([a, b]) => wavenumber >= a - 10 && wavenumber <= b + 10).map(b => b[2]);
  }

  // ---- SVG plot ------------------------------------------------------------
  function niceTicks(lo, hi, count) {
    const span = hi - lo || 1;
    const step0 = span / count, mag = Math.pow(10, Math.floor(Math.log10(step0)));
    const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= step0) || step0;
    const out = [];
    for (let t = Math.ceil(lo / step) * step; t <= hi + 1e-9; t += step) out.push(+t.toFixed(10));
    return out;
  }

  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  /* series: [{ x, y, sticks, label, color, normalise }]
     opts: { reverseX, xLabel, yLabel, peaks: [{x,y,label}], height } */
  function plot(series, opts = {}) {
    const W = 720, H = opts.height || 300, L = 54, R = 14, T = 14, B = 44;
    const pts = series.filter(s => s.x.length);
    if (!pts.length) return '<p class="muted">No data points.</p>';
    const norm = s => {
      if (!s.normalise) return s.y;
      const lo = Math.min(...s.y), hi = Math.max(...s.y), r = hi - lo || 1;
      return s.y.map(v => (v - lo) / r * 100);
    };
    const ys = pts.map(norm);
    let x0 = Math.min(...pts.map(s => Math.min(...s.x))), x1 = Math.max(...pts.map(s => Math.max(...s.x)));
    let y0 = Math.min(0, ...ys.map(a => Math.min(...a))), y1 = Math.max(...ys.map(a => Math.max(...a)));
    if (x0 === x1) { x0 -= 1; x1 += 1; }
    if (y0 === y1) y1 = y0 + 1;
    y1 += (y1 - y0) * 0.06;
    const sx = x => opts.reverseX ? L + (x1 - x) / (x1 - x0) * (W - L - R) : L + (x - x0) / (x1 - x0) * (W - L - R);
    const sy = y => T + (y1 - y) / (y1 - y0) * (H - T - B);
    let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opts.title || 'Spectrum plot')}" class="plot">`;
    for (const t of niceTicks(x0, x1, 8)) {
      svg += `<line x1="${sx(t)}" x2="${sx(t)}" y1="${T}" y2="${H - B}" class="grid"/><text x="${sx(t)}" y="${H - B + 16}" text-anchor="middle" class="p-tick">${t}</text>`;
    }
    for (const t of niceTicks(y0, y1, 5)) {
      svg += `<line x1="${L}" x2="${W - R}" y1="${sy(t)}" y2="${sy(t)}" class="grid"/><text x="${L - 6}" y="${sy(t) + 4}" text-anchor="end" class="p-tick">${+t.toPrecision(4)}</text>`;
    }
    svg += `<line x1="${L}" x2="${W - R}" y1="${H - B}" y2="${H - B}" class="axis"/><line x1="${L}" x2="${L}" y1="${T}" y2="${H - B}" class="axis"/>`;
    pts.forEach((s, k) => {
      const yv = ys[k], color = s.color || 'var(--plot1)';
      if (s.sticks) {
        s.x.forEach((x, i) => { svg += `<line x1="${sx(x)}" x2="${sx(x)}" y1="${sy(Math.max(y0, 0))}" y2="${sy(yv[i])}" stroke="${color}" stroke-width="1.6"/>`; });
      } else {
        const step = Math.max(1, Math.floor(s.x.length / 2400));
        let d = '';
        for (let i = 0; i < s.x.length; i += step) d += (d ? 'L' : 'M') + sx(s.x[i]).toFixed(1) + ',' + sy(yv[i]).toFixed(1);
        svg += `<path d="${d}" fill="none" stroke="${color}" stroke-width="1.3"/>`;
      }
    });
    (opts.peaks || []).forEach(p => {
      svg += `<text x="${sx(p.x)}" y="${Math.max(T + 10, sy(p.y) - 5)}" text-anchor="middle" class="p-peak">${esc(p.label)}</text>`;
    });
    svg += `<text x="${(L + W - R) / 2}" y="${H - 6}" text-anchor="middle" class="p-label">${esc(opts.xLabel || '')}</text>`;
    svg += `<text transform="translate(13 ${(T + H - B) / 2}) rotate(-90)" text-anchor="middle" class="p-label">${esc(opts.yLabel || '')}</text>`;
    return svg + '</svg>';
  }

  const api = { parse, parseJcamp, parseColumns, decodeLine, pickPeaks, irAssign, plot, isTransmittance };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.Spectra = api;
})(typeof window !== 'undefined' ? window : globalThis);
