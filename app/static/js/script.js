/* ============================================================
   Volume Health Analysis Agent — Dashboard Script
   ============================================================ */

async function initDashboard() {
    // Collect fresh volume data first, then render all widgets
    await collectVolumeData();
    loadLastUpdate();
    loadAlertBanner();
    loadKpiStrip();
    loadAgentSummary();
    loadCurrentVolume();
    loadAvailableDrives();
    loadAllDrives();
    loadSwitchLog();
    loadSwitchHistory();
    loadUsageTrend();
}

async function collectVolumeData() {
    try {
        await fetch('/collect_volume_data', { method: 'POST' });
    } catch (e) {
        console.warn('Volume data collection failed:', e);
    }
}

/* ---- Classify -------------------------------------------- */
function classify(pct) {
    if (pct >= 90) return 'critical';
    if (pct >= 60) return 'moderate';
    return 'healthy';
}
function fillClass(s)  { return 'fill-' + s; }
function accentClass(s){ return 'tile-accent-' + s; }
function pctClass(s)   { return 'pct-' + s; }
function pillClass(s)  { return 'pill-' + s; }
function statusPill(s) {
    const labels = { critical:'Critical — Action Required', moderate:'Moderate Usage', healthy:'Healthy', unknown:'Status Unknown' };
    return `<span class="status-pill ${pillClass(s)}">${labels[s] || s}</span>`;
}

/* ---- Refresh --------------------------------------------- */
async function refreshDashboard() {
    const btn  = document.getElementById('refresh-btn');
    const icon = document.getElementById('refresh-icon');
    if (!btn) return;

    btn.disabled = true;
    btn.classList.add('refreshing');
    icon.textContent = '⟳';

    // Clear dynamic content and re-render
    const content = document.getElementById('dynamic-content');
    if (content) {
        const html = await fetch('/home').then(r => r.text());
        content.innerHTML = html;
    }

    await initDashboard();

    btn.disabled = false;
    btn.classList.remove('refreshing');
    icon.textContent = '↻';
}

/* ---- Agent Summary --------------------------------------- */
async function loadAgentSummary() {
    const d       = await fetch('/get_agent_summary').then(r => r.json());
    const content = document.getElementById('agent-summary-content');
    const empty   = document.getElementById('agent-summary-empty');
    const card    = document.getElementById('agent-summary-card');
    const tsEl    = document.getElementById('agent-summary-generated');

    if (!d.exists || !d.data.trim()) {
        if (content) content.classList.add('hidden');
        if (empty)   empty.classList.remove('hidden');
        return;
    }

    if (empty) empty.classList.add('hidden');

    const raw   = d.data;
    const lines = raw.split('\n');

    // Extract "Generated:" timestamp from first line written by agent_runner
    let bodyLines = lines;
    if (lines[0] && lines[0].startsWith('Generated:')) {
        if (tsEl) tsEl.textContent = lines[0];
        bodyLines = lines.slice(2);   // skip "Generated:" line and blank line
    }

    const body = bodyLines.join('\n').trim();

    // Parse the overall rating for the card accent colour
    const ratingMatch = body.match(/OVERALL HEALTH RATING\s*[:\-–]\s*(\w+)/i);
    const rating      = ratingMatch ? ratingMatch[1].toLowerCase() : 'unknown';
    const ratingColor = rating === 'critical' ? 'var(--red)'
                      : rating === 'warning'  ? 'var(--amber)'
                      : rating === 'watch'    ? 'var(--amber)'
                      : rating === 'healthy'  ? 'var(--green)'
                      : 'var(--purple)';
    if (card) card.style.borderTopColor = ratingColor;

    // Render structured sections
    const SECTIONS = [
        'OVERALL HEALTH RATING',
        'ACTIVE TC VOLUME',
        'ALL DRIVES',
        'ANOMALIES DETECTED',
        'ACTIONS TAKEN',
        'RECOMMENDATIONS',
    ];

    const SECTION_META = {
        'OVERALL HEALTH RATING': { icon: '🩺', badge: null },
        'ACTIVE TC VOLUME':      { icon: '💾', badge: 'sb-blue' },
        'ALL DRIVES':            { icon: '🖥',  badge: 'sb-purple' },
        'ANOMALIES DETECTED':    { icon: '⚠️', badge: 'sb-amber' },
        'ACTIONS TAKEN':         { icon: '⚡', badge: 'sb-cyan' },
        'RECOMMENDATIONS':       { icon: '📋', badge: 'sb-green' },
    };

    // Split body into named sections
    const sectionMap = {};
    let currentSection = null;
    let currentLines   = [];

    body.split('\n').forEach(line => {
        const matchedSection = SECTIONS.find(s =>
            line.trim().toUpperCase().startsWith(s)
        );
        if (matchedSection) {
            if (currentSection) sectionMap[currentSection] = currentLines.join('\n').trim();
            currentSection = matchedSection;
            // Capture any text after the heading colon on the same line
            const colonIdx = line.indexOf(':');
            currentLines   = colonIdx >= 0 ? [line.slice(colonIdx + 1).trim()] : [];
        } else if (currentSection) {
            currentLines.push(line);
        }
    });
    if (currentSection) sectionMap[currentSection] = currentLines.join('\n').trim();

    // Build HTML
    let html = '';

    // Overall rating banner
    const overallText = sectionMap['OVERALL HEALTH RATING'] || rating.toUpperCase();
    const ratingClass = rating === 'critical' ? 'rating-critical'
                      : (rating === 'warning' || rating === 'watch') ? 'rating-warning'
                      : rating === 'healthy' ? 'rating-healthy'
                      : 'rating-unknown';
    html += `<div class="agent-rating-banner ${ratingClass}">
        <span class="agent-rating-icon">🩺</span>
        <span class="agent-rating-label">Overall Health</span>
        <span class="agent-rating-value">${_esc(overallText)}</span>
    </div>`;

    // Remaining sections as collapsible blocks
    const renderSections = ['ACTIVE TC VOLUME', 'ALL DRIVES', 'ANOMALIES DETECTED', 'ACTIONS TAKEN', 'RECOMMENDATIONS'];
    renderSections.forEach(sec => {
        const text = sectionMap[sec];
        if (!text) return;
        const meta = SECTION_META[sec] || { icon: '•', badge: null };
        const badgeHtml = meta.badge
            ? `<span class="sect-badge ${meta.badge}" style="margin-left:auto;font-size:0.62rem">${sec}</span>`
            : '';
        const formattedText = _formatSummaryText(text, sec);
        html += `
        <div class="agent-section">
            <div class="agent-section-head">
                <span class="agent-section-icon">${meta.icon}</span>
                <span class="agent-section-title">${sec}</span>
                ${badgeHtml}
            </div>
            <div class="agent-section-body">${formattedText}</div>
        </div>`;
    });

    // Fallback: if no sections were found, render raw text
    if (!Object.keys(sectionMap).length) {
        html += `<pre class="agent-raw-text">${_esc(body)}</pre>`;
    }

    if (content) {
        content.innerHTML = html;
        content.classList.remove('hidden');
    }
}

function _esc(str) {
    return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function _formatSummaryText(text, section) {
    const lines = text.split('\n');
    let html = '';
    lines.forEach(line => {
        const trimmed = line.trim();
        if (!trimmed) return;

        // Bullet / list item lines (start with -, •, *, number.)
        if (/^[-•*]\s/.test(trimmed) || /^\d+\.\s/.test(trimmed)) {
            // Highlight drive names like C:, D:, or VOLUME_NAME
            const content = _esc(trimmed.replace(/^[-•*\d.]\s*/, ''));
            html += `<div class="agent-list-item">${content}</div>`;
            return;
        }

        // Key: Value lines
        if (/^[A-Za-z ]+\s*:/.test(trimmed)) {
            const colonIdx = trimmed.indexOf(':');
            const key      = _esc(trimmed.slice(0, colonIdx).trim());
            const val      = _esc(trimmed.slice(colonIdx + 1).trim());
            if (val) {
                const valClass = _summaryValueClass(val);
                html += `<div class="agent-kv-row">
                    <span class="agent-kv-key">${key}</span>
                    <span class="agent-kv-val ${valClass}">${val}</span>
                </div>`;
                return;
            }
        }

        // Plain text
        html += `<div class="agent-text-line">${_esc(trimmed)}</div>`;
    });
    return html || `<div class="agent-text-line">${_esc(text)}</div>`;
}

function _summaryValueClass(val) {
    const v = val.toUpperCase();
    if (v.includes('CRITICAL'))  return 'aval-critical';
    if (v.includes('WARNING') || v.includes('WATCH')) return 'aval-warning';
    if (v.includes('HEALTHY'))   return 'aval-healthy';
    if (v.includes('PERFORMED') || v.includes('SWITCHED')) return 'aval-warning';
    if (v.includes('NO SWITCH') || v.includes('NOT REQUIRED') || v.includes('NO ACTION')) return 'aval-ok';
    if (v.includes('NONE') || v.includes('NO ANOMAL')) return 'aval-ok';
    return '';
}

async function generateAgentSummary() {
    const btn  = document.getElementById('btn-generate-summary');
    const icon = document.getElementById('generate-summary-icon');
    if (!btn) return;

    btn.disabled = true;
    btn.classList.add('generating');
    if (icon) icon.textContent = '⟳';

    // Show a spinner in the card body while waiting
    const content = document.getElementById('agent-summary-content');
    const empty   = document.getElementById('agent-summary-empty');
    if (content) content.innerHTML = '<div class="agent-generating-msg">&#129302;&nbsp; Claude is analysing your volumes&hellip;</div>';
    if (content) content.classList.remove('hidden');
    if (empty)   empty.classList.add('hidden');

    try {
        const resp = await fetch('/run_agent_summary', { method: 'POST' });
        const d    = await resp.json();
        if (d.ok) {
            await loadAgentSummary();   // re-render with fresh file
        } else {
            if (content) content.innerHTML =
                `<div class="agent-error-msg">&#10060;&nbsp; Agent error: ${_esc(d.error || 'Unknown error')}</div>`;
        }
    } catch (err) {
        if (content) content.innerHTML =
            `<div class="agent-error-msg">&#10060;&nbsp; Request failed: ${_esc(String(err))}</div>`;
    } finally {
        btn.disabled = false;
        btn.classList.remove('generating');
        if (icon) icon.textContent = '⚡';
    }
}

/* ---- Last Update ----------------------------------------- */
async function loadLastUpdate() {
    const d = await fetch('/get_last_update').then(r => r.json());
    const el = document.getElementById('last-update-header');
    if (el) el.innerHTML = 'Last updated: <span>' + d.last_update + '</span>';
}

/* ---- Alert Banner ---------------------------------------- */
async function loadAlertBanner() {
    const d = await fetch('/get_alert_message').then(r => r.json());
    const banner = document.getElementById('alert-banner');
    if (!banner || !d.message) return;
    const icon = d.type === 'switch' ? '&#128260;' : '&#9888;&#65039;';
    banner.innerHTML = icon + '&nbsp; ' + d.message;
    banner.classList.remove('hidden');
    banner.classList.add(d.type === 'switch' ? 'switch-alert' : 'critical');
}

/* ---- KPI Strip + Donut ----------------------------------- */
async function loadKpiStrip() {
    const d     = await fetch('/get_drive_category_counts').then(r => r.json());
    const total = d.high + d.moderate + d.healthy;

    _setText('kpi-total',    total);
    _setText('kpi-critical', d.high);
    _setText('kpi-moderate', d.moderate);
    _setText('kpi-healthy',  d.healthy);

    _drawUtilSplit(d.high, d.moderate, d.healthy, total);
}

function _drawUtilSplit(high, moderate, healthy, total) {
    // Stacked bar segments
    const pctOf = n => total > 0 ? ((n / total) * 100).toFixed(1) : 0;

    const segs = [
        { id: 'useg-critical', val: high,     pct: pctOf(high) },
        { id: 'useg-moderate', val: moderate, pct: pctOf(moderate) },
        { id: 'useg-healthy',  val: healthy,  pct: pctOf(healthy) },
    ];

    segs.forEach(s => {
        const el = document.getElementById(s.id);
        if (!el) return;
        el.style.width = (total > 0 ? s.pct : 0) + '%';
        el.title = `${s.val} drives (${s.pct}%)`;
    });

    // Tick labels under bar
    const ticks = document.getElementById('util-bar-ticks');
    if (ticks) {
        ticks.innerHTML = segs
            .filter(s => s.val > 0)
            .map(s => `<span style="width:${s.pct}%">${s.pct}%</span>`)
            .join('');
    }

    // Metric tiles
    [
        { numId: 'um-critical', pctId: 'ump-critical', val: high,     pct: pctOf(high) },
        { numId: 'um-moderate', pctId: 'ump-moderate', val: moderate, pct: pctOf(moderate) },
        { numId: 'um-healthy',  pctId: 'ump-healthy',  val: healthy,  pct: pctOf(healthy) },
    ].forEach(m => {
        _setText(m.numId, m.val);
        _setText(m.pctId, m.pct + '%');
    });

    _setText('util-total', total);
}

/* ---- Active TC Volume ------------------------------------ */
async function loadCurrentVolume() {
    const d    = await fetch('/get_current_volume').then(r => r.json());
    const card = document.getElementById('tc-volume-card');
    _setText('tc-vol-name', d.name);

    if (d.found && d.percent !== null) {
        const s = d.status || classify(d.percent);
        _setText('tc-vol-used',  d.used_gb);
        _setText('tc-vol-total', d.total_gb);
        _setText('tc-vol-free',  d.free_gb);
        _setText('tc-vol-pct',   d.percent + '%');
        _show('tc-vol-stats');
        _show('tc-vol-bar-wrap');

        const bar = document.getElementById('tc-vol-bar');
        bar.style.width = d.percent + '%';
        bar.className = 'progress-fill ' + fillClass(s);

        document.getElementById('tc-vol-badge').innerHTML = statusPill(s);
        if (card) card.style.borderTopColor = _statusColor(s);
    } else {
        document.getElementById('tc-vol-badge').innerHTML =
            `<span style="font-size:0.75rem;color:var(--text-muted)">Volume not visible in local drives — TC-managed network volume</span>`;
    }
}

/* ---- Most-Used Drive ------------------------------------- */
async function loadTopDrive() {
    const d = await fetch('/get_critical_drive').then(r => r.json());
    if (!d.drive) return;
    const drive = d.drive;
    const s     = classify(drive.percent);

    _setText('top-drive-name',  drive.name + '  (' + drive.mountpoint + ')');
    _setText('top-drive-used',  drive.used_gb);
    _setText('top-drive-total', drive.total_gb);
    _setText('top-drive-free',  drive.free_gb);
    _setText('top-drive-pct',   drive.percent + '%');

    const bar = document.getElementById('top-drive-bar');
    bar.style.width  = drive.percent + '%';
    bar.className    = 'progress-fill ' + fillClass(s);

    document.getElementById('top-drive-badge').innerHTML = statusPill(s);

    const card = document.getElementById('top-drive-card');
    if (card) card.style.borderTopColor = _statusColor(s);
}

/* ---- Available Drives ------------------------------------ */
async function loadAvailableDrives() {
    const d    = await fetch('/get_available_drives').then(r => r.json());
    const list = document.getElementById('available-drives-list');
    if (!list) return;
    list.innerHTML = '';

    if (d.drives && d.drives.length > 0) {
        d.drives.forEach(drive => {
            list.innerHTML += `
                <div class="drive-row">
                    <span>
                        <span class="drive-row-name">${drive.name}</span>
                        <span class="drive-row-mount">${drive.mountpoint}</span>
                    </span>
                    <span class="dr-pct-chip">${drive.percent}%</span>
                </div>`;
        });
    } else {
        list.innerHTML = '<div class="no-data">No drives below 60%</div>';
    }

    const footer  = document.getElementById('available-drives-status');
    if (footer) {
        const isWarn = d.status.includes('Action') || d.status.includes('not available');
        footer.textContent = (isWarn ? '⚠  ' : '✓  ') + d.status;
        footer.className   = 'status-footer ' + (isWarn ? 'warn' : 'ok');
    }
}

/* ---- All Drives Overview --------------------------------- */
async function loadAllDrives() {
    const d    = await fetch('/get_all_drives').then(r => r.json());
    const body = document.getElementById('all-drives-body');
    if (!body || !d.drives) return;

    const grid = document.createElement('div');
    grid.className = 'all-drives-grid';

    d.drives.forEach(drive => {
        const s       = classify(drive.percent);
        const tcBadge = drive.is_current_tc_vol ? `<span class="tc-badge">TC Active</span>` : '';
        grid.innerHTML += `
            <div class="drive-tile ${accentClass(s)}">
                <div class="drive-tile-top">
                    <div>
                        <div class="drive-tile-name">${drive.name} ${tcBadge}</div>
                        <div class="drive-tile-mount">${drive.mountpoint} &middot; ${drive.fstype}</div>
                    </div>
                    <div class="drive-tile-pct ${pctClass(s)}">${drive.percent}%</div>
                </div>
                <div class="progress-track">
                    <div class="progress-fill ${fillClass(s)}" style="width:${drive.percent}%"></div>
                </div>
                <div class="drive-tile-meta">
                    <span>Used&nbsp;${drive.used_gb}</span>
                    <span>Free&nbsp;${drive.free_gb}</span>
                    <span>Total&nbsp;${drive.total_gb}</span>
                </div>
            </div>`;
    });

    body.appendChild(grid);
}

/* ---- Switch Log ------------------------------------------ */
async function loadSwitchLog() {
    const d    = await fetch('/get_switch_log').then(r => r.json());
    const el   = document.getElementById('switch-log-content');
    const card = document.getElementById('switch-log-card');
    if (!el) return;

    if (d.exists && d.data) {
        el.textContent = d.data;
        if (card && (d.data.includes('SUCCESS') || d.data.includes('PARTIAL'))) {
            card.style.borderTopColor = 'var(--amber)';
        }
    } else {
        el.textContent = 'No volume switch has been performed yet.';
        el.style.color = 'var(--text-muted)';
    }
}

/* ---- Switch History -------------------------------------- */
async function loadSwitchHistory() {
    const d    = await fetch('/get_switch_history').then(r => r.json());
    const el   = document.getElementById('switch-history-content');
    const card = document.getElementById('switch-history-card');
    if (!el) return;

    if (d.exists && d.data) {
        el.textContent = d.data;
    } else {
        el.textContent = 'No switch history yet. History is recorded here after each volume switch.';
        el.style.color = 'var(--text-muted)';
    }
}

function openHistoryModal() {
    const modal = document.getElementById('switchHistoryModal');
    if (!modal) return;
    const src  = document.getElementById('switch-history-content');
    const dest = document.getElementById('switch-history-modal-content');
    if (src && dest) dest.textContent = src.textContent;
    modal.classList.remove('hidden');
}

/* ---- Modal helpers --------------------------------------- */
function openModal(id) {
    const modal = document.getElementById(id);
    if (!modal) return;
    const src  = document.getElementById('switch-log-content');
    const dest = document.getElementById('switch-modal-content');
    if (src && dest) dest.textContent = src.textContent;
    modal.classList.remove('hidden');
}
function closeModal(id, event) {
    const modal = document.getElementById(id);
    if (!modal) return;
    if (!event || event.target === modal) modal.classList.add('hidden');
}

/* ---- Usage Trend Chart ----------------------------------- */
const _trendState = { range: 'all', hidden: new Set() };
let   _trendRawData = null;

async function loadUsageTrend() {
    const d = await fetch('/get_usage_history').then(r => r.json());
    _trendRawData = (d.data || '').trim();
    _renderTrend();
}

function _renderTrend() {
    const svg             = document.getElementById('usageTrendChart');
    const legendContainer = document.getElementById('usageLegend');
    const filterBar       = document.getElementById('trend-filters');
    const statsWrap       = document.getElementById('trendStatsTable');
    if (!svg) return;
    svg.innerHTML = '';
    legendContainer.innerHTML = '';

    if (!_trendRawData) {
        _svgMsg(svg, 'No history data. Run analysis to populate trend.');
        if (filterBar) filterBar.innerHTML = '';
        if (statsWrap) statsWrap.innerHTML = '';
        return;
    }

    // Parse all records
    const allRecords = [];
    _trendRawData.split('\n').filter(Boolean).forEach(line => {
        const parts = line.split('|').map(x => x.trim());
        if (parts.length < 3) return;
        const [ts, drive, pctStr] = parts;
        const pct = parseFloat(pctStr.replace('%', ''));
        if (!isNaN(pct)) allRecords.push({ ts, drive, pct });
    });

    if (!allRecords.length) { _svgMsg(svg, 'No history data. Run analysis to populate trend.'); return; }

    const allDrives = [...new Set(allRecords.map(r => r.drive))];
    const allTs     = [...new Set(allRecords.map(r => r.ts))];

    // Time range filter
    let visibleTs = allTs;
    if (_trendState.range !== 'all') {
        const n = parseInt(_trendState.range);
        visibleTs = allTs.slice(-n);
    }

    const records = allRecords.filter(r => visibleTs.includes(r.ts));
    const labels  = [...new Set(records.map(r => r.ts))];

    const palette  = ['#7c5cfc','#22c55e','#f59e0b','#3b82f6','#ef4444','#06b6d4','#ec4899','#a78bfa'];
    const colorMap = {};
    allDrives.forEach((drive, i) => { colorMap[drive] = palette[i % palette.length]; });

    // ---- Filter bar ----
    if (filterBar) {
        const ranges = [
            { key: 'all', label: 'All' },
            { key: '5',   label: 'Last 5' },
            { key: '10',  label: 'Last 10' },
            { key: '20',  label: 'Last 20' },
        ];
        const rangeHtml = ranges.map(r =>
            `<button class="trend-range-btn ${_trendState.range === r.key ? 'active' : ''}"
                     onclick="_setTrendRange('${r.key}')">${r.label}</button>`
        ).join('');

        const driveChips = allDrives.map(drive => {
            const hidden = _trendState.hidden.has(drive);
            const dot    = `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${colorMap[drive]};margin-right:5px;flex-shrink:0"></span>`;
            return `<button class="trend-drive-chip ${hidden ? 'dimmed' : ''}"
                            onclick="_toggleDrive('${drive}')"
                            title="${hidden ? 'Show' : 'Hide'} ${drive}">
                        ${dot}${drive}
                    </button>`;
        }).join('');

        filterBar.innerHTML = `
            <div class="trend-filter-row">
                <div class="trend-filter-group">
                    <span class="trend-filter-label">Time Range</span>
                    <div class="trend-range-btns">${rangeHtml}</div>
                </div>
                <div class="trend-filter-group">
                    <span class="trend-filter-label">Drives</span>
                    <div class="trend-drive-chips">${driveChips}</div>
                </div>
            </div>`;
    }

    // Apply drive visibility
    const visibleDrives = allDrives.filter(d => !_trendState.hidden.has(d));
    const byDrive = {};
    visibleDrives.forEach(drive => {
        byDrive[drive] = records.filter(r => r.drive === drive);
    });

    if (labels.length < 2) {
        _svgMsg(svg, 'Not enough history points yet — run analysis again to build trend.');
        _renderStatsTable(statsWrap, allDrives, allRecords, colorMap);
        return;
    }

    // ---- Chart ----
    const W      = svg.clientWidth  || 700;
    const H      = svg.clientHeight || 280;
    const pad    = { top: 20, right: 90, bottom: 42, left: 46 };
    const innerW = W - pad.left - pad.right;
    const innerH = H - pad.top  - pad.bottom;
    const xStep  = innerW / Math.max(labels.length - 1, 1);

    const defs = _el('defs');
    visibleDrives.forEach((drive, i) => {
        const grad = _el('linearGradient');
        grad.setAttribute('id', 'grad_' + i);
        grad.setAttribute('x1', '0'); grad.setAttribute('y1', '0');
        grad.setAttribute('x2', '0'); grad.setAttribute('y2', '1');
        const s1 = _el('stop'); s1.setAttribute('offset', '0%');
        s1.setAttribute('stop-color', colorMap[drive]); s1.setAttribute('stop-opacity', '0.18');
        const s2 = _el('stop'); s2.setAttribute('offset', '100%');
        s2.setAttribute('stop-color', colorMap[drive]); s2.setAttribute('stop-opacity', '0');
        grad.appendChild(s1); grad.appendChild(s2);
        defs.appendChild(grad);
    });
    svg.appendChild(defs);

    // Grid + Y labels
    for (let i = 0; i <= 100; i += 20) {
        const y  = pad.top + innerH - (i / 100) * innerH;
        const gl = _el('line');
        gl.setAttribute('x1', pad.left); gl.setAttribute('y1', y.toFixed(1));
        gl.setAttribute('x2', W - pad.right); gl.setAttribute('y2', y.toFixed(1));
        gl.setAttribute('stroke', '#1f2330'); gl.setAttribute('stroke-width', '1');
        svg.appendChild(gl);
        const yt = _el('text');
        yt.setAttribute('x', pad.left - 6); yt.setAttribute('y', (y + 4).toFixed(1));
        yt.setAttribute('text-anchor', 'end'); yt.setAttribute('font-size', '9'); yt.setAttribute('fill', '#4b5268');
        yt.textContent = i + '%';
        svg.appendChild(yt);
    }

    // Threshold lines
    [{ y: 90, color: '#ef4444', label: '90% Critical' },
     { y: 60, color: '#f59e0b', label: '60% Moderate' }].forEach(ref => {
        const yy = pad.top + innerH - (ref.y / 100) * innerH;
        const rl = _el('line');
        rl.setAttribute('x1', pad.left); rl.setAttribute('y1', yy.toFixed(1));
        rl.setAttribute('x2', W - pad.right); rl.setAttribute('y2', yy.toFixed(1));
        rl.setAttribute('stroke', ref.color); rl.setAttribute('stroke-width', '1');
        rl.setAttribute('stroke-dasharray', '5,4'); rl.setAttribute('opacity', '0.55');
        svg.appendChild(rl);
        const rt = _el('text');
        rt.setAttribute('x', W - pad.right + 4); rt.setAttribute('y', (yy + 4).toFixed(1));
        rt.setAttribute('font-size', '8'); rt.setAttribute('fill', ref.color);
        rt.textContent = ref.label;
        svg.appendChild(rt);
    });

    // X tick labels
    const tickEvery = Math.ceil(labels.length / 7);
    labels.forEach((lbl, i) => {
        if (i % tickEvery !== 0 && i !== labels.length - 1) return;
        const x  = pad.left + xStep * i;
        const xt = _el('text');
        xt.setAttribute('x', x.toFixed(1)); xt.setAttribute('y', H - pad.bottom + 16);
        xt.setAttribute('text-anchor', 'middle'); xt.setAttribute('font-size', '8'); xt.setAttribute('fill', '#4b5268');
        xt.textContent = lbl;
        svg.appendChild(xt);
    });

    // Axes
    const xa = _el('line');
    xa.setAttribute('x1', pad.left); xa.setAttribute('y1', pad.top + innerH);
    xa.setAttribute('x2', W - pad.right); xa.setAttribute('y2', pad.top + innerH);
    xa.setAttribute('stroke', '#2a2f3e'); svg.appendChild(xa);
    const ya = _el('line');
    ya.setAttribute('x1', pad.left); ya.setAttribute('y1', pad.top);
    ya.setAttribute('x2', pad.left); ya.setAttribute('y2', pad.top + innerH);
    ya.setAttribute('stroke', '#2a2f3e'); svg.appendChild(ya);

    // Lines + areas + dots per drive
    visibleDrives.forEach((drive, idx) => {
        const color  = colorMap[drive];
        const points = byDrive[drive];
        if (!points || !points.length) return;

        const coords = points.map(pt => ({
            x: pad.left + xStep * labels.indexOf(pt.ts),
            y: pad.top + innerH - (pt.pct / 100) * innerH,
            pct: pt.pct, ts: pt.ts
        }));

        if (coords.length >= 2) {
            let aD = `M${coords[0].x.toFixed(2)} ${(pad.top + innerH).toFixed(2)} `;
            coords.forEach(c => { aD += `L${c.x.toFixed(2)} ${c.y.toFixed(2)} `; });
            aD += `L${coords[coords.length-1].x.toFixed(2)} ${(pad.top + innerH).toFixed(2)} Z`;
            const area = _el('path'); area.setAttribute('d', aD); area.setAttribute('fill', `url(#grad_${idx})`);
            svg.appendChild(area);
        }

        let lD = '';
        coords.forEach((c, i) => { lD += (i === 0 ? `M${c.x.toFixed(2)} ${c.y.toFixed(2)}` : ` L${c.x.toFixed(2)} ${c.y.toFixed(2)}`); });
        const ln = _el('path'); ln.setAttribute('d', lD); ln.setAttribute('stroke', color);
        ln.setAttribute('stroke-width', '2'); ln.setAttribute('fill', 'none'); ln.setAttribute('stroke-linejoin', 'round');
        svg.appendChild(ln);

        coords.forEach(c => {
            const ci = _el('circle');
            ci.setAttribute('cx', c.x.toFixed(2)); ci.setAttribute('cy', c.y.toFixed(2));
            ci.setAttribute('r', '4'); ci.setAttribute('fill', color);
            ci.setAttribute('stroke', '#0d0f14'); ci.setAttribute('stroke-width', '1.5');
            const tt = _el('title'); tt.textContent = `${c.ts}  |  ${drive}  |  ${c.pct}%`;
            ci.appendChild(tt); svg.appendChild(ci);
        });

        legendContainer.innerHTML += `
            <div class="trend-legend-item">
                <span class="trend-dot" style="background:${color};border-radius:50%"></span>
                <span>${drive}</span>
            </div>`;
    });

    // Stats table
    _renderStatsTable(statsWrap, allDrives, records, colorMap);
}

function _renderStatsTable(wrap, drives, records, colorMap) {
    if (!wrap || !drives.length) return;
    const rows = drives.map(drive => {
        const pts = records.filter(r => r.drive === drive).map(r => r.pct);
        if (!pts.length) return null;
        const latest = pts[pts.length - 1];
        const min    = Math.min(...pts);
        const max    = Math.max(...pts);
        const avg    = (pts.reduce((a, b) => a + b, 0) / pts.length).toFixed(1);
        const status = latest >= 90 ? 'critical' : latest >= 60 ? 'moderate' : 'healthy';
        return { drive, latest, min, max, avg, status, color: colorMap[drive] };
    }).filter(Boolean);

    const trs = rows.map(r => `
        <tr>
            <td><span class="trend-stat-dot" style="background:${r.color}"></span>${r.drive}</td>
            <td class="ts-num pct-${r.status}">${r.latest}%</td>
            <td class="ts-num">${r.min}%</td>
            <td class="ts-num">${r.max}%</td>
            <td class="ts-num">${r.avg}%</td>
            <td><span class="status-pill pill-${r.status}" style="font-size:0.65rem;padding:2px 8px">${r.status.charAt(0).toUpperCase()+r.status.slice(1)}</span></td>
        </tr>`).join('');

    wrap.innerHTML = `
        <table class="trend-stats-table">
            <thead><tr>
                <th>Drive</th><th>Latest</th><th>Min</th><th>Max</th><th>Avg</th><th>Status</th>
            </tr></thead>
            <tbody>${trs}</tbody>
        </table>`;
}

function _setTrendRange(key) {
    _trendState.range = key;
    _renderTrend();
}

function _toggleDrive(drive) {
    if (_trendState.hidden.has(drive)) _trendState.hidden.delete(drive);
    else _trendState.hidden.add(drive);
    _renderTrend();
}

/* ---- Tiny helpers ---------------------------------------- */
function _setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
}
function _show(id) {
    const el = document.getElementById(id);
    if (el) el.style.display = '';
}
function _el(tag) { return document.createElementNS('http://www.w3.org/2000/svg', tag); }
function _svgMsg(svg, msg) {
    const t = _el('text');
    t.setAttribute('x', '50%'); t.setAttribute('y', '50%');
    t.setAttribute('text-anchor', 'middle'); t.setAttribute('font-size', '12');
    t.setAttribute('fill', '#4b5268');
    t.textContent = msg;
    svg.appendChild(t);
}
function _statusColor(s) {
    return s === 'critical' ? 'var(--red)' : s === 'moderate' ? 'var(--amber)' : 'var(--green)';
}
