/* arXiv daily: static reader. Data comes from ./data/*.json written by the daily workflow.
   Personal state (watchlist, saved papers, filters) lives only in this browser's localStorage. */
(function () {
  'use strict';

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const KINDS = { new: 'New submissions', cross: 'Cross-lists', replace: 'Replacements' };
  const KIND_SHORT = { new: ['new', 'new'], cross: ['cross-list', 'cross-lists'], replace: ['replacement', 'replacements'] };
  const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

  /* ---------------- storage (never leaves the browser) ---------------- */
  const store = {
    get(k, d) { try { const v = localStorage.getItem('ad.' + k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem('ad.' + k, JSON.stringify(v)); } catch (e) {} }
  };

  const S = {
    index: null, date: null, day: null, cache: {},
    view: 'day',
    watch: store.get('watch', { keywords: [], authors: [] }),
    saved: store.get('saved', {}),
    filters: Object.assign({ cats: null, kinds: ['new', 'cross'], only: false }, store.get('filters', {})),
    q: '', cur: -1, expanded: new Set(), authorsOpen: new Set()
  };

  function toast(msg) { const t = $('#toast'); t.textContent = msg; t.classList.add('on'); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove('on'), 2000); }
  async function getJSON(p) { const r = await fetch(p, { cache: 'no-cache' }); if (!r.ok) throw new Error(`${p}: ${r.status}`); return r.json(); }

  function fmtDay(iso) {
    const [y, m, d] = iso.split('-').map(Number), dt = new Date(Date.UTC(y, m - 1, d));
    return `${DAYS[dt.getUTCDay()]} ${d} ${MONTHS[m - 1]} ${y}`;
  }

  /* ---------------- math + highlighting ---------------- */
  const katexCache = new Map();
  function tex(src, display) {
    const k = (display ? 'D' : 'I') + src;
    if (!katexCache.has(k)) {
      let h;
      try { h = window.katex ? katex.renderToString(src, { displayMode: display, throwOnError: false, trust: false, strict: 'ignore', maxExpand: 200, output: 'html' }) : esc(`$${src}$`); }
      catch (e) { h = esc(`$${src}$`); }
      katexCache.set(k, h);
    }
    return katexCache.get(k);
  }
  function highlight(text, res) {
    if (!res.length || !text) return esc(text);
    const spans = [];
    res.forEach(re => { re.lastIndex = 0; let m; while ((m = re.exec(text)) && m[0]) { spans.push([m.index, m.index + m[0].length]); if (!re.global) break; } });
    if (!spans.length) return esc(text);
    spans.sort((a, b) => a[0] - b[0]);
    let out = '', at = 0;
    for (const [a, b] of spans) { if (a < at) continue; out += esc(text.slice(at, a)) + '<mark>' + esc(text.slice(a, b)) + '</mark>'; at = b; }
    return out + esc(text.slice(at));
  }
  /** Escape text, render $…$ / $$…$$ with KaTeX, highlight watch keywords outside math. */
  function rich(text, res = []) {
    let out = '', at = 0;
    const re = /\$\$([\s\S]+?)\$\$|(?<!\\)\$([^$]+?)\$/g;
    let m;
    while ((m = re.exec(text || ''))) {
      out += highlight(text.slice(at, m.index), res);
      out += m[1] != null ? tex(m[1], true) : tex(m[2], false);
      at = m.index + m[0].length;
    }
    return out + highlight((text || '').slice(at), res);
  }

  /* ---------------- watchlist matching ---------------- */
  const norm = s => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z\s\-']/g, ' ').replace(/\s+/g, ' ').trim();
  function compileWatch() {
    const kws = S.watch.keywords.map(k => {
      let re;
      if (/^\/.+\/$/.test(k)) { try { re = new RegExp(k.slice(1, -1), 'gi'); } catch (e) { re = null; } }
      else {
        const body = k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '[\\s\\-]+');
        re = new RegExp((/^\w/.test(k) ? '\\b' : '') + body + (/\w$/.test(k) ? '\\b' : ''), 'gi');
      }
      return re && { label: k, re, t: new RegExp(re.source, 'i') };
    }).filter(Boolean);
    const aus = S.watch.authors.map(a => {
      let last, first = '';
      if (a.includes(',')) { [last, first] = a.split(',').map(norm); }
      else { const t = norm(a).split(' '); last = t.pop(); first = t[0] || ''; }
      return { label: a, last, initial: first ? first[0] : '' };
    }).filter(x => x.last);
    return { kws, aus };
  }
  let W = compileWatch();
  function authorHit(name) {
    const n = norm(name), toks = n.split(' ');
    return W.aus.find(w => (toks[toks.length - 1] === w.last || n.endsWith(' ' + w.last)) && (!w.initial || toks[0][0] === w.initial));
  }
  function score(p) {
    let s = 0; const why = [];
    p.authors.forEach(a => { const h = authorHit(a); if (h) { s += 5; why.push(h.label); } });
    const tags = (p.summary?.tags || []).join(' ');
    W.kws.forEach(k => {
      const t = k.t.test(p.title), g = k.t.test(tags), a = k.t.test(p.abstract + ' ' + (p.summary?.tldr || ''));
      if (t || g || a) { s += (t ? 3 : 0) + (g ? 2 : 0) + (a ? 1 : 0); why.push(k.label); }
    });
    return { s, why: [...new Set(why)] };
  }

  /* ---------------- filtering ---------------- */
  function visible(p) {
    const f = S.filters;
    if (f.cats && !p.listed_in.some(c => f.cats.includes(c))) return false;
    if (!f.kinds.includes(p.kind)) return false;
    if (S.q) {
      const hay = (p.title + ' ' + p.authors.join(' ') + ' ' + p.abstract + ' ' + (p.summary?.tldr || '') + ' ' + (p.summary?.tags || []).join(' ') + ' ' + p.id).toLowerCase();
      if (!S.q.toLowerCase().split(/\s+/).every(w => hay.includes(w))) return false;
    }
    return true;
  }

  /* ---------------- rendering ---------------- */
  const ICON_STAR = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 2.8l2.2 4.6 5 .7-3.6 3.5.9 5-4.5-2.4-4.5 2.4.9-5L2.8 8.1l5-.7z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>';
  const ICON_CHEV = '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M4 2.5 7.5 6 4 9.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  function authorsHtml(p, key) {
    const open = S.authorsOpen.has(key), max = 8, list = p.authors;
    const show = open || list.length <= max + 2 ? list : list.slice(0, max);
    const html = show.map(a => authorHit(a) ? `<span class="me">${esc(a)}</span>` : esc(a)).join(', ');
    const hidden = list.length - show.length;
    const hiddenHit = hidden > 0 && list.slice(max).some(authorHit);
    return html + (hidden > 0 ? `, <button type="button" class="more" data-authors="${esc(key)}">${hiddenHit ? 'and a watched author, ' : ''}+${hidden} more</button>` : '');
  }

  function card(p, n, sc, key) {
    const res = W.kws.map(k => new RegExp(k.re.source, 'gi'));
    const cats = [p.primary, ...p.categories.filter(c => c !== p.primary)].filter(Boolean);
    const saved = !!S.saved[p.id];
    const sum = p.summary;
    const open = S.expanded.has(key);
    const abs = `https://arxiv.org/abs/${p.id}`;
    return `<li class="card" data-id="${esc(p.id)}" data-key="${esc(key)}">
      <span class="num">${n}</span>
      <div>
        <div class="card-top">
          <a class="id" href="${abs}" rel="noreferrer" target="_blank">arXiv:${esc(p.id)}</a>
          ${cats.map((c, i) => `<span class="cat ${i === 0 ? 'primary' : ''}" title="${i === 0 ? 'Primary category' : 'Cross-listed'}">${esc(c)}</span>`).join('')}
          ${sc && sc.why.length ? `<span class="why" aria-label="Matches your watchlist">${sc.why.map(w => `<span>${esc(w)}</span>`).join('')}</span>` : ''}
          <button class="save" type="button" data-save="${esc(p.id)}" aria-pressed="${saved}" aria-label="${saved ? 'Remove from saved' : 'Save paper'}">${ICON_STAR}${saved ? 'Saved' : 'Save'}</button>
        </div>
        <h3 class="title"><a href="${abs}" rel="noreferrer" target="_blank">${rich(p.title, res)}</a></h3>
        <p class="authors">${authorsHtml(p, key)}</p>
        ${sum ? `<p class="tldr">${rich(sum.tldr, res)}</p>` : `<p class="tldr missing">${p.kind === 'replace' ? 'Replacement: not summarised.' : 'Summary not available yet.'} Open the details for the abstract.</p>`}
        <div class="card-actions">
          <button class="more-btn" type="button" data-toggle="${esc(key)}" aria-expanded="${open}">${ICON_CHEV}${sum ? 'Summary and abstract' : 'Abstract'}</button>
          <a href="https://arxiv.org/pdf/${esc(p.id)}" rel="noreferrer" target="_blank">PDF</a>
          <a href="https://arxiv.org/html/${esc(p.id)}${esc(p.version || '')}" rel="noreferrer" target="_blank">HTML</a>
          ${p.comments ? `<span class="comments">${rich(p.comments)}</span>` : ''}
        </div>
        <div class="detail" ${open ? '' : 'hidden'}>${open ? detailHtml(p, res) : ''}</div>
      </div>
    </li>`;
  }
  function detailHtml(p, res) {
    const s = p.summary;
    return `${s ? `<dl>
        ${s.motivation ? `<dt>Motivation</dt><dd>${rich(s.motivation, res)}</dd>` : ''}
        ${s.method ? `<dt>Method</dt><dd>${rich(s.method, res)}</dd>` : ''}
        ${s.results ? `<dt>Results</dt><dd>${rich(s.results, res)}</dd>` : ''}
      </dl>
      ${s.tags && s.tags.length ? `<div class="tags">${s.tags.map(t => `<button type="button" data-tag="${esc(t)}" title="Search this day for “${esc(t)}”">${esc(t)}</button>`).join('')}</div>` : ''}` : ''}
      <p class="abs-h">Abstract</p>
      <p class="abs">${rich(p.abstract, res)}</p>
      ${p.journal_ref ? `<p class="ai-note">Journal reference: ${esc(p.journal_ref)}</p>` : ''}
      ${s ? `<p class="ai-note">Summary generated by ${esc(S.day?.model || 'an AI model')} from the title and abstract only. Check the abstract before relying on it.</p>` : ''}`;
  }

  function renderSide() {
    const d = S.day, cats = Object.keys(S.index?.categories || {});
    const counts = {};
    cats.forEach(c => counts[c] = d ? d.papers.filter(p => p.listed_in.includes(c) && S.filters.kinds.includes(p.kind)).length : 0);
    const sel = S.filters.cats || cats;
    $('#cat-filters').innerHTML = cats.map(c => `<label class="check" title="${esc(S.index.categories[c])}"><input type="checkbox" data-cat="${esc(c)}" ${sel.includes(c) ? 'checked' : ''}><span>${esc(c)}</span><span class="n">${counts[c]}</span></label>`).join('');
    const kc = k => d ? d.papers.filter(p => p.kind === k).length : 0;
    $('#kind-filters').innerHTML = Object.keys(KINDS).map(k => `<label class="check"><input type="checkbox" data-kind="${k}" ${S.filters.kinds.includes(k) ? 'checked' : ''}><span>${KINDS[k]}</span><span class="n">${kc(k)}</span></label>`).join('');
    $('#only-matches').checked = S.filters.only;
    const chips = (arr, kind) => arr.length ? arr.map((x, i) => `<li><span>${esc(x)}</span><button type="button" data-rm="${kind}" data-i="${i}" aria-label="Remove ${esc(x)}">×</button></li>`).join('') : `<li class="none">None yet</li>`;
    $('#kw-list').innerHTML = chips(S.watch.keywords, 'keywords');
    $('#au-list').innerHTML = chips(S.watch.authors, 'authors');
    $('#saved-count').textContent = Object.keys(S.saved).length;
  }

  function renderHead() {
    const dates = S.index?.dates || [];
    const i = dates.findIndex(x => x.date === S.date);
    $('#prev-day').disabled = S.view !== 'day' || i < 0 || i >= dates.length - 1;
    $('#next-day').disabled = S.view !== 'day' || i <= 0;
    $('#day-select').innerHTML = dates.map(x => `<option value="${x.date}" ${x.date === S.date ? 'selected' : ''}>${esc(fmtDay(x.date))} (${x.total})</option>`).join('');
    $('#day-select').closest('.day-pick').hidden = S.view !== 'day' || !dates.length;
    if (S.view === 'saved') {
      $('#day-title').textContent = 'Saved papers';
      $('#day-meta').textContent = 'Saved in this browser only. Use the buttons below to copy them out.';
      return;
    }
    if (!S.day) { $('#day-title').textContent = dates.length ? 'Loading' : 'No digest yet'; $('#day-meta').textContent = ''; return; }
    const d = S.day, ps = d.papers, c = k => ps.filter(p => p.kind === k).length;
    const summ = ps.filter(p => p.summary).length;
    $('#day-title').textContent = fmtDay(d.date);
    const parts = Object.keys(KINDS).filter(k => c(k)).map(k => `${c(k)} ${KIND_SHORT[k][c(k) === 1 ? 0 : 1]}`);
    $('#day-meta').textContent = `${ps.length} papers announced: ${parts.join(', ')}. `
      + (summ ? `${summ} summarised by ${d.model || 'an AI model'}${d.language ? ` in ${d.language}` : ''}.` : 'Summaries are not available for this day yet.');
  }

  function renderDay() {
    const d = S.day, box = $('#content');
    if (!d) return;
    const ps = d.papers.map((p, i) => ({ p, n: i + 1 })).filter(x => visible(x.p));
    const hasWatch = W.kws.length || W.aus.length;
    const scored = hasWatch ? ps.map(x => ({ ...x, sc: score(x.p) })) : ps.map(x => ({ ...x, sc: null }));
    let html = '';
    if (hasWatch) {
      const mine = scored.filter(x => x.sc.s > 0).sort((a, b) => b.sc.s - a.sc.s);
      html += `<section class="group foryou"><h2 class="group-h">For you<span class="n">${mine.length}</span></h2>
        ${mine.length ? `<ol class="cards">${mine.map(x => card(x.p, x.n, x.sc, 'f-' + x.p.id)).join('')}</ol>`
          : `<p class="group-note">Nothing on this day matches your watchlist.</p>`}</section>`;
    }
    if (!S.filters.only) {
      for (const k of Object.keys(KINDS)) {
        const list = scored.filter(x => x.p.kind === k);
        if (!S.filters.kinds.includes(k) || !list.length) continue;
        html += `<section class="group"><h2 class="group-h">${KINDS[k]}<span class="n">${list.length}</span></h2>
          <ol class="cards">${list.map(x => card(x.p, x.n, x.sc && x.sc.s ? x.sc : null, x.p.id)).join('')}</ol></section>`;
      }
    } else if (!hasWatch) {
      html += `<div class="empty"><strong>Your watchlist is empty</strong>Add keywords or authors in the sidebar to see matching papers here.</div>`;
    }
    if (!ps.length) html = `<div class="empty"><strong>No papers match these filters</strong>Clear the search or tick more categories in the sidebar.</div>`;
    box.innerHTML = html;
    S.cur = -1;
  }

  function renderSaved() {
    const items = Object.values(S.saved).sort((a, b) => (b.date || '').localeCompare(a.date || '') || b.id.localeCompare(a.id));
    const box = $('#content');
    if (!items.length) { box.innerHTML = `<div class="empty"><strong>Nothing saved yet</strong>Press Save on a paper, or <kbd>s</kbd> on the highlighted one, to keep it here.</div>`; return; }
    box.innerHTML = `<div class="saved-tools"><button type="button" id="copy-md">Copy as Markdown</button><button type="button" id="copy-ids">Copy arXiv IDs</button><button type="button" id="clear-saved">Clear all</button></div>
      <section class="group"><ol class="cards">${items.map((s, i) => `<li class="card" data-id="${esc(s.id)}">
        <span class="num">${i + 1}</span><div>
        <div class="card-top"><a class="id" href="https://arxiv.org/abs/${esc(s.id)}" rel="noreferrer" target="_blank">arXiv:${esc(s.id)}</a><span>${s.date ? esc(fmtDay(s.date)) : ''}</span>
        <button class="save" type="button" data-save="${esc(s.id)}" aria-pressed="true" aria-label="Remove from saved">${ICON_STAR}Saved</button></div>
        <h3 class="title"><a href="https://arxiv.org/abs/${esc(s.id)}" rel="noreferrer" target="_blank">${rich(s.title)}</a></h3>
        <p class="authors">${esc(s.authors)}</p>${s.tldr ? `<p class="tldr">${rich(s.tldr)}</p>` : ''}</div></li>`).join('')}</ol></section>`;
    const copy = async (text, msg) => { try { await navigator.clipboard.writeText(text); toast(msg); } catch (e) { toast('Copy failed: your browser blocked clipboard access'); } };
    $('#copy-md').onclick = () => copy(items.map(s => `- [${s.title.replace(/\s+/g, ' ')}](https://arxiv.org/abs/${s.id}), ${s.authors}`).join('\n'), 'Copied as Markdown');
    $('#copy-ids').onclick = () => copy(items.map(s => s.id).join('\n'), 'Copied arXiv IDs');
    $('#clear-saved').onclick = () => { S.saved = {}; store.set('saved', S.saved); render(); toast('Saved list cleared'); };
  }

  function render() {
    renderHead(); renderSide();
    if (S.view === 'saved') renderSaved();
    else if (S.day) renderDay();
    $('#saved-btn').setAttribute('aria-pressed', String(S.view === 'saved'));
  }

  /* ---------------- data loading / routing ---------------- */
  async function loadDay(date) {
    S.date = date; S.view = 'day';
    if (!S.cache[date]) {
      renderHead();
      $('#content').innerHTML = '<p class="empty">Loading…</p>';
      try { S.cache[date] = await getJSON(`data/${date}.json`); }
      catch (e) { $('#content').innerHTML = `<div class="empty"><strong>This day could not be loaded</strong>${esc(e.message)}</div>`; return; }
    }
    S.day = S.cache[date];
    S.expanded.clear(); S.authorsOpen.clear();
    render();
  }
  function route() {
    const h = decodeURIComponent(location.hash.slice(1));
    if (h === 'saved') { S.view = 'saved'; render(); return; }
    const dates = (S.index?.dates || []).map(d => d.date);
    const date = dates.includes(h) ? h : S.index?.latest;
    if (date) loadDay(date); else render();
  }
  function go(hash) { if (location.hash !== '#' + hash) location.hash = hash; else route(); }

  /* ---------------- events ---------------- */
  function persistFilters() { store.set('filters', S.filters); }
  function toggleSave(id) {
    if (S.saved[id]) { delete S.saved[id]; }
    else {
      const p = S.day?.papers.find(x => x.id === id); if (!p) return;
      const au = p.authors.length > 3 ? p.authors.slice(0, 3).join(', ') + ' et al.' : p.authors.join(', ');
      S.saved[id] = { id, title: p.title, authors: au, date: S.day.date, tldr: p.summary?.tldr || '' };
    }
    store.set('saved', S.saved);
    $$(`[data-save="${CSS.escape(id)}"]`).forEach(b => { const on = !!S.saved[id]; b.setAttribute('aria-pressed', on); b.innerHTML = ICON_STAR + (on ? 'Saved' : 'Save'); });
    $('#saved-count').textContent = Object.keys(S.saved).length;
    if (S.view === 'saved') renderSaved();
  }
  function toggleDetail(key) {
    const li = $(`.card[data-key="${CSS.escape(key)}"]`); if (!li) return;
    const p = S.day.papers.find(x => x.id === li.dataset.id), det = $('.detail', li), btn = $('[data-toggle]', li);
    const open = det.hidden;
    if (open) { S.expanded.add(key); det.innerHTML = detailHtml(p, W.kws.map(k => new RegExp(k.re.source, 'gi'))); }
    else S.expanded.delete(key);
    det.hidden = !open; btn.setAttribute('aria-expanded', String(open));
  }

  document.addEventListener('click', e => {
    const t = e.target.closest('button'); if (!t) return;
    if (t.dataset.save) toggleSave(t.dataset.save);
    else if (t.dataset.toggle) toggleDetail(t.dataset.toggle);
    else if (t.dataset.authors) { S.authorsOpen.add(t.dataset.authors); const li = t.closest('.card'); const p = S.day.papers.find(x => x.id === li.dataset.id); $('.authors', li).innerHTML = authorsHtml(p, t.dataset.authors); }
    else if (t.dataset.tag) { $('#search').value = t.dataset.tag; S.q = t.dataset.tag; renderDay(); window.scrollTo({ top: 0 }); }
    else if (t.dataset.rm) { S.watch[t.dataset.rm].splice(+t.dataset.i, 1); saveWatch(); }
  });
  $('#side').addEventListener('change', e => {
    const t = e.target;
    if (t.dataset.cat) { const cats = Object.keys(S.index.categories); S.filters.cats = $$('[data-cat]').filter(x => x.checked).map(x => x.dataset.cat); if (S.filters.cats.length === cats.length) S.filters.cats = null; }
    else if (t.dataset.kind) { S.filters.kinds = $$('[data-kind]').filter(x => x.checked).map(x => x.dataset.kind); }
    else if (t.id === 'only-matches') S.filters.only = t.checked;
    else return;
    persistFilters(); render();
  });
  let qt; $('#search').addEventListener('input', e => { clearTimeout(qt); qt = setTimeout(() => { S.q = e.target.value.trim(); if (S.view === 'day') renderDay(); }, 120); });

  function saveWatch() { store.set('watch', S.watch); W = compileWatch(); render(); }
  function addTo(kind, input) {
    const v = input.value.trim(); if (!v) return;
    if (!S.watch[kind].some(x => x.toLowerCase() === v.toLowerCase())) S.watch[kind].push(v);
    input.value = ''; saveWatch();
  }
  $('#kw-form').addEventListener('submit', e => { e.preventDefault(); addTo('keywords', $('#kw-input')); });
  $('#au-form').addEventListener('submit', e => { e.preventDefault(); addTo('authors', $('#au-input')); });
  $('#export-btn').addEventListener('click', () => {
    const blob = new Blob([JSON.stringify({ keywords: S.watch.keywords, authors: S.watch.authors }, null, 2)], { type: 'application/json' });
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'arxiv-daily-watchlist.json'; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  });
  $('#import-btn').addEventListener('click', () => $('#import-file').click());
  $('#import-file').addEventListener('change', async e => {
    const f = e.target.files[0]; if (!f) return;
    try {
      const j = JSON.parse(await f.text());
      const clean = a => Array.isArray(a) ? [...new Set(a.filter(x => typeof x === 'string' && x.trim()).map(x => x.trim().slice(0, 120)))] : [];
      S.watch = { keywords: clean(j.keywords), authors: clean(j.authors) }; saveWatch(); toast('Watchlist imported');
    } catch (err) { toast('That file is not a watchlist export'); }
    e.target.value = '';
  });

  $('#prev-day').addEventListener('click', () => step(1));
  $('#next-day').addEventListener('click', () => step(-1));
  $('#day-select').addEventListener('change', e => go(e.target.value));
  function step(d) { const ds = S.index.dates, i = ds.findIndex(x => x.date === S.date); const n = ds[i + d]; if (n) go(n.date); }
  $('#saved-btn').addEventListener('click', () => go(S.view === 'saved' ? (S.date || '') : 'saved'));
  $('#side-toggle').addEventListener('click', e => { const b = e.currentTarget; b.setAttribute('aria-expanded', String(b.getAttribute('aria-expanded') !== 'true')); });
  $('#theme-toggle').addEventListener('click', () => {
    const cur = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    const next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('ad.theme', next); } catch (e) {}
  });
  window.addEventListener('hashchange', route);

  document.addEventListener('keydown', e => {
    if (e.target.closest('input, select, textarea') || e.metaKey || e.ctrlKey || e.altKey) {
      if (e.key === 'Escape' && e.target.id === 'search') e.target.blur();
      return;
    }
    const cards = $$('#content .card');
    const move = d => {
      if (!cards.length) return;
      S.cur = Math.max(0, Math.min(cards.length - 1, S.cur + d));
      cards.forEach((c, i) => c.classList.toggle('cur', i === S.cur));
      cards[S.cur].scrollIntoView({ block: 'nearest' });
    };
    if (e.key === 'j') move(1);
    else if (e.key === 'k') move(-1);
    else if (e.key === 'o' && cards[S.cur]?.dataset.key) toggleDetail(cards[S.cur].dataset.key);
    else if (e.key === 's' && cards[S.cur]) toggleSave(cards[S.cur].dataset.id);
    else if (e.key === '[' && S.view === 'day') step(1);
    else if (e.key === ']' && S.view === 'day') step(-1);
    else if (e.key === '/') { e.preventDefault(); $('#search').focus(); }
    else return;
  });

  /* ---------------- boot ---------------- */
  (async function boot() {
    try { S.index = await getJSON('data/index.json'); }
    catch (e) {
      $('#day-title').textContent = 'No digest yet';
      $('#content').innerHTML = `<div class="empty"><strong>The data could not be loaded</strong>${location.protocol === 'file:' ? 'Open this page through a web server, for example <code>python3 -m http.server</code> in the project folder.' : esc(e.message)}</div>`;
      return;
    }
    if (!S.index.dates?.length) {
      S.index.categories = S.index.categories || {};
      render();
      $('#content').innerHTML = `<div class="empty"><strong>The first digest has not been published yet</strong>arXiv announces new papers at 20:00 US Eastern time, Sunday to Thursday. This page fetches them from 02:10 UTC the following morning.</div>`;
      return;
    }
    route();
  })();
})();
