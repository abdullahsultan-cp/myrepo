/* Hash routing between screens, plus one search per screen. */
const screens = [...document.querySelectorAll('.scr')];
const navLinks = [...document.querySelectorAll('aside nav a')];

function show(id) {
  if (!screens.some(s => s.id === id)) id = 'overview';
  screens.forEach(s => s.classList.toggle('on', s.id === id));
  navLinks.forEach(a => a.classList.toggle('on', a.dataset.s === id));
  if (id === 'chart') centreChart();
  window.scrollTo(0, 0);
}
window.addEventListener('hashchange', () => show(location.hash.slice(1)));

/* ---- folder tree ---- */
const nodes = [...document.querySelectorAll('#tree .n')];
const treePages = [...document.querySelectorAll('#tree .pg')];
document.querySelectorAll('#tree .row').forEach(r => {
  r.onclick = () => {
    const n = r.closest('.n');
    if (n.querySelector(':scope > .ch')) n.classList.toggle('cl');
  };
});
function depth(n) {
  let d = 0, p = n.parentElement;
  while (p) { if (p.classList && p.classList.contains('n')) d++; p = p.parentElement; }
  return d;
}
function setDepth(k) {
  nodes.forEach(n => {
    if (n.querySelector(':scope > .ch')) n.classList.toggle('cl', depth(n) >= k);
  });
}
function openUp(el) {
  let p = el.parentElement;
  while (p) {
    if (p.classList && p.classList.contains('n')) p.classList.remove('cl');
    p = p.parentElement;
  }
}
function level(k) {
  const q = document.getElementById('q1');
  if (q) q.value = '';
  document.getElementById('h1').textContent = '';
  nodes.forEach(n => n.classList.remove('hide'));
  treePages.forEach(p => p.classList.remove('hide'));
  setDepth(k);
}
function treeSearch(t) {
  t = t.trim().toLowerCase();
  if (!t) { level(1); return; }
  let np = 0;
  treePages.forEach(p => {
    const m = p.dataset.n.includes(t);
    p.classList.toggle('hide', !m);
    if (m) { np++; openUp(p); }
  });
  [...nodes].reverse().forEach(n => {
    const self = n.querySelector(':scope > .row').dataset.n.includes(t);
    const kid = [...n.querySelectorAll(':scope > .ch > .n')].some(c => !c.classList.contains('hide'))
      || [...n.querySelectorAll(':scope > .ch > .pgs > .pg')].some(c => !c.classList.contains('hide'));
    const show = self || kid;
    n.classList.toggle('hide', !show);
    if (show) {
      if (self) n.querySelectorAll('.n,.pg').forEach(c => c.classList.remove('hide'));
      n.classList.remove('cl');
      openUp(n);
    }
  });
  const nf = nodes.filter(n => !n.classList.contains('hide')).length;
  document.getElementById('h1').textContent = nf + ' folders · ' + np + ' pages';
}

/* ---- org chart. Centre on the first root box: with two roots side by side the
   canvas midpoint falls in the gap between them and the top scrolls out of view. */
function centreChart() {
  const c = document.querySelector('.ocwrap');
  if (!c) return;
  const b = c.querySelector('.oc > ul > li > .ocb');
  if (!b) { c.scrollLeft = 0; return; }
  const cr = c.getBoundingClientRect(), br = b.getBoundingClientRect();
  c.scrollLeft = Math.max(0, c.scrollLeft + (br.left + br.width / 2) - (cr.left + cr.width / 2));
}
document.querySelectorAll('.octg').forEach(t => {
  t.onclick = ev => {
    const li = t.closest('li');
    li.classList.toggle('cl');
    t.textContent = li.classList.contains('cl') ? '+' : '−';
    ev.stopPropagation();
    centreChart();
  };
});

/* ---- pages list ---- */
const prows = [...document.querySelectorAll('.prow')];
let pfilter = '';
function pagesSearch() {
  const t = (document.getElementById('q2').value || '').trim().toLowerCase();
  let v = 0;
  prows.forEach(r => {
    const s = r.dataset.n;
    const ok = (!t || s.includes(t)) && (!pfilter || s.includes(pfilter)
      || r.textContent.toLowerCase().includes(pfilter));
    r.classList.toggle('hide', !ok);
    if (ok) v++;
  });
  document.getElementById('h2').textContent =
    v.toLocaleString() + ' of ' + prows.length.toLocaleString() + ' pages';
}

/* ---- generic table search ---- */
function tableSearch(inputId, tableId, hitsId, unit) {
  const q = document.getElementById(inputId);
  if (!q) return;
  const rows = [...document.querySelectorAll('#' + tableId + ' tbody tr')];
  const run = () => {
    const t = q.value.trim().toLowerCase();
    let v = 0;
    rows.forEach(r => {
      const ok = !t || r.textContent.toLowerCase().includes(t);
      r.classList.toggle('hide', !ok);
      if (ok) v++;
    });
    document.getElementById(hitsId).textContent =
      v.toLocaleString() + ' of ' + rows.length.toLocaleString() + ' ' + unit;
  };
  let tm;
  q.addEventListener('input', () => { clearTimeout(tm); tm = setTimeout(run, 110); });
  run();
}

/* ---- wire up ---- */
let t1;
const q1 = document.getElementById('q1');
q1.addEventListener('input', () => { clearTimeout(t1); t1 = setTimeout(() => treeSearch(q1.value), 120); });
document.getElementById('L1').onclick = () => level(1);
document.getElementById('L2').onclick = () => level(3);
document.getElementById('L3').onclick = () => level(4);
document.getElementById('L9').onclick = () => {
  q1.value = '';
  document.getElementById('h1').textContent = '';
  nodes.forEach(n => n.classList.remove('hide', 'cl'));
  treePages.forEach(p => p.classList.remove('hide'));
};
document.getElementById('he').onchange = ev =>
  document.getElementById('tree').classList.toggle('he', ev.target.checked);

let t2;
const q2 = document.getElementById('q2');
q2.addEventListener('input', () => { clearTimeout(t2); t2 = setTimeout(pagesSearch, 130); });
document.querySelectorAll('.f2').forEach(b => {
  b.onclick = () => { pfilter = b.dataset.f; pagesSearch(); };
});

/* ---- people ---- */
const persons = [...document.querySelectorAll('.prsn')];
let cfilter = '';
function peopleSearch() {
  const q = document.getElementById('q5');
  if (!q) return;
  const t = (q.value || '').trim().toLowerCase();
  let v = 0;
  persons.forEach(r => {
    const s = r.dataset.n;
    const ok = (!t || s.includes(t)) && (!cfilter || s.includes(cfilter));
    r.classList.toggle('hide', !ok);
    if (ok) v++;
  });
  document.getElementById('h5').textContent =
    v.toLocaleString() + ' of ' + persons.length.toLocaleString() + ' people';
}
let t5;
const q5 = document.getElementById('q5');
if (q5) {
  q5.addEventListener('input', () => { clearTimeout(t5); t5 = setTimeout(peopleSearch, 120); });
  document.querySelectorAll('.f5').forEach(b => {
    b.onclick = () => { cfilter = b.dataset.f; peopleSearch(); };
  });
  peopleSearch();
}

/* ---- base URL: rewrite every "new" link live, so dev/staging/live all work ---- */
const bu = document.getElementById('bu');
if (bu) {
  const newLinks = [...document.querySelectorAll('a.nu, a.lk.new')];
  const origins = newLinks.map(a => a.getAttribute('href'));
  const paths = origins.map(h => h.replace(/^https?:\/\/[^/]+/, ''));
  const texts = newLinks.map(a => a.textContent);
  const apply = () => {
    let base = bu.value.trim().replace(/\/+$/, '');
    if (!base) base = 'https://www.aku.edu';
    newLinks.forEach((a, i) => {
      a.href = base + paths[i];
      if (a.classList.contains('nu')) a.textContent = texts[i];
    });
  };
  let tb;
  bu.addEventListener('input', () => { clearTimeout(tb); tb = setTimeout(apply, 250); });
}

tableSearch('q3', 'rt', 'h3', 'folders');
tableSearch('q4', 'rl', 'h4', 'roles');

level(1);
pagesSearch();
show(location.hash.slice(1) || 'overview');
