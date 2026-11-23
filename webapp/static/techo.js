/* Plano de techo — editor: aerial photo + scaled solar-module strings (move, rotate, rows, orientation) with fit checks.
   The geometry mirrors techo/geometry.py (photo pixels, y down, rotation clockwise). State saves itself through D.saveUrl. */
(function () {
  const D = JSON.parse(document.getElementById('techo-data').textContent);
  const NS = 'http://www.w3.org/2000/svg';
  const $ = (id) => document.getElementById(id);
  const svg = $('tc-svg'), world = $('tc-world'), stage = $('tc-stage');
  const info = D.info, panel = info.panel;
  let plan = D.plan, photoUrl = D.photoUrl;
  let sel = plan.strings.length ? plan.strings[0].id : null;
  let tool = 'select', tmp = [], view = { x: 0, y: 0, k: 1 }, drag = null, saveTimer = null;

  /* ---------- geometry (same maths as techo/geometry.py) ---------- */
  const pxPerM = () => (plan.scale ? plan.scale.px_per_m : (plan.photo ? plan.photo.w / 40 : 50));   // provisional 40 m wide until calibrated
  const gapM = () => (plan.gap_mm || 0) / 1000;
  const modDims = (s) => (s.orient === 'landscape' ? [panel.height_m, panel.width_m] : [panel.width_m, panel.height_m]);
  function block(s) {
    const [w, h] = modDims(s), count = Math.max(0, s.count | 0), rows = Math.max(1, Math.min(s.rows | 0 || 1, Math.max(1, count)));
    const cols = Math.max(1, Math.ceil(count / rows)), g = gapM();
    return { w, h, rows, cols, W: cols * w + (cols - 1) * g, H: rows * h + (rows - 1) * g };
  }
  const rot = (x, y, deg) => { const a = deg * Math.PI / 180, c = Math.cos(a), s = Math.sin(a); return [x * c - y * s, x * s + y * c]; };
  function polys(s) {
    const b = block(s), k = pxPerM(), g = gapM(), out = [];
    for (let i = 0; i < (s.count | 0); i++) {
      const r = Math.floor(i / b.cols), c = i % b.cols;
      const x0 = -b.W / 2 + c * (b.w + g), y0 = -b.H / 2 + r * (b.h + g);
      out.push([[x0, y0], [x0 + b.w, y0], [x0 + b.w, y0 + b.h], [x0, y0 + b.h]].map(([lx, ly]) => {
        const [rx, ry] = rot(lx * k, ly * k, s.rot || 0); return [s.x + rx, s.y + ry];
      }));
    }
    return out;
  }
  function outline(s) {   // rotated bounding block of a string
    const b = block(s), k = pxPerM();
    return [[-b.W / 2, -b.H / 2], [b.W / 2, -b.H / 2], [b.W / 2, b.H / 2], [-b.W / 2, b.H / 2]].map(([lx, ly]) => {
      const [rx, ry] = rot(lx * k, ly * k, s.rot || 0); return [s.x + rx, s.y + ry];
    });
  }
  function axes(p) { return p.map((a, i) => { const b = p[(i + 1) % p.length], ex = b[0] - a[0], ey = b[1] - a[1], n = Math.hypot(ex, ey) || 1; return [-ey / n, ex / n]; }); }
  function overlap(a, b) {
    for (const [ax, ay] of axes(a).concat(axes(b))) {
      const pa = a.map((p) => p[0] * ax + p[1] * ay), pb = b.map((p) => p[0] * ax + p[1] * ay);
      if (Math.max(...pa) <= Math.min(...pb) + 0.5 || Math.max(...pb) <= Math.min(...pa) + 0.5) return false;
    }
    return true;
  }
  function inPoly(pt, poly) {
    let inside = false;
    for (let i = 0, n = poly.length; i < n; i++) {
      const [x1, y1] = poly[i], [x2, y2] = poly[(i + 1) % n];
      if ((y1 > pt[1]) !== (y2 > pt[1]) && pt[0] < (x2 - x1) * (pt[1] - y1) / ((y2 - y1) || 1e-12) + x1) inside = !inside;
    }
    return inside;
  }
  function checks() {
    const P = {}, overlaps = [], outside = {};
    plan.strings.forEach((s) => { P[s.id] = polys(s); });
    const ids = plan.strings.map((s) => s.id);
    for (let i = 0; i < ids.length; i++) for (let j = i + 1; j < ids.length; j++)
      if (P[ids[i]].some((a) => P[ids[j]].some((b) => overlap(a, b)))) overlaps.push([ids[i], ids[j]]);
    if (plan.roof.length >= 3) plan.strings.forEach((s) => {
      const n = P[s.id].filter((q) => !q.every((p) => inPoly(p, plan.roof))).length; if (n) outside[s.id] = n;
    });
    return { P, overlaps, outside };
  }

  /* ---------- drawing ---------- */
  const el = (name, attrs, parent) => { const e = document.createElementNS(NS, name); for (const k in attrs) e.setAttribute(k, attrs[k]); (parent || world).appendChild(e); return e; };
  const pts = (p) => p.map((q) => q[0].toFixed(1) + ',' + q[1].toFixed(1)).join(' ');
  const color = (id) => D.colors[(id - 1) % D.colors.length];

  function render() {
    world.setAttribute('transform', `translate(${view.x} ${view.y}) scale(${view.k})`);
    world.textContent = '';
    $('tc-empty').hidden = !!(plan.photo && photoUrl);
    if (plan.photo && photoUrl) el('image', { href: photoUrl, x: 0, y: 0, width: plan.photo.w, height: plan.photo.h });
    const inv = 1 / view.k;
    if (plan.roof.length >= 3) el('polygon', { points: pts(plan.roof), fill: 'rgba(255,255,255,.06)', stroke: '#fff', 'stroke-width': 2 * inv, 'stroke-dasharray': `${8 * inv} ${5 * inv}`, 'pointer-events': 'none' });
    const c = checks();
    const bad = new Set([].concat(...c.overlaps));
    plan.strings.forEach((s) => {
      const g = el('g', { 'data-id': s.id, style: 'cursor:move' });
      c.P[s.id].forEach((q) => el('polygon', { points: pts(q), fill: color(s.id), 'fill-opacity': 0.6, stroke: bad.has(s.id) ? '#ff3b30' : '#fff', 'stroke-width': (bad.has(s.id) ? 2.2 : 1) * inv }, g));
      const o = outline(s);
      if (s.id === sel) el('polygon', { points: pts(o), fill: 'none', stroke: '#facc15', 'stroke-width': 2 * inv, 'stroke-dasharray': `${6 * inv} ${4 * inv}`, 'pointer-events': 'none' }, g);
      const cx = s.x, cy = s.y, t = el('text', { x: cx, y: cy + 5 * inv, 'text-anchor': 'middle', fill: '#fff', 'font-size': 16 * inv, 'font-weight': 700, 'pointer-events': 'none',
        style: 'paint-order:stroke;stroke:#000;stroke-width:' + 3 * inv + 'px' }, g);
      t.textContent = 'S' + s.id;
    });
    if (plan.scale && plan.scale.p1 && plan.scale.p2) {
      el('line', { x1: plan.scale.p1[0], y1: plan.scale.p1[1], x2: plan.scale.p2[0], y2: plan.scale.p2[1], stroke: '#22d3ee', 'stroke-width': 2 * inv, 'pointer-events': 'none' });
      const m = el('text', { x: (plan.scale.p1[0] + plan.scale.p2[0]) / 2, y: (plan.scale.p1[1] + plan.scale.p2[1]) / 2 - 6 * inv, 'text-anchor': 'middle', fill: '#22d3ee',
        'font-size': 13 * inv, 'font-weight': 700, 'pointer-events': 'none', style: 'paint-order:stroke;stroke:#000;stroke-width:' + 3 * inv + 'px' });
      m.textContent = plan.scale.dist_m + ' m';
    }
    if (tmp.length) {
      el('polyline', { points: pts(tmp), fill: 'none', stroke: tool === 'calib' ? '#22d3ee' : '#fff', 'stroke-width': 2 * inv, 'pointer-events': 'none' });
      tmp.forEach((p) => el('circle', { cx: p[0], cy: p[1], r: 4 * inv, fill: tool === 'calib' ? '#22d3ee' : '#fff' }));
    }
    side(c);
  }

  function side(c) {
    const list = $('tc-list'); list.textContent = '';
    plan.strings.forEach((s) => {
      const flag = c.overlaps.some((p) => p.includes(s.id)) ? 'choca' : (c.outside[s.id] ? 'fuera del techo' : '');
      const row = document.createElement('div'); row.className = 'tc-srow' + (s.id === sel ? ' on' : ''); row.dataset.id = s.id;
      row.innerHTML = `<span class="tc-chip" style="background:${color(s.id)}"></span><span class="t">S${s.id} · ${s.count} módulos</span><span class="f">${flag}</span>`;
      row.onclick = () => { sel = s.id; render(); };
      list.appendChild(row);
    });
    const s = plan.strings.find((x) => x.id === sel);
    $('tc-form').style.display = s ? '' : 'none';
    if (s) {
      const set = (id, v) => { const e = $(id); if (document.activeElement !== e) e.value = v; };
      set('f-count', s.count); set('f-rows', s.rows); set('f-orient', s.orient); set('f-rot', +(s.rot || 0).toFixed(1));
    }
    if (document.activeElement !== $('f-gap')) $('f-gap').value = plan.gap_mm;
    const placed = plan.strings.reduce((a, x) => a + (x.count | 0), 0), kwp = placed * panel.wp / 1000;
    const L = [];
    L.push(`Módulos: <b>${placed}</b> de ${info.panel_count} del diseño · ${kwp.toFixed(2)} kWp`);
    L.push(plan.scale ? `<span class="tc-ok">Escala calibrada</span> (${plan.scale.px_per_m.toFixed(1)} px/m)` : '<span class="tc-bad">Escala sin calibrar: las medidas no son reales</span>');
    if (c.overlaps.length) L.push(`<span class="tc-bad">Chocan: ${c.overlaps.map((p) => 'S' + p[0] + '–S' + p[1]).join(', ')}</span>`);
    const outs = Object.keys(c.outside);
    if (outs.length) L.push(`<span class="tc-bad">Fuera del contorno: ${outs.map((i) => 'S' + i + ' (' + c.outside[i] + ')').join(', ')}</span>`);
    if (plan.scale && !c.overlaps.length && !outs.length && placed === info.panel_count) L.push('<span class="tc-ok">✔ Todo cabe sin chocar</span>');
    if (plan.scale && placed !== info.panel_count) L.push(`<span class="tc-warn">Faltan o sobran ${Math.abs(info.panel_count - placed)} módulo(s) respecto al diseño</span>`);
    if (s) { const b = block(s); L.push(`S${s.id}: bloque de ${b.W.toFixed(2)} × ${b.H.toFixed(2)} m (${b.rows} fila(s) × ${b.cols})`); }
    $('tc-stat').innerHTML = L.join('<br>');
    $('tc-hint').textContent = tool === 'calib' ? (tmp.length ? 'Marca el segundo punto' : 'Calibrar: marca el primer punto de una medida real conocida')
      : tool === 'roof' ? 'Contorno: clic en cada esquina, doble clic para cerrar' : '';
    $('tc-hint').style.display = $('tc-hint').textContent ? '' : 'none';
    $('tc-calib').classList.toggle('on', tool === 'calib'); $('tc-roof').classList.toggle('on', tool === 'roof');
  }

  /* ---------- view + coordinates ---------- */
  function toWorld(e) { const r = svg.getBoundingClientRect(); return [(e.clientX - r.left - view.x) / view.k, (e.clientY - r.top - view.y) / view.k]; }
  function fit() {
    const r = svg.getBoundingClientRect(), w = plan.photo ? plan.photo.w : 2000, h = plan.photo ? plan.photo.h : 1125;
    view.k = Math.min(r.width / w, r.height / h) * 0.98; view.x = (r.width - w * view.k) / 2; view.y = (r.height - h * view.k) / 2;
  }

  /* ---------- saving ---------- */
  function save() {
    clearTimeout(saveTimer); $('tc-saved').textContent = 'Guardando…';
    saveTimer = setTimeout(() => {
      fetch(D.saveUrl, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(plan) })
        .then((r) => r.json()).then((j) => { $('tc-saved').textContent = j.ok ? 'Guardado ✓' : 'No se pudo guardar: ' + (j.error || ''); })
        .catch(() => { $('tc-saved').textContent = 'No se pudo guardar'; });
    }, 450);
  }
  const changed = () => { render(); save(); };

  /* ---------- pointer interaction ---------- */
  svg.addEventListener('pointerdown', (e) => {
    const p = toWorld(e);
    if (tool === 'calib' && plan.photo) {
      tmp.push(p);
      if (tmp.length === 2) {
        const d = Math.hypot(tmp[1][0] - tmp[0][0], tmp[1][1] - tmp[0][1]);
        const v = parseFloat(String(prompt('Distancia real entre los dos puntos (metros):', '10') || '').replace(',', '.'));
        if (v > 0 && d > 0) { plan.scale = { px_per_m: d / v, p1: tmp[0], p2: tmp[1], dist_m: v }; tool = 'select'; tmp = []; changed(); return; }
        tmp = [];
      }
      render(); return;
    }
    if (tool === 'roof' && plan.photo) { tmp.push(p); render(); return; }
    const g = e.target.closest && e.target.closest('g[data-id]');
    svg.setPointerCapture(e.pointerId);
    if (g) {
      sel = +g.dataset.id; const s = plan.strings.find((x) => x.id === sel);
      drag = { kind: 'string', s, dx: s.x - p[0], dy: s.y - p[1] }; render();
    } else drag = { kind: 'pan', sx: e.clientX, sy: e.clientY, vx: view.x, vy: view.y };
  });
  svg.addEventListener('pointermove', (e) => {
    if (!drag) return;
    if (drag.kind === 'pan') { view.x = drag.vx + e.clientX - drag.sx; view.y = drag.vy + e.clientY - drag.sy; render(); return; }
    const p = toWorld(e); drag.s.x = p[0] + drag.dx; drag.s.y = p[1] + drag.dy; render();
  });
  const end = () => { if (drag && drag.kind === 'string') save(); drag = null; };
  svg.addEventListener('pointerup', end); svg.addEventListener('pointercancel', end);
  svg.addEventListener('dblclick', () => {
    if (tool === 'roof' && tmp.length >= 3) { plan.roof = tmp.slice(0, tmp.length - (tmp.length > 3 ? 1 : 0)); tmp = []; tool = 'select'; changed(); }
  });
  svg.addEventListener('wheel', (e) => {
    e.preventDefault();
    const r = svg.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top, f = e.deltaY < 0 ? 1.12 : 1 / 1.12;
    const nk = Math.max(0.05, Math.min(40, view.k * f));
    view.x = mx - (mx - view.x) * (nk / view.k); view.y = my - (my - view.y) * (nk / view.k); view.k = nk; render();
  }, { passive: false });
  document.addEventListener('keydown', (e) => {
    if (/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) return;
    const s = plan.strings.find((x) => x.id === sel); if (!s) return;
    const step = (e.shiftKey ? 10 : 1) / view.k; let used = true;
    if (e.key === 'ArrowLeft') s.x -= step; else if (e.key === 'ArrowRight') s.x += step;
    else if (e.key === 'ArrowUp') s.y -= step; else if (e.key === 'ArrowDown') s.y += step;
    else if (e.key === '[') s.rot = ((s.rot || 0) - (e.shiftKey ? 5 : 1) + 360) % 360;
    else if (e.key === ']') s.rot = ((s.rot || 0) + (e.shiftKey ? 5 : 1)) % 360;
    else if (e.key === 'Escape') { tool = 'select'; tmp = []; } else used = false;
    if (used) { e.preventDefault(); changed(); }
  });

  /* ---------- controls ---------- */
  const cur = () => plan.strings.find((x) => x.id === sel);
  $('f-count').oninput = (e) => { const s = cur(); if (s) { s.count = Math.max(0, Math.min(200, parseInt(e.target.value, 10) || 0)); changed(); } };
  $('f-rows').oninput = (e) => { const s = cur(); if (s) { s.rows = Math.max(1, Math.min(20, parseInt(e.target.value, 10) || 1)); changed(); } };
  $('f-orient').onchange = (e) => { const s = cur(); if (s) { s.orient = e.target.value; changed(); } };
  $('f-rot').oninput = (e) => { const s = cur(); if (s) { s.rot = (((parseFloat(e.target.value) || 0) % 360) + 360) % 360; changed(); } };
  $('f-gap').oninput = (e) => { plan.gap_mm = Math.max(0, Math.min(200, parseFloat(e.target.value) || 0)); changed(); };
  document.querySelectorAll('[data-rot]').forEach((b) => b.onclick = () => {
    const s = cur(); if (!s) return; const v = +b.dataset.rot; s.rot = v === 0 ? 0 : (((s.rot || 0) + v) % 360 + 360) % 360; changed();
  });
  $('tc-add').onclick = () => {
    const id = plan.strings.reduce((m, s) => Math.max(m, s.id), 0) + 1, r = svg.getBoundingClientRect();
    plan.strings.push({ id, count: info.counts[0] || 8, rows: 1, orient: 'portrait', x: (r.width / 2 - view.x) / view.k, y: (r.height / 2 - view.y) / view.k, rot: 0 });
    sel = id; changed();
  };
  $('tc-del').onclick = () => { if (sel && confirm('¿Quitar el string S' + sel + '?')) { plan.strings = plan.strings.filter((s) => s.id !== sel); sel = plan.strings.length ? plan.strings[0].id : null; changed(); } };
  $('tc-reset').onclick = () => {
    if (!confirm('Esto vuelve a los strings del diseño y pierde los cambios de los strings. ¿Seguir?')) return;
    const w = plan.photo ? plan.photo.w : 2000, h = plan.photo ? plan.photo.h : 1125, n = Math.max(1, info.counts.length);
    plan.strings = (info.counts.length ? info.counts : [info.panel_count]).map((c, i) => ({ id: i + 1, count: c, rows: 1, orient: 'portrait', x: w / 2, y: h * (i + 1) / (n + 1), rot: 0 }));
    sel = plan.strings[0].id; changed();
  };
  $('tc-calib').onclick = () => { tool = tool === 'calib' ? 'select' : 'calib'; tmp = []; render(); };
  $('tc-roof').onclick = () => { tool = tool === 'roof' ? 'select' : 'roof'; tmp = []; render(); };
  $('tc-roof-clear').onclick = () => { plan.roof = []; changed(); };
  $('tc-fit').onclick = () => { fit(); render(); };
  $('tc-file').onchange = (e) => {
    const f = e.target.files[0]; if (!f) return;
    $('tc-saved').textContent = 'Subiendo foto…';
    const fd = new FormData(); fd.append('foto', f);
    fetch(D.photoPostUrl, { method: 'POST', body: fd }).then((r) => r.json()).then((j) => {
      if (!j.ok) { $('tc-saved').textContent = j.error || 'No se pudo subir la foto'; return; }
      plan = j.plan; photoUrl = j.photoUrl; sel = plan.strings.length ? plan.strings[0].id : null; tool = 'select'; tmp = [];
      $('tc-saved').textContent = 'Foto guardada. Ahora calibra la escala.'; fit(); render();
    }).catch(() => { $('tc-saved').textContent = 'No se pudo subir la foto'; });
    e.target.value = '';
  };

  window.addEventListener('resize', () => { render(); });
  fit(); render();
})();
