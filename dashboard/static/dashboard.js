const state = {
  timer: null,
  config: null,
  view: 'live',
  decisionsLimit: 20,
};

let pnlChartInstance = null;
let scoreChartInstance = null;
let activeCardMenuSymbol = null;

const $ = (id) => document.getElementById(id);

function esc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function number(value, digits = 2) {
  if (value === null || value === undefined || value === '') return '--';
  const num = Number(value);
  if (!Number.isFinite(num)) return '--';
  return num.toLocaleString('fr-CA', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function price(value) {
  if (value === null || value === undefined || value === '') return '--';
  const num = Number(value);
  if (!Number.isFinite(num)) return '--';

  let decimals = 2;
  if (num < 1) {
    decimals = 6;
  } else if (num < 10) {
    decimals = 4;
  }

  return num.toLocaleString('fr-CA', {
    minimumFractionDigits: num < 1 ? 4 : 2,
    maximumFractionDigits: decimals,
  });
}

function qty(value) {
  if (value === null || value === undefined || value === '') return '--';
  const num = Number(value);
  if (!Number.isFinite(num)) return '--';
  return num.toLocaleString('fr-CA', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 8,
  });
}

function percent(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return '--';
  return `${number(num, 1)}%`;
}

function signedPercent(value, digits = 3) {
  const num = Number(value);
  if (!Number.isFinite(num)) return '--';
  const sign = num > 0 ? '+' : '';
  return `${sign}${number(num, digits)}%`;
}

function seconds(value) {
  const total = Number(value) || 0;
  const minutes = Math.floor(total / 60);
  const hours = Math.floor(minutes / 60);
  if (hours > 0) return `${hours}h ${minutes % 60}m`;
  const secs = total % 60;
  if (minutes <= 0) return `${secs}s`;
  return `${minutes}m ${secs}s`;
}

function duration(value, compact = true) {
  let remaining = Math.max(0, Math.floor(Number(value) || 0));
  const units = [
    ['mois', 2592000],
    ['j', 86400],
    ['h', 3600],
    ['min', 60],
    ['s', 1],
  ];
  const parts = [];

  for (const [label, size] of units) {
    const amount = Math.floor(remaining / size);
    if (amount > 0 || (label === 's' && !parts.length)) {
      parts.push(`${amount}${label}`);
      remaining -= amount * size;
    }
    if (compact && parts.length >= 2) break;
  }

  return parts.join(' ');
}

function parseDate(value) {
  if (!value) return null;
  const normalized = String(value).trim();
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

function parseLogLine(line) {
  const text = String(line ?? '').trim();
  const match = text.match(/^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})(?:[,.](\d{1,6}))?\s*-\s*([A-Z]+)\s*-\s*(.*)$/);
  if (!match) {
    return { date: null, level: null, message: text };
  }

  const [, day, time, fraction = '0', level, message] = match;
  const millis = fraction.padEnd(3, '0').slice(0, 3);
  return {
    date: parseDate(`${day}T${time}.${millis}`),
    level,
    message,
  };
}

function formatDateTime(value, showSeconds = true) {
  const date = value instanceof Date ? value : parseDate(value);
  if (!date) return '--';
  const options = {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  };
  if (showSeconds) {
    options.second = '2-digit';
  }
  return date.toLocaleString('fr-CA', options);
}

function formatFriendlyDate(value, showSeconds = true) {
  const date = value instanceof Date ? value : parseDate(value);
  if (!date) return '--';

  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const target = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const diffDays = Math.round((today - target) / 86400000);

  const timeOptions = {
    hour: '2-digit',
    minute: '2-digit',
  };
  if (showSeconds) {
    timeOptions.second = '2-digit';
  }
  const time = date.toLocaleTimeString('fr-FR', timeOptions).replace(':', 'h');

  if (diffDays === 0) return `Aujourd'hui · ${time}`;
  if (diffDays === 1) return `Hier · ${time}`;

  const day = date.getDate();
  const month = date.toLocaleDateString('fr-FR', { month: 'short' }).replace('.', '');
  return `${day} ${month}. · ${time}`;
}

function relativeTime(value) {
  const date = value instanceof Date ? value : parseDate(value);
  if (!date) return '--';
  const diffSeconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  return `il y a ${duration(diffSeconds)}`;
}

function dateWithRelative(value, showSeconds = true) {
  const date = value instanceof Date ? value : parseDate(value);
  if (!date) return '--';
  return `${formatFriendlyDate(date, showSeconds)} · ${relativeTime(date)}`;
}

function badgeClass(ok, warn = false) {
  if (warn) return 'badge warn';
  return ok ? 'badge good' : 'badge bad';
}

function regimeClass(mode) {
  const normalized = String(mode || '').toUpperCase();
  if (normalized.includes('BEAR')) return 'bear';
  if (normalized.includes('BULL')) return 'bull';
  return 'normal';
}

function setBadge(el, text, className) {
  if (!el) return;
  const textEl = el.querySelector('.badge-text') || el;
  textEl.textContent = text;
  el.className = className;
}

function setView(view) {
  const validViews = ['live', 'analytics', 'trades', 'console', 'config'];
  const next = validViews.includes(view) ? view : 'live';
  state.view = next;
  document.querySelectorAll('.view').forEach((el) => {
    el.classList.toggle('active', el.id === `view${next[0].toUpperCase()}${next.slice(1)}`);
  });
  document.querySelectorAll('.nav-button').forEach((button) => {
    button.classList.toggle('active', button.dataset.view === next);
  });
  if (window.location.hash !== `#${next}`) {
    history.replaceState(null, '', `#${next}`);
  }
  if (next === 'config' && !state.config) {
    loadConfig().catch((error) => {
      $('configStatus').textContent = `Erreur chargement config: ${error.message}`;
      $('configStatus').className = 'config-status bad';
    });
  }
  if (next === 'console') {
    consoleState.pinned = true;
    const pinBtn = $('consolePinButton');
    if (pinBtn) {
      pinBtn.textContent = '⬇ Auto';
      pinBtn.classList.add('active');
    }
    refreshConsole(true);
  }
  if (next === 'analytics') {
    refreshAnalytics();
  }
  if (next === 'trades') {
    refreshTrades();
  }
}

function currentHashView() {
  const hash = window.location.hash.replace('#', '');
  const validViews = ['live', 'analytics', 'trades', 'console', 'config'];
  if (validViews.includes(hash)) return hash;
  return 'live';
}

function getSectionIcon(section) {
  const sec = section.toLowerCase();
  if (sec.includes('général') || sec.includes('general')) {
    return `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="section-icon"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="9" y1="3" x2="9" y2="21"/><line x1="15" y1="3" x2="15" y2="21"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/></svg>`;
  }
  if (sec.includes('stratégie') || sec.includes('strategie') || sec.includes('support') || sec.includes('touch') || sec.includes('algo')) {
    return `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="section-icon"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>`;
  }
  if (sec.includes('notification') || sec.includes('telegram') || sec.includes('alerte')) {
    return `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="section-icon"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>`;
  }
  if (sec.includes('kraken') || sec.includes('api') || sec.includes('exchange') || sec.includes('échange') || sec.includes('credential')) {
    return `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="section-icon"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>`;
  }
  if (sec.includes('risque') || sec.includes('risk') || sec.includes('limite') || sec.includes('sécurité')) {
    return `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="section-icon"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>`;
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="section-icon"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`;
}

function renderConfig(config) {
  state.config = config;
  $('configHint').textContent = `${config.file} · secrets masqués · redémarrage requis selon badge`;
  const form = $('configForm');
  const sections = {};
  for (const field of config.fields || []) {
    if (!sections[field.section]) sections[field.section] = [];
    sections[field.section].push(field);
  }

  form.innerHTML = Object.entries(sections).map(([section, fields]) => `
    <section class="config-section">
      <div class="config-section-title">
        ${getSectionIcon(section)}
        <h3>${esc(section)}</h3>
      </div>
      <div class="config-grid">
        ${fields.map((field) => renderConfigField(field)).join('')}
      </div>
    </section>
  `).join('');
}

function renderConfigField(field) {
  const common = `
    id="cfg_${esc(field.name)}"
    name="${esc(field.name)}"
    data-type="${esc(field.type)}"
  `;
  const source = field.source === 'dashboard' ? '.env.dashboard' : 'env';

  let restartBadge = '';
  if (field.restart === 'bot') {
    restartBadge = `<span class="cfg-badge reboot" title="Nécessite de redémarrer le bot"><svg xmlns="http://www.w3.org/2000/svg" width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: middle; margin-right: 3px; display: inline-block;"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/><line x1="8" y1="16" x2="8" y2="16"/><line x1="16" y1="16" x2="16" y2="16"/></svg>bot</span>`;
  } else if (field.restart === 'dashboard') {
    restartBadge = `<span class="cfg-badge reboot-dash" title="Nécessite de redémarrer le dashboard"><svg xmlns="http://www.w3.org/2000/svg" width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: middle; margin-right: 3px; display: inline-block;"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>dash</span>`;
  } else {
    restartBadge = `<span class="cfg-badge dynamic" title="Pris en compte instantanément"><svg xmlns="http://www.w3.org/2000/svg" width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: middle; margin-right: 3px; display: inline-block;"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>live</span>`;
  }

  let control = '';
  if (field.type === 'bool') {
    const checked = String(field.value).toLowerCase() === 'true' ? 'checked' : '';
    control = `<label class="switch"><input ${common} type="checkbox" ${checked}><span></span></label>`;

    return `
      <div class="config-field bool-field">
        <div class="config-meta-container">
          <span class="config-label">${esc(field.label)}</span>
          <span class="config-meta">
            <code>${esc(field.name)}</code>
            ${restartBadge}
          </span>
        </div>
        ${control}
      </div>
    `;
  } else {
    const inputType = ['int', 'float'].includes(field.type) ? 'number' : 'text';
    const step = field.type === 'int' ? '1' : field.type === 'float' ? '0.01' : undefined;
    const attrs = [
      common,
      `type="${inputType}"`,
      `value="${esc(field.value)}"`,
      step ? `step="${step}"` : '',
      field.min !== null && field.min !== undefined ? `min="${esc(field.min)}"` : '',
      field.max !== null && field.max !== undefined ? `max="${esc(field.max)}"` : '',
    ].filter(Boolean).join(' ');
    control = `<input ${attrs}>`;

    return `
      <div class="config-field text-field">
        <div style="display:flex; justify-content:space-between; align-items:center; width:100%; margin-bottom:2px;">
          <span class="config-label">${esc(field.label)}</span>
          ${restartBadge}
        </div>
        ${control}
        <span class="config-meta"><code>${esc(field.name)}</code> · ${source}</span>
      </div>
    `;
  }
}

async function loadConfig() {
  const response = await fetch('/api/config', { cache: 'no-store' });
  if (!response.ok) throw new Error(`Config HTTP ${response.status}`);
  renderConfig(await response.json());
}

async function saveConfig() {
  const values = {};
  for (const input of document.querySelectorAll('#configForm [name]')) {
    values[input.name] = input.type === 'checkbox' ? input.checked : input.value;
  }

  const response = await fetch('/api/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ values }),
  });
  const data = await response.json();
  if (!response.ok || !data.ok) {
    const errors = data.errors || {};
    $('configStatus').textContent = `Erreur config: ${Object.entries(errors).map(([key, value]) => `${key}: ${value}`).join(' · ')}`;
    $('configStatus').className = 'config-status bad';
    if (data.fields) renderConfig(data);
    return;
  }

  renderConfig(data);
  $('configStatus').textContent = `Sauvé dans ${data.file}. Redémarrage requis pour appliquer les changements au bot.`;
  $('configStatus').className = 'config-status good';
}

function renderBotProcess(control) {
  const running = Boolean(control?.running);
  const dot = $('botStatusDot');
  if (dot) {
    dot.className = `status-dot ${running ? 'live' : 'off'}`;
  }
  setBadge($('botProcessBadge'), running ? 'bot ON' : 'bot OFF', running ? 'badge good' : 'badge bad');

  const toggleBtn = $('toggleBotButton');
  if (toggleBtn) {
    toggleBtn.className = `btn ${running ? 'btn-danger' : 'btn-success'}`;
    const btnText = toggleBtn.querySelector('.btn-text') || toggleBtn;
    btnText.textContent = running ? 'Arrêter' : 'Démarrer';

    const svgIcon = running
      ? `<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="btn-icon"><rect x="4" y="4" width="16" height="16" rx="2" ry="2"/></svg>`
      : `<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="btn-icon"><polygon points="5 3 19 12 5 21 5 3"/></svg>`;
    const iconContainer = toggleBtn.querySelector('.btn-icon-wrapper') || toggleBtn;
    if (iconContainer !== toggleBtn) {
      iconContainer.innerHTML = svgIcon;
    }
  }
}

async function restartBot() {
  const button = $('restartBotButton');
  button.disabled = true;
  button.textContent = 'Redémarrage...';
  $('configStatus').textContent = 'Redémarrage du bot en cours...';
  $('configStatus').className = 'config-status';

  try {
    const response = await fetch('/api/bot/restart', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
    renderBotProcess(data.status);
    $('configStatus').textContent = `Bot redémarré. PID actif: ${data.status?.processes?.map((item) => item.pid).join(', ') || data.pid || '--'}.`;
    $('configStatus').className = 'config-status good';
  } catch (error) {
    $('configStatus').textContent = `Erreur redémarrage bot: ${error.message}`;
    $('configStatus').className = 'config-status bad';
  } finally {
    button.disabled = false;
    button.textContent = 'Redémarrer bot';
    safeRefresh();
  }
}

function supportReasonLabel(reason) {
  const labels = {
    insufficient_trades: 'Pas assez de signaux',
    winrate_below_threshold: 'Win rate trop bas',
    total_pnl_below_threshold: 'Profit total trop faible',
    avg_pnl_below_threshold: 'Moyenne trop faible',
    no_backtest_result: 'Aucun backtest',
    not_evaluated: 'Non évalué',
    backtest_error: 'Erreur backtest',
  };
  return labels[reason] || reason.replaceAll('_', ' ');
}

function supportReasonTooltip(reason, item = {}, thresholds = {}) {
  const minTrades = item.threshold_trades ?? thresholds.min_trades ?? 10;
  const minWinrate = item.threshold_win_rate ?? thresholds.min_winrate ?? 50;
  const minTotalPnl = item.threshold_total_pnl ?? thresholds.min_total_pnl ?? 0;
  const minAvgPnl = item.threshold_avg_pnl ?? thresholds.min_avg_pnl ?? 0;

  const tips = {
    insufficient_trades: `Attendre plus de signaux backtest. Actuel: ${item.trades ?? 0}. Requis: ${minTrades}.`,
    winrate_below_threshold: `Le taux de réussite est trop faible. Actuel: ${percent(item.win_rate)}. Requis: ${percent(minWinrate)} ou plus.`,
    total_pnl_below_threshold: `Le profit total simulé est insuffisant. Actuel: ${percent(item.total_pnl_percent)}. Requis: ${percent(minTotalPnl)} ou plus.`,
    avg_pnl_below_threshold: `Le gain moyen par trade est insuffisant. Actuel: ${percent(item.avg_pnl_percent)}. Requis: ${percent(minAvgPnl)} ou plus.`,
    no_backtest_result: 'Aucun résultat backtest utilisable. Attendre le prochain backtest automatique ou relancer le bot.',
    not_evaluated: 'La paire n’a pas encore été évaluée par le filtre Support Touch.',
    backtest_error: 'Le backtest a échoué. Vérifier la connexion exchange et les logs.',
  };
  return tips[reason] || supportReasonLabel(reason);
}

function renderReasonChips(reason, item = {}, thresholds = {}) {
  const reasons = String(reason || '--')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);

  if (!reasons.length || reasons[0] === '--') {
    return '<span class="reason-chip neutral">--</span>';
  }

  return reasons.map((reasonKey) => `
    <span class="reason-chip tooltip" tabindex="0" title="${esc(supportReasonTooltip(reasonKey, item, thresholds))}" data-tip="${esc(supportReasonTooltip(reasonKey, item, thresholds))}">
      ${esc(supportReasonLabel(reasonKey))}
    </span>
  `).join('');
}

function decisionReasonTitle(reason) {
  const labels = {
    score_below_dynamic_threshold: 'Score marché insuffisant',
    technical_signal_below_threshold: 'Signal technique trop faible',
    bear_mode_pair_not_allowed: 'Paire bloquée en marché baissier',
    falling_knife_without_reversal: 'Chute sans retournement confirmé',
    support_touch_disabled_in_bear_mode: 'Support Touch désactivé en bear mode',
    insufficient_trades: 'Backtest insuffisant',
    total_pnl_below_threshold: 'Profit backtest trop faible',
    avg_pnl_below_threshold: 'Moyenne backtest trop faible',
    winrate_below_threshold: 'Win rate backtest trop faible',
    symbol_cooldown_active: 'Cooldown actif',
    position_or_capital_blocked: 'Position ou capital bloqué',
    htf_bias_rejected: 'Tendance haute période défavorable',
    outside_optimal_trading_time: 'Hors plage de trading',
    analysis_error: 'Erreur d’analyse',
    order_failed: 'Ordre échoué',
    buy_executed: 'Achat exécuté',
  };
  const key = String(reason || '').split(':')[0];
  return labels[key] || supportReasonLabel(key || '--');
}

function decisionExplanation(item) {
  const reason = String(item.reason || '');
  const key = reason.split(':')[0];
  const metrics = item.metrics || {};

  if (key === 'score_below_dynamic_threshold') {
    return `Le bot attend un meilleur score avant d’acheter. Score actuel ${number(metrics.score, 1)} / seuil ${number(metrics.min_score, 1)}.`;
  }
  if (key === 'technical_signal_below_threshold') {
    return `Le signal technique ne confirme pas assez l’achat. Confiance ${number(metrics.confidence, 1)}% / seuil ${number(metrics.min_confidence, 1)}%.`;
  }
  if (key === 'bear_mode_pair_not_allowed') {
    return `Marché en mode BEAR: cette paire n’est pas dans la liste autorisée pour acheter prudemment.`;
  }
  if (key === 'falling_knife_without_reversal') {
    return `Le prix tombe encore et le retournement n’est pas confirmé. Le bot évite d’attraper une chute.`;
  }
  if (key === 'support_touch_disabled_in_bear_mode') {
    return `Même si un support est touché, l’override Support Touch est coupé pendant ce régime de marché.`;
  }
  if (['insufficient_trades', 'total_pnl_below_threshold', 'avg_pnl_below_threshold', 'winrate_below_threshold'].includes(key)) {
    return `Le backtest Support Touch ne respecte pas tous les seuils de sécurité. Trades ${metrics.trades ?? '--'}, win rate ${percent(metrics.win_rate)}, total ${percent(metrics.total_pnl_percent)}.`;
  }
  if (key === 'symbol_cooldown_active') {
    return `Le bot attend avant de retrader cette paire. Temps restant: ${duration(metrics.cooldown_remaining_seconds)}.`;
  }
  if (key === 'position_or_capital_blocked') {
    return `Le bot évite d’ouvrir une nouvelle position: limite de positions, capital, ou exposition déjà atteinte.`;
  }
  if (key === 'htf_bias_rejected') {
    return `La tendance haute période ne soutient pas l’achat, donc le signal court terme est ignoré.`;
  }
  if (key === 'outside_optimal_trading_time') {
    return `Le bot est hors fenêtre horaire préférée pour ouvrir une nouvelle position.`;
  }
  if (key === 'order_failed') {
    return `L’ordre n’a pas été accepté ou exécuté. Vérifier minimum exchange, solde et permissions API.`;
  }
  if (item.allowed) {
    return `Décision autorisée par les filtres actifs.`;
  }
  return supportReasonLabel(key || reason || '--');
}

function decisionMetricChips(item) {
  const metrics = item.metrics || {};
  const chips = [];
  if (metrics.price !== undefined) chips.push(`Prix ${price(metrics.price)}`);
  if (metrics.score !== undefined || metrics.min_score !== undefined) chips.push(`Score ${number(metrics.score, 1)} / ${number(metrics.min_score, 1)}`);
  if (metrics.confidence !== undefined || metrics.min_confidence !== undefined) chips.push(`Confiance ${number(metrics.confidence, 1)}% / ${number(metrics.min_confidence, 1)}%`);
  if (metrics.mode || metrics.market_context?.mode) chips.push(`Régime ${metrics.mode || metrics.market_context?.mode}`);
  if (metrics.trades !== undefined) chips.push(`${metrics.trades} trades`);
  return chips.map((chip) => `<span>${esc(chip)}</span>`).join('');
}

function renderPositions(positions, liveSymbols) {
  const body = $('positionsBody');
  if (!positions.length) {
    body.innerHTML = '<tr><td colspan="8" class="empty">Aucune position ouverte</td></tr>';
    return;
  }

  body.innerHTML = positions.map((position) => {
    const symbol = position.symbol;
    const normKey = symbol.replace('/', '');
    const liveInfo = liveSymbols ? (liveSymbols[symbol] || liveSymbols[normKey]) : null;
    const currentPx = (liveInfo && liveInfo.price !== undefined && liveInfo.price !== null) ? Number(liveInfo.price) : null;

    let currentValText = '--';
    let pnlText = '--';
    let pnlClass = 'badge neutral';

    if (currentPx) {
      const currentValue = position.amount * currentPx;
      const pnlVal = currentValue - position.entry_value;
      const pnlPct = (pnlVal / position.entry_value) * 100;

      currentValText = `${number(currentValue, 2)} USD`;
      pnlText = `${pnlVal >= 0 ? '+' : ''}${number(pnlVal, 2)} (${pnlPct >= 0 ? '+' : ''}${number(pnlPct, 2)}%)`;
      pnlClass = badgeClass(pnlVal >= 0);
    }

    let slText = price(position.stop_loss_price);
    if (position.is_trailing) {
      slText += ` (${number(position.trailing_percent, 1)}%)`;
    }

    return `
      <tr>
        <td><strong>${esc(symbol)}</strong></td>
        <td>${qty(position.amount)}</td>
        <td>${price(position.avg_entry_price)}</td>
        <td>${price(position.avg_entry_price)} <span style="color: #94a3b8; margin: 0 4px;">➔</span> <strong style="color: #10b981;">${price(position.target_price)}</strong></td>
        <td><span style="font-weight: 600; color: #ef4444;">${esc(slText)}</span></td>
        <td>${number(position.entry_value, 2)} USD</td>
        <td>${currentValText}</td>
        <td>
          <span class="${pnlClass}">
            ${pnlText}
          </span>
        </td>
      </tr>
    `;
  }).join('');
}

function renderCooldowns(cooldowns) {
  const box = $('cooldownsList');
  if (!cooldowns.length) {
    box.innerHTML = '<p class="empty">Aucun cooldown actif</p>';
    return;
  }

  box.innerHTML = cooldowns.map((item) => `
    <div class="item">
      <strong>${esc(item.symbol)}</strong>
      <span class="badge warn">${seconds(item.remaining_seconds)}</span>
    </div>
  `).join('');
}

function renderSupportTouch(data) {
  const pairs = data.pairs || [];
  const thresholds = data.thresholds || {};
  const allowed = pairs.filter((item) => item.allowed).length;
  const supportSummaryEl = $('supportSummary');
  if (supportSummaryEl) {
    supportSummaryEl.textContent = `${allowed}/${pairs.length || 0}`;
  }
  $('supportLastRun').textContent = data.last_run ? `Dernier run ${dateWithRelative(data.last_run, false)}` : '';

  const grid = $('supportGrid');
  if (!pairs.length) {
    grid.innerHTML = '<p class="empty">Aucun résultat backtest</p>';
    return;
  }

  grid.innerHTML = pairs.map((item) => {
    const regimeText = item.regime && item.regime !== 'UNKNOWN' ? ` <span class="badge info" style="font-size: 9px; padding: 2px 6px; font-weight: 700; background: var(--info-bg); border: 1px solid var(--info-border); color: #bfdbfe; border-radius: 99px; margin-left: 6px;">${item.regime.replaceAll('_', ' ')}</span>` : '';
    return `
      <section class="support-card">
        <header style="align-items: center;">
          <h3 style="display: flex; align-items: center; flex-wrap: wrap;">${esc(item.symbol)}${regimeText}</h3>
          <span class="${badgeClass(item.allowed)}">${item.allowed ? 'OK' : 'Bloqué'}</span>
        </header>
        <div class="support-stats">
          <div><span>Trades</span><strong>${item.trades ?? 0}</strong></div>
          <div><span>Win rate</span><strong>${percent(item.win_rate)}</strong></div>
          <div><span>Total</span><strong>${signedPercent(item.total_pnl_percent, 2)}</strong></div>
          <div><span>Moyenne</span><strong>${signedPercent(item.avg_pnl_percent, 3)}</strong></div>
        </div>
        <div class="reason-list" aria-label="Raisons">${renderReasonChips(item.reason, item, thresholds)}</div>
      </section>
    `;
  }).join('');
}

function renderMarketContext(context) {
  const entries = Object.entries(context || {});
  const grid = $('marketContextGrid');
  if (!entries.length) {
    grid.innerHTML = '<p class="empty">Aucun contexte marché calculé pour le moment</p>';
    return;
  }

  grid.innerHTML = entries.map(([symbol, item]) => {
    const bear = Boolean(item.bear_mode);
    const falling = Boolean(item.falling_knife?.is_falling);
    const reversal = Boolean(item.reversal?.confirmed);
    const mode = item.mode || '--';
    const modeClass = regimeClass(mode);
    const multiplier = Number(item.trade_multiplier || 1);

    // Formater le texte du régime (remplacer underscores par des espaces)
    const rawRegime = item.symbol_regime || '--';
    const cleanRegime = rawRegime.replace(/_/g, ' ');

    // Classe de couleur pour le texte du régime
    let regimeColorClass = '';
    if (rawRegime.includes('BULL')) {
      regimeColorClass = 'regime-val-bull';
    } else if (rawRegime.includes('BEAR')) {
      regimeColorClass = 'regime-val-bear';
    } else if (rawRegime.includes('SIDE') || rawRegime.includes('RANGE')) {
      regimeColorClass = 'regime-val-side';
    }

    // Classes pour les badges de statut du bas
    const knifeClass = falling ? 'regime-flag-pill danger' : 'regime-flag-pill';
    const supportClass = item.support_touch_override_allowed ? 'regime-flag-pill success' : 'regime-flag-pill danger';
    const modePillClass = bear ? 'regime-flag-pill danger' : 'regime-flag-pill';

    return `
      <section class="support-card regime-card ${modeClass}">
        <header style="margin-bottom: 8px;">
          <div>
            <h3>${esc(symbol)}</h3>
            <span class="live-source">BTC ${esc(item.btc_regime || '--')}</span>
          </div>
          <span class="${badgeClass(!bear, bear)}">${esc(mode)}</span>
        </header>

        <div class="regime-hero">
          <div>
            <span>Régime symbole</span>
            <strong class="${regimeColorClass}">${esc(cleanRegime)}</strong>
          </div>
          <span class="regime-momentum ${Number(item.btc_momentum_percent) >= 0 ? 'up' : 'down'}">
            ${signedPercent(item.btc_momentum_percent, 2)}
          </span>
        </div>

        <div class="regime-metrics">
          <div class="regime-metric-box">
            <span>Protection</span>
            <strong style="color: ${multiplier < 1 ? 'var(--warn)' : 'var(--good)'}">
              ${multiplier < 1 ? `${number(multiplier, 2)}x` : '1,00x'}
            </strong>
          </div>
          <div class="regime-metric-box">
            <span>Retournement</span>
            <strong style="color: ${reversal ? 'var(--good)' : 'var(--text-muted)'}">
              ${reversal ? 'confirmé' : 'non'}
            </strong>
          </div>
        </div>

        <div class="regime-flags">
          <span class="${knifeClass}">Knife: ${falling ? 'oui' : 'non'}</span>
          <span class="${supportClass}">Support: ${item.support_touch_override_allowed ? 'OK' : 'Bloqué'}</span>
          ${bear ? `<span class="${modePillClass}">Bear Mode</span>` : ''}
        </div>

        <div class="regime-footer">
          <span>Mise à jour ${item.last_update ? relativeTime(item.last_update) : '--'}</span>
        </div>
      </section>
    `;
  }).join('');
}

function renderLive(data) {
  const symbols = data?.symbols || {};
  const entries = Object.entries(symbols).filter(([key]) => !key.endsWith('_logged'));
  const connected = Boolean(data?.connected);
  const totalTicks = entries.reduce((sum, [, item]) => sum + Number(item.tick_count || 0), 0);
  const queueSize = Number(data?.queue_size || 0);
  const wsBadge = $('wsBadge');
  if (wsBadge) {
    wsBadge.className = connected ? 'badge good' : 'badge warn';
    $('wsSummaryText').textContent = connected ? 'WS OK' : 'WS REST';
  }
  if (data?.timestamp) {
    if (connected) {
      $('wsLastUpdate').innerHTML = `<span class="live-indicator-pulse"></span> Temps réel`;
    } else {
      $('wsLastUpdate').innerHTML = `<span style="display:inline-block;width:8px;height:8px;background:var(--warn);border-radius:50%;margin-right:6px;vertical-align:middle;"></span> Mode REST (il y a ${relativeTime(data.timestamp).replace('il y a ', '')})`;
    }
  } else {
    $('wsLastUpdate').textContent = 'Aucune télémétrie live';
  }
  $('wsMeta').innerHTML = `
    <span class="${badgeClass(connected)}">${connected ? 'WebSocket connecté' : 'Fallback REST'}</span>
    <span class="${badgeClass(Boolean(data?.ws_thread_alive))}">WS thread ${data?.ws_thread_alive ? 'OK' : 'OFF'}</span>
    <span class="${badgeClass(Boolean(data?.worker_alive))}">Worker ${data?.worker_alive ? 'OK' : 'OFF'}</span>
    <span class="${badgeClass(queueSize < Number(data?.queue_maxsize || 100), queueSize > 20)}">Queue ${queueSize}/${data?.queue_maxsize ?? '--'}</span>
    <span class="badge neutral">Ticks ${totalTicks}</span>
    <span class="badge neutral">Reconnect ${data?.reconnect_attempts ?? 0}</span>
  `;

  const grid = $('wsGrid');
  if (!entries.length) {
    grid.innerHTML = '<p class="empty">Aucun tick WebSocket enregistré. Redémarre le bot pour activer live_status.json.</p>';
    return;
  }
  // Vérifier si toutes les cartes existent déjà pour faire une mise à jour en place
  const allCardsExist = entries.every(([symbol]) => document.getElementById(`liveCard-${symbol}`));

  if (!allCardsExist) {
    grid.innerHTML = entries.map(([symbol, item]) => {
      const tickAge = item.last_tick_age_seconds;
      const stale = tickAge === null || tickAge === undefined || tickAge > 30;
      const spreadText = item.spread_percent === null || item.spread_percent === undefined
        ? '--'
        : signedPercent(item.spread_percent, 2);
      const deltaText = signedPercent(item.price_change_since_analysis_percent, 2);
      const deltaValue = Number(item.price_change_since_analysis_percent);
      const deltaClass = Number.isFinite(deltaValue) && deltaValue >= 0 ? 'up' : 'down';
      const formattedSymbol = symbol.endsWith('USD') ? symbol.slice(0, -3) + '/USD' : symbol;
      return `
        <section id="liveCard-${symbol}" class="support-card live-card" style="position: relative;">
          <header style="display: flex; justify-content: space-between; align-items: center;">
            <div style="display: flex; align-items: center; gap: 8px;">
              <h3>${esc(formattedSymbol)}</h3>
              <span class="badge-status ${badgeClass(!stale, !connected)}">${stale ? 'stale' : 'live'}</span>
            </div>
            
            <div class="card-more-menu-container" style="position: relative;">
              <button class="btn-card-more" onclick="toggleCardMenu(event, '${symbol}')" style="background: none; border: none; padding: 4px; color: var(--text-muted); cursor: pointer; display: flex; align-items: center; border-radius: 4px; transition: background 0.2s;">
                <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="color: #10b981; filter: drop-shadow(0 0 2px rgba(16,185,129,0.3));">
                  <circle cx="12" cy="12" r="1.5"/>
                  <circle cx="12" cy="5" r="1.5"/>
                  <circle cx="12" cy="19" r="1.5"/>
                </svg>
              </button>
            <div id="cardMenu-${symbol}" class="card-dropdown-menu">
              <button class="action-buy" onclick="triggerCardAction(event, 'force_buy', '${formattedSymbol}')">
                <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 6px;"><line x1="7" y1="17" x2="17" y2="7"/><polyline points="7 7 17 7 17 17"/></svg>
                Force BUY
              </button>
              <button class="action-sell" onclick="triggerCardAction(event, 'force_sell', '${formattedSymbol}')">
                <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 6px;"><line x1="7" y1="7" x2="17" y2="17"/><polyline points="17 7 17 17 7 17"/></svg>
                Force SELL
              </button>
              <div class="menu-divider"></div>
              <div class="menu-section-header">Pause</div>
              <button class="action-pause" onclick="triggerCardAction(event, 'pause_pair', '${formattedSymbol}', 900)">
                <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 6px;"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                15 min
              </button>
              <button class="action-pause" onclick="triggerCardAction(event, 'pause_pair', '${formattedSymbol}', 3600)">
                <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 6px;"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                1 heure
              </button>
              <button class="action-pause" onclick="triggerCardAction(event, 'pause_pair', '${formattedSymbol}', 14400)">
                <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 6px;"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                4 heures
              </button>
              <button class="action-pause" onclick="triggerCardAction(event, 'pause_pair', '${formattedSymbol}', 86400)">
                <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 6px;"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                24 heures
              </button>
            </div>
          </div>
          </header>
          
          <div class="live-quote">
            <div>
              <span>Dernier prix</span>
              <strong class="val-price">${price(item.price)}</strong>
            </div>
            <span class="live-delta val-delta ${deltaClass}">${deltaText}</span>
          </div>

          <div class="quote-row">
            <div><span>Bid</span><strong class="val-bid">${price(item.bid)}</strong></div>
            <div><span>Ask</span><strong class="val-ask">${price(item.ask)}</strong></div>
          </div>

          <div class="live-statbar">
            <span class="val-analysis">Analyse ${item.last_analysis_age_seconds === null || item.last_analysis_age_seconds === undefined ? '--' : duration(Math.round(item.last_analysis_age_seconds))}</span>
            <span class="val-spread">Spread ${spreadText}</span>
            <span class="val-ticks">${item.tick_count ?? 0} ticks</span>
          </div>
        </section>
      `;
    }).join('');
  } else {
    // Mettre à jour les valeurs textuelles en place sans toucher au DOM structurel
    entries.forEach(([symbol, item]) => {
      const card = document.getElementById(`liveCard-${symbol}`);
      if (!card) return;

      const tickAge = item.last_tick_age_seconds;
      const stale = tickAge === null || tickAge === undefined || tickAge > 30;
      const spreadText = item.spread_percent === null || item.spread_percent === undefined
        ? '--'
        : signedPercent(item.spread_percent, 2);
      const deltaText = signedPercent(item.price_change_since_analysis_percent, 2);
      const deltaValue = Number(item.price_change_since_analysis_percent);
      const deltaClass = Number.isFinite(deltaValue) && deltaValue >= 0 ? 'up' : 'down';

      // Status badge
      const badge = card.querySelector('.badge-status');
      if (badge) {
        badge.className = `badge-status ${badgeClass(!stale, !connected)}`;
        badge.textContent = stale ? 'stale' : 'live';
      }

      // Price
      const priceEl = card.querySelector('.val-price');
      if (priceEl) priceEl.textContent = price(item.price);

      // Delta
      const deltaEl = card.querySelector('.val-delta');
      if (deltaEl) {
        deltaEl.className = `live-delta val-delta ${deltaClass}`;
        deltaEl.textContent = deltaText;
      }

      // Bid
      const bidEl = card.querySelector('.val-bid');
      if (bidEl) bidEl.textContent = price(item.bid);

      // Ask
      const askEl = card.querySelector('.val-ask');
      if (askEl) askEl.textContent = price(item.ask);

      // Analysis age
      const analysisEl = card.querySelector('.val-analysis');
      if (analysisEl) {
        analysisEl.textContent = `Analyse ${item.last_analysis_age_seconds === null || item.last_analysis_age_seconds === undefined ? '--' : duration(Math.round(item.last_analysis_age_seconds))}`;
      }

      // Spread
      const spreadEl = card.querySelector('.val-spread');
      if (spreadEl) {
        spreadEl.textContent = `Spread ${spreadText}`;
      }

      // Ticks
      const ticksEl = card.querySelector('.val-ticks');
      if (ticksEl) {
        ticksEl.textContent = `${item.tick_count ?? 0} ticks`;
      }
    });
  }
}

function renderDecisions(decisions, totalCount) {
  const box = $('decisionsList');
  if (!decisions.length) {
    box.innerHTML = '<p class="empty">Aucune décision récente</p>';
    return;
  }

  const actualTotal = Math.max(totalCount || 0, decisions.length);
  const visible = decisions.slice().reverse();

  box.innerHTML = visible.map((item) => `
    <div class="event">
      <div class="event-top">
        <strong>${esc(item.symbol || '--')} · ${esc(decisionReasonTitle(item.reason))}</strong>
        <span class="${badgeClass(item.allowed, item.allowed === null || item.allowed === undefined)}">
          ${item.allowed ? 'autorisé' : 'bloqué'}
        </span>
      </div>
      <p>${esc(decisionExplanation(item))}</p>
      <div class="decision-meta">${decisionMetricChips(item)}</div>
      <p class="event-time">${esc(item.action || '--')} · ${esc(dateWithRelative(item.timestamp, false))}</p>
    </div>
  `).join('') + (
      actualTotal > visible.length
        ? `<p class="timeline-more">+${actualTotal - visible.length} décision(s) plus ancienne(s) masquée(s)</p>`
        : ''
    );
}

function renderLogs(logs) {
  const box = $('logsList');
  if (!logs.length) {
    box.innerHTML = '<p class="empty">Aucune alerte récente</p>';
    return;
  }

  box.innerHTML = logs.slice().reverse().map((line) => {
    const parsed = parseLogLine(line);
    const label = parsed.date ? dateWithRelative(parsed.date, true) : 'Date inconnue';
    const level = parsed.level ? `${parsed.level} · ` : '';
    return `
      <div class="log-entry">
        <span class="log-time">${esc(level)}${esc(label)}</span>
        <div class="log-message">${esc(parsed.message)}</div>
      </div>
    `;
  }).join('');
}

async function refresh() {
  const response = await fetch('/api/status', { cache: 'no-store' });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const data = await response.json();

  $('botName').textContent = data.bot.name || 'Aegis';
  $('lastUpdate').textContent = data.bot.last_update
    ? `Dernière synchronisation · ${dateWithRelative(data.bot.last_update, false)}`
    : 'Synchronisation en cours...';

  setBadge($('modeBadge'), data.bot.mode, data.bot.mode === 'paper' ? 'badge good' : 'badge bad');
  setBadge($('exchangeBadge'), data.bot.exchange, 'badge neutral');
  renderBotProcess(data.bot.control);

  const balance = data.balance.paper_balance;
  $('paperBalance').textContent = balance === null || balance === undefined
    ? '--'
    : `${number(balance, 2)} USD`;

  // Trade stats
  const stats = data.stats || {};
  const pnl = Number(stats.total_pnl);
  $('totalPnl').textContent = Number.isFinite(pnl) ? `${pnl >= 0 ? '+' : ''}${number(pnl, 4)} USD` : '--';
  $('totalPnl').style.color = pnl > 0 ? 'var(--good)' : pnl < 0 ? 'var(--bad)' : '';
  const pnlCard = $('totalPnl').closest('.metric-card');
  if (pnlCard) {
    pnlCard.className = `metric-card ${pnl > 0 ? 'color-good' : pnl < 0 ? 'color-bad' : 'color-accent'}`;
  }

  $('totalTrades').textContent = stats.total_trades != null ? `${stats.total_trades} (${stats.wins}W / ${stats.losses}L)` : '--';
  $('winRate').textContent = stats.win_rate ? `${stats.win_rate}%` : '--';
  $('winRate').style.color = stats.win_rate >= 50 ? 'var(--good)' : stats.win_rate > 0 ? 'var(--bad)' : '';
  const winRateCard = $('winRate').closest('.metric-card');
  if (winRateCard) {
    winRateCard.className = `metric-card ${stats.win_rate >= 50 ? 'color-good' : stats.win_rate > 0 ? 'color-bad' : 'color-accent'}`;
  }

  // Growth per trade = avg PnL / initial capital per trade
  const growthPct = stats.total_trades ? (stats.total_pnl / stats.total_trades) / (Number(data.balance.paper_balance) || 100) * 100 : null;
  $('growthPerTrade').textContent = growthPct !== null ? `${growthPct >= 0 ? '+' : ''}${number(growthPct, 3)}%` : '--';
  $('growthPerTrade').style.color = growthPct > 0 ? 'var(--good)' : growthPct < 0 ? 'var(--bad)' : '';

  // Growth per day = total PnL% / days active
  const days = Number(stats.days_active) || 0;
  const totalPnlPct = (Number(data.balance.paper_balance) || 100) > 0 ? pnl / (Number(data.balance.paper_balance) || 100) * 100 : 0;
  const dailyGrowth = days > 0.01 ? totalPnlPct / days : null;
  $('growthPerDay').textContent = dailyGrowth !== null ? `${dailyGrowth >= 0 ? '+' : ''}${number(dailyGrowth, 3)}%` : '--';
  $('growthPerDay').style.color = dailyGrowth > 0 ? 'var(--good)' : dailyGrowth < 0 ? 'var(--bad)' : '';

  // Yield relative to average stake size
  const avgStake = Number(stats.avg_stake) || 5;
  const growthMisePct = avgStake > 0 ? (pnl / avgStake) * 100 : 0;
  $('growthPerStake').textContent = stats.total_trades ? `${growthMisePct >= 0 ? '+' : ''}${number(growthMisePct, 2)}%` : '--';
  $('growthPerStake').style.color = growthMisePct > 0 ? 'var(--good)' : growthMisePct < 0 ? 'var(--bad)' : '';
  const growthStakeCard = $('growthPerStake').closest('.metric-card');
  if (growthStakeCard) {
    growthStakeCard.className = `metric-card ${growthMisePct > 0 ? 'color-good' : growthMisePct < 0 ? 'color-bad' : 'color-accent'}`;
  }

  const posCountEl = $('positionCount');
  if (posCountEl) posCountEl.textContent = data.positions.length;

  const coolCountEl = $('cooldownCount');
  if (coolCountEl) coolCountEl.textContent = data.cooldowns.length;

  renderLive(data.live);
  renderPositions(data.positions, data.live?.symbols);
  renderCooldowns(data.cooldowns);
  renderSupportTouch(data.support_touch);
  renderMarketContext(data.market_context);
  let decisionsData = data.decisions;
  let totalDecisions = data.total_decisions || decisionsData.length;

  if (state.decisionsLimit !== 20) {
    try {
      const decResponse = await fetch(`/api/decisions?limit=${state.decisionsLimit}`, { cache: 'no-store' });
      if (decResponse.ok) {
        const decJson = await decResponse.json();
        decisionsData = decJson.decisions;
        totalDecisions = decJson.total_count;
      }
    } catch (e) {
      // Silencieux
    }
  }

  renderDecisions(decisionsData, totalDecisions);
  renderLogs(data.logs);
}

// ===== NOUVEAU: Fonctions Analytics =====

function renderAdvancedMetrics(metrics) {
  if (!metrics || !metrics.total_trades) {
    $('sharpeRatio').textContent = '--';
    $('profitFactor').textContent = '--';
    $('maxDrawdown').textContent = '--';
    $('kellyPercent').textContent = '--';
    $('expectancy').textContent = '--';
    $('avgWin').textContent = '--';
    $('avgLoss').textContent = '--';
    return;
  }

  const sharpe = Number(metrics.sharpe_ratio);
  $('sharpeRatio').textContent = number(sharpe, 2);
  $('sharpeRatio').style.color = sharpe >= 1.5 ? 'var(--good)' : sharpe >= 0.5 ? 'var(--warn)' : 'var(--bad)';
  const sharpeCard = $('sharpeRatio').closest('.metric-card');
  if (sharpeCard) {
    sharpeCard.className = `metric-card ${sharpe >= 1.5 ? 'color-good' : sharpe >= 0.5 ? 'color-warn' : 'color-bad'}`;
  }

  const pf = Number(metrics.profit_factor);
  $('profitFactor').textContent = pf === 999.99 ? '\u221e' : number(pf, 2);
  $('profitFactor').style.color = pf >= 2 ? 'var(--good)' : pf >= 1 ? 'var(--warn)' : 'var(--bad)';
  const pfCard = $('profitFactor').closest('.metric-card');
  if (pfCard) {
    pfCard.className = `metric-card ${pf >= 2 ? 'color-good' : pf >= 1 ? 'color-warn' : 'color-bad'}`;
  }

  $('maxDrawdown').textContent = `${number(metrics.max_drawdown, 2)} USD`;
  $('maxDrawdown').style.color = 'var(--bad)';
  const ddCard = $('maxDrawdown').closest('.metric-card');
  if (ddCard) {
    ddCard.className = `metric-card ${metrics.max_drawdown > 0 ? 'color-bad' : 'color-accent'}`;
  }

  $('kellyPercent').textContent = `${number(metrics.kelly_percent, 1)}%`;
  $('kellyPercent').style.color = metrics.kelly_percent >= 10 ? 'var(--good)' : 'var(--warn)';
  const kellyCard = $('kellyPercent').closest('.metric-card');
  if (kellyCard) {
    kellyCard.className = `metric-card ${metrics.kelly_percent >= 10 ? 'color-good' : 'color-warn'}`;
  }

  $('expectancy').textContent = `${metrics.expectancy >= 0 ? '+' : ''}${number(metrics.expectancy, 4)} USD`;
  $('expectancy').style.color = metrics.expectancy > 0 ? 'var(--good)' : metrics.expectancy < 0 ? 'var(--bad)' : '';
  const expCard = $('expectancy').closest('.metric-card');
  if (expCard) {
    expCard.className = `metric-card ${metrics.expectancy > 0 ? 'color-good' : metrics.expectancy < 0 ? 'color-bad' : 'color-accent'}`;
  }

  $('avgWin').textContent = `+${number(metrics.avg_win, 4)} USD`;
  $('avgWin').style.color = 'var(--good)';

  $('avgLoss').textContent = `${number(metrics.avg_loss, 4)} USD`;
  $('avgLoss').style.color = 'var(--bad)';
}

function renderCapitalBreakdown(capital) {
  const box = $('capitalBreakdown');
  if (!capital || !capital.total_capital) {
    box.innerHTML = '<p class="empty">Aucune donnée capital</p>';
    return;
  }

  // Calculate percentages based on actual components
  const total = capital.total_capital;
  const pctPositions = total > 0 ? (capital.in_positions / total) * 100 : 0;
  const pctLimit = total > 0 ? (capital.in_limit_orders / total) * 100 : 0;
  const pctAvailable = total > 0 ? (capital.available / total) * 100 : 0;

  // Modern animated glow progress bar
  const barHtml = `
    <div style="margin-bottom:24px;">
      <div style="display:flex;height:12px;border-radius:99px;overflow:hidden;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.08);box-shadow:inset 0 1px 3px rgba(0,0,0,0.5);">
        <div style="width:${pctAvailable}%;background:linear-gradient(90deg,#10b981,#059669);transition:width 0.3s ease;box-shadow:0 0 8px rgba(16,185,129,0.35);" title="Disponible"></div>
        <div style="width:${pctPositions}%;background:linear-gradient(90deg,#6366f1,#4f46e5);transition:width 0.3s ease;box-shadow:0 0 8px rgba(99,102,241,0.35);" title="En Positions"></div>
        <div style="width:${pctLimit}%;background:linear-gradient(90deg,#f59e0b,#d97706);transition:width 0.3s ease;box-shadow:0 0 8px rgba(245,158,11,0.35);" title="Ordres Limites"></div>
      </div>
      
      <div style="display:flex;justify-content:space-between;font-size:11px;margin-top:8px;color:var(--text-secondary);">
        <div style="display:flex;gap:16px;flex-wrap:wrap;">
          <span style="display:flex;align-items:center;gap:6px;">
            <span style="width:8px;height:8px;border-radius:50%;background:#10b981;display:inline-block;"></span>
            Disponible (${number(pctAvailable, 1)}%)
          </span>
          <span style="display:flex;align-items:center;gap:6px;">
            <span style="width:8px;height:8px;border-radius:50%;background:#6366f1;display:inline-block;"></span>
            En Positions (${number(pctPositions, 1)}%)
          </span>
          ${pctLimit > 0.1 ? `
            <span style="display:flex;align-items:center;gap:6px;">
              <span style="width:8px;height:8px;border-radius:50%;background:#f59e0b;display:inline-block;"></span>
              Ordres Limites (${number(pctLimit, 1)}%)
            </span>
          ` : ''}
        </div>
        <span style="font-weight:600;color:var(--text-muted);">Allocations</span>
      </div>
    </div>
  `;

  // Grid of styled premium cards
  const detailHtml = `
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px;">
      <div class="cap-card" style="padding:14px 16px;background:rgba(0,0,0,0.15);border-radius:var(--radius);border:1px solid rgba(255,255,255,0.04);transition:var(--transition);">
        <span style="display:block;color:var(--text-muted);font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">Capital Total</span>
        <strong style="font-family:'Outfit',sans-serif;font-size:20px;font-weight:700;color:var(--text);">${number(capital.total_capital, 2)} <span style="font-size:12px;color:var(--text-muted);">USD</span></strong>
      </div>
      <div class="cap-card" style="padding:14px 16px;background:rgba(0,0,0,0.15);border-radius:var(--radius);border:1px solid rgba(255,255,255,0.04);transition:var(--transition);">
        <span style="display:block;color:var(--text-muted);font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">Disponible</span>
        <strong style="font-family:'Outfit',sans-serif;font-size:20px;font-weight:700;color:#10b981;">${number(capital.available, 2)} <span style="font-size:12px;color:rgba(16,185,129,0.7);">USD</span></strong>
      </div>
      <div class="cap-card" style="padding:14px 16px;background:rgba(0,0,0,0.15);border-radius:var(--radius);border:1px solid rgba(255,255,255,0.04);transition:var(--transition);">
        <span style="display:block;color:var(--text-muted);font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">En Positions</span>
        <strong style="font-family:'Outfit',sans-serif;font-size:20px;font-weight:700;color:#6366f1;">${number(capital.in_positions, 2)} <span style="font-size:12px;color:rgba(99,102,241,0.7);">USD</span></strong>
      </div>
      <div class="cap-card" style="padding:14px 16px;background:rgba(0,0,0,0.15);border-radius:var(--radius);border:1px solid rgba(255,255,255,0.04);transition:var(--transition);">
        <span style="display:block;color:var(--text-muted);font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">Ordres Limites</span>
        <strong style="font-family:'Outfit',sans-serif;font-size:20px;font-weight:700;color:#f59e0b;">${number(capital.in_limit_orders, 2)} <span style="font-size:12px;color:rgba(245,158,11,0.7);">USD</span></strong>
      </div>
    </div>
  `;

  let positionsHtml = '';
  if (capital.positions_detail && capital.positions_detail.length) {
    positionsHtml = `
      <div style="margin-top:16px;border-top:1px solid rgba(255,255,255,0.05);padding-top:16px;">
        <span style="display:block;font-size:11px;font-weight:700;text-transform:uppercase;color:var(--text-muted);letter-spacing:0.5px;margin-bottom:12px;">Répartition par actif</span>
        <table style="width:100%;border-collapse:collapse;">
          <thead>
            <tr>
              <th style="padding:8px 0;text-align:left;color:var(--text-muted);font-size:10px;font-weight:700;text-transform:uppercase;border-bottom:1px solid rgba(255,255,255,0.05);">Actif</th>
              <th style="padding:8px 0;text-align:right;color:var(--text-muted);font-size:10px;font-weight:700;text-transform:uppercase;border-bottom:1px solid rgba(255,255,255,0.05);">Valeur</th>
              <th style="padding:8px 0;text-align:right;color:var(--text-muted);font-size:10px;font-weight:700;text-transform:uppercase;border-bottom:1px solid rgba(255,255,255,0.05);">% Allocation</th>
            </tr>
          </thead>
          <tbody>
            ${capital.positions_detail.map(p => `
              <tr>
                <td style="padding:10px 0;border-bottom:1px solid rgba(255,255,255,0.03);font-size:12px;"><strong style="color:var(--text);">${esc(p.symbol)}</strong></td>
                <td style="padding:10px 0;border-bottom:1px solid rgba(255,255,255,0.03);font-size:12px;text-align:right;font-weight:600;color:var(--text-secondary);">${number(p.value, 2)} USD</td>
                <td style="padding:10px 0;border-bottom:1px solid rgba(255,255,255,0.03);font-size:12px;text-align:right;font-weight:700;color:var(--info);">${number(p.percent, 1)}%</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
  }

  box.innerHTML = barHtml + detailHtml + positionsHtml;
}

function renderPnlHistory(pnlData) {
  const summary = $('pnlSummary');

  if (!pnlData || !pnlData.history || pnlData.history.length < 2) {
    $('pnlChart').innerHTML = '<p class="empty">Pas assez de trades pour afficher l\'historique</p>';
    return;
  }

  if (!$('pnlCanvas')) {
    $('pnlChart').innerHTML = '<canvas id="pnlCanvas"></canvas>';
  }

  summary.textContent = `${number(pnlData.initial_balance, 2)} USD → ${number(pnlData.current_balance, 2)} USD (${pnlData.total_pnl >= 0 ? '+' : ''}${number(pnlData.total_pnl, 2)} USD)`;

  const history = pnlData.history;
  const labels = history.map((h, i) => {
    if (i === 0) return 'Start';
    if (!h.time) return `#${i}`;
    const date = parseDate(h.time);
    return date ? date.toLocaleDateString('fr-CA', { month: '2-digit', day: '2-digit' }) + ' ' + date.toLocaleTimeString('fr-CA', { hour: '2-digit', minute: '2-digit' }) : `#${i}`;
  });
  const dataPoints = history.map(h => h.pnl);

  const ctx = $('pnlCanvas').getContext('2d');

  if (pnlChartInstance && $('pnlCanvas')) {
    const isProfitable = pnlData.total_pnl >= 0;
    pnlChartInstance.data.labels = labels;
    pnlChartInstance.data.datasets[0].data = dataPoints;
    pnlChartInstance.data.datasets[0].borderColor = isProfitable ? '#34d399' : '#fb7185';
    pnlChartInstance.data.datasets[0].backgroundColor = isProfitable ? 'rgba(52, 211, 153, 0.08)' : 'rgba(251, 113, 133, 0.08)';
    pnlChartInstance.data.datasets[0].pointBackgroundColor = isProfitable ? '#34d399' : '#fb7185';
    pnlChartInstance.data.datasets[0].pointRadius = history.length < 30 ? 4 : 1;

    pnlChartInstance.options.plugins.tooltip.callbacks.title = function (context) {
      const idx = context[0].dataIndex;
      const h = history[idx];
      if (h.time === 'start') return 'Solde Initial';
      return h.event || 'Trade';
    };
    pnlChartInstance.options.plugins.tooltip.callbacks.label = function (context) {
      const idx = context.dataIndex;
      const h = history[idx];
      return [
        `P&L: ${h.pnl >= 0 ? '+' : ''}${number(h.pnl, 2)} USD`,
        `Solde: ${number(h.balance, 2)} USD`
      ];
    };

    pnlChartInstance.update();
    return;
  }

  pnlChartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'P&L Cumulé (USD)',
          data: dataPoints,
          borderColor: pnlData.total_pnl >= 0 ? '#34d399' : '#fb7185',
          backgroundColor: pnlData.total_pnl >= 0 ? 'rgba(52, 211, 153, 0.08)' : 'rgba(251, 113, 133, 0.08)',
          borderWidth: 2.5,
          tension: 0.35,
          fill: true,
          pointRadius: history.length < 30 ? 4 : 1,
          pointHoverRadius: 6,
          pointBackgroundColor: pnlData.total_pnl >= 0 ? '#34d399' : '#fb7185',
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: false
        },
        tooltip: {
          backgroundColor: '#111418',
          titleColor: '#e8edf2',
          bodyColor: '#e8edf2',
          borderColor: '#262c33',
          borderWidth: 1,
          callbacks: {
            title: function (context) {
              const idx = context[0].dataIndex;
              const h = history[idx];
              if (h.time === 'start') return 'Solde Initial';
              return h.event || 'Trade';
            },
            label: function (context) {
              const idx = context.dataIndex;
              const h = history[idx];
              return [
                `P&L: ${h.pnl >= 0 ? '+' : ''}${number(h.pnl, 2)} USD`,
                `Solde: ${number(h.balance, 2)} USD`
              ];
            }
          }
        }
      },
      scales: {
        x: {
          grid: {
            color: 'rgba(38, 44, 51, 0.3)',
          },
          ticks: {
            color: '#8a9aa8',
            font: {
              size: 9
            },
            maxTicksLimit: 10
          }
        },
        y: {
          grid: {
            color: 'rgba(38, 44, 51, 0.3)',
          },
          ticks: {
            color: '#8a9aa8',
            font: {
              size: 9
            }
          }
        }
      }
    }
  });
}

function renderHeatmapCrypto(data) {
  const box = $('heatmapCrypto');
  if (!data || !data.length) {
    box.innerHTML = '<p class="empty">Aucun trade</p>';
    return;
  }

  box.innerHTML = data.map(c => {
    const pnlColor = c.total_pnl >= 0 ? 'var(--good)' : 'var(--bad)';
    return `
      <div class="item">
        <strong>${esc(c.symbol)}</strong>
        <div style="text-align:right;">
          <div style="color:${pnlColor};font-size:13px;font-weight:800;">${c.total_pnl >= 0 ? '+' : ''}${number(c.total_pnl, 4)} USD</div>
          <div style="font-size:11px;color:var(--muted);">${c.trades} trades (${c.win_rate}%)</div>
        </div>
      </div>
    `;
  }).join('');
}

function renderHeatmapByDay(data) {
  const box = $('heatmapDay');
  if (!data || !data.length) {
    box.innerHTML = '<p class="empty">--</p>';
    return;
  }

  const dayNames = { 'Monday': 'Lun', 'Tuesday': 'Mar', 'Wednesday': 'Mer', 'Thursday': 'Jeu', 'Friday': 'Ven', 'Saturday': 'Sam', 'Sunday': 'Dim' };

  box.innerHTML = data.map(d => {
    const pnlColor = d.total_pnl >= 0 ? 'var(--good)' : 'var(--bad)';
    return `
      <div class="item">
        <strong>${dayNames[d.day] || d.day}</strong>
        <div style="text-align:right;">
          <div style="color:${pnlColor};font-size:12px;font-weight:800;">${d.total_pnl >= 0 ? '+' : ''}${number(d.total_pnl, 4)}</div>
          <div style="font-size:10px;color:var(--muted);">${d.trades} (${d.win_rate}%)</div>
        </div>
      </div>
    `;
  }).join('');
}

function renderHeatmapByHour(data) {
  const box = $('heatmapHour');
  if (!data || !data.length) {
    box.innerHTML = '<p class="empty">--</p>';
    return;
  }

  box.innerHTML = data.map(h => {
    const pnlColor = h.total_pnl >= 0 ? 'var(--good)' : 'var(--bad)';
    return `
      <div class="item">
        <strong>${String(h.hour).padStart(2, '0')}h</strong>
        <div style="text-align:right;">
          <div style="color:${pnlColor};font-size:12px;font-weight:800;">${h.total_pnl >= 0 ? '+' : ''}${number(h.total_pnl, 4)}</div>
          <div style="font-size:10px;color:var(--muted);">${h.trades} (${h.win_rate}%)</div>
        </div>
      </div>
    `;
  }).join('');
}

// ===== Fonctions Trades =====

function renderTrades(trades) {
  const body = $('tradesBody');
  const summary = $('tradesSummary');

  if (!trades || !trades.length) {
    body.innerHTML = '<tr><td colspan="7" class="empty">Aucun trade</td></tr>';
    summary.textContent = '0 trades';
    return;
  }

  const totalPnl = trades.reduce((sum, t) => sum + t.pnl, 0);
  const wins = trades.filter(t => t.profitable).length;
  const losses = trades.length - wins;

  summary.textContent = `${trades.length} trades | ${wins}W / ${losses}L | P&L total: ${totalPnl >= 0 ? '+' : ''}${number(totalPnl, 4)} USD`;

  body.innerHTML = trades.map(t => {
    const buyVal = t.amount * t.buy_price;
    const sellVal = t.amount * t.sell_price;
    const pnlClass = t.profitable ? 'badge good' : 'badge bad';

    return `
      <tr>
        <td style="font-size: 11px; color: var(--text-muted); font-weight: 500;">
          ${t.sell_time ? formatFriendlyDate(t.sell_time, false) : '--'}
        </td>
        <td><strong>${esc(t.symbol)}</strong></td>
        <td>
          <div style="font-weight: 600;">${price(t.buy_price)} USD</div>
          <div style="font-size: 10px; color: var(--text-muted);">${number(buyVal, 2)} USD</div>
        </td>
        <td>
          <div style="font-weight: 600;">${price(t.sell_price)} USD</div>
          <div style="font-size: 10px; color: var(--text-muted);">${number(sellVal, 2)} USD</div>
        </td>
        <td>${number(t.amount, 6)}</td>
        <td style="color: ${t.profitable ? 'var(--good)' : 'var(--bad)'}; font-weight: 800;">
          ${t.pnl >= 0 ? '+' : ''}${number(t.pnl, 2)} USD
        </td>
        <td>
          <span class="${pnlClass}">
            ${t.pnl_pct >= 0 ? '+' : ''}${number(t.pnl_pct, 2)}%
          </span>
        </td>
      </tr>
    `;
  }).join('');
}

async function refreshAnalytics() {
  try {
    const response = await fetch('/api/analytics', { cache: 'no-store' });
    if (!response.ok) return;
    const data = await response.json();

    renderAdvancedMetrics(data.advanced_metrics);
    renderCapitalBreakdown(data.capital_breakdown);
    renderPnlHistory(data.pnl_history);
    renderHeatmapCrypto(data.heatmap.by_crypto);
    renderHeatmapByDay(data.heatmap.by_day);
    renderHeatmapByHour(data.heatmap.by_hour);
    await refreshScoreChart();
  } catch (e) {
    // Silencieux
  }
}

async function refreshScoreChart() {
  const chartContainer = $('scoreChart');
  if (!chartContainer) return;

  const symbol = $('scoreChartSymbol')?.value || 'BTC/USD';
  const hours = $('scoreChartHours')?.value || '24';

  try {
    const url = `/api/analytics/scores?symbol=${encodeURIComponent(symbol)}&hours=${hours}`;
    const response = await fetch(url, { cache: 'no-store' });
    if (!response.ok) return;
    const scores = await response.json();

    if (!scores || scores.length < 2) {
      if (scoreChartInstance) {
        try { scoreChartInstance.destroy(); } catch (e) { }
        scoreChartInstance = null;
      }
      chartContainer.innerHTML = '<p class="empty" style="text-align:center;padding:40px;color:var(--text-muted);">Pas assez de scores historisés pour cette période</p>';
      return;
    }

    if (!$('scoreCanvas')) {
      if (scoreChartInstance) {
        try { scoreChartInstance.destroy(); } catch (e) { }
        scoreChartInstance = null;
      }
      chartContainer.innerHTML = '<canvas id="scoreCanvas"></canvas>';
    }

    const labels = scores.map(s => {
      const date = parseDate(s.timestamp);
      return date ? date.toLocaleDateString('fr-CA', { month: '2-digit', day: '2-digit' }) + ' ' + date.toLocaleTimeString('fr-CA', { hour: '2-digit', minute: '2-digit' }) : '';
    });

    const dataPoints = scores.map(s => s.score);
    const ctx = $('scoreCanvas').getContext('2d');

    if (scoreChartInstance && $('scoreCanvas')) {
      scoreChartInstance.data.labels = labels;
      scoreChartInstance.data.datasets[0].data = dataPoints;
      scoreChartInstance.update();
      return;
    }

    scoreChartInstance = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'Score Crypto (0-100)',
            data: dataPoints,
            borderColor: '#3b82f6',
            backgroundColor: 'rgba(59, 130, 246, 0.08)',
            borderWidth: 2.5,
            tension: 0.3,
            fill: true,
            pointRadius: scores.length < 30 ? 4 : 1,
            pointHoverRadius: 6,
            pointBackgroundColor: '#3b82f6',
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            grid: { color: 'rgba(255, 255, 255, 0.03)' },
            ticks: { color: '#94a3b8', font: { size: 10 } }
          },
          y: {
            min: 0,
            max: 100,
            grid: { color: 'rgba(255, 255, 255, 0.03)' },
            ticks: { color: '#94a3b8', font: { size: 10 } }
          }
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#0f172a',
            titleColor: '#f8fafc',
            bodyColor: '#f8fafc',
            borderColor: 'rgba(255, 255, 255, 0.08)',
            borderWidth: 1,
            callbacks: {
              label: function (context) {
                const idx = context.dataIndex;
                const s = scores[idx];
                return [
                  `Score: ${s.score}/100`,
                  `Prix: ${number(s.price, 2)} USD`
                ];
              }
            }
          }
        }
      }
    });

  } catch (error) {
    console.error('Erreur refreshScoreChart:', error);
  }
}

async function refreshTrades() {
  try {
    const symbol = ($('tradeFilterSymbol')?.value || '').trim();
    const profitable = $('tradeFilterProfitable')?.value || '';

    let url = '/api/trades';
    const params = [];
    if (symbol) params.push(`symbol=${encodeURIComponent(symbol)}`);
    if (profitable) params.push(`profitable=${encodeURIComponent(profitable)}`);
    if (params.length) url += '?' + params.join('&');

    const response = await fetch(url, { cache: 'no-store' });
    if (!response.ok) return;
    const data = await response.json();
    renderTrades(data.trades);
  } catch (e) {
    // Silencieux
  }
}

async function safeRefresh() {
  try {
    await refresh();
  } catch (error) {
    $('lastUpdate').textContent = `Erreur dashboard: ${error.message}`;
  }
}

// Console state
const consoleState = { lastTotal: 0, pinned: true, limit: 500 };

const ANSI_COLORS = {
  '30': '#4a5568', '31': '#fc8181', '32': '#68d391', '33': '#f6e05e',
  '34': '#63b3ed', '35': '#d6bcfa', '36': '#76e4f7', '37': '#e2e8f0',
  '90': '#718096', '91': '#feb2b2', '92': '#9ae6b4', '93': '#faf089',
  '94': '#90cdf4', '95': '#e9d8fd', '96': '#b2f5ea', '97': '#f7fafc',
};

function ansiToHtml(line) {
  return esc(line).replace(/\x1b\[(\d+(?:;\d+)*)m/g, (_, codes) => {
    const parts = codes.split(';');
    const styles = [];
    for (const code of parts) {
      if (code === '0' || code === '') { return '</span>'; }
      if (code === '1') styles.push('font-weight:bold');
      if (ANSI_COLORS[code]) styles.push(`color:${ANSI_COLORS[code]}`);
    }
    return styles.length ? `<span style="${styles.join(';')}">` : '';
  });
}

function logLineClass(line) {
  if (/❌|error|erreur|failed|échou/i.test(line)) return 'console-error';
  if (/⚠️|warn|warning/i.test(line)) return 'console-warn';
  if (/✅|success|succès/i.test(line)) return 'console-ok';
  if (/🎯|buy|achat|sell|vente/i.test(line)) return 'console-trade';
  return '';
}

async function refreshConsole(full = false) {
  try {
    const limit = consoleState.limit;
    const url = `/api/bot/console?lines=${limit}`;
    const response = await fetch(url, { cache: 'no-store' });
    if (!response.ok) return;
    const data = await response.json();
    const el = $('consoleOutput');
    // Only re-render if line count changed
    if (full || data.total !== consoleState.lastTotal) {
      el.innerHTML = data.lines.map((l) => `<span class="cl ${logLineClass(l)}">${ansiToHtml(l)}</span>`).join('\n');
      consoleState.lastTotal = data.total;
      if (consoleState.pinned) {
        setTimeout(() => {
          el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
        }, 0);
      }
    }
    $('consoleStatus').textContent = `${data.lines.length} lignes`;
  } catch (e) {
    $('consoleStatus').textContent = `Erreur: ${e.message}`;
  }
}

function setConsoleLimit(limit) {
  consoleState.limit = limit;
  consoleState.lastTotal = 0;
  refreshConsole(true);
}

function clearConsole() {
  $('consoleOutput').innerHTML = '';
  consoleState.lastTotal = 0;
}

// Auto-scroll toggle on manual scroll
setTimeout(() => {
  const el = $('consoleOutput');
  if (el) {
    el.addEventListener('scroll', () => {
      consoleState.pinned = el.scrollTop + el.clientHeight >= el.scrollHeight - 40;
      const pinBtn = $('consolePinButton');
      if (pinBtn) {
        pinBtn.textContent = consoleState.pinned ? '⬇ Auto' : '⬇ Bas';
        if (consoleState.pinned) {
          pinBtn.classList.add('active');
        } else {
          pinBtn.classList.remove('active');
        }
      }
    });
  }
  const pinBtn = $('consolePinButton');
  if (pinBtn) {
    // Initial active state since it starts pinned
    pinBtn.classList.add('active');
    pinBtn.addEventListener('click', () => {
      consoleState.pinned = true;
      pinBtn.textContent = '⬇ Auto';
      pinBtn.classList.add('active');
      if (el) {
        el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
      }
    });
  }
}, 500);

// Console refresh every 1s always
setInterval(refreshConsole, 1000);

// WebSocket live prices
function connectLiveWs() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws/live`);
  ws.onmessage = (event) => {
    try { renderLive(JSON.parse(event.data)); } catch (e) { }
  };
  ws.onclose = () => setTimeout(connectLiveWs, 2000);
  ws.onerror = () => ws.close();
}
connectLiveWs();

// Slow poll for non-live data (positions, decisions, etc.) every 3s
setInterval(safeRefresh, 3000);

// Analytics refresh every 5s
setInterval(refreshAnalytics, 5000);

// Trades refresh every 5s
setInterval(refreshTrades, 5000);

// Function for CSV export
async function exportTradesCsv() {
  try {
    const symbol = ($('tradeFilterSymbol')?.value || '').trim();
    const profitable = $('tradeFilterProfitable')?.value || '';

    let url = '/api/trades';
    const params = [];
    if (symbol) params.push(`symbol=${encodeURIComponent(symbol)}`);
    if (profitable) params.push(`profitable=${encodeURIComponent(profitable)}`);
    if (params.length) url += '?' + params.join('&');

    const response = await fetch(url, { cache: 'no-store' });
    if (!response.ok) return;
    const data = await response.json();
    const trades = data.trades || [];

    if (!trades.length) {
      alert('Aucun trade à exporter.');
      return;
    }

    // Generate CSV content
    const headers = ['Date', 'Symbole', 'Prix Achat', 'Prix Vente', 'Quantité', 'PNL USD', 'PNL %', 'Type'];
    const rows = trades.map(t => [
      t.sell_time || '',
      t.symbol || '',
      t.buy_price || 0,
      t.sell_price || 0,
      t.amount || 0,
      t.pnl || 0,
      t.pnl_pct || 0,
      t.profitable ? 'WIN' : 'LOSS'
    ]);

    const csvContent = "data:text/csv;charset=utf-8,"
      + [headers.join(','), ...rows.map(e => e.join(','))].join('\n');

    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `aegis_trades_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  } catch (e) {
    alert("Erreur lors de l'export CSV : " + e.message);
  }
}

// Trades filter events
if ($('tradeFilterSymbol')) $('tradeFilterSymbol').addEventListener('input', refreshTrades);
if ($('tradeFilterProfitable')) $('tradeFilterProfitable').addEventListener('change', refreshTrades);
if ($('tradeRefreshButton')) $('tradeRefreshButton').addEventListener('click', refreshTrades);
if ($('tradeExportCsvButton')) $('tradeExportCsvButton').addEventListener('click', exportTradesCsv);

$('consoleClearButton').addEventListener('click', clearConsole);
if ($('consoleLimitSelect')) $('consoleLimitSelect').addEventListener('change', (e) => setConsoleLimit(e.target.value));
if ($('decisionsLimitSelect')) {
  $('decisionsLimitSelect').addEventListener('change', (e) => {
    state.decisionsLimit = e.target.value === 'all' ? 'all' : parseInt(e.target.value);
    safeRefresh();
  });
}
if ($('scoreChartSymbol')) $('scoreChartSymbol').addEventListener('change', refreshScoreChart);
if ($('scoreChartHours')) $('scoreChartHours').addEventListener('change', refreshScoreChart);
if ($('refreshButton')) $('refreshButton').addEventListener('click', safeRefresh);
$('saveConfigButton').addEventListener('click', saveConfig);
if ($('toggleBotButton')) {
  $('toggleBotButton').addEventListener('click', async () => {
    const isRunning = $('botStatusDot').classList.contains('live');
    const endpoint = isRunning ? '/api/bot/stop' : '/api/bot/start';

    const toggleBtn = $('toggleBotButton');
    toggleBtn.disabled = true;
    const btnText = toggleBtn.querySelector('.btn-text') || toggleBtn;
    btnText.textContent = isRunning ? 'Arrêt...' : 'Démarrage...';

    try {
      const response = await fetch(endpoint, { method: 'POST' });
      const data = await response.json();
      if (data && data.status) {
        renderBotProcess(data.status);
      }
    } catch (error) {
      console.error('Erreur toggle bot:', error);
    } finally {
      toggleBtn.disabled = false;
      await safeRefresh();
    }
  });
}
$('restartBotButton').addEventListener('click', restartBot);
document.querySelectorAll('.nav-button').forEach((button) => {
  button.addEventListener('click', () => setView(button.dataset.view));
});

// ===== CUSTOM DROPDOWNS INITIALIZATION =====
function initializeCustomDropdowns() {
  document.querySelectorAll('select.custom-select').forEach((select) => {
    if (select.nextElementSibling && select.nextElementSibling.classList.contains('custom-dropdown-container')) {
      return;
    }

    select.style.display = 'none';

    const container = document.createElement('div');
    container.className = 'custom-dropdown-container';

    const trigger = document.createElement('div');
    trigger.className = 'custom-dropdown-trigger';

    const label = document.createElement('span');
    label.className = 'custom-dropdown-label';

    const selectedOption = select.options[select.selectedIndex] || select.options[0];
    label.textContent = selectedOption ? selectedOption.textContent : '';

    const arrow = document.createElement('span');
    arrow.className = 'custom-dropdown-arrow';
    arrow.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="10" height="6" viewBox="0 0 10 6" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="1 1 5 5 9 1"/></svg>`;

    trigger.appendChild(label);
    trigger.appendChild(arrow);
    container.appendChild(trigger);

    const menu = document.createElement('div');
    menu.className = 'custom-dropdown-menu';

    Array.from(select.options).forEach((opt) => {
      const item = document.createElement('div');
      item.className = 'custom-dropdown-item';
      if (opt.selected) item.classList.add('active');
      item.textContent = opt.textContent;
      item.dataset.value = opt.value;

      item.addEventListener('click', (e) => {
        e.stopPropagation();
        menu.querySelectorAll('.custom-dropdown-item').forEach(i => i.classList.remove('active'));
        item.classList.add('active');
        label.textContent = opt.textContent;
        select.value = opt.value;
        select.dispatchEvent(new Event('change'));
        container.classList.remove('open');
      });

      menu.appendChild(item);
    });

    container.appendChild(menu);
    select.parentNode.insertBefore(container, select.nextSibling);

    trigger.addEventListener('click', (e) => {
      e.stopPropagation();
      document.querySelectorAll('.custom-dropdown-container.open').forEach((other) => {
        if (other !== container) other.classList.remove('open');
      });
      container.classList.toggle('open');
    });
  });
}

document.addEventListener('click', () => {
  document.querySelectorAll('.custom-dropdown-container.open').forEach((container) => {
    container.classList.remove('open');
  });
  document.querySelectorAll('.card-dropdown-menu').forEach((menu) => {
    menu.style.display = 'none';
  });
  activeCardMenuSymbol = null;
});

// ===== CARD OVERRIDE FUNCTIONS =====
window.toggleCardMenu = function (event, symbol) {
  event.stopPropagation();
  const menu = document.getElementById(`cardMenu-${symbol}`);
  if (menu) {
    const isOpen = menu.style.display === 'block';
    // Fermer tous les menus de carte
    document.querySelectorAll('.card-dropdown-menu').forEach((m) => {
      m.style.display = 'none';
    });
    if (!isOpen) {
      menu.style.display = 'block';
      activeCardMenuSymbol = symbol;
    } else {
      menu.style.display = 'none';
      activeCardMenuSymbol = null;
    }
  }
};

window.triggerCardAction = function (event, action, symbol, seconds = null) {
  event.stopPropagation();
  // Fermer le menu
  document.querySelectorAll('.card-dropdown-menu').forEach((menu) => {
    menu.style.display = 'none';
  });
  activeCardMenuSymbol = null;

  if (action === 'force_buy') {
    if (confirm(`Voulez-vous forcer un ACHAT (BUY) sur ${symbol} ?`)) {
      sendBotCommand('force_buy', symbol);
    }
  } else if (action === 'force_sell') {
    if (confirm(`Voulez-vous forcer une VENTE (SELL) sur ${symbol} ?`)) {
      sendBotCommand('force_sell', symbol);
    }
  } else if (action === 'pause_pair') {
    sendBotCommand('pause_pair', symbol, seconds);
  }
};

// ===== MANUAL OVERRIDE HANDLERS =====
async function sendBotCommand(action, symbol, seconds = null) {
  const statusSpan = $('overrideStatusMessage');
  if (statusSpan) {
    statusSpan.style.opacity = '1';
    statusSpan.style.color = 'var(--text-muted)';
    statusSpan.textContent = 'Envoi de la commande...';
  }

  try {
    const response = await fetch('/api/bot/command', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, symbol, seconds: seconds ? parseInt(seconds) : null })
    });
    const data = await response.json();
    if (data && data.ok) {
      if (statusSpan) {
        statusSpan.style.color = 'var(--good)';
        statusSpan.textContent = data.message;
      }
    } else {
      if (statusSpan) {
        statusSpan.style.color = 'var(--bad)';
        statusSpan.textContent = data.error || 'Erreur inconnue';
      }
    }
  } catch (error) {
    if (statusSpan) {
      statusSpan.style.color = 'var(--bad)';
      statusSpan.textContent = `Erreur: ${error.message}`;
    }
  }

  setTimeout(() => {
    if (statusSpan) {
      statusSpan.style.opacity = '0';
    }
  }, 4000);
}

// ===== MANUAL BACKTEST RUNNER =====
let backtestInterval = null;

function pollBacktestStatus() {
  fetch('/api/support_touch/backtest_status')
    .then(r => r.json())
    .then(data => {
      const btn = $('runBacktestBtn');
      if (data.running) {
        if (btn) {
          btn.disabled = true;
          btn.textContent = '⏳ Backtest en cours...';
        }
      } else {
        if (backtestInterval) {
          clearInterval(backtestInterval);
          backtestInterval = null;
        }
        if (btn) {
          btn.disabled = false;
          btn.textContent = '🔄 Lancer Backtest';
        }

        // Si le backtest vient de finir (exit_code !== null)
        if (data.exit_code !== null) {
          // Rafraîchir les données immédiatement sur l'UI
          safeRefresh();
          // Notifier le bot de rafraîchir son filtre Support Touch immédiatement
          fetch('/api/bot/command', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'refresh_support_touch' })
          }).catch(err => console.error('Failed to notify bot:', err));
        }
      }
    })
    .catch(err => console.error('Error polling backtest status:', err));
}

function startManualBacktest() {
  const btn = $('runBacktestBtn');
  if (btn) {
    btn.disabled = true;
    btn.textContent = '⏳ Initialisation...';
  }

  fetch('/api/support_touch/run_backtest', { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      if (data.ok) {
        if (btn) {
          btn.textContent = '⏳ Backtest en cours...';
        }
        if (!backtestInterval) {
          backtestInterval = setInterval(pollBacktestStatus, 1000);
        }
      } else {
        alert('Erreur au lancement du backtest : ' + (data.error || 'Erreur inconnue'));
        if (btn) {
          btn.disabled = false;
          btn.textContent = '🔄 Lancer Backtest';
        }
      }
    })
    .catch(err => {
      alert('Erreur réseau au lancement du backtest : ' + err.message);
      if (btn) {
        btn.disabled = false;
        btn.textContent = '🔄 Lancer Backtest';
      }
    });
}

// Enregistrement de l'écouteur du bouton
const runBacktestBtn = $('runBacktestBtn');
if (runBacktestBtn) {
  runBacktestBtn.addEventListener('click', startManualBacktest);
}
pollBacktestStatus();

window.addEventListener('hashchange', () => setView(currentHashView()));
initializeCustomDropdowns();
setView(currentHashView());
safeRefresh();
