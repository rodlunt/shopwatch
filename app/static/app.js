/* Shopwatch UI: inline editing, dialogs, price watch, import.
   Deliberately small and framework-free. */

const MONEY = new Intl.NumberFormat('en-AU', { style: 'currency', currency: 'AUD',
  minimumFractionDigits: 0, maximumFractionDigits: 2 });
const money = v => (v === null || v === undefined || v === '') ? '—' : MONEY.format(v);

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
    span.innerHTML = '<span class="unresolved">—</span>';
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
    price.innerHTML = listing.delivered_price === null
      ? '<span class="unresolved">no price</span>'
      : `${money(listing.delivered_price)}<small>${listing.delivered_resolved ? 'delivered' : 'before freight'}</small>`;
  }

  const tag = row.querySelector('[data-cell="classification"]');
  if (tag) tag.innerHTML = tagFor(listing);

  row.classList.toggle('is-act', ['HISTORICAL_LOW', 'EXCELLENT'].includes(listing.classification));
  row.classList.toggle('is-close', listing.classification === 'TRIGGER_MET');

  for (const [field, prov] of Object.entries(listing.provenance || {})) {
    const span = row.querySelector(`[data-edit][data-field="${field}"]`);
    if (!span) continue;
    renderValue(span, listing[field]);
    const label = span.closest('.field')?.querySelector('.k');
    if (label) {
      label.querySelectorAll('.lock, .src').forEach(n => n.remove());
      label.insertAdjacentHTML('beforeend', provenanceMark(listing.id, field, prov));
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
  best.innerHTML = `<b>${money(product.scale.best.value)}</b>` +
    `<small>${product.best_retailer || ''}${product.best_resolved ? '' : ', freight unknown'}</small><i></i>`;
}

function tagFor(listing) {
  if (listing.verification?.model?.status === 'FLAGGED') return '<span class="tag fault">model mismatch</span>';
  if (['HISTORICAL_LOW', 'EXCELLENT'].includes(listing.classification)) {
    return `<span class="tag act">${listing.classification === 'HISTORICAL_LOW' ? 'historical low' : 'excellent'}</span>`;
  }
  if (listing.classification === 'TRIGGER_MET') return '<span class="tag close">at target</span>';
  if (listing.classification === 'UNRESOLVED') return '<span class="tag">unconfirmed</span>';
  return '';
}

function provenanceMark(listingId, field, prov) {
  if (prov.manual_locked) {
    return ` <button class="lock" data-clear-override data-listing="${listingId}" data-field="${field}"` +
           ` title="You set this by hand. Automated runs will not change it. Click to hand it back.">set by hand</button>`;
  }
  if (prov.state === 'STALE') return ' <span class="src">stale</span>';
  if (prov.source) return ` <span class="src">${prov.source}</span>`;
  return '';
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
