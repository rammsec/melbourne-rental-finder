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
  newOnly: false,
  leaseTransferOnly: false,
  strictOnly: false
};

let filterStateNormal = {
  search: '',
  suburb: 'all',
  bedrooms: 'all',
  furnished: 'all',
  maxRent: 600,
  newOnly: false,
  excludeLeaseTransfers: false
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

function cycleStarStatus(listingId) {
  const current = getSavedStatuses();
  const st = current[listingId] || 'none';
  // 3-state toggle: Default (none) -> 1st click: Green Star (shortlist) -> 2nd click: Red Star (skipped) -> 3rd click: Reset (none)
  if (st === 'none') {
    setSavedStatus(listingId, 'shortlist');
  } else if (st === 'shortlist' || st === 'inspecting' || st === 'applied') {
    setSavedStatus(listingId, 'skipped');
  } else {
    setSavedStatus(listingId, 'none');
  }
}

function isStudentOnlyListing(item) {
  if (item.is_student_only) return true;
  const text = `${item.title || ''} ${item.subhead || ''} ${item.description || ''}`.toLowerCase();
  return /\bstudent\s+only\b|\bstudents\s+only\b|\bstudent\s+accommodation\b|\bunilodge\b|\bsha\.com\.au\b|\bstudent\s+housing\s+australia\b|\bscape\b|\biglu\b|\byugo\b|\brooming\s+house\b|^wanted:/i.test(text);
}

function isRecentNewListing(item) {
  if (item.is_new) return true;
  if (item.listed_at) {
    const dt = new Date(item.listed_at);
    if (!isNaN(dt.getTime())) {
      const ageHours = (Date.now() - dt.getTime()) / (1000 * 60 * 60);
      if (ageHours >= 0 && ageHours <= 60) return true;
    }
  }
  const sub = (item.subhead || '').toLowerCase();
  if (sub.includes('hour') || sub.includes('yesterday') || sub.includes('today')) return true;
  return false;
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

function getListingAgeDays(listedAt) {
  if (!listedAt) return 0;
  const dt = new Date(listedAt);
  if (isNaN(dt.getTime())) return 0;
  return Math.max(0, (Date.now() - dt.getTime()) / (1000 * 60 * 60 * 24));
}

function getAllMergedListings() {
  const custom = getCustomPosts();
  const base = appData.listings || [];
  const seen = new Set(custom.map(i => i.id));
  const merged = [...custom, ...base.filter(i => !seen.has(i.id))];
  const statuses = getSavedStatuses();

  return merged.filter(item => {
    // 1. Exclude Student Only Accommodation
    if (isStudentOnlyListing(item)) return false;

    // 2. Exclude if user marked as leased / gone
    if (statuses[item.id] === 'leased') return false;

    // 3. Exclude missing price or invalid dummy listings
    const rent = item.weekly_rent;
    if (!rent || rent < 200) return false;
    if ((item.title || '').trim().toLowerCase() === 'lease listing') return false;

    // 4. Enforce strict freshness cutoffs:
    // - Lease transfers: within last 15 days
    // - Normal listings: within last 10 days
    const ageDays = getListingAgeDays(item.listed_at);
    if (item.is_lease_transfer) {
      if (ageDays > 15.5) return false;
    } else {
      if (ageDays > 10.5) return false;
    }

    return true;
  });
}

function createListingCardHTML(item) {
  const statuses = getSavedStatuses();
  const userStatus = statuses[item.id] || 'none';
  const isNew = isRecentNewListing(item);

  const isGreenStar = userStatus === 'shortlist' || userStatus === 'inspecting' || userStatus === 'applied';
  const isRedStar = userStatus === 'skipped' || userStatus === 'hidden';

  let starBtnClass = 'star-btn';
  let starIcon = '☆';
  let starLabel = 'Star';
  let starTitle = 'Click once for Green Star (Interested), twice for Red Star (Skip to bottom)';
  if (isGreenStar) {
    starBtnClass = 'star-btn star-green';
    starIcon = '★';
    starLabel = 'Interested';
    starTitle = 'Green Star (Interested) — Click again for Red Star (Not Interested / Move to bottom)';
  } else if (isRedStar) {
    starBtnClass = 'star-btn star-red';
    starIcon = '★';
    starLabel = 'Skipped';
    starTitle = 'Red Star (Skipped) — Click again to reset star';
  }

  const cardExtraClasses = [
    isNew ? 'is-new-listing' : '',
    isGreenStar ? 'is-shortlisted-card' : ''
  ].filter(Boolean).join(' ');

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
    <article class="listing-card ${cardExtraClasses}" data-id="${escapeHtml(item.id)}">
      <div class="listing-media">
        <img src="${escapeHtml(photoUrl)}" alt="${escapeHtml(item.title)}" loading="lazy">
        <div class="media-top-badges">
          <div class="media-left-badges">
            <span class="score-pill ${scoreClass}">${item.match_score}% Match</span>
            ${isNew ? `<span class="new-listing-badge">✨ NEW LISTING</span>` : ''}
            ${item.is_lease_transfer ? `<span class="lease-transfer-ribbon">🔄 Lease Transfer</span>` : `<span class="lease-transfer-ribbon normal-ribbon">🏠 Normal Rental</span>`}
          </div>
          <button
            type="button"
            class="${starBtnClass}"
            data-star-id="${escapeHtml(item.id)}"
            title="${escapeHtml(starTitle)}"
            aria-label="${escapeHtml(starTitle)}"
          >
            <span class="star-icon">${starIcon}</span>
            <span>${starLabel}</span>
          </button>
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
            <option value="none" ${userStatus === 'none' ? 'selected' : ''}>☆ No Star (Default)</option>
            <option value="shortlist" ${userStatus === 'shortlist' ? 'selected' : ''}>🟢 Green Star (Shortlisted)</option>
            <option value="inspecting" ${userStatus === 'inspecting' ? 'selected' : ''}>🗓️ Booked Inspection</option>
            <option value="applied" ${userStatus === 'applied' ? 'selected' : ''}>✅ Applied for Lease</option>
            <option value="skipped" ${(userStatus === 'skipped' || userStatus === 'hidden') ? 'selected' : ''}>🔴 Red Star (Skip to Bottom)</option>
            <option value="leased" ${userStatus === 'leased' ? 'selected' : ''}>🔴 Mark as Leased / Gone</option>
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
  const skippedSection = document.getElementById('skipped-section');
  const skippedContainer = document.getElementById('skipped-container');
  const countSkippedEl = document.getElementById('count-skipped');
  const shortlistContainer = document.getElementById('shortlist-container');
  const statuses = getSavedStatuses();
  const all = getAllMergedListings();

  const matchingFilter = all.filter(item => {
    if (filterState.strictOnly && !item.pass_strict_filter) return false;
    if (filterState.leaseTransferOnly && !item.is_lease_transfer) return false;
    if (filterState.newOnly && !isRecentNewListing(item)) return false;

    if (filterState.suburb && filterState.suburb !== 'all') {
      const sub = (item.suburb || '').toLowerCase();
      const addr = (item.address || '').toLowerCase();
      const q = filterState.suburb.toLowerCase();
      if (!sub.includes(q) && !addr.includes(q)) return false;
    }

    if (filterState.bedrooms === '1' && item.bedrooms !== 1) return false;
    if (filterState.bedrooms === '2' && item.bedrooms !== 2) return false;
    if (filterState.bedrooms === '3' && item.bedrooms < 3) return false;

    if (filterState.furnished === 'unfurnished' && item.is_furnished) return false;
    if (filterState.furnished === 'furnished' && !item.is_furnished) return false;

    if (filterState.search) {
      const q = filterState.search.toLowerCase();
      const hay = `${item.title} ${item.suburb} ${item.address} ${item.commute_line} ${item.station_distance_display || ''} ${item.description}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  // Partition into active vs red-starred (skipped) listings
  const activeListings = [];
  const skippedListings = [];
  for (const item of matchingFilter) {
    const st = statuses[item.id] || 'none';
    if (st === 'skipped' || st === 'hidden') {
      skippedListings.push(item);
    } else {
      activeListings.push(item);
    }
  }

  // Sort active listings so Green Star (shortlisted) or New Listings are easy to spot
  activeListings.sort((a, b) => {
    const stA = statuses[a.id] === 'shortlist' ? 1 : 0;
    const stB = statuses[b.id] === 'shortlist' ? 1 : 0;
    if (stA !== stB) return stB - stA;
    return 0;
  });

  if (activeListings.length === 0) {
    container.innerHTML = `
      <div class="panel-card" style="grid-column: 1 / -1; text-align: center; padding: 2.5rem;">
        <h3>No active listings match the current filter combination</h3>
        <p class="helper-text" style="margin-top: 0.4rem;">Try clearing a filter chip or check the Skipped section below.</p>
      </div>
    `;
  } else {
    container.innerHTML = activeListings.map(createListingCardHTML).join('');
  }

  // Render Bottom Skipped (Red Star) Section
  if (skippedSection && skippedContainer) {
    if (skippedListings.length > 0) {
      skippedSection.style.display = 'block';
      if (countSkippedEl) countSkippedEl.textContent = skippedListings.length;
      skippedContainer.innerHTML = skippedListings.map(createListingCardHTML).join('');
    } else {
      skippedSection.style.display = 'none';
      skippedContainer.innerHTML = '';
    }
  }

  // Render Shortlist tab (Green Star / Inspecting / Applied)
  const shortlisted = all.filter(item => {
    const st = statuses[item.id];
    return st === 'shortlist' || st === 'inspecting' || st === 'applied';
  });

  document.getElementById('count-strict').textContent = activeListings.length;
  document.getElementById('count-shortlist').textContent = shortlisted.length;

  if (shortlisted.length === 0) {
    shortlistContainer.innerHTML = `
      <div class="panel-card" style="grid-column: 1 / -1; text-align: center; padding: 2.5rem;">
        <h3>No properties shortlisted yet</h3>
        <p class="helper-text" style="margin-top: 0.4rem;">Click the star button once on any card (turns <strong>Green ★</strong>) or use the status dropdown to shortlist properties.</p>
      </div>
    `;
  } else {
    shortlistContainer.innerHTML = shortlisted.map(createListingCardHTML).join('');
  }

  // Bind 3-state Star button listeners
  document.querySelectorAll('.star-btn').forEach(btnEl => {
    btnEl.addEventListener('click', e => {
      e.preventDefault();
      e.stopPropagation();
      const id = btnEl.getAttribute('data-star-id');
      cycleStarStatus(id);
    });
  });

  // Bind status dropdown listeners
  document.querySelectorAll('.status-select').forEach(selectEl => {
    selectEl.addEventListener('change', e => {
      const id = e.target.getAttribute('data-listing-id');
      setSavedStatus(id, e.target.value);
    });
  });
}

function renderNormalListings() {
  const container = document.getElementById('normal-listings-container');
  if (!container) return;
  const skippedSection = document.getElementById('normal-skipped-section');
  const skippedContainer = document.getElementById('normal-skipped-container');
  const countSkippedEl = document.getElementById('count-normal-skipped');
  const countNormalEl = document.getElementById('count-normal');
  const statuses = getSavedStatuses();
  const all = getAllMergedListings();

  const matchingNormal = all.filter(item => {
    // Whole properties only
    if (item.is_sharehouse) return false;
    if (isStudentOnlyListing(item)) return false;

    // Price cap (default <= $600/wk)
    const rent = item.weekly_rent;
    if (!rent || rent > filterStateNormal.maxRent || rent < 200) return false;

    // Option to exclude lease transfers
    if (filterStateNormal.excludeLeaseTransfers && item.is_lease_transfer) return false;

    // New only
    if (filterStateNormal.newOnly && !isRecentNewListing(item)) return false;

    // Suburb filter
    if (filterStateNormal.suburb && filterStateNormal.suburb !== 'all') {
      const sub = (item.suburb || '').toLowerCase();
      const addr = (item.address || '').toLowerCase();
      const q = filterStateNormal.suburb.toLowerCase();
      if (!sub.includes(q) && !addr.includes(q)) return false;
    }

    // BHK filter
    if (filterStateNormal.bedrooms === '1' && item.bedrooms !== 1) return false;
    if (filterStateNormal.bedrooms === '2' && item.bedrooms !== 2) return false;
    if (filterStateNormal.bedrooms === '3' && item.bedrooms < 3) return false;

    // Furnished filter
    if (filterStateNormal.furnished === 'unfurnished' && item.is_furnished) return false;
    if (filterStateNormal.furnished === 'furnished' && !item.is_furnished) return false;

    // Search query
    if (filterStateNormal.search) {
      const q = filterStateNormal.search.toLowerCase();
      const hay = `${item.title} ${item.suburb} ${item.address} ${item.commute_line} ${item.station_distance_display || ''} ${item.description}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }

    return true;
  });

  const activeNormal = [];
  const skippedNormal = [];
  for (const item of matchingNormal) {
    const st = statuses[item.id] || 'none';
    if (st === 'skipped' || st === 'hidden') {
      skippedNormal.push(item);
    } else {
      activeNormal.push(item);
    }
  }

  // Sort: shortlisted first, then lowest rent first
  activeNormal.sort((a, b) => {
    const stA = statuses[a.id] === 'shortlist' ? 1 : 0;
    const stB = statuses[b.id] === 'shortlist' ? 1 : 0;
    if (stA !== stB) return stB - stA;
    return (a.weekly_rent || 9999) - (b.weekly_rent || 9999);
  });

  if (countNormalEl) countNormalEl.textContent = activeNormal.length;

  if (activeNormal.length === 0) {
    container.innerHTML = `
      <div class="panel-card" style="grid-column: 1 / -1; text-align: center; padding: 2.5rem;">
        <h3>No normal listings match the current filter combination</h3>
        <p class="helper-text" style="margin-top: 0.4rem;">Try adjusting the Max Rent filter or clearing a filter chip.</p>
      </div>
    `;
  } else {
    container.innerHTML = activeNormal.map(createListingCardHTML).join('');
  }

  // Render bottom skipped section
  if (skippedSection && skippedContainer) {
    if (skippedNormal.length > 0) {
      skippedSection.style.display = 'block';
      if (countSkippedEl) countSkippedEl.textContent = skippedNormal.length;
      skippedContainer.innerHTML = skippedNormal.map(createListingCardHTML).join('');
    } else {
      skippedSection.style.display = 'none';
      skippedContainer.innerHTML = '';
    }
  }

  // Re-bind star and status buttons in the newly rendered normal grid
  container.querySelectorAll('.star-btn').forEach(btnEl => {
    btnEl.addEventListener('click', e => {
      e.preventDefault();
      e.stopPropagation();
      cycleStarStatus(btnEl.getAttribute('data-star-id'));
    });
  });

  container.querySelectorAll('.status-select').forEach(selectEl => {
    selectEl.addEventListener('change', e => {
      setSavedStatus(e.target.getAttribute('data-listing-id'), e.target.value);
    });
  });

  if (skippedContainer) {
    skippedContainer.querySelectorAll('.star-btn').forEach(btnEl => {
      btnEl.addEventListener('click', e => {
        e.preventDefault();
        e.stopPropagation();
        cycleStarStatus(btnEl.getAttribute('data-star-id'));
      });
    });
  }
}

function parseWeeklyRentJS(rawText) {
  if (!rawText) return null;
  const clean = rawText.replace(/,/g, '').toLowerCase();

  // Dual quote or explicit weekly: $1050 pw / $4563 pcm -> 1050
  const mDual = clean.match(/\$\s*(\d{3,4})\s*(?:pw|p\/w|p\.w|\/wk|\/week|per\s+week)/);
  if (mDual) return parseInt(mDual[1], 10);

  // Explicit monthly: $2200 pcm, $2400 per month
  const mPcm = clean.match(/\$\s*(\d{3,5})\s*(?:pcm|p\.c\.m|per\s+month|\/month|\/mth|pm\b|\bmonthly\b)/);
  if (mPcm) return Math.round(parseInt(mPcm[1], 10) * 12 / 52);

  // Explicit weekly: $1450 per week, $2500 per week
  const mWk = clean.match(/\$\s*(\d{3,5})\s*(?:pw|p\/w|p\.w|\/wk|\/week|per\s+week|\bweekly\b)/);
  if (mWk) return parseInt(mWk[1], 10);

  // Standalone dollar
  const mStd = clean.match(/\$\s*(\d{3,5})/);
  if (mStd) {
    const val = parseInt(mStd[1], 10);
    if (/\b(?:pcm|p\.c\.m|per\s+month|\/month|\/mth)\b/.test(clean)) {
      return Math.round(val * 12 / 52);
    }
    if (val >= 1900 && !/\b(?:per\s+week|pw|p\/w|\/wk|\/week)\b/.test(clean) && val <= 4000) {
      return Math.round(val * 12 / 52);
    }
    return val;
  }
  return null;
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

  // 2. Price detection (accurate Australian rental parsing)
  const weeklyRent = parseWeeklyRentJS(rawText);
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

  // 5. Move-in date detection (Dec 5, 2026 – Jan 15, 2027)
  const mDec = lower.match(/\b(?:(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?dec(?:ember)?|dec(?:ember)?\s+(\d{1,2}))\b/);
  const mJan = lower.match(/\b(?:(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?jan(?:uary)?|jan(?:uary)?\s+(\d{1,2}))\b/);
  let availDisplay = 'Dec 2026 (Flexible)';
  let isWindow = true;
  if (mDec) {
    const day = parseInt(mDec[1] || mDec[2], 10);
    availDisplay = `Dec ${day}, 2026`;
    isWindow = day >= 5 && day <= 31;
  } else if (mJan) {
    const day = parseInt(mJan[1] || mJan[2], 10);
    availDisplay = `Jan ${day}, 2027`;
    isWindow = day <= 15;
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
  if (isWindow) score += 10;

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
  const ltCount = all.filter(i => i.is_lease_transfer).length;
  const normalUnder600 = all.filter(i => !i.is_sharehouse && (i.weekly_rent || 9999) <= 600 && (i.weekly_rent || 0) >= 200).length;
  const twoBhkUnder600 = all.filter(i => !i.is_sharehouse && i.bedrooms === 2 && (i.weekly_rent || 9999) <= 600).length;

  document.getElementById('stat-strict-matches').textContent = `${strictCount} Strict Matches`;
  document.getElementById('stat-sub-summary').textContent =
    `${normalUnder600} Whole Properties ≤$600 • ${twoBhkUnder600} are 2BHK • ${ltCount} Lease Transfers`;

  if (appData.last_updated) {
    const dt = new Date(appData.last_updated);
    document.getElementById('last-updated-pill').textContent =
      `Last Scraped: ${dt.toLocaleDateString('en-AU', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}`;
  }

  renderListings();
  renderNormalListings();
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

  // Main Listings Filters
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

  const chipNew = document.getElementById('chip-new-only');
  if (chipNew) {
    chipNew.addEventListener('click', () => {
      filterState.newOnly = !filterState.newOnly;
      chipNew.classList.toggle('active', filterState.newOnly);
      renderListings();
    });
  }

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

  // Normal Listings (Below $600) Filters
  const searchNorm = document.getElementById('search-input-normal');
  if (searchNorm) {
    searchNorm.addEventListener('input', e => {
      filterStateNormal.search = e.target.value.trim();
      renderNormalListings();
    });
  }

  const suburbNorm = document.getElementById('suburb-filter-normal');
  if (suburbNorm) {
    suburbNorm.addEventListener('change', e => {
      filterStateNormal.suburb = e.target.value;
      renderNormalListings();
    });
  }

  const bedNorm = document.getElementById('bedroom-filter-normal');
  if (bedNorm) {
    bedNorm.addEventListener('change', e => {
      filterStateNormal.bedrooms = e.target.value;
      renderNormalListings();
    });
  }

  const furnNorm = document.getElementById('furn-filter-normal');
  if (furnNorm) {
    furnNorm.addEventListener('change', e => {
      filterStateNormal.furnished = e.target.value;
      renderNormalListings();
    });
  }

  const priceCapNorm = document.getElementById('price-cap-normal');
  if (priceCapNorm) {
    priceCapNorm.addEventListener('change', e => {
      filterStateNormal.maxRent = parseInt(e.target.value, 10) || 600;
      renderNormalListings();
    });
  }

  const chipNewNorm = document.getElementById('chip-new-only-normal');
  if (chipNewNorm) {
    chipNewNorm.addEventListener('click', () => {
      filterStateNormal.newOnly = !filterStateNormal.newOnly;
      chipNewNorm.classList.toggle('active', filterStateNormal.newOnly);
      renderNormalListings();
    });
  }

  const chipExcludeLtNorm = document.getElementById('chip-exclude-lt-normal');
  if (chipExcludeLtNorm) {
    chipExcludeLtNorm.addEventListener('click', () => {
      filterStateNormal.excludeLeaseTransfers = !filterStateNormal.excludeLeaseTransfers;
      chipExcludeLtNorm.classList.toggle('active', filterStateNormal.excludeLeaseTransfers);
      renderNormalListings();
    });
  }

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
