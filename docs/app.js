/**
 * Melbourne Lease Transfer & Hawthorn Commute Finder — Frontend Application
 *
 * Loads daily scraped listings from `data/listings.json`, merges user-saved
 * Facebook Marketplace / Fairy Floss posts and application statuses from localStorage,
 * and provides interactive filtering and live criteria scoring.
 */

const STORAGE_STATUS_KEY = 'melb_rental_statuses_v1';
const STORAGE_CUSTOM_POSTS_KEY = 'melb_rental_custom_fb_v1';

let appData = {
  listings: [],
  portal_quick_links: [],
  hawthorn_corridor_suburbs: {},
  stats: {},
  last_updated: null
};

let filterState = {
  search: '',
  suburb: 'all',
  bedrooms: 'all',
  furnished: 'all',
  leaseTransferOnly: false,
  strictOnly: false
};

function getSavedStatuses() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_STATUS_KEY) || '{}');
  } catch {
    return {};
  }
}

function setSavedStatus(listingId, status) {
  const current = getSavedStatuses();
  if (!status || status === 'none') {
    delete current[listingId];
  } else {
    current[listingId] = status;
  }
  localStorage.setItem(STORAGE_STATUS_KEY, JSON.stringify(current));
  renderAll();
}

function getCustomPosts() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_CUSTOM_POSTS_KEY) || '[]');
  } catch {
    return [];
  }
}

function saveCustomPost(listing) {
  const posts = getCustomPosts();
  posts.unshift(listing);
  localStorage.setItem(STORAGE_CUSTOM_POSTS_KEY, JSON.stringify(posts));
}

function updateCountdownBanner() {
  const now = new Date();
  const dec3 = new Date('2026-12-03T23:59:59+11:00');
  const diffDays = Math.max(0, Math.ceil((dec3 - now) / (1000 * 60 * 60 * 24)));
  const pill = document.getElementById('countdown-pill');
  if (pill) {
    pill.textContent = `⏳ ${diffDays} Days to Dec 3 Notice Deadline`;
  }
}

function getAllMergedListings() {
  const custom = getCustomPosts();
  const base = appData.listings || [];
  const seen = new Set(custom.map(i => i.id));
  return [...custom, ...base.filter(i => !seen.has(i.id))];
}

function createListingCardHTML(item) {
  const statuses = getSavedStatuses();
  const userStatus = statuses[item.id] || 'none';

  const scoreClass = item.match_score >= 85 ? '' : item.match_score >= 70 ? 'medium' : 'low';
  const furnLabel = item.is_furnished ? 'Furnished (≤$560 cap)' : 'Unfurnished (≤$525 cap)';
  const fallbackPhoto = 'https://images.unsplash.com/photo-1502672260266-1c1ef2d93688?auto=format&fit=crop&w=800&q=80';
  const photoUrl = item.photo && item.photo.startsWith('http') ? item.photo : fallbackPhoto;

  const badgePills = [];
  if (item.bedrooms === 2) {
    badgePills.push(`<span class="spec-badge highlight-2bhk">★ 2 BHK (Preferred)</span>`);
  } else {
    badgePills.push(`<span class="spec-badge">${item.bedrooms || 1} BHK Entire Place</span>`);
  }

  badgePills.push(`<span class="spec-badge highlight-dec">📅 ${escapeHtml(item.availability_display || item.date_available)}</span>`);

  if (item.rejection_reason) {
    badgePills.push(`<span class="spec-badge rejected">⚠️ ${escapeHtml(item.rejection_reason)}</span>`);
  }

  return `
    <article class="listing-card" data-id="${escapeHtml(item.id)}">
      <div class="listing-media">
        <img src="${escapeHtml(photoUrl)}" alt="${escapeHtml(item.title)}" loading="lazy">
        <div class="media-top-badges">
          <span class="score-pill ${scoreClass}">${item.match_score}% Match</span>
          ${item.is_lease_transfer ? `<span class="lease-transfer-ribbon">🔄 Lease Transfer</span>` : ''}
        </div>
        <div class="price-overlay">
          $${item.weekly_rent || '—'}/wk
          <span class="furn-tag">${escapeHtml(furnLabel)}</span>
        </div>
      </div>

      <div class="listing-body">
        <div class="listing-meta-row">
          <span class="suburb-pill">📍 ${escapeHtml(item.suburb || 'Melbourne')} ${escapeHtml(item.postcode || '')}</span>
          <span>${escapeHtml(item.source || 'Listing')}</span>
        </div>

        <h3 class="listing-title">${escapeHtml(item.title)}</h3>

        <div class="transit-box">
          <strong>🚆 Direct to Hawthorn: ${escapeHtml(item.commute_mode || 'Check route')} (~${item.commute_mins || 15} mins)</strong>
          <span>${escapeHtml(item.commute_line || '')}</span>
        </div>

        <div class="station-box">
          <span>🚉 <strong>Train Station:</strong> ${escapeHtml(item.station_distance_display || 'Near local station')}</span>
        </div>

        <div class="specs-row">
          ${badgePills.join('')}
        </div>

        <p class="listing-desc">${escapeHtml(item.description || item.subhead || '')}</p>

        <div class="listing-footer">
          <select class="status-select" data-listing-id="${escapeHtml(item.id)}" aria-label="Application status">
            <option value="none" ${userStatus === 'none' ? 'selected' : ''}>📌 Status: Untracked</option>
            <option value="shortlist" ${userStatus === 'shortlist' ? 'selected' : ''}>⭐ Shortlisted</option>
            <option value="inspecting" ${userStatus === 'inspecting' ? 'selected' : ''}>🗓️ Booked Inspection</option>
            <option value="applied" ${userStatus === 'applied' ? 'selected' : ''}>✅ Applied for Lease</option>
            <option value="hidden" ${userStatus === 'hidden' ? 'selected' : ''}>🚫 Hide Listing</option>
          </select>

          <a href="${escapeHtml(item.url || '#')}" target="_blank" rel="noopener" class="btn btn-primary">
            Open Listing ↗
          </a>
        </div>
      </div>
    </article>
  `;
}

function renderListings() {
  const container = document.getElementById('listings-container');
  const shortlistContainer = document.getElementById('shortlist-container');
  const statuses = getSavedStatuses();
  const all = getAllMergedListings();

  const filtered = all.filter(item => {
    const st = statuses[item.id] || 'none';
    if (st === 'hidden') return false;

    if (filterState.strictOnly && !item.pass_strict_filter) return false;
    if (filterState.leaseTransferOnly && !item.is_lease_transfer) return false;

    if (filterState.suburb && filterState.suburb !== 'all') {
      const sub = (item.suburb || '').toLowerCase();
      const addr = (item.address || '').toLowerCase();
      const q = filterState.suburb.toLowerCase();
      if (!sub.includes(q) && !addr.includes(q)) return false;
    }

    if (filterState.bedrooms === '2' && item.bedrooms !== 2) return false;
    if (filterState.bedrooms === '1' && item.bedrooms !== 1) return false;

    if (filterState.furnished === 'unfurnished' && item.is_furnished) return false;
    if (filterState.furnished === 'furnished' && !item.is_furnished) return false;

    if (filterState.search) {
      const q = filterState.search.toLowerCase();
      const hay = `${item.title} ${item.suburb} ${item.address} ${item.commute_line} ${item.station_distance_display || ''} ${item.description}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  if (filtered.length === 0) {
    container.innerHTML = `
      <div class="panel-card" style="grid-column: 1 / -1; text-align: center; padding: 2.5rem;">
        <h3>No listings match the current filter combination</h3>
        <p class="helper-text" style="margin-top: 0.4rem;">Try unchecking "Lease Transfers Only" or "Strict Criteria Only" to see near-matches.</p>
      </div>
    `;
  } else {
    container.innerHTML = filtered.map(createListingCardHTML).join('');
  }

  // Render Shortlist tab
  const shortlisted = all.filter(item => {
    const st = statuses[item.id];
    return st === 'shortlist' || st === 'inspecting' || st === 'applied';
  });

  document.getElementById('count-strict').textContent = filtered.length;
  document.getElementById('count-shortlist').textContent = shortlisted.length;

  if (shortlisted.length === 0) {
    shortlistContainer.innerHTML = `
      <div class="panel-card" style="grid-column: 1 / -1; text-align: center; padding: 2.5rem;">
        <h3>No properties shortlisted yet</h3>
        <p class="helper-text" style="margin-top: 0.4rem;">Use the status dropdown on any listing card to mark it as Shortlisted, Booked Inspection, or Applied.</p>
      </div>
    `;
  } else {
    shortlistContainer.innerHTML = shortlisted.map(createListingCardHTML).join('');
  }

  // Bind status dropdown listeners
  document.querySelectorAll('.status-select').forEach(selectEl => {
    selectEl.addEventListener('change', e => {
      const id = e.target.getAttribute('data-listing-id');
      setSavedStatus(id, e.target.value);
    });
  });
}

function renderPortalsAndCorridor() {
  const portalContainer = document.getElementById('portal-links-container');
  const links = appData.portal_quick_links || [];
  document.getElementById('count-portals').textContent = links.length;

  portalContainer.innerHTML = links.map(link => `
    <div class="portal-link-card">
      <div>
        <span class="suburb-pill" style="display:inline-block; margin-bottom: 0.45rem;">${escapeHtml(link.category)}</span>
        <h3 style="font-size: 1rem; margin-bottom: 0.35rem;">${escapeHtml(link.name)}</h3>
        <p style="font-size: 0.84rem; color: var(--text-secondary);">${escapeHtml(link.note)}</p>
      </div>
      <a href="${escapeHtml(link.url)}" target="_blank" rel="noopener" class="btn btn-primary" style="align-self: flex-start;">
        Launch Filtered Search ↗
      </a>
    </div>
  `).join('');

  // Render Hawthorn commute table
  const tbody = document.getElementById('corridor-tbody');
  const suburbsObj = appData.hawthorn_corridor_suburbs || {};
  const entries = Object.entries(suburbsObj).sort((a, b) => a[1].commute_mins - b[1].commute_mins);

  tbody.innerHTML = entries.map(([name, info]) => `
    <tr>
      <td><strong>${escapeHtml(name.replace(/\b\w/g, c => c.toUpperCase()))}</strong></td>
      <td style="font-family: var(--font-mono);">${escapeHtml(info.postcode)}</td>
      <td><span class="suburb-pill">${escapeHtml(info.mode)}</span></td>
      <td>${escapeHtml(info.line)}</td>
      <td style="font-family: var(--font-mono); font-weight: 600;">~${info.commute_mins} mins</td>
    </tr>
  `).join('');
}

function analyzeFacebookPostText(rawText, postUrl) {
  const lower = rawText.toLowerCase();

  // 1. Furnished detection
  const isUnfurn = /\bunfurnished\b|\bnot\s+furnished\b/.test(lower);
  const isFurn = !isUnfurn && (/\bfully\s+furnished\b|\bfurnished\b|\bincludes\s+furniture\b/.test(lower));
  const maxCap = isFurn ? 560 : 525;

  // 2. Price detection
  const mPrice = rawText.replace(/,/g, '').match(/\$\s*(\d{3,4})/);
  let weeklyRent = mPrice ? parseInt(mPrice[1], 10) : null;
  if (weeklyRent && weeklyRent > 1400) {
    weeklyRent = Math.round((weeklyRent * 12) / 52);
  }
  const withinBudget = weeklyRent !== null && weeklyRent >= 260 && weeklyRent <= maxCap;

  // 3. Bedrooms & Sharehouse check
  const mBed = lower.match(/\b(\d)\s*(?:bed|br|bhk|bedroom)/);
  const bedrooms = mBed ? parseInt(mBed[1], 10) : 2;
  const isSharehouse = /\bshare\s*house\b|\bflat\s*share\b|\broom\s+for\s+rent\b|\bprivate\s+room\b|\bhousemates?\b/.test(lower)
    && !/\bentire\b|\bwhole\s+property\b|\bno\s+housemates\b/.test(lower);

  const isLeaseTransfer = /\blease\s+transfer\b|\blease\s+break\b|\bbreak\s+lease\b|\btake\s*over\b/.test(lower);

  // 4. Match suburb against Hawthorn direct corridor
  const suburbsObj = appData.hawthorn_corridor_suburbs || {};
  let matchedSuburb = 'Melbourne';
  let commuteInfo = null;
  const sortedNames = Object.keys(suburbsObj).sort((a, b) => b.length - a.length);
  for (const sName of sortedNames) {
    if (lower.includes(sName)) {
      matchedSuburb = sName.replace(/\b\w/g, c => c.toUpperCase());
      commuteInfo = suburbsObj[sName];
      break;
    }
  }

  // 5. Move-in date detection
  const mDec = lower.match(/\b(?:(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?dec(?:ember)?|dec(?:ember)?\s+(\d{1,2}))\b/);
  let availDisplay = 'Dec 2026 (Flexible)';
  let isDecWindow = true;
  if (mDec) {
    const day = parseInt(mDec[1] || mDec[2], 10);
    availDisplay = `Dec ${day}, 2026`;
    isDecWindow = day >= 5 && day <= 30;
  }

  // Calculate score
  let score = 0;
  const reasons = [];
  if (isSharehouse) reasons.push('Sharehouse / Room only');
  if (!weeklyRent) reasons.push('Weekly rent not detected');
  else if (!withinBudget) reasons.push(`Over budget ($${weeklyRent}/wk vs $${maxCap} cap)`);
  if (!commuteInfo) reasons.push('Suburb not on direct Hawthorn train/tram line');

  if (withinBudget) score += 30;
  if (bedrooms === 2) score += 25;
  else if (bedrooms === 1) score += 15;
  if (commuteInfo) score += (commuteInfo.tier === 1 ? 25 : 19);
  if (isLeaseTransfer) score += 10;
  if (isDecWindow) score += 10;

  const passStrict = reasons.length === 0;

  return {
    id: 'fb-custom-' + Date.now(),
    source: 'FB Marketplace / Group (Saved)',
    title: `${isLeaseTransfer ? 'Lease Transfer: ' : ''}${bedrooms}BHK in ${matchedSuburb}`,
    subhead: `Saved from FB • ${isFurn ? 'Furnished' : 'Unfurnished'}`,
    address: `${matchedSuburb}, VIC ${commuteInfo ? commuteInfo.postcode : ''}`,
    weekly_rent: weeklyRent,
    is_furnished: isFurn,
    bedrooms,
    is_lease_transfer: isLeaseTransfer,
    is_sharehouse: isSharehouse,
    suburb: matchedSuburb,
    postcode: commuteInfo ? commuteInfo.postcode : '',
    commute_mode: commuteInfo ? commuteInfo.mode : 'Indirect / Check PTV',
    commute_line: commuteInfo ? commuteInfo.line : 'Requires transfer to reach Hawthorn',
    commute_mins: commuteInfo ? commuteInfo.commute_mins : 35,
    availability_display: availDisplay,
    description: rawText.trim(),
    url: postUrl || 'https://www.facebook.com/marketplace/melbourne/propertyrentals',
    photo: 'https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?auto=format&fit=crop&w=800&q=80',
    match_score: Math.min(100, score),
    pass_strict_filter: passStrict,
    rejection_reason: reasons.length ? reasons.join('; ') : null
  };
}

function escapeHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function renderAll() {
  const all = getAllMergedListings();
  const strictCount = all.filter(i => i.pass_strict_filter).length;
  const ltCount = all.filter(i => i.pass_strict_filter && i.is_lease_transfer).length;
  const twoBhkCount = all.filter(i => i.pass_strict_filter && i.bedrooms === 2).length;

  document.getElementById('stat-strict-matches').textContent = `${strictCount} Strict Matches`;
  document.getElementById('stat-sub-summary').textContent =
    `${twoBhkCount} are 2BHK • ${ltCount} Lease Transfers • ${all.length} total scanned`;

  if (appData.last_updated) {
    const dt = new Date(appData.last_updated);
    document.getElementById('last-updated-pill').textContent =
      `Last Scraped: ${dt.toLocaleDateString('en-AU', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}`;
  }

  renderListings();
  renderPortalsAndCorridor();
}

async function initApp() {
  updateCountdownBanner();

  // Tab switching
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.panel-section').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      const target = document.getElementById(btn.getAttribute('data-tab'));
      if (target) target.classList.add('active');
    });
  });

  // Quick button to jump to FB analyzer
  document.getElementById('btn-open-fb-analyzer').addEventListener('click', () => {
    document.getElementById('tab-fb-analyzer').click();
    document.getElementById('fb-post-text').focus();
  });

  // Filters
  document.getElementById('search-input').addEventListener('input', e => {
    filterState.search = e.target.value.trim();
    renderListings();
  });

  const suburbEl = document.getElementById('suburb-filter');
  if (suburbEl) {
    suburbEl.addEventListener('change', e => {
      filterState.suburb = e.target.value;
      renderListings();
    });
  }

  document.getElementById('bedroom-filter').addEventListener('change', e => {
    filterState.bedrooms = e.target.value;
    renderListings();
  });

  document.getElementById('furn-filter').addEventListener('change', e => {
    filterState.furnished = e.target.value;
    renderListings();
  });

  const chipLT = document.getElementById('chip-lease-transfer');
  chipLT.addEventListener('click', () => {
    filterState.leaseTransferOnly = !filterState.leaseTransferOnly;
    chipLT.classList.toggle('active', filterState.leaseTransferOnly);
    renderListings();
  });

  const chipStrict = document.getElementById('chip-strict-only');
  chipStrict.addEventListener('click', () => {
    filterState.strictOnly = !filterState.strictOnly;
    chipStrict.classList.toggle('active', filterState.strictOnly);
    renderListings();
  });

  // FB Post Analyzer
  document.getElementById('btn-load-sample-fb').addEventListener('click', () => {
    document.getElementById('fb-post-url').value = 'https://www.facebook.com/groups/fairyflossrealestate/';
    document.getElementById('fb-post-text').value =
      'LEASE TRANSFER — Camberwell / Hawthorn East border (3124)! Entire 2 bedroom, 1 bathroom furnished apartment with balcony and carpark. $545 per week (furnished). 3 mins walk to Riversdale Tram 70 & Camberwell train station (direct to Hawthorn in 5 mins). Move-in date flexible from December 14th, 2026. Not a sharehouse — whole apartment lease takeover until Sept 2027.';
  });

  document.getElementById('btn-score-fb-post').addEventListener('click', () => {
    const rawText = document.getElementById('fb-post-text').value.trim();
    const postUrl = document.getElementById('fb-post-url').value.trim();
    if (!rawText) return;

    const evaluated = analyzeFacebookPostText(rawText, postUrl);
    saveCustomPost(evaluated);
    setSavedStatus(evaluated.id, 'shortlist');

    const out = document.getElementById('fb-analysis-output');
    out.innerHTML = `
      <div style="padding: 0.9rem; border-radius: 8px; background: ${evaluated.pass_strict_filter ? 'var(--brand-forest-soft)' : 'var(--danger-soft)'}; margin-bottom: 0.85rem;">
        <strong style="color: ${evaluated.pass_strict_filter ? 'var(--brand-forest)' : 'var(--danger-crimson)'}; font-size: 1rem;">
          ${evaluated.pass_strict_filter ? `✅ PASSED ALL CRITERIA (${evaluated.match_score}% Match)` : `⚠️ FLAGGED: ${escapeHtml(evaluated.rejection_reason)}`}
        </strong>
      </div>
      <ul style="list-style: none; display: grid; gap: 0.45rem;">
        <li><strong>Detected Rent:</strong> $${evaluated.weekly_rent || '—'}/wk (${evaluated.is_furnished ? 'Furnished ≤$560 cap' : 'Unfurnished ≤$525 cap'})</li>
        <li><strong>Property Type:</strong> ${evaluated.bedrooms} BHK (${evaluated.is_sharehouse ? 'Sharehouse Flagged' : 'Entire Property'})</li>
        <li><strong>Hawthorn Commute:</strong> ${escapeHtml(evaluated.suburb)} — ${escapeHtml(evaluated.commute_mode)} (~${evaluated.commute_mins}m)</li>
        <li><strong>Move-In Window:</strong> ${escapeHtml(evaluated.availability_display)}</li>
      </ul>
      <p style="margin-top: 0.85rem; font-weight: 600; color: var(--brand-forest);">
        Saved to "Strict Hawthorn Matches" and "My Shortlist"!
      </p>
    `;
    renderAll();
  });

  try {
    const resp = await fetch(`data/listings.json?t=${Date.now()}`);
    appData = await resp.json();
  } catch (err) {
    console.error('Error loading listings.json:', err);
  }

  renderAll();
}

document.addEventListener('DOMContentLoaded', initApp);
