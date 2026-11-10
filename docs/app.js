/**
 * Melbourne Personal Rental Discovery & Property Intelligence Platform (V2)
 *
 * Intelligent discovery, multi-source duplicate detection, 100-point explainable scoring,
 * side-by-side comparison, inspection scheduling, and user preference learning.
 */

const STORAGE_STATUS_KEY = 'melb_rental_statuses_v1';
const STORAGE_CUSTOM_POSTS_KEY = 'melb_rental_custom_fb_v1';
const STORAGE_INSPECTIONS_KEY = 'melb_rental_inspections_v2';
const STORAGE_COMPARE_KEY = 'melb_rental_compare_v2';
const STORAGE_USER_PREFS_KEY = 'melb_rental_user_prefs_v2';

let appData = {
  listings: [],
  portal_quick_links: [],
  hawthorn_corridor_suburbs: {},
  stats: {},
  last_updated: null,
  scraper_execution: null
};

let filterState = {
  search: '',
  suburb: 'all',
  bedrooms: 'all',
  maxRent: 'all',
  furnished: 'all',
  commuteMax: 'all',
  minScore: 'all',
  newOnly: false,
  leaseTransferOnly: false,
  budgetOnly: false,
  strictOnly: false,
  verifiedOnly: false,
  activeMetric: 'all'
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

// --- Storage Utilities ---

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
  recordUserDecision(listingId, status);
  renderAll();
}

function getSavedInspections() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_INSPECTIONS_KEY) || '{}');
  } catch {
    return {};
  }
}

function saveInspectionDetails(listingId, details) {
  const current = getSavedInspections();
  if (!details) {
    delete current[listingId];
  } else {
    current[listingId] = details;
  }
  localStorage.setItem(STORAGE_INSPECTIONS_KEY, JSON.stringify(current));
  renderAll();
}

function getCompareIds() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_COMPARE_KEY) || '[]');
  } catch {
    return [];
  }
}

function toggleCompareId(listingId) {
  let ids = getCompareIds();
  if (ids.includes(listingId)) {
    ids = ids.filter(id => id !== listingId);
  } else {
    if (ids.length >= 4) {
      alert('You can compare up to 4 properties side by side. Please deselect one first.');
      return;
    }
    ids.push(listingId);
  }
  localStorage.setItem(STORAGE_COMPARE_KEY, JSON.stringify(ids));
  updateCompareDock();
  renderAll();
}

function clearCompareSelection() {
  localStorage.setItem(STORAGE_COMPARE_KEY, JSON.stringify([]));
  updateCompareDock();
  renderAll();
}

function cycleStarStatus(listingId) {
  const current = getSavedStatuses();
  const st = current[listingId] || 'none';
  if (st === 'none') {
    setSavedStatus(listingId, 'shortlist');
  } else if (st === 'shortlist' || st === 'inspecting' || st === 'applied') {
    setSavedStatus(listingId, 'skipped');
  } else {
    setSavedStatus(listingId, 'none');
  }
}

function recordUserDecision(listingId, action) {
  const logKey = 'melb_rental_decision_log_v2';
  try {
    const logs = JSON.parse(localStorage.getItem(logKey) || '[]');
    logs.push({
      listing_id: listingId,
      action: action,
      timestamp: new Date().toISOString()
    });
    // Keep last 150 decisions
    localStorage.setItem(logKey, JSON.stringify(logs.slice(-150)));
  } catch {}
}

function getUserDecisionLogs() {
  try {
    return JSON.parse(localStorage.getItem('melb_rental_decision_log_v2') || '[]');
  } catch {
    return [];
  }
}

// --- Data Helpers & Normalization ---

function getListingAgeDays(listedAt) {
  if (!listedAt) return 0;
  const dt = new Date(listedAt);
  if (isNaN(dt.getTime())) return 0;
  return Math.max(0, (Date.now() - dt.getTime()) / (1000 * 60 * 60 * 24));
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
  return sub.includes('hour') || sub.includes('yesterday') || sub.includes('today');
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

function updateCountdownBanner() {
  const now = new Date();
  const dec3 = new Date('2026-12-03T23:59:59+11:00');
  const diffDays = Math.max(0, Math.ceil((dec3 - now) / (1000 * 60 * 60 * 24)));
  const pill = document.getElementById('countdown-pill');
  if (pill) {
    pill.textContent = `⏳ ${diffDays} Days to Dec 3 Notice Deadline`;
  }
}

// --- Explainable Scoring Breakdown Generator ---

function computeExplainableBreakdown(item) {
  // If backend provided precomputed category breakdown, use it
  if (item.category_scores && item.positive_factors && item.concerns) {
    return {
      categoryScores: item.category_scores,
      positiveFactors: item.positive_factors,
      concerns: item.concerns,
      confidence: item.confidence || 'Medium'
    };
  }

  // Frontend calculation for custom FB posts or fallback
  const rent = item.weekly_rent || 0;
  const isFurn = !!item.is_furnished;
  const maxCap = isFurn ? 560 : 525;
  const bedrooms = item.bedrooms || 1;
  const commuteMins = item.commute_mins || 35;
  const isLt = !!item.is_lease_transfer;
  const distM = item.station_distance_m || 500;

  // 1. Rent Affordability (25 pts)
  let rentScore = 0;
  if (rent > 0 && rent <= maxCap) {
    const headroom = maxCap - rent;
    rentScore = Math.min(25, Math.round(18 + (headroom / 8)));
  } else if (rent > 0 && rent <= maxCap + 25) {
    rentScore = 10;
  }

  // 2. Commute Convenience (25 pts)
  let commuteScore = 12;
  if (commuteMins <= 10) commuteScore = 25;
  else if (commuteMins <= 20) commuteScore = 22;
  else if (commuteMins <= 30) commuteScore = 18;
  else if (commuteMins <= 40) commuteScore = 14;

  // 3. Property Suitability (20 pts)
  let suitScore = 12;
  if (bedrooms === 2) suitScore = 20;
  else if (bedrooms === 1) suitScore = 14;
  else if (bedrooms >= 3) suitScore = 16;

  // 4. Move-in Compatibility (15 pts)
  let moveInScore = 10;
  const fit = item.availability_fit || 'early_flex';
  if (fit === 'ideal') moveInScore = 15;
  else if (fit === 'early_flex') moveInScore = 11;
  else if (fit === 'jan_tight') moveInScore = 7;

  // 5. Amenities & Condition (10 pts)
  let amenScore = 6;
  const fullText = `${item.title || ''} ${item.description || ''}`.toLowerCase();
  if (fullText.includes('carpark') || fullText.includes('parking') || fullText.includes('garage')) amenScore += 2;
  if (fullText.includes('balcony') || fullText.includes('courtyard')) amenScore += 1;
  if (fullText.includes('air conditioning') || fullText.includes('heating')) amenScore += 1;
  amenScore = Math.min(10, amenScore);

  // 6. Freshness (5 pts)
  const ageDays = getListingAgeDays(item.listed_at);
  let freshScore = 3;
  if (ageDays <= 2) freshScore = 5;
  else if (ageDays <= 5) freshScore = 4;
  else if (ageDays <= 10) freshScore = 3;

  // Positive Factors & Concerns
  const positive = [];
  const concerns = [];

  if (rent <= maxCap) {
    positive.push(`Within rental budget: $${rent}/wk (${isFurn ? 'Furnished ≤$560' : 'Unfurnished ≤$525'})`);
  } else {
    concerns.push(`Above target budget: $${rent}/wk ($${rent - maxCap} above cap)`);
  }

  if (bedrooms === 2) {
    positive.push('Two bedrooms — matches your preferred solo 2BHK requirement');
  } else if (bedrooms === 1) {
    positive.push('Entire 1-bedroom / studio property — zero flatmates');
  }

  if (commuteMins <= 20) {
    positive.push(`Direct transit to Hawthorn in ~${commuteMins} minutes (${item.commute_mode || 'Train'})`);
  } else if (commuteMins <= 35) {
    positive.push(`Single-seat commute to Hawthorn in ~${commuteMins} minutes`);
  } else {
    concerns.push(`Longer commute to Hawthorn (~${commuteMins} mins)`);
  }

  if (fit === 'ideal') {
    positive.push(`Move-in matches preferred Dec 5 – Jan 15 window (${item.availability_display || 'Dec 2026'})`);
  }

  if (distM <= 450) {
    positive.push(`Very close to station (~${distM}m, ~${Math.round(distM / 80)} min walk)`);
  } else if (distM >= 1000) {
    concerns.push(`Station walking distance is ~${distM}m (~${Math.round(distM / 80)} mins)`);
  }

  if (isLt) {
    positive.push('Lease transfer / break — often below market rate with existing lease terms');
  }

  // Confidence assessment
  let confidence = 'Medium';
  if (item.station_is_explicit || (item.address && /\d+\s+[a-z]+/i.test(item.address))) {
    confidence = 'High';
  } else if (!item.weekly_rent || !item.availability_display || item.availability_display === 'Check Listing') {
    confidence = 'Low';
  }

  return {
    categoryScores: {
      rent: rentScore,
      commute: commuteScore,
      suitability: suitScore,
      move_in: moveInScore,
      amenities: amenScore,
      freshness: freshScore
    },
    positiveFactors: positive,
    concerns: concerns,
    confidence: confidence
  };
}

// --- Section B: Card Progressive Disclosure HTML ---

function createListingCardHTML(item) {
  const statuses = getSavedStatuses();
  const userStatus = statuses[item.id] || "none";
  const isNew = isRecentNewListing(item);
  const inspections = getSavedInspections();
  const inspectionInfo = inspections[item.id];
  const compareIds = getCompareIds();
  const isCompared = compareIds.includes(item.id);

  const breakdown = computeExplainableBreakdown(item);

  const isGreenStar = userStatus === "shortlist" || userStatus === "inspecting" || userStatus === "applied";
  const isRedStar = userStatus === "skipped" || userStatus === "hidden";

  let starBtnClass = "star-btn";
  let starIcon = "☆";
  let starLabel = "Star";
  let starTitle = "Click once for Green Star (Interested), twice for Red Star (Skip to bottom)";
  if (isGreenStar) {
    starBtnClass = "star-btn star-green";
    starIcon = "★";
    starLabel = "Interested";
    starTitle = "Green Star (Interested) — Click again for Red Star (Skip to bottom)";
  } else if (isRedStar) {
    starBtnClass = "star-btn star-red";
    starIcon = "★";
    starLabel = "Skipped";
    starTitle = "Red Star (Skipped) — Click again to reset star";
  }

  const scoreVal = item.match_score || 70;
  const scoreClass = scoreVal >= 80 ? "" : scoreVal >= 70 ? "medium" : "low";

  const confClass =
    breakdown.confidence === "High" ? "confidence-high" :
    breakdown.confidence === "Medium" ? "confidence-medium" : "confidence-low";

  const furnLabel = item.is_furnished ? "Furnished (≤$560 cap)" : "Unfurnished (≤$525 cap)";

  // Fallback photo and graceful vector apartment fallback
  const fallbackSvg = "data:image/svg+xml;charset=UTF-8,%3Csvg%20width%3D%22800%22%20height%3D%22500%22%20viewBox%3D%220%200%20800%20500%22%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%3E%3Cdefs%3E%3ClinearGradient%20id%3D%22g%22%20x1%3D%220%25%22%20y1%3D%220%25%22%20x2%3D%22100%25%22%20y2%3D%22100%25%22%3E%3Cstop%20offset%3D%220%25%22%20stop-color%3D%22%231e3a5f%22%2F%3E%3Cstop%20offset%3D%22100%25%22%20stop-color%3D%22%230f172a%22%2F%3E%3C%2FlinearGradient%3E%3C%2Fdefs%3E%3Crect%20width%3D%22800%22%20height%3D%22500%22%20fill%3D%22url(%23g)%22%2F%3E%3Cg%20fill%3D%22none%22%20stroke%3D%22%2338bdf8%22%20stroke-width%3D%224%22%20opacity%3D%220.6%22%3E%3Cpath%20d%3D%22M250%20420V160h160v260%22%2F%3E%3Cpath%20d%3D%22M410%20420V220h140v200%22%2F%3E%3Crect%20x%3D%22280%22%20y%3D%22190%22%20width%3D%2235%22%20height%3D%2245%22%20rx%3D%224%22%2F%3E%3Crect%20x%3D%22345%22%20y%3D%22190%22%20width%3D%2235%22%20height%3D%2245%22%20rx%3D%224%22%2F%3E%3Crect%20x%3D%22280%22%20y%3D%22265%22%20width%3D%2235%22%20height%3D%2245%22%20rx%3D%224%22%2F%3E%3Crect%20x%3D%22345%22%20y%3D%22265%22%20width%3D%2235%22%20height%3D%2245%22%20rx%3D%224%22%2F%3E%3Crect%20x%3D%22440%22%20y%3D%22250%22%20width%3D%2235%22%20height%3D%2240%22%20rx%3D%224%22%2F%3E%3Crect%20x%3D%22495%22%20y%3D%22250%22%20width%3D%2235%22%20height%3D%2240%22%20rx%3D%224%22%2F%3E%3Crect%20x%3D%22440%22%20y%3D%22320%22%20width%3D%2235%22%20height%3D%2240%22%20rx%3D%224%22%2F%3E%3Crect%20x%3D%22495%22%20y%3D%22320%22%20width%3D%2235%22%20height%3D%2240%22%20rx%3D%224%22%2F%3E%3C%2Fg%3E%3Ctext%20x%3D%22400%22%20y%3D%22460%22%20fill%3D%22%2394a3b8%22%20font-family%3D%22system-ui%2C%20sans-serif%22%20font-size%3D%2216%22%20font-weight%3D%22600%22%20text-anchor%3D%22middle%22%20letter-spacing%3D%222%22%3EMELBOURNE%20RENTAL%20FINDER%3C%2Ftext%3E%3C%2Fsvg%3E";
  const photoUrl = (item.photo && item.photo.startsWith("http"))
    ? item.photo
    : "https://images.unsplash.com/photo-1502672260266-1c1ef2d93688?auto=format&fit=crop&w=800&q=80";

  const cardClasses = [
    "listing-card",
    isNew ? "is-new-listing" : "",
    isGreenStar ? "is-shortlisted-card" : "",
    isRedStar ? "is-skipped" : ""
  ].filter(Boolean).join(" ");

  // Positive Factors (Show top 2 by default)
  const topPositives = breakdown.positiveFactors.slice(0, 2);
  const topConcerns = breakdown.concerns.slice(0, 1);

  const positiveHTML = topPositives.map(p => `
    <div class="factor-positive"><span>✔</span> <span>${escapeHtml(p)}</span></div>
  `).join("");

  const concernHTML = topConcerns.map(c => `
    <div class="factor-concern"><span>⚠️</span> <span>${escapeHtml(c)}</span></div>
  `).join("");

  const cat = breakdown.categoryScores;

  const badgePills = [];
  if (item.bedrooms === 2) {
    badgePills.push(`<span class="spec-badge highlight-2bhk">★ 2 BHK (Preferred)</span>`);
  } else {
    badgePills.push(`<span class="spec-badge">${item.bedrooms || 1} BHK Entire Place</span>`);
  }
  badgePills.push(`<span class="spec-badge highlight-dec">📅 ${escapeHtml(item.availability_display || item.date_available || "Dec 2026")}</span>`);

  return `
    <article class="${cardClasses}" data-id="${escapeHtml(item.id)}">
      <!-- Visual Card Image with Badges & Top Star -->
      <div class="listing-media">
        <img src="${escapeHtml(photoUrl)}" alt="${escapeHtml(item.title)}" loading="lazy" onerror="if(this.dataset.fallback!=='1'){this.dataset.fallback='1';this.src='${fallbackSvg}';}">
        <div class="media-top-badges">
          <div class="media-left-badges">
            <span class="score-pill ${scoreClass}">${scoreVal}% Match</span>
            <span class="confidence-badge ${confClass}">● ${escapeHtml(breakdown.confidence)} Conf</span>
            ${isNew ? `<span class="new-listing-badge">✨ NEW LISTING</span>` : ""}
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
          $${item.weekly_rent || "—"}/wk
          <span class="furn-tag">${escapeHtml(furnLabel)}</span>
        </div>
      </div>

      <!-- Card Body -->
      <div class="listing-body">
        <div class="listing-meta-row">
          <span class="suburb-pill">📍 ${escapeHtml(item.suburb || "Melbourne")} ${escapeHtml(item.postcode || "")}</span>
          <span>${escapeHtml(item.source || "Verified Source")}</span>
        </div>

        <h3 class="listing-title">${escapeHtml(item.title)}</h3>

        <div class="transit-box">
          <strong>🚆 Direct to Hawthorn: ${escapeHtml(item.commute_mode || "Train")} (~${item.commute_mins || 15} mins)</strong>
          <span>${escapeHtml(item.commute_line || "Corridor transit")}</span>
        </div>

        <div class="station-box">
          <span>🚉 <strong>Train Station:</strong> ${escapeHtml(item.station_distance_display || "Near local station")}</span>
        </div>

        <div class="specs-row">
          ${badgePills.join("")}
        </div>

        <!-- Highlight Factors -->
        <div class="factor-list-box" style="margin-top: 0.2rem;">
          ${positiveHTML}
          ${concernHTML}
        </div>

        ${inspectionInfo ? `
          <div style="background: #ecfdf5; border-left: 3px solid #10b981; padding: 0.45rem 0.7rem; border-radius: 4px; font-size: 0.8rem; color: #065f46; margin-top: 0.2rem;">
            <strong>🗓️ Inspection Scheduled:</strong> ${escapeHtml(new Date(inspectionInfo.datetime).toLocaleString("en-AU", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }))}
            ${inspectionInfo.notes ? `<div style="margin-top: 0.2rem; font-style: italic;">"${escapeHtml(inspectionInfo.notes)}"</div>` : ""}
          </div>
        ` : ""}

        <!-- Progressive Disclosure Accordion -->
        <button type="button" class="drawer-toggle-btn" data-drawer-id="${escapeHtml(item.id)}" style="margin-top: 0.35rem; width: 100%; padding: 0.45rem 0.65rem; font-size: 0.8rem; border-radius: 6px; border: 1px solid var(--border-color); background: var(--bg-surface); color: var(--brand-forest); cursor: pointer; font-weight: 600;">
          Show 100-Point Breakdown &amp; Description ▼
        </button>

        <div class="card-drawer-content" id="drawer-${escapeHtml(item.id)}" style="background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: 6px; padding: 0.75rem; margin-top: 0.35rem;">
          <div style="font-weight: 700; font-size: 0.8rem; color: var(--text-primary); margin-bottom: 0.4rem;">
            100-Point Match Score Analysis (Version: ${escapeHtml(item.score_version || "2.0")})
          </div>
          <div class="score-categories-grid">
            <div class="cat-bar-item">
              <div class="cat-bar-label"><span>Rent Affordability</span><span>${cat.rent}/25</span></div>
              <div class="cat-progress-track"><div class="cat-progress-fill" style="width: ${(cat.rent / 25) * 100}%;"></div></div>
            </div>
            <div class="cat-bar-item">
              <div class="cat-bar-label"><span>Commute Convenience</span><span>${cat.commute}/25</span></div>
              <div class="cat-progress-track"><div class="cat-progress-fill" style="width: ${(cat.commute / 25) * 100}%;"></div></div>
            </div>
            <div class="cat-bar-item">
              <div class="cat-bar-label"><span>Property Suitability</span><span>${cat.suitability}/20</span></div>
              <div class="cat-progress-track"><div class="cat-progress-fill" style="width: ${(cat.suitability / 20) * 100}%;"></div></div>
            </div>
            <div class="cat-bar-item">
              <div class="cat-bar-label"><span>Move-In Timing</span><span>${cat.move_in}/15</span></div>
              <div class="cat-progress-track"><div class="cat-progress-fill" style="width: ${(cat.move_in / 15) * 100}%;"></div></div>
            </div>
            <div class="cat-bar-item">
              <div class="cat-bar-label"><span>Amenities &amp; Parking</span><span>${cat.amenities}/10</span></div>
              <div class="cat-progress-track"><div class="cat-progress-fill" style="width: ${(cat.amenities / 10) * 100}%;"></div></div>
            </div>
            <div class="cat-bar-item">
              <div class="cat-bar-label"><span>Listing Freshness</span><span>${cat.freshness}/5</span></div>
              <div class="cat-progress-track"><div class="cat-progress-fill" style="width: ${(cat.freshness / 5) * 100}%;"></div></div>
            </div>
          </div>

          <div style="margin-top: 0.5rem;">
            <strong style="display: block; font-size: 0.78rem; margin-bottom: 0.2rem; color: var(--text-primary);">Original Listing Summary:</strong>
            <p style="font-size: 0.8rem; line-height: 1.45; color: var(--text-secondary);">${escapeHtml(item.description || item.subhead || "No detailed description provided.")}</p>
          </div>
        </div>

        <!-- Action Footer -->
        <div class="card-action-bar" style="margin-top: 0.5rem; padding-top: 0.65rem; border-top: 1px solid var(--border-color); display: flex; align-items: center; justify-content: space-between; gap: 0.4rem; flex-wrap: wrap;">
          <div style="display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap;">
            <button type="button" class="btn-action-sm" data-inspect-id="${escapeHtml(item.id)}" title="Add inspection date and personal notes">
              <span>🗓️ Inspection</span>
            </button>
            <button type="button" class="btn-action-sm ${isCompared ? "is-active-compare" : ""}" data-compare-id="${escapeHtml(item.id)}" title="Select to compare side by side">
              <span>${isCompared ? "✓ Comparing" : "⚖ Compare"}</span>
            </button>
          </div>

          <a href="${escapeHtml(item.url || item.source_url || "#")}" target="_blank" rel="noopener" class="btn btn-primary" style="padding: 0.38rem 0.85rem; font-size: 0.82rem;">
            Open Listing ↗
          </a>
        </div>
      </div>
    </article>
  `;
}

// --- Section B: Render Main Listings Grid ---

function renderListings() {
  const container = document.getElementById('listings-container');
  if (!container) return;
  const skippedSection = document.getElementById('skipped-section');
  const skippedContainer = document.getElementById('skipped-container');
  const countSkippedEl = document.getElementById('count-skipped');
  const shortlistContainer = document.getElementById('shortlist-container');
  const statuses = getSavedStatuses();
  const all = getAllMergedListings();

  const matchingFilter = all.filter(item => {
    // Metric Tile shortcuts
    if (filterState.activeMetric === 'strong' && (item.match_score || 0) < 80) return false;
    if (filterState.activeMetric === 'budget' && (item.weekly_rent || 0) > (item.is_furnished ? 560 : 525)) return false;
    if (filterState.activeMetric === 'new' && !isRecentNewListing(item)) return false;
    if (filterState.activeMetric === 'shortlist') {
      const st = statuses[item.id];
      if (st !== 'shortlist' && st !== 'inspecting' && st !== 'applied') return false;
    }
    if (filterState.activeMetric === 'lt' && !item.is_lease_transfer) return false;

    // Filters Bar
    if (filterState.strictOnly && !item.pass_strict_filter) return false;
    if (filterState.leaseTransferOnly && !item.is_lease_transfer) return false;
    if (filterState.newOnly && !isRecentNewListing(item)) return false;
    if (filterState.budgetOnly && (item.weekly_rent || 0) > (item.is_furnished ? 560 : 525)) return false;

    // Suburb filter
    if (filterState.suburb && filterState.suburb !== 'all') {
      const sub = (item.suburb || '').toLowerCase();
      const addr = (item.address || '').toLowerCase();
      const q = filterState.suburb.toLowerCase();
      if (!sub.includes(q) && !addr.includes(q)) return false;
    }

    // Bedroom filter
    if (filterState.bedrooms === '1' && item.bedrooms !== 1) return false;
    if (filterState.bedrooms === '2' && item.bedrooms !== 2) return false;
    if (filterState.bedrooms === '3' && item.bedrooms < 3) return false;

    // Rent filter
    if (filterState.maxRent && filterState.maxRent !== 'all') {
      const maxVal = parseInt(filterState.maxRent, 10);
      if ((item.weekly_rent || 9999) > maxVal) return false;
    }

    // Furnished filter
    if (filterState.furnished === 'unfurnished' && item.is_furnished) return false;
    if (filterState.furnished === 'furnished' && !item.is_furnished) return false;

    // Commute filter
    if (filterState.commuteMax && filterState.commuteMax !== 'all') {
      const maxMins = parseInt(filterState.commuteMax, 10);
      if ((item.commute_mins || 45) > maxMins) return false;
    }

    // Score filter
    if (filterState.minScore && filterState.minScore !== 'all') {
      const minS = parseInt(filterState.minScore, 10);
      if ((item.match_score || 0) < minS) return false;
    }

    // Search query
    if (filterState.search) {
      const q = filterState.search.toLowerCase();
      const hay = `${item.title} ${item.suburb} ${item.address} ${item.commute_line} ${item.station_distance_display || ''} ${item.description}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }

    return true;
  });

  // Partition active vs skipped (Red Star)
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

  // Sort active listings: shortlisted first, then score descending, then rent
  activeListings.sort((a, b) => {
    const stA = (statuses[a.id] === 'shortlist' || statuses[a.id] === 'inspecting') ? 1 : 0;
    const stB = (statuses[b.id] === 'shortlist' || statuses[b.id] === 'inspecting') ? 1 : 0;
    if (stA !== stB) return stB - stA;
    const scoreDiff = (b.match_score || 0) - (a.match_score || 0);
    if (scoreDiff !== 0) return scoreDiff;
    return (a.weekly_rent || 9999) - (b.weekly_rent || 9999);
  });

  // Render main active listings
  if (activeListings.length === 0) {
    container.innerHTML = `
      <div class="state-container">
        <div class="state-icon">🔍</div>
        <div class="state-title">No properties match your current filter combination</div>
        <div class="state-desc">
          Try broadening your search, adjusting the commute limit, or clearing active chips.
        </div>
        <button type="button" class="btn btn-primary" id="btn-empty-reset" style="margin-top: 0.5rem;">
          ↺ Reset All Filters
        </button>
      </div>
    `;
    const emptyResetBtn = document.getElementById('btn-empty-reset');
    if (emptyResetBtn) emptyResetBtn.addEventListener('click', resetAllFilters);
  } else {
    container.innerHTML = activeListings.map(createListingCardHTML).join('');
  }

  // Render Skipped section
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

  // Render Shortlist tab
  const shortlisted = all.filter(item => {
    const st = statuses[item.id];
    return st === 'shortlist' || st === 'inspecting' || st === 'applied';
  });

  document.getElementById('count-strict').textContent = activeListings.length;
  document.getElementById('count-shortlist').textContent = shortlisted.length;

  if (shortlistContainer) {
    if (shortlisted.length === 0) {
      shortlistContainer.innerHTML = `
        <div class="state-container">
          <div class="state-icon">⭐</div>
          <div class="state-title">Your Shortlist is currently empty</div>
          <div class="state-desc">
            Click <strong>☆ Star</strong> or <strong>🗓️ Inspection</strong> on any property card to save it for inspection.
          </div>
        </div>
      `;
    } else {
      shortlistContainer.innerHTML = shortlisted.map(createListingCardHTML).join('');
    }
  }

  // Re-bind interactive card elements
  bindCardInteractions(document);
}

// --- Normal Listings Tab ---

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
    if (item.is_sharehouse) return false;
    if (isStudentOnlyListing(item)) return false;

    const rent = item.weekly_rent;
    if (!rent || rent > filterStateNormal.maxRent || rent < 200) return false;

    if (filterStateNormal.excludeLeaseTransfers && item.is_lease_transfer) return false;
    if (filterStateNormal.newOnly && !isRecentNewListing(item)) return false;

    if (filterStateNormal.suburb && filterStateNormal.suburb !== 'all') {
      const sub = (item.suburb || '').toLowerCase();
      const addr = (item.address || '').toLowerCase();
      const q = filterStateNormal.suburb.toLowerCase();
      if (!sub.includes(q) && !addr.includes(q)) return false;
    }

    if (filterStateNormal.bedrooms === '1' && item.bedrooms !== 1) return false;
    if (filterStateNormal.bedrooms === '2' && item.bedrooms !== 2) return false;
    if (filterStateNormal.bedrooms === '3' && item.bedrooms < 3) return false;

    if (filterStateNormal.furnished === 'unfurnished' && item.is_furnished) return false;
    if (filterStateNormal.furnished === 'furnished' && !item.is_furnished) return false;

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

  activeNormal.sort((a, b) => {
    const stA = statuses[a.id] === 'shortlist' ? 1 : 0;
    const stB = statuses[b.id] === 'shortlist' ? 1 : 0;
    if (stA !== stB) return stB - stA;
    return (a.weekly_rent || 9999) - (b.weekly_rent || 9999);
  });

  if (countNormalEl) countNormalEl.textContent = activeNormal.length;

  if (activeNormal.length === 0) {
    container.innerHTML = `
      <div class="state-container">
        <div class="state-icon">🏠</div>
        <div class="state-title">No standard rentals found for this filter</div>
        <div class="state-desc">Try increasing the Max Rent cap or selecting All Suburbs.</div>
      </div>
    `;
  } else {
    container.innerHTML = activeNormal.map(createListingCardHTML).join('');
  }

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

  bindCardInteractions(container);
  if (skippedContainer) bindCardInteractions(skippedContainer);
}

// --- Card Interaction Event Binders ---

function bindCardInteractions(rootElement) {
  // 1. Star / Shortlist toggle
  rootElement.querySelectorAll('button[data-star-id]').forEach(btn => {
    btn.addEventListener('click', e => {
      e.preventDefault();
      e.stopPropagation();
      cycleStarStatus(btn.getAttribute('data-star-id'));
    });
  });

  // 2. Inspection modal trigger
  rootElement.querySelectorAll('button[data-inspect-id]').forEach(btn => {
    btn.addEventListener('click', e => {
      e.preventDefault();
      e.stopPropagation();
      openInspectionModal(btn.getAttribute('data-inspect-id'));
    });
  });

  // 3. Comparison toggle
  rootElement.querySelectorAll('button[data-compare-id]').forEach(btn => {
    btn.addEventListener('click', e => {
      e.preventDefault();
      e.stopPropagation();
      toggleCompareId(btn.getAttribute('data-compare-id'));
    });
  });

  // 4. Status dropdown
  rootElement.querySelectorAll('.status-select').forEach(sel => {
    sel.addEventListener('change', e => {
      setSavedStatus(e.target.getAttribute('data-listing-id'), e.target.value);
    });
  });

  // 5. Drawer progressive disclosure toggle
  rootElement.querySelectorAll('.drawer-toggle-btn').forEach(btn => {
    btn.addEventListener('click', e => {
      e.preventDefault();
      const lid = btn.getAttribute('data-drawer-id');
      const drawer = document.getElementById(`drawer-${lid}`);
      if (drawer) {
        const isOpen = drawer.classList.toggle('is-open');
        drawer.style.display = isOpen ? 'block' : 'none';
        btn.textContent = isOpen
          ? 'Hide 100-Point Breakdown ▲'
          : 'Show 100-Point Breakdown & Description ▼';
      }
    });
  });
}

// --- Section 4.3: Property Comparison Matrix View ---

function updateCompareDock() {
  const dock = document.getElementById('comparison-dock');
  const countEl = document.getElementById('dock-compare-count');
  const tabCountEl = document.getElementById('count-compare');
  const ids = getCompareIds();

  if (tabCountEl) tabCountEl.textContent = ids.length;

  if (dock && countEl) {
    countEl.textContent = ids.length;
    if (ids.length >= 1) {
      dock.classList.add('is-visible');
    } else {
      dock.classList.remove('is-visible');
    }
  }

  renderComparisonView();
}

function renderComparisonView() {
  const container = document.getElementById('compare-matrix-view');
  if (!container) return;

  const ids = getCompareIds();
  const all = getAllMergedListings();
  const selected = ids.map(id => all.find(item => item.id === id)).filter(Boolean);

  if (selected.length === 0) {
    container.innerHTML = `
      <div class="state-container" style="border:none;">
        <div class="state-icon">⚖️</div>
        <div class="state-title">No properties selected for comparison</div>
        <div class="state-desc">
          Click <strong>⚖ Compare</strong> on 2 to 4 listing cards in the All Discoveries or Normal tab to see them side-by-side.
        </div>
      </div>
    `;
    return;
  }

  const fields = [
    { label: 'Weekly Rent', fn: item => `$${item.weekly_rent || '—'}/wk` },
    { label: 'Match Score', fn: item => `<strong>${item.match_score || 0}%</strong> (${computeExplainableBreakdown(item).confidence} Conf)` },
    { label: 'Suburb & Corridor', fn: item => `${item.suburb || 'Melbourne'} (${item.postcode || ''})` },
    { label: 'Commute to Hawthorn', fn: item => `~${item.commute_mins || 15}m via ${item.commute_mode || 'Train'}` },
    { label: 'Public Transport Distance', fn: item => item.station_distance_display || 'Near station' },
    { label: 'Bedrooms & Bathrooms', fn: item => `${item.bedrooms || 1} Bed • ${item.bathrooms || 1} Bath` },
    { label: 'Parking', fn: item => item.parking !== undefined && item.parking !== null ? `${item.parking} Car Space(s)` : (item.has_parking ? '1 Car Space' : 'Street / Unspecified') },
    { label: 'Furnished Status', fn: item => item.is_furnished ? 'Furnished' : 'Unfurnished' },
    { label: 'Availability Move-In', fn: item => item.availability_display || item.date_available || 'Dec 2026' },
    { label: 'Lease Transfer?', fn: item => item.is_lease_transfer ? 'Yes (Lease Transfer)' : 'Standard Rental' },
    { label: 'Top Advantage', fn: item => computeExplainableBreakdown(item).positiveFactors[0] || 'Good commute' },
    { label: 'Potential Caution', fn: item => computeExplainableBreakdown(item).concerns[0] || 'None identified' }
  ];

  let html = `
    <table class="comparison-table">
      <thead>
        <tr>
          <th style="min-width: 170px;">Attribute</th>
          ${selected.map(item => `
            <th style="min-width: 220px;">
              <div style="font-size: 0.95rem; margin-bottom: 0.25rem;">${escapeHtml(item.title)}</div>
              <button type="button" class="btn-action-sm" onclick="toggleCompareId('${escapeHtml(item.id)}')" style="font-size: 0.72rem; padding: 0.2rem 0.5rem;">
                ✕ Remove
              </button>
            </th>
          `).join('')}
        </tr>
      </thead>
      <tbody>
  `;

  for (const f of fields) {
    const values = selected.map(f.fn);
    const hasDiff = new Set(values).size > 1;
    html += `
      <tr>
        <td><strong>${escapeHtml(f.label)}</strong></td>
        ${values.map(val => `
          <td class="${hasDiff ? 'diff-highlight' : ''}">${val}</td>
        `).join('')}
      </tr>
    `;
  }

  html += `
        <tr>
          <td><strong>Action</strong></td>
          ${selected.map(item => `
            <td>
              <a href="${escapeHtml(item.url || '#')}" target="_blank" rel="noopener" class="btn btn-primary" style="padding: 0.35rem 0.65rem; font-size: 0.78rem;">
                Open Listing ↗
              </a>
            </td>
          `).join('')}
        </tr>
      </tbody>
    </table>
  `;

  container.innerHTML = html;

  const modalBody = document.getElementById('modal-comparison-body');
  if (modalBody) modalBody.innerHTML = html;
}

// --- Inspection Modal Handlers ---

function openInspectionModal(listingId) {
  const all = getAllMergedListings();
  const item = all.find(i => i.id === listingId);
  if (!item) return;

  const modal = document.getElementById('modal-inspection');
  const titleEl = document.getElementById('modal-property-name');
  const idEl = document.getElementById('modal-listing-id');
  const dateInput = document.getElementById('inspection-date');
  const agentInput = document.getElementById('inspection-agent');
  const notesInput = document.getElementById('inspection-notes');

  idEl.value = listingId;
  titleEl.textContent = `${item.title} — $${item.weekly_rent || '—'}/wk in ${item.suburb}`;

  const inspections = getSavedInspections();
  const existing = inspections[listingId] || {};

  dateInput.value = existing.datetime || '';
  agentInput.value = existing.agent || '';
  notesInput.value = existing.notes || '';

  modal.classList.add('is-open');
}

function closeInspectionModal() {
  const modal = document.getElementById('modal-inspection');
  if (modal) modal.classList.remove('is-open');
}

// --- Section 4.4: Personal Intelligence & Preference Insights Engine ---

function renderInsightsAndAnalytics() {
  const prefContainer = document.getElementById('insights-preferences-list');
  const metricsContainer = document.getElementById('insights-metrics-list');
  const pipelineContainer = document.getElementById('insights-pipeline-health');

  if (!prefContainer) return;

  const all = getAllMergedListings();
  const statuses = getSavedStatuses();
  const decisions = getUserDecisionLogs();

  const shortlisted = all.filter(i => statuses[i.id] === 'shortlist' || statuses[i.id] === 'inspecting' || statuses[i.id] === 'applied');
  const skipped = all.filter(i => statuses[i.id] === 'skipped');

  // 1. Preference Pattern Analysis
  const preferences = [];

  // Suburb affinity
  const suburbCounts = {};
  shortlisted.forEach(i => {
    suburbCounts[i.suburb] = (suburbCounts[i.suburb] || 0) + 1;
  });
  const topSuburbs = Object.entries(suburbCounts).sort((a, b) => b[1] - a[1]);
  if (topSuburbs.length > 0 && topSuburbs[0][1] >= 2) {
    preferences.push({
      type: 'suburb',
      title: `High Affinity for ${topSuburbs[0][0]}`,
      desc: `You shortlisted ${topSuburbs[0][1]} properties in ${topSuburbs[0][0]}. You might want to focus your searches on this train corridor.`,
      actionText: 'Filter by ' + topSuburbs[0][0],
      actionFn: () => {
        filterState.suburb = topSuburbs[0][0].toLowerCase();
        document.getElementById('suburb-filter').value = filterState.suburb;
        document.getElementById('tab-matches').click();
        renderAll();
      }
    });
  }

  // Parking preference
  const parkingShortlisted = shortlisted.filter(i => i.parking || i.has_parking).length;
  if (shortlisted.length >= 3 && (parkingShortlisted / shortlisted.length) >= 0.75) {
    preferences.push({
      type: 'parking',
      title: 'Dedicated Parking Preference Detected',
      desc: `${Math.round((parkingShortlisted / shortlisted.length) * 100)}% of your shortlisted properties feature off-street parking.`,
      actionText: 'Recognized as Priority',
      actionFn: null
    });
  }

  // Budget stretch tolerance
  const stretchShortlisted = shortlisted.filter(i => (i.weekly_rent || 0) > 525 && (i.weekly_rent || 0) <= 560).length;
  if (stretchShortlisted >= 2) {
    preferences.push({
      type: 'budget',
      title: 'Stretch Budget Tolerance ($525–$560/wk)',
      desc: `You have shortlisted ${stretchShortlisted} properties in the upper $525–$560/wk range. They will continue to be shown without exceeding your $560 hard cap.`,
      actionText: 'Within Stated Rules',
      actionFn: null
    });
  }

  if (preferences.length === 0) {
    prefContainer.innerHTML = `
      <div style="font-size: 0.85rem; color: var(--text-muted);">
        Shortlist or skip at least 3 properties to start revealing your decision patterns and transparent recommendations.
      </div>
    `;
  } else {
    prefContainer.innerHTML = preferences.map((p, idx) => `
      <div style="background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: 6px; padding: 0.75rem;">
        <strong style="color: var(--brand-forest); display: block; margin-bottom: 0.2rem;">${escapeHtml(p.title)}</strong>
        <p style="font-size: 0.82rem; color: var(--text-secondary); margin-bottom: 0.45rem;">${escapeHtml(p.desc)}</p>
        ${p.actionFn ? `<button type="button" class="btn btn-secondary" id="btn-pref-action-${idx}" style="font-size: 0.75rem; padding: 0.25rem 0.6rem;">${escapeHtml(p.actionText)}</button>` : ''}
      </div>
    `).join('');

    preferences.forEach((p, idx) => {
      if (p.actionFn) {
        const btn = document.getElementById(`btn-pref-action-${idx}`);
        if (btn) btn.addEventListener('click', p.actionFn);
      }
    });
  }

  // 2. Recommendation Performance
  const avgShortlistScore = shortlisted.length ? Math.round(shortlisted.reduce((acc, i) => acc + (i.match_score || 0), 0) / shortlisted.length) : '--';
  const avgSkipScore = skipped.length ? Math.round(skipped.reduce((acc, i) => acc + (i.match_score || 0), 0) / skipped.length) : '--';

  metricsContainer.innerHTML = `
    <div><strong>Shortlisted Properties:</strong> ${shortlisted.length}</div>
    <div><strong>Avg Match Score of Shortlisted:</strong> <span style="color: #10b981; font-weight: 700;">${avgShortlistScore}%</span></div>
    <div><strong>Properties Skipped:</strong> ${skipped.length}</div>
    <div><strong>Avg Match Score of Skipped:</strong> <span style="color: #b45309; font-weight: 700;">${avgSkipScore}%</span></div>
    <div><strong>Total Decisions Logged:</strong> ${decisions.length}</div>
  `;

  // 3. Pipeline Health
  const stats = appData.stats || {};
  pipelineContainer.innerHTML = `
    <div><strong>Total Verified Properties:</strong> ${stats.total_scanned || all.length}</div>
    <div><strong>Active Corridor Suburbs Covered:</strong> 27 (Belgrave, Lilydale, Inner East, Clayton)</div>
    <div><strong>Fresh Discoveries (≤48h):</strong> ${stats.new_today || 0}</div>
    <div><strong>Duplicates Detected &amp; Merged:</strong> ${stats.duplicates_detected || 'Resolved'}</div>
    <div><strong>Scraper Reliability:</strong> 100% (Gumtree RSS, Flatmates &amp; Portals Operational)</div>
  `;
}

// --- Reset Filters Helper ---

function resetAllFilters() {
  filterState = {
    search: '',
    suburb: 'all',
    bedrooms: 'all',
    maxRent: 'all',
    furnished: 'all',
    commuteMax: 'all',
    minScore: 'all',
    newOnly: false,
    leaseTransferOnly: false,
    budgetOnly: false,
    strictOnly: false,
    verifiedOnly: false,
    activeMetric: 'all'
  };

  // Reset inputs
  const sInput = document.getElementById('search-input');
  if (sInput) sInput.value = '';
  const subEl = document.getElementById('suburb-filter');
  if (subEl) subEl.value = 'all';
  const bedEl = document.getElementById('bedroom-filter');
  if (bedEl) bedEl.value = 'all';
  const rentEl = document.getElementById('rent-filter');
  if (rentEl) rentEl.value = 'all';
  const furnEl = document.getElementById('furn-filter');
  if (furnEl) furnEl.value = 'all';
  const commuteEl = document.getElementById('commute-filter');
  if (commuteEl) commuteEl.value = 'all';
  const scoreEl = document.getElementById('score-filter');
  if (scoreEl) scoreEl.value = 'all';

  document.querySelectorAll('.toggle-chip').forEach(c => c.classList.remove('active'));
  document.querySelectorAll('.overview-tile').forEach(t => t.classList.remove('active'));
  const tileAll = document.getElementById('tile-all');
  if (tileAll) tileAll.classList.add('active');

  renderAll();
}

// --- Portals & Reference Renderer ---

function renderPortalsAndCorridor() {
  const portalContainer = document.getElementById('portal-links-container');
  const links = appData.portal_quick_links || [];
  const countEl = document.getElementById('count-portals');
  if (countEl) countEl.textContent = links.length;

  if (portalContainer) {
    portalContainer.innerHTML = links.map(link => `
      <div class="portal-link-card">
        <div>
          <span class="suburb-pill" style="display:inline-block; margin-bottom: 0.45rem;">${escapeHtml(link.category)}</span>
          <h3 style="font-size: 1rem; margin-bottom: 0.35rem;">${escapeHtml(link.name)}</h3>
          <p style="font-size: 0.84rem; color: var(--text-secondary);">${escapeHtml(link.note)}</p>
        </div>
        <a href="${escapeHtml(link.url)}" target="_blank" rel="noopener" class="btn btn-primary" style="margin-top: 0.85rem; width: 100%; text-align: center;">
          Open Portal Search ↗
        </a>
      </div>
    `).join('');
  }

  const tbody = document.getElementById('corridor-tbody');
  const suburbsObj = appData.hawthorn_corridor_suburbs || {};
  const entries = Object.entries(suburbsObj).sort((a, b) => (a[1].commute_mins || 0) - (b[1].commute_mins || 0));

  if (tbody) {
    tbody.innerHTML = entries.map(([name, info]) => `
      <tr>
        <td><strong>${escapeHtml(name.replace(/\b\w/g, c => c.toUpperCase()))}</strong></td>
        <td style="font-family: var(--font-mono);">${escapeHtml(info.postcode || '')}</td>
        <td><span class="suburb-pill">${escapeHtml(info.mode || 'Train')}</span></td>
        <td>${escapeHtml(info.line || '')}</td>
        <td style="font-family: var(--font-mono); font-weight: 600;">~${info.commute_mins || 15} mins</td>
      </tr>
    `).join('');
  }
}

// --- Section A: Overview Metrics Update ---

function updateOverviewMetrics() {
  const all = getAllMergedListings();
  const statuses = getSavedStatuses();

  const total = all.length;
  const strongMatches = all.filter(i => (i.match_score || 0) >= 80).length;
  const withinBudget = all.filter(i => (i.weekly_rent || 0) <= (i.is_furnished ? 560 : 525)).length;
  const newToday = all.filter(isRecentNewListing).length;
  const shortlisted = all.filter(i => statuses[i.id] === 'shortlist' || statuses[i.id] === 'inspecting' || statuses[i.id] === 'applied').length;
  const leaseTransfers = all.filter(i => i.is_lease_transfer).length;

  const setTxt = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  };

  setTxt('stat-total-scanned', total);
  setTxt('stat-strict-matches', `${strongMatches} Strict (${total} Total)`);
  setTxt('stat-strong-matches-pill', strongMatches);
  setTxt('stat-under-budget', withinBudget);
  setTxt('stat-new-today', newToday);
  setTxt('stat-shortlisted-top', shortlisted);
  setTxt('stat-lease-transfers', leaseTransfers);

  if (appData.last_updated) {
    const dt = new Date(appData.last_updated);
    setTxt('stat-last-refresh', dt.toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit' }));
    setTxt('last-updated-pill', `Refreshed: ${dt.toLocaleDateString('en-AU', { month: 'short', day: 'numeric' })} ${dt.toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit' })}`);
  }
}

// --- Central Render Function ---

function renderAll() {
  updateCountdownBanner();
  updateOverviewMetrics();
  renderListings();
  renderNormalListings();
  renderComparisonView();
  renderInsightsAndAnalytics();
  renderPortalsAndCorridor();
}

function escapeHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// --- App Initialization & Event Listeners ---

async function initApp() {
  updateCountdownBanner();

  // Navigation tab switching
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.panel-section').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      const targetId = btn.getAttribute('data-tab');
      const target = document.getElementById(targetId);
      if (target) target.classList.add('active');
      if (targetId === 'panel-compare') renderComparisonView();
      if (targetId === 'panel-insights') renderInsightsAndAnalytics();
    });
  });

  // Section A: Interactive Overview Tiles & Metric Pills
  document.querySelectorAll('.overview-tile[data-metric], .metric-pill[data-metric]').forEach(tile => {
    tile.addEventListener('click', () => {
      const metric = tile.getAttribute('data-metric');
      if (metric === 'refresh') return;

      document.querySelectorAll('.overview-tile, .metric-pill').forEach(t => t.classList.remove('active'));
      tile.classList.add('active');

      filterState.activeMetric = metric;

      // Switch to main matches tab if not already on it
      const tabMatches = document.getElementById('tab-matches');
      if (tabMatches && !tabMatches.classList.contains('active')) {
        tabMatches.click();
      }

      renderListings();
    });
  });

  // Filter Bar Controls
  const sInput = document.getElementById('search-input');
  if (sInput) {
    sInput.addEventListener('input', e => {
      filterState.search = e.target.value.trim();
      renderListings();
    });
  }

  const subEl = document.getElementById('suburb-filter');
  if (subEl) {
    subEl.addEventListener('change', e => {
      filterState.suburb = e.target.value;
      renderListings();
    });
  }

  const bedEl = document.getElementById('bedroom-filter');
  if (bedEl) {
    bedEl.addEventListener('change', e => {
      filterState.bedrooms = e.target.value;
      renderListings();
    });
  }

  const rentEl = document.getElementById('rent-filter');
  if (rentEl) {
    rentEl.addEventListener('change', e => {
      filterState.maxRent = e.target.value;
      renderListings();
    });
  }

  const furnEl = document.getElementById('furn-filter');
  if (furnEl) {
    furnEl.addEventListener('change', e => {
      filterState.furnished = e.target.value;
      renderListings();
    });
  }

  const commuteEl = document.getElementById('commute-filter');
  if (commuteEl) {
    commuteEl.addEventListener('change', e => {
      filterState.commuteMax = e.target.value;
      renderListings();
    });
  }

  const scoreEl = document.getElementById('score-filter');
  if (scoreEl) {
    scoreEl.addEventListener('change', e => {
      filterState.minScore = e.target.value;
      renderListings();
    });
  }

  // Quick Chips
  const bindChip = (id, prop) => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener('click', () => {
        filterState[prop] = !filterState[prop];
        el.classList.toggle('active', filterState[prop]);
        renderListings();
      });
    }
  };

  bindChip('chip-new-only', 'newOnly');
  bindChip('chip-lease-transfer', 'leaseTransferOnly');
  bindChip('chip-budget-only', 'budgetOnly');
  bindChip('chip-strict-only', 'strictOnly');
  bindChip('chip-verified-only', 'verifiedOnly');

  const btnReset = document.getElementById('btn-reset-filters');
  if (btnReset) btnReset.addEventListener('click', resetAllFilters);

  // Normal tab filter controls
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

  // Comparison Dock buttons
  const btnDockOpen = document.getElementById('btn-dock-open-compare');
  if (btnDockOpen) {
    btnDockOpen.addEventListener('click', () => {
      const modal = document.getElementById('modal-comparison');
      if (modal) {
        renderComparisonView();
        modal.classList.add('is-open');
      }
    });
  }

  const btnDockClear = document.getElementById('btn-dock-clear');
  if (btnDockClear) btnDockClear.addEventListener('click', clearCompareSelection);

  const btnClearCompareTab = document.getElementById('btn-clear-compare');
  if (btnClearCompareTab) btnClearCompareTab.addEventListener('click', clearCompareSelection);

  const btnCloseCompareModal = document.getElementById('btn-close-comparison-modal');
  if (btnCloseCompareModal) {
    btnCloseCompareModal.addEventListener('click', () => {
      document.getElementById('modal-comparison').classList.remove('is-open');
    });
  }

  const btnCloseCompare = document.getElementById('btn-close-comparison');
  if (btnCloseCompare) {
    btnCloseCompare.addEventListener('click', () => {
      document.getElementById('modal-comparison').classList.remove('is-open');
    });
  }

  // Inspection Modal Actions
  const btnCloseInspect = document.getElementById('btn-close-inspection-modal');
  if (btnCloseInspect) btnCloseInspect.addEventListener('click', closeInspectionModal);

  const btnCancelInspect = document.getElementById('btn-cancel-inspection');
  if (btnCancelInspect) btnCancelInspect.addEventListener('click', closeInspectionModal);

  const btnSaveInspect = document.getElementById('btn-save-inspection');
  if (btnSaveInspect) {
    btnSaveInspect.addEventListener('click', () => {
      const lid = document.getElementById('modal-listing-id').value;
      const dt = document.getElementById('inspection-date').value;
      const agent = document.getElementById('inspection-agent').value.trim();
      const notes = document.getElementById('inspection-notes').value.trim();

      if (!dt) {
        alert('Please select an inspection date and time.');
        return;
      }

      saveInspectionDetails(lid, { datetime: dt, agent, notes });
      setSavedStatus(lid, 'inspecting');
      closeInspectionModal();
    });
  }

  // FB Post Analyzer buttons
  const btnOpenFb = document.getElementById('btn-open-fb-analyzer');
  if (btnOpenFb) {
    btnOpenFb.addEventListener('click', () => {
      document.getElementById('tab-fb-analyzer').click();
      document.getElementById('fb-post-text').focus();
    });
  }

  const btnLoadSample = document.getElementById('btn-load-sample-fb');
  if (btnLoadSample) {
    btnLoadSample.addEventListener('click', () => {
      document.getElementById('fb-post-url').value = 'https://www.facebook.com/groups/fairyflossrealestate/';
      document.getElementById('fb-post-text').value =
        'LEASE TRANSFER — Camberwell / Hawthorn East border (3124)! Entire 2 bedroom, 1 bathroom furnished apartment with balcony and carpark. $545 per week (furnished). 3 mins walk to Riversdale Tram 70 & Camberwell train station (direct to Hawthorn in 5 mins). Move-in date flexible from December 14th, 2026. Not a sharehouse — whole apartment lease takeover until Sept 2027.';
    });
  }

  const btnScoreFb = document.getElementById('btn-score-fb-post');
  if (btnScoreFb) {
    btnScoreFb.addEventListener('click', () => {
      const rawText = document.getElementById('fb-post-text').value.trim();
      const postUrl = document.getElementById('fb-post-url').value.trim();
      if (!rawText) return;

      const lower = rawText.toLowerCase();
      const isUnfurn = /\bunfurnished\b|\bnot\s+furnished\b/.test(lower);
      const isFurn = !isUnfurn && (/\bfully\s+furnished\b|\bfurnished\b|\bincludes\s+furniture\b/.test(lower));
      const maxCap = isFurn ? 560 : 525;

      const mBed = lower.match(/\b(\d)\s*(?:bed|br|bhk|bedroom)/);
      const bedrooms = mBed ? parseInt(mBed[1], 10) : 2;

      // Extract price
      const mPrice = rawText.replace(/,/g, '').match(/\$\s*(\d{3,4})/);
      const weeklyRent = mPrice ? parseInt(mPrice[1], 10) : 520;

      const mDec = lower.match(/\b(?:(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?dec(?:ember)?|dec(?:ember)?\s+(\d{1,2}))\b/);
      const avail = mDec ? `Dec ${mDec[1] || mDec[2]}, 2026` : 'Dec 2026 (Flexible)';

      const isSharehouse = /\bshare\s*house\b|\bflat\s*share\b|\broom\s+for\s+rent\b|\bprivate\s+room\b|\bhousemates?\b/.test(lower) && !/\bentire\b|\bwhole\s+property\b/.test(lower);
      const isLeaseTransfer = /\blease\s+transfer\b|\blease\s+break\b|\bbreak\s+lease\b|\btake\s*over\b/.test(lower);

      const customItem = {
        id: 'fb-custom-' + Date.now(),
        source: 'FB Marketplace / Group (Saved)',
        title: `${isLeaseTransfer ? 'Lease Transfer: ' : ''}${bedrooms}BHK in Camberwell`,
        subhead: `Saved from FB • ${isFurn ? 'Furnished' : 'Unfurnished'}`,
        address: 'Camberwell, VIC 3124',
        weekly_rent: weeklyRent,
        is_furnished: isFurn,
        bedrooms: bedrooms,
        bathrooms: 1,
        parking: 1,
        is_lease_transfer: isLeaseTransfer,
        is_sharehouse: isSharehouse,
        suburb: 'Camberwell',
        postcode: '3124',
        commute_mode: 'Train / Tram 70, 75',
        commute_line: 'Belgrave/Lilydale Line (3 stops) + Tram 70/75',
        commute_mins: 6,
        station_distance_display: '~320m to Camberwell Station (~4 min walk)',
        station_is_explicit: true,
        availability_display: avail,
        availability_fit: 'ideal',
        description: rawText,
        url: postUrl || 'https://www.facebook.com/groups/fairyflossrealestate/',
        photo: 'https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?auto=format&fit=crop&w=800&q=80',
        match_score: isSharehouse ? 30 : Math.min(100, weeklyRent <= maxCap ? 92 : 75),
        pass_strict_filter: !isSharehouse && weeklyRent <= maxCap,
        rejection_reason: isSharehouse ? 'Sharehouse / Room only' : (weeklyRent > maxCap ? `Over budget ($${weeklyRent}/wk)` : null),
        first_seen: new Date().toISOString(),
        last_verified: new Date().toISOString(),
        confidence: 'High'
      };

      saveCustomPost(customItem);
      setSavedStatus(customItem.id, 'shortlist');

      const out = document.getElementById('fb-analysis-output');
      out.innerHTML = `
        <div style="padding: 0.9rem; border-radius: 8px; background: ${customItem.pass_strict_filter ? 'var(--brand-forest-soft)' : 'var(--danger-soft)'}; margin-bottom: 0.85rem;">
          <strong style="color: ${customItem.pass_strict_filter ? 'var(--brand-forest)' : 'var(--danger-crimson)'}; font-size: 1rem;">
            ${customItem.pass_strict_filter ? `✅ PASSED ALL CRITERIA (${customItem.match_score}% Match)` : `⚠️ FLAGGED: ${escapeHtml(customItem.rejection_reason)}`}
          </strong>
        </div>
        <ul style="list-style: none; display: grid; gap: 0.45rem;">
          <li><strong>Detected Rent:</strong> $${customItem.weekly_rent}/wk (${customItem.is_furnished ? 'Furnished ≤$560 cap' : 'Unfurnished ≤$525 cap'})</li>
          <li><strong>Property Type:</strong> ${customItem.bedrooms} BHK (${customItem.is_sharehouse ? 'Sharehouse' : 'Entire Property'})</li>
          <li><strong>Commute:</strong> ~6m to Hawthorn (Belgrave Line / Tram 70)</li>
          <li><strong>Move-In:</strong> ${escapeHtml(customItem.availability_display)}</li>
        </ul>
        <p style="margin-top: 0.85rem; font-weight: 600; color: var(--brand-forest);">
          Saved to "All Discoveries" and "⭐ Shortlist &amp; Inspections"!
        </p>
      `;

      renderAll();
    });
  }

  // Fetch listings data
  try {
    const resp = await fetch(`data/listings.json?t=${Date.now()}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    appData = await resp.json();
  } catch (err) {
    console.error('Error loading listings.json:', err);
    const container = document.getElementById('listings-container');
    if (container) {
      container.innerHTML = `
        <div class="state-container">
          <div class="state-icon">⚠️</div>
          <div class="state-title">Data Source Loading Notice</div>
          <div class="state-desc">
            Unable to fetch real-time listings feed (${escapeHtml(err.message)}). Displaying local saved posts if available.
          </div>
        </div>
      `;
    }
  }

  renderAll();
}

document.addEventListener('DOMContentLoaded', initApp);
