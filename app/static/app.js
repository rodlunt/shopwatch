/* Shopwatch UI: inline editing, dialogs, price watch, import.
   Deliberately small and framework-free. */

const MONEY = new Intl.NumberFormat('en-AU', { style: 'currency', currency: 'AUD',
  minimumFractionDigits: 0, maximumFractionDigits: 2 });
const money = v => (v === null || v === undefined || v === '') ? '-' : MONEY.format(v);

const CLASS_STYLE = {
  HISTORICAL_LOW: 'good', EXCELLENT: 'good', TRIGGER_MET: 'warn',
  ABOVE_TARGET: 'bad', UNRESOLVED: 'none'
};
const CLASS_LABEL = {
  HISTORICAL_LOW: 'HISTORICAL LOW TERRITORY', EXCELLENT: 'EXCELLENT',
  TRIGGER_MET: 'TRIGGER MET', ABOVE_TARGET: 'ABOVE TARGET', UNRESOLVED: 'UNRESOLVED'
};
const CONDITIONS = ['NEW', 'FACTORY_SECOND', 'CARTON_DAMAGED', 'EX_DISPLAY', 'REFURBISHED', 'USED'];

/* ------------------------------------------------------------------ utilities */

function toast(message, kind = '') {
  const box = document.getElementById('toast');
  const el = document.createElement('div');
  el.className = kind;
  el.textContent = message;
  box.appendChild(el);
  setTimeout(() => el.remove(), kind === 'bad' ? 9000 : 4000);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined
  });
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (e) { data = { detail: text }; }
  if (!response.ok) {
    throw new Error((data && (data.detail || data.error)) || `HTTP ${response.status}`);
  }
  return data;
}

/* Unsaved work must never disappear silently. */
const dirtyCells = new Set();
window.addEventListener('beforeunload', event => {
  if (dirtyCells.size === 0) return;
  event.preventDefault();
  event.returnValue = '';
});

/* ------------------------------------------------------------ inline editing */

function renderValue(span, value) {
  const kind = span.dataset.kind;
  span.dataset.raw = (value === null || value === undefined) ? '' : value;
  if (value === null || value === undefined || value === '') {
    span.replaceChildren(el('span', '-', 'unresolved'));
  } else if (kind === 'money') {
    span.textContent = money(value);
  } else {
    span.textContent = value;
  }
}

function applyListing(listing) {
  const row = document.querySelector(`[data-listing-row="${listing.id}"]`);
  if (!row) return;

  const price = row.querySelector('[data-cell="delivered"]');
  if (price) {
    price.replaceChildren(...(listing.delivered_price === null
      ? [el('span', 'no price', 'unresolved')]
      : [document.createTextNode(money(listing.delivered_price)),
         el('small', listing.delivered_resolved ? 'delivered' : 'before freight')]));
  }

  const tag = row.querySelector('[data-cell="classification"]');
  if (tag) {
    const node = tagFor(listing);
    if (node) tag.replaceChildren(node); else tag.replaceChildren();
  }

  // Same precedence as the server macro: a ruled-out listing is never styled as a
  // buy, however its price classifies. Applying both left the row green and struck
  // through at once.
  const out = Boolean(listing.ruled_out);
  row.classList.toggle('is-ruled-out', out);
  row.classList.toggle('is-act', !out && ['HISTORICAL_LOW', 'EXCELLENT'].includes(listing.classification));
  row.classList.toggle('is-close', !out && listing.classification === 'TRIGGER_MET');

  for (const [field, prov] of Object.entries(listing.provenance || {})) {
    const span = row.querySelector(`[data-edit][data-field="${field}"]`);
    if (!span) continue;
    renderValue(span, listing[field]);
    const label = span.closest('.field')?.querySelector('.k');
    if (label) {
      label.querySelectorAll('.lock, .src').forEach(n => n.remove());
      const mark = provenanceMark(listing.id, field, prov);
      if (mark) label.appendChild(mark);
    }
  }
}

/* The headline sentence and the ruler are derived from every listing at once, so an
   edit to one row can change both. Without this the page contradicts itself: the row
   reads "at target" under a sentence still saying "unconfirmed". */
function applyProductSummary(product) {
  if (!product) return;
  const card = document.getElementById(`product-${product.id}`);
  if (!card) return;

  const verdict = card.querySelector('.verdict');
  if (verdict) {
    verdict.textContent = product.verdict_line;
    verdict.className = `verdict ${product.tone}`;
  }

  const track = card.querySelector('.ruler-track');
  if (!track || !product.scale) return;

  track.querySelectorAll('.ruler-mark').forEach((mark, i) => {
    const m = product.scale.marks[i];
    if (m) mark.style.left = `${m.pos}%`;
  });

  let best = track.querySelector('.ruler-best');
  if (!product.scale.best) { if (best) best.remove(); return; }
  if (!best) {
    best = document.createElement('span');
    best.className = 'ruler-best';
    track.appendChild(best);
  }
  best.className = `ruler-best ${product.tone}`;
  best.style.left = `${product.scale.best.pos}%`;
  /* Built as nodes, not markup. A retailer name arrives through POST /api/import,
     which is the documented way to paste in research produced elsewhere, so it is
     untrusted text by design and must never be interpolated into innerHTML. */
  best.replaceChildren(
    el('b', money(product.scale.best.value)),
    el('small', `${product.best_retailer || ''}${product.best_resolved ? '' : ', freight unknown'}`),
    document.createElement('i')
  );
}

/* Small helper: element with text, never markup. */
function el(tag, text, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function tagFor(listing) {
  // Ruled out comes first, exactly as the server macro orders it. Without this an
  // inline edit re-rendered a ruled-out listing as "excellent" or "at target", with
  // is-act and is-ruled-out both applied, until the next reload.
  if (listing.ruled_out) return el('span', 'ruled out', 'tag ruled-out');
  if (listing.verification?.model?.status === 'FLAGGED') return el('span', 'model mismatch', 'tag fault');
  if (listing.classification === 'HISTORICAL_LOW') return el('span', 'historical low', 'tag act');
  if (listing.classification === 'EXCELLENT') return el('span', 'excellent', 'tag act');
  if (listing.classification === 'TRIGGER_MET') return el('span', 'at target', 'tag close');
  if (listing.classification === 'UNRESOLVED') return el('span', 'unconfirmed', 'tag');
  return null;
}

/* Returns a node or null. `prov.source` is attacker-controllable through the import
   endpoint, so it is set as text and never as markup. */
function provenanceMark(listingId, field, prov) {
  if (prov.manual_locked) {
    const button = el('button', 'set by hand', 'lock');
    button.dataset.clearOverride = '';
    button.dataset.listing = listingId;
    button.dataset.field = field;
    button.title = 'You set this by hand. Automated runs will not change it. Click to hand it back.';
    return button;
  }
  if (prov.state === 'STALE') return el('span', 'stale', 'src');
  if (prov.source) return el('span', prov.source, 'src');
  return null;
}

function startEdit(span) {
  if (span.classList.contains('editing')) return;
  const original = span.dataset.raw;
  const kind = span.dataset.kind;
  span.classList.add('editing');

  let input;
  if (kind === 'condition') {
    input = document.createElement('select');
    for (const c of CONDITIONS) {
      const option = document.createElement('option');
      option.value = option.textContent = c;
      if (c === original) option.selected = true;
      input.appendChild(option);
    }
  } else {
    input = document.createElement('input');
    input.type = kind === 'money' ? 'number' : 'text';
    if (kind === 'money') input.step = '0.01';
    input.value = original;
    input.size = Math.max(6, String(original).length + 2);
  }
  input.style.width = kind === 'money' ? '85px' : 'auto';
  span.textContent = '';
  span.appendChild(input);
  input.focus();
  if (input.select) input.select();
  dirtyCells.add(span);
  span.classList.add('dirty');

  let settled = false;
  const cancel = () => {
    if (settled) return;
    settled = true;
    dirtyCells.delete(span);
    span.classList.remove('editing', 'dirty');
    renderValue(span, original === '' ? null : original);
  };
  const commit = async () => {
    if (settled) return;
    settled = true;
    const value = input.value.trim();
    span.classList.remove('editing');
    if (value === original) { cancel(); return; }
    span.classList.add('saving');
    try {
      const payload = {};
      payload[span.dataset.field] = value === '' ? null : value;
      const result = await api(`/api/retailers/${span.dataset.listing}`, { method: 'PATCH', body: payload });
      dirtyCells.delete(span);
      span.classList.remove('dirty', 'saving');
      applyListing(result.listing);
      applyProductSummary(result.product);
      const target = document.querySelector(
        `[data-listing-row="${result.listing.id}"] [data-edit][data-field="${span.dataset.field}"]`);
      if (target) { target.classList.add('saved'); setTimeout(() => target.classList.remove('saved'), 1200); }
    } catch (err) {
      span.classList.remove('saving');
      span.classList.add('error', 'dirty');
      renderValue(span, value === '' ? null : value);
      toast(`Save failed, value kept in the cell: ${err.message}`, 'bad');
      settled = true;
    }
  };

  input.addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); commit(); }
    if (event.key === 'Escape') { event.preventDefault(); cancel(); }
  });
  input.addEventListener('blur', commit);
}

/* --------------------------------------------------------- progressive disclosure */

function toggleRegion(button, region) {
  const open = region.hidden;
  region.hidden = !open;
  button.setAttribute('aria-expanded', String(open));
  const row = button.closest('.listing');
  if (row) row.classList.toggle('open', open);
  return open;
}

document.addEventListener('click', async event => {
  const ruleOutOpen = event.target.closest('[data-rule-out-open]');
  if (ruleOutOpen) {
    const id = ruleOutOpen.dataset.ruleOutOpen;
    const form = document.querySelector(`[data-rule-out-form="${id}"]`);
    if (form) {
      form.hidden = false;
      ruleOutOpen.hidden = true;
      const input = form.querySelector('[data-rule-out-reason]');
      if (input) input.focus();
    }
    return;
  }
  const ruleOut = event.target.closest('[data-rule-out]');
  if (ruleOut) {
    const id = ruleOut.dataset.ruleOut;
    const input = document.querySelector(`[data-rule-out-reason="${id}"]`);
    const reason = input ? input.value.trim() : '';
    try {
      await api(`/api/retailers/${id}/ruled-out`,
        { method: 'POST', body: { ruled_out: true, reason } });
      location.reload();
    } catch (err) { toast(`Could not rule it out: ${err.message}`, 'bad'); }
    return;
  }
  const ruleIn = event.target.closest('[data-rule-in]');
  if (ruleIn) {
    try {
      await api(`/api/retailers/${ruleIn.dataset.ruleIn}/ruled-out`,
        { method: 'POST', body: { ruled_out: false } });
      location.reload();
    } catch (err) { toast(`Could not put it back: ${err.message}`, 'bad'); }
    return;
  }

  const detailBtn = event.target.closest('[data-toggle-detail]');
  if (detailBtn) {
    const region = document.getElementById(`detail-${detailBtn.dataset.toggleDetail}`);
    if (region) toggleRegion(detailBtn, region);
    return;
  }

  const alsoRan = event.target.closest('[data-toggle-alsoran]');
  if (alsoRan) {
    const region = document.getElementById(`alsoran-${alsoRan.dataset.toggleAlsoran}`);
    if (region) {
      const open = toggleRegion(alsoRan, region);
      const n = region.querySelectorAll('.listing').length;
      alsoRan.textContent = open ? 'Hide the ones above target'
                                 : `Show ${n} more, all above target`;
    }
    return;
  }

  const cell = event.target.closest('[data-edit]');
  if (cell && !event.target.closest('input, select')) { startEdit(cell); return; }

  const lock = event.target.closest('[data-clear-override]');
  if (lock) {
    const { listing, field } = lock.dataset;
    if (!confirm(`Clear the manual override on "${field}"? Automated runs will be able to change it again.`)) return;
    try {
      const result = await api(`/api/retailers/${listing}/clear-override`,
        { method: 'POST', body: { field } });
      lock.remove();
      toast(`${field} handed back to automated updates.`, 'good');
      if (result.listing) applyListing(result.listing);
      applyProductSummary(result.product);
    } catch (err) { toast(`Could not clear override: ${err.message}`, 'bad'); }
    return;
  }

  if (event.target.matches('[data-close]')) {
    event.target.closest('dialog').close();
  }
});

/* ------------------------------------------------------------------ toolbar */

function wire(id, handler) {
  const el = document.getElementById(id);
  if (el) el.addEventListener('click', handler);
}

wire('btn-watch', async event => {
  await runWatch(event.currentTarget, {});
});
wire('btn-watch-product', async event => {
  await runWatch(event.currentTarget, { product_id: Number(event.currentTarget.dataset.product) });
});

async function runWatch(button, body) {
  button.disabled = true;
  const label = button.textContent;
  button.textContent = 'Running…';
  try {
    const summary = await api('/api/price-watch/run', { method: 'POST', body });
    const parts = [`${summary.status}`, `checked ${summary.checked}`, `ok ${summary.ok}`,
      `unresolved ${summary.unresolved}`, `skipped ${summary.skipped}`, `errors ${summary.errors}`,
      `alerts ${summary.alerts.length}`];
    toast(`Price watch: ${parts.join(', ')}`, summary.status === 'failed' ? 'bad' : 'good');
    if (summary.delivery_failures.length) {
      toast(`ALERT DELIVERY FAILED: ${summary.delivery_failures.join('; ')}`, 'bad');
    }
    setTimeout(() => location.reload(), 1400);
  } catch (err) {
    toast(`Price watch failed: ${err.message}`, 'bad');
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
}

wire('btn-backup', async () => {
  try {
    const result = await api('/api/backup', { method: 'POST' });
    toast(`Backup written to ${result.backup}`, 'good');
  } catch (err) { toast(`Backup failed: ${err.message}`, 'bad'); }
});

wire('btn-import', () => document.getElementById('import-dialog').showModal());
wire('import-go', async () => {
  const out = document.getElementById('import-result');
  let payload;
  try {
    payload = JSON.parse(document.getElementById('import-text').value);
  } catch (err) {
    out.textContent = `Not valid JSON: ${err.message}`;
    return;
  }
  out.textContent = 'Importing…';
  try {
    const result = await api('/api/import', { method: 'POST', body: payload });
    out.textContent = JSON.stringify(result, null, 2);
    toast('Import complete. Manual overrides were preserved.', 'good');
    setTimeout(() => location.reload(), 2500);
  } catch (err) {
    out.textContent = `Import failed: ${err.message}`;
    toast(`Import failed: ${err.message}`, 'bad');
  }
});

wire('btn-dry-alerts', async () => {
  try {
    const result = await api('/api/alerts/evaluate', { method: 'POST', body: {} });
    if (!result.alerts.length) { toast('No alert rule would fire right now.'); return; }
    for (const alert of result.alerts) {
      toast(`${alert.rule}: ${alert.retailer} ${money(alert.delivered)} (${alert.classification})`, 'good');
    }
  } catch (err) { toast(`Evaluate failed: ${err.message}`, 'bad'); }
});

/* ------------------------------------------------------------------ dialogs */

wire('btn-new-product', () => document.getElementById('new-product-dialog').showModal());
wire('np-save', async () => {
  const value = id => document.getElementById(id).value.trim();
  const number = id => value(id) === '' ? null : Number(value(id));
  try {
    const product = await api('/api/products', { method: 'POST', body: {
      name: value('np-name'), model: value('np-model'), brand: value('np-brand'),
      category: value('np-category') || 'general', verdict: value('np-verdict'),
      trigger_price: number('np-trigger'), excellent_price: number('np-excellent'),
      historical_low_price: number('np-histlow')
    }});
    location.href = `/products/${product.id}`;
  } catch (err) { toast(`Could not create product: ${err.message}`, 'bad'); }
});

wire('btn-add-listing', () => document.getElementById('listing-dialog').showModal());
wire('al-save', async () => {
  const value = id => document.getElementById(id).value.trim();
  const number = id => value(id) === '' ? null : Number(value(id));
  const productId = Number(location.pathname.split('/').pop());
  const body = {
    retailer: value('al-retailer'), url: value('al-url') || null,
    model_on_page: value('al-model') || null, advertised_price: number('al-price'),
    freight: number('al-freight'), cashback: number('al-cashback'),
    condition: value('al-condition'), stock_status: value('al-stock') || null,
    pickup_status: value('al-pickup') || null, warranty: value('al-warranty') || null,
    included_components: value('al-contents') || null, seller_notes: value('al-notes') || null
  };
  try {
    await api(`/api/products/${productId}/retailers`, { method: 'POST', body });
    toast('Listing added.', 'good');
    location.reload();
  } catch (err) { toast(`Could not add listing: ${err.message}`, 'bad'); }
});

/* ----------------------------------------------------------------- purchases */

wire('btn-mark-purchased', () => {
  const today = new Date().toISOString().slice(0, 10);
  const date = document.getElementById('pu-date');
  if (date && !date.value) date.value = today;
  prefillFromListing();
  document.getElementById('purchase-dialog').showModal();
});

/* Picking a listing fills the numbers from what the board already knows, so the common
   case is two clicks. Every field stays editable: what you paid is frequently not what
   the page said. */
function prefillFromListing() {
  const select = document.getElementById('pu-listing');
  if (!select) return;
  const option = select.selectedOptions[0];
  if (!option || !option.value) return;
  const set = (id, value) => {
    const el = document.getElementById(id);
    if (el && value !== undefined && value !== '') el.value = value;
  };
  set('pu-price', option.dataset.delivered);
  set('pu-advertised', option.dataset.advertised);
  set('pu-freight', option.dataset.freight);
  set('pu-condition', option.dataset.condition);
}
document.getElementById('pu-listing')?.addEventListener('change', prefillFromListing);

wire('pu-save', async () => {
  const productId = Number(location.pathname.split('/').pop());
  const value = id => (document.getElementById(id)?.value || '').trim();
  const number = id => value(id) === '' ? null : Number(value(id));
  if (value('pu-price') === '') {
    toast('Delivered price paid is required: it is the number the whole board ranks on.', 'bad');
    return;
  }
  const body = {
    listing_id: value('pu-listing') ? Number(value('pu-listing')) : null,
    retailer_name: value('pu-retailer') || null,
    price_paid: number('pu-price'),
    advertised_paid: number('pu-advertised'),
    freight_paid: number('pu-freight'),
    purchased_at: value('pu-date') || null,
    condition: value('pu-condition'),
    order_reference: value('pu-order') || null,
    warranty_months: number('pu-warranty'),
    price_protection_until: value('pu-protection') || null,
    notes: value('pu-notes') || null
  };
  try {
    await api(`/api/products/${productId}/purchase`, { method: 'POST', body });
    toast('Purchase recorded. Alerts for this product are off.', 'good');
    location.reload();
  } catch (err) { toast(`Could not record the purchase: ${err.message}`, 'bad'); }
});

wire('btn-undo-purchase', async event => {
  if (!confirm('Undo the purchase record and return this product to ACTIVE? The price history row is kept.')) return;
  const productId = Number(event.currentTarget.dataset.product);
  try {
    await api(`/api/products/${productId}/purchase`, { method: 'DELETE' });
    toast('Purchase record removed. Product is ACTIVE again.', 'good');
    location.reload();
  } catch (err) { toast(`Could not undo: ${err.message}`, 'bad'); }
});

wire('btn-edit-product', () => document.getElementById('product-dialog').showModal());
wire('ep-save', async () => {
  const productId = Number(location.pathname.split('/').pop());
  const text = ['name', 'model', 'brand', 'category', 'generation', 'verdict', 'status', 'vesa',
    'fit_notes', 'notes', 'lowest_known_notes', 'lowest_known_date', 'lowest_known_retailer'];
  const numeric = ['trigger_price', 'excellent_price', 'historical_low_price',
    'lowest_known_price', 'width_mm', 'height_mm', 'depth_mm', 'weight_kg'];
  const body = {};
  for (const key of text) {
    const el = document.getElementById(`ep-${key}`);
    if (el) body[key] = el.value.trim() || null;
  }
  for (const key of numeric) {
    const el = document.getElementById(`ep-${key}`);
    if (el) body[key] = el.value.trim() === '' ? null : Number(el.value);
  }
  try {
    body.specs = JSON.parse(document.getElementById('ep-specs').value || '{}');
    body.components = JSON.parse(document.getElementById('ep-components').value || '{}');
  } catch (err) {
    toast(`Specifications JSON is invalid: ${err.message}`, 'bad');
    return;
  }
  try {
    await api(`/api/products/${productId}`, { method: 'PATCH', body });
    toast('Product saved.', 'good');
    location.reload();
  } catch (err) { toast(`Could not save product: ${err.message}`, 'bad'); }
});

/* ----------------------------------------------------------------- price axis
 *
 * The axis carries every contender, so its domain is set by the dearest one and the
 * three targets end up crushed together at the cheap end. Zoom is therefore not a
 * nicety: at full extent the interesting part of the axis is a few percent wide.
 *
 * Two invariants:
 *   - the visible window is always stated in the readout. A zoomed axis that does not
 *     say where it is looking reads as the full picture and is worse than no axis.
 *   - labels are assigned to lanes by measured width, so a label never covers the line
 *     or another label. Server-rendered positions are the no-JS fallback, which is
 *     honest but unzoomed.
 */

const AXIS_MIN_SPAN = 20;        // never zoom past a $20 window: the dots would separate
                                 // into meaninglessness and the readout would imply
                                 // precision the prices do not have.
const LANE_HEIGHT = 30;
const LANE_COUNT = 3;
const CLUSTER_GAP = 26;          // px between dot centres below which they are one marker
const LABEL_PAD = 12;            // px of clear air each side of a label before it is a collision

function axisMoney(value) {
  return '$' + Math.round(value).toLocaleString('en-AU');
}

function setupAxis(root) {
  const plot = root.querySelector('[data-axis-plot]');
  const readout = root.querySelector('[data-axis-window]');
  const controls = root.querySelector('[data-axis-controls]');
  if (!plot) return;

  const full = { lo: Number(root.dataset.lo), hi: Number(root.dataset.hi) };
  if (!isFinite(full.lo) || !isFinite(full.hi) || full.hi <= full.lo) return;

  const points = Array.from(plot.querySelectorAll('[data-point]'));
  const thresholds = Array.from(plot.querySelectorAll('[data-threshold]'));
  const bands = Array.from(plot.querySelectorAll('[data-band]'));

  // Bands were positioned server-side against the full domain. Recover each band's
  // price range once, so zooming re-projects from prices rather than compounding
  // percentages, which would drift.
  const span = full.hi - full.lo;
  for (const band of bands) {
    band._from = full.lo + (Number(band.dataset.from) / 100) * span;
    band._to = full.lo + (Number(band.dataset.to) / 100) * span;
  }

  let view = { ...full };
  if (controls) controls.hidden = false;

  const project = value => ((value - view.lo) / (view.hi - view.lo)) * 100;

  function place(el, value) {
    const pos = project(value);
    const visible = pos >= -12 && pos <= 112;
    el.style.left = pos + '%';
    el.style.visibility = visible ? '' : 'hidden';
    return visible;
  }

  function clusterAndLabel() {
    // Five of these retailers sit within $32 of each other. Drawn individually at full
    // extent they are one illegible smudge of overlapping dots and text, which is worse
    // than not plotting them: it looks like a rendering fault rather than like a tie.
    //
    // So anything closer together than CLUSTER_GAP collapses into one marker that says
    // how many and over what range. Zooming in separates them again, which is the
    // honest relationship: they ARE nearly the same price, and the axis should say so.
    const width = plot.clientWidth || 1;
    const ordered = points
      .map(el => ({ el, value: Number(el.dataset.value), centre: (project(Number(el.dataset.value)) / 100) * width }))
      .filter(item => item.el.style.visibility !== 'hidden')
      .sort((a, b) => a.value - b.value);

    for (const { el } of ordered) {
      el.classList.remove('is-cluster', 'is-clustered');
      const label = el.querySelector('.axis-label');
      if (label && el._label !== undefined) label.innerHTML = el._label;
    }

    const groups = [];
    for (const item of ordered) {
      const last = groups[groups.length - 1];
      if (last && item.centre - last[last.length - 1].centre < CLUSTER_GAP) last.push(item);
      else groups.push([item]);
    }

    const laneEnds = new Array(LANE_COUNT).fill(-Infinity);
    for (const group of groups) {
      const lead = group[0];
      const label = lead.el.querySelector('.axis-label');

      if (group.length > 1) {
        for (const item of group.slice(1)) item.el.classList.add('is-clustered');
        lead.el.classList.add('is-cluster');
        lead.el.dataset.count = group.length;
        const lo = group[0].value;
        const hi = group[group.length - 1].value;
        if (label) {
          if (lead.el._label === undefined) lead.el._label = label.innerHTML;
          label.innerHTML = `<b>${axisMoney(lo)}${hi > lo ? ' to ' + axisMoney(hi) : ''}</b>${group.length} retailers`;
        }
      } else if (label && lead.el._label === undefined) {
        lead.el._label = label.innerHTML;
      }

      const half = (label ? label.offsetWidth : 60) / 2 + LABEL_PAD;
      // No lane has room. Hide the label rather than stacking it on the one already
      // in the bottom lane: an unreadable overlap is worse than an absent label, and
      // the dot still carries the figure in its title. The block comment above
      // promises labels never cover each other; this is what keeps that true.
      const lane = laneEnds.findIndex(end => lead.centre - half > end);
      if (lane === -1) {
        if (label) label.style.visibility = 'hidden';
        continue;
      }
      if (label) label.style.visibility = '';
      laneEnds[lane] = lead.centre + half;
      lead.el.style.setProperty('--leader', lane * LANE_HEIGHT + 'px');
      if (label) label.style.marginTop = (5 + lane * LANE_HEIGHT) + 'px';
    }
  }

  function draw() {
    for (const el of points) place(el, Number(el.dataset.value));
    for (const el of thresholds) place(el, Number(el.dataset.value));

    for (const band of bands) {
      const from = project(band._from);
      const to = project(band._to);
      const left = Math.max(from, -5);
      const right = Math.min(to, 105);
      const visible = right > left;
      band.style.visibility = visible ? '' : 'hidden';
      band.style.left = left + '%';
      band.style.width = Math.max(right - left, 0) + '%';
      // Name the band only when there is room for the words.
      const px = ((right - left) / 100) * (plot.clientWidth || 1);
      band.classList.toggle('is-roomy', px > 78);
    }

    clusterAndLabel();
    if (readout) {
      readout.textContent = view.lo <= full.lo && view.hi >= full.hi
        ? `${axisMoney(full.lo)} to ${axisMoney(full.hi)}, everything`
        : `${axisMoney(view.lo)} to ${axisMoney(view.hi)}`;
    }
  }

  function clamp(next) {
    let { lo, hi } = next;
    if (hi - lo < AXIS_MIN_SPAN) {
      const mid = (lo + hi) / 2;
      lo = mid - AXIS_MIN_SPAN / 2;
      hi = mid + AXIS_MIN_SPAN / 2;
    }
    // Allow a little overscroll so an edge dot is not pinned to the frame, but never
    // let the window wander off the data entirely.
    const pad = (full.hi - full.lo) * 0.25;
    if (lo < full.lo - pad) { hi += (full.lo - pad) - lo; lo = full.lo - pad; }
    if (hi > full.hi + pad) { lo -= hi - (full.hi + pad); hi = full.hi + pad; }
    view = { lo, hi };
  }

  function zoomAt(factor, anchorRatio) {
    const width = view.hi - view.lo;
    const anchor = view.lo + width * anchorRatio;
    const next = width * factor;
    clamp({ lo: anchor - next * anchorRatio, hi: anchor + next * (1 - anchorRatio) });
    draw();
  }

  // Zoom on ctrl/cmd + wheel only. Swallowing every wheel event made the axis a
  // scroll trap: with the pointer anywhere over a 150px plot the page stopped
  // moving and the axis zoomed instead, with no modifier to escape it and no way
  // to scroll past. With several products stacked that is a wall, not a quirk.
  // A plain wheel now scrolls the page, which is what a wheel is for.
  plot.addEventListener('wheel', event => {
    if (!event.ctrlKey && !event.metaKey) return;   // let the page have it
    event.preventDefault();
    const rect = plot.getBoundingClientRect();
    const ratio = rect.width ? (event.clientX - rect.left) / rect.width : 0.5;
    zoomAt(event.deltaY > 0 ? 1.18 : 0.85, Math.min(Math.max(ratio, 0), 1));
  }, { passive: false });

  let dragging = null;
  plot.addEventListener('pointerdown', event => {
    dragging = { x: event.clientX, lo: view.lo, hi: view.hi };
    plot.setPointerCapture(event.pointerId);
  });
  plot.addEventListener('pointermove', event => {
    if (!dragging) return;
    const rect = plot.getBoundingClientRect();
    if (!rect.width) return;
    const moved = ((event.clientX - dragging.x) / rect.width) * (dragging.hi - dragging.lo);
    clamp({ lo: dragging.lo - moved, hi: dragging.hi - moved });
    draw();
  });
  const endDrag = () => { dragging = null; };
  plot.addEventListener('pointerup', endDrag);
  plot.addEventListener('pointercancel', endDrag);

  plot.addEventListener('keydown', event => {
    const step = (view.hi - view.lo) * 0.15;
    if (event.key === 'ArrowRight') { clamp({ lo: view.lo + step, hi: view.hi + step }); }
    else if (event.key === 'ArrowLeft') { clamp({ lo: view.lo - step, hi: view.hi - step }); }
    else if (event.key === '+' || event.key === '=') { zoomAt(0.8, 0.5); return; }
    else if (event.key === '-') { zoomAt(1.25, 0.5); return; }
    else if (event.key === '0') { view = { ...full }; }
    else return;
    event.preventDefault();
    draw();
  });

  if (controls) {
    controls.addEventListener('click', event => {
      const button = event.target.closest('[data-axis-zoom]');
      if (!button) return;
      const mode = button.dataset.axisZoom;
      if (mode === 'in') zoomAt(0.7, 0.5);
      else if (mode === 'out') zoomAt(1.4, 0.5);
      else if (mode === 'fit') { view = { ...full }; draw(); }
      else if (mode === 'targets') {
        // The three targets plus a little air. This is the view that answers "how far
        // off are we", which is the question the product exists to answer.
        const values = thresholds.map(el => Number(el.dataset.value)).filter(isFinite);
        if (!values.length) return;
        const lo = Math.min(...values);
        const hi = Math.max(...values);
        const pad = Math.max((hi - lo) * 0.35, 40);
        clamp({ lo: lo - pad, hi: hi + pad });
        draw();
      }
    });
  }

  // Tone each dot by the territory it actually lands in, so the colour on the axis and
  // the colour in the list below come from the same fact rather than being set twice.
  const toneBands = bands
    .filter(b => b.classList.contains('tone-act') || b.classList.contains('tone-close'))
    .map(b => ({ to: b._to, tone: b.classList.contains('tone-act') ? 'at-act' : 'at-close' }))
    .sort((a, b) => a.to - b.to);
  for (const el of points) {
    const value = Number(el.dataset.value);
    const hit = toneBands.find(b => value <= b.to);
    if (hit) el.classList.add(hit.tone);
  }

  const observer = new ResizeObserver(() => draw());
  observer.observe(plot);
  draw();
}

for (const root of document.querySelectorAll('[data-axis]')) setupAxis(root);
