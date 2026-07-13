const state = {
  timer: null,
  config: null,
  view: 'live',
};

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
  const num = Number(value);
  if (!Number.isFinite(num)) return '--';
  return num.toLocaleString('fr-CA', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function price(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return '--';
  return num.toLocaleString('fr-CA', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
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

function formatDateTime(value) {
  const date = value instanceof Date ? value : parseDate(value);
  if (!date) return '--';
  return date.toLocaleString('fr-CA', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function formatFriendlyDate(value) {
  const date = value instanceof Date ? value : parseDate(value);
  if (!date) return '--';

  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const target = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const diffDays = Math.round((today - target) / 86400000);
  const time = date.toLocaleTimeString('fr-CA', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });

  if (diffDays === 0) return `Aujourd'hui ${time}`;
  if (diffDays === 1) return `Hier ${time}`;
  return date.toLocaleString('fr-CA', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function relativeTime(value) {
  const date = value instanceof Date ? value : parseDate(value);
  if (!date) return '--';
  const diffSeconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  return `il y a ${duration(diffSeconds)}`;
}

function dateWithRelative(value) {
  const date = value instanceof Date ? value : parseDate(value);
  if (!date) return '--';
  return `${formatFriendlyDate(date)} · ${relativeTime(date)}`;
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
  el.textContent = text;
  el.className = className;
}

function setView(view) {
  const next = ['config', 'console'].includes(view) ? view : 'live';
  state.view = next;
  document.querySelectorAll('.view').forEach((el) => {
    el.classList.toggle('active', el.id === `view${next[0].toUpperCase()}${next.slice(1)}`);
  });
  document.querySelectorAll('.tab-button').forEach((button) => {
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
    refreshConsole();
  }
}

function currentHashView() {
  const hash = window.location.hash.replace('#', '');
  if (hash === 'config') return 'config';
  if (hash === 'console') return 'console';
  return 'live';
}

function renderConfig(config) {
  state.config = config;
  $('configHint').textContent = `${config.file} · secrets masqués · redémarrage selon champ`;
  const form = $('configForm');
  const sections = {};
  for (const field of config.fields || []) {
    if (!sections[field.section]) sections[field.section] = [];
    sections[field.section].push(field);
  }

  form.innerHTML = Object.entries(sections).map(([section, fields]) => `
    <section class="config-section">
      <h3>${esc(section)}</h3>
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
  const restart = field.restart === 'dashboard' ? 'Dashboard' : 'Bot';
  const source = field.source === 'dashboard' ? '.env.dashboard' : 'env';
  let control = '';

  if (field.type === 'bool') {
    const checked = String(field.value).toLowerCase() === 'true' ? 'checked' : '';
    control = `<label class="switch"><input ${common} type="checkbox" ${checked}><span></span></label>`;
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
  }

  return `
    <label class="config-field">
      <span class="config-label">${esc(field.label)}</span>
      ${control}
      <span class="config-meta">${esc(field.name)} · ${source} · restart ${restart}</span>
    </label>
  `;
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
  const count = control?.processes?.length || 0;
  setBadge($('botProcessBadge'), running ? `bot ON (${count})` : 'bot OFF', running ? 'badge good' : 'badge bad');
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

function supportReasonTooltip(reason, item, thresholds = {}) {
  const tips = {
    insufficient_trades: `Attendre plus de signaux backtest. Actuel: ${item.trades ?? 0}. Requis: ${thresholds.min_trades ?? 10}.`,
    winrate_below_threshold: `Le taux de réussite est trop faible. Actuel: ${percent(item.win_rate)}. Requis: ${percent(thresholds.min_winrate ?? 50)} ou plus.`,
    total_pnl_below_threshold: `Le profit total simulé est insuffisant. Actuel: ${percent(item.total_pnl_percent)}. Requis: ${percent(thresholds.min_total_pnl ?? 0)} ou plus.`,
    avg_pnl_below_threshold: `Le gain moyen par trade est insuffisant. Actuel: ${percent(item.avg_pnl_percent)}. Requis: ${percent(thresholds.min_avg_pnl ?? 0)} ou plus.`,
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

function renderPositions(positions) {
  const body = $('positionsBody');
  if (!positions.length) {
    body.innerHTML = '<tr><td colspan="4" class="empty">Aucune position ouverte</td></tr>';
    return;
  }

  body.innerHTML = positions.map((position) => `
    <tr>
      <td><strong>${esc(position.symbol)}</strong></td>
      <td>${number(position.amount, 8)}</td>
      <td>${price(position.avg_entry_price)}</td>
      <td>${number(position.entry_value, 2)} USDT</td>
    </tr>
  `).join('');
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
  $('supportSummary').textContent = `${allowed}/${pairs.length || 0}`;
  $('supportLastRun').textContent = data.last_run ? `Dernier run ${dateWithRelative(data.last_run)}` : '';

  const grid = $('supportGrid');
  if (!pairs.length) {
    grid.innerHTML = '<p class="empty">Aucun résultat backtest</p>';
    return;
  }

  grid.innerHTML = pairs.map((item) => `
    <section class="support-card">
      <header>
        <h3>${esc(item.symbol)}</h3>
        <span class="${badgeClass(item.allowed)}">${item.allowed ? 'OK' : 'Bloqué'}</span>
      </header>
      <div class="support-stats">
        <div><span>Trades</span><strong>${item.trades ?? 0}</strong></div>
        <div><span>Win rate</span><strong>${percent(item.win_rate)}</strong></div>
        <div><span>Total</span><strong>${percent(item.total_pnl_percent)}</strong></div>
        <div><span>Moyenne</span><strong>${percent(item.avg_pnl_percent)}</strong></div>
      </div>
      <div class="reason-list" aria-label="Raisons">${renderReasonChips(item.reason, item, thresholds)}</div>
    </section>
  `).join('');
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
    return `
      <section class="support-card regime-card ${modeClass}">
        <header>
          <div>
            <h3>${esc(symbol)}</h3>
            <span class="live-source">BTC ${esc(item.btc_regime || '--')}</span>
          </div>
          <span class="${badgeClass(!bear, bear)}">${esc(mode)}</span>
        </header>

        <div class="regime-hero">
          <div>
            <span>Régime symbole</span>
            <strong>${esc(item.symbol_regime || '--')}</strong>
          </div>
          <span class="regime-momentum ${Number(item.btc_momentum_percent) >= 0 ? 'up' : 'down'}">
            ${signedPercent(item.btc_momentum_percent, 2)}
          </span>
        </div>

        <div class="quote-row">
          <div><span>Protection</span><strong>${multiplier < 1 ? `${number(multiplier, 2)}x` : '1,00x'}</strong></div>
          <div><span>Retournement</span><strong>${reversal ? 'confirmé' : 'non'}</strong></div>
        </div>

        <div class="live-statbar">
          <span class="${falling ? 'risk-chip' : ''}">Falling knife ${falling ? 'oui' : 'non'}</span>
          <span>Support ${item.support_touch_override_allowed ? 'autorisé' : 'bloqué'}</span>
          <span>${bear ? 'Bear mode' : 'Marché normal'}</span>
          <span>Update ${item.last_update ? relativeTime(item.last_update).replace('il y a ', '') : '--'}</span>
        </div>
      </section>
    `;
  }).join('');
}

function renderLive(data) {
  const symbols = data?.symbols || {};
  const entries = Object.entries(symbols);
  const connected = Boolean(data?.connected);
  const totalTicks = entries.reduce((sum, [, item]) => sum + Number(item.tick_count || 0), 0);
  const queueSize = Number(data?.queue_size || 0);
  $('wsSummary').textContent = connected ? 'OK' : 'REST';
  $('wsSummary').style.color = connected ? 'var(--good)' : 'var(--warn)';
  $('wsLastUpdate').textContent = data?.timestamp
    ? `${data.mode || 'unknown'} · ${dateWithRelative(data.timestamp)}`
    : 'Aucune télémétrie live';
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

  grid.innerHTML = entries.map(([symbol, item]) => {
    const tickAge = item.last_tick_age_seconds;
    const stale = tickAge === null || tickAge === undefined || tickAge > 30;
    const spreadText = item.spread_percent === null || item.spread_percent === undefined
      ? '--'
      : signedPercent(item.spread_percent, 2);
    const deltaText = signedPercent(item.price_change_since_analysis_percent, 2);
    const deltaValue = Number(item.price_change_since_analysis_percent);
    const deltaClass = Number.isFinite(deltaValue) && deltaValue >= 0 ? 'up' : 'down';
    const source = item.source || '--';
    return `
      <section class="support-card live-card">
        <header>
          <div>
            <h3>${esc(symbol.replace('USDT', '/USDT'))}</h3>
            <span class="live-source">${esc(source)}</span>
          </div>
          <span class="${badgeClass(!stale, !connected)}">${stale ? 'stale' : 'live'}</span>
        </header>

        <div class="live-quote">
          <div>
            <span>Dernier prix</span>
            <strong>${price(item.price)}</strong>
          </div>
          <span class="live-delta ${deltaClass}">${deltaText}</span>
        </div>

        <div class="quote-row">
          <div><span>Bid</span><strong>${price(item.bid)}</strong></div>
          <div><span>Ask</span><strong>${price(item.ask)}</strong></div>
        </div>

        <div class="live-statbar">
          <span>Tick ${tickAge === null || tickAge === undefined ? '--' : duration(Math.round(tickAge))}</span>
          <span>Analyse ${item.last_analysis_age_seconds === null || item.last_analysis_age_seconds === undefined ? '--' : duration(Math.round(item.last_analysis_age_seconds))}</span>
          <span>Spread ${spreadText}</span>
          <span>${item.tick_count ?? 0} ticks</span>
          <span>${item.kline_count ?? 0} bougies</span>
        </div>
      </section>
    `;
  }).join('');
}

function renderDecisions(decisions) {
  const box = $('decisionsList');
  if (!decisions.length) {
    box.innerHTML = '<p class="empty">Aucune décision récente</p>';
    return;
  }

  const visible = decisions.slice(-8).reverse();
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
      <p class="event-time">${esc(item.action || '--')} · ${esc(dateWithRelative(item.timestamp))}</p>
    </div>
  `).join('') + (
    decisions.length > visible.length
      ? `<p class="timeline-more">+${decisions.length - visible.length} décision(s) plus ancienne(s) masquée(s)</p>`
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
    const label = parsed.date ? dateWithRelative(parsed.date) : 'Date inconnue';
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
    ? `State ${data.bot.state_file} · ${dateWithRelative(data.bot.last_update)}`
    : `State ${data.bot.state_file}`;

  setBadge($('modeBadge'), data.bot.mode, data.bot.mode === 'paper' ? 'badge good' : 'badge bad');
  setBadge($('exchangeBadge'), data.bot.exchange, 'badge neutral');
  renderBotProcess(data.bot.control);

  $('paperBalance').textContent = data.balance.paper_balance === null || data.balance.paper_balance === undefined
    ? '--'
    : `${number(data.balance.paper_balance, 2)} USDT`;
  $('positionCount').textContent = data.positions.length;
  $('cooldownCount').textContent = data.cooldowns.length;

  renderLive(data.live);
  renderPositions(data.positions);
  renderCooldowns(data.cooldowns);
  renderSupportTouch(data.support_touch);
  renderMarketContext(data.market_context);
  renderDecisions(data.decisions);
  renderLogs(data.logs);
}

async function safeRefresh() {
  try {
    await refresh();
  } catch (error) {
    $('lastUpdate').textContent = `Erreur dashboard: ${error.message}`;
  }
}

// Console state
const consoleState = { lastTotal: 0, timer: null };

async function refreshConsole() {
  try {
    const response = await fetch(`/api/bot/console?lines=200&after=${consoleState.lastTotal}`, { cache: 'no-store' });
    if (!response.ok) return;
    const data = await response.json();
    const el = $('consoleOutput');
    if (consoleState.lastTotal === 0) {
      el.textContent = data.lines.join('\n');
    } else if (data.lines.length > 0) {
      el.textContent += '\n' + data.lines.join('\n');
    }
    consoleState.lastTotal = data.total;
    $('consoleStatus').textContent = `${data.total} lignes`;
    // Auto-scroll
    el.scrollTop = el.scrollHeight;
  } catch (e) {
    $('consoleStatus').textContent = `Erreur: ${e.message}`;
  }
}

function clearConsole() {
  $('consoleOutput').textContent = '';
  consoleState.lastTotal = 0;
}

// Console auto-refresh when visible
setInterval(() => {
  if (state.view === 'console') refreshConsole();
}, 2000);

$('consoleClearButton').addEventListener('click', clearConsole);
$('refreshButton').addEventListener('click', safeRefresh);
$('saveConfigButton').addEventListener('click', saveConfig);
$('restartBotButton').addEventListener('click', restartBot);
document.querySelectorAll('.tab-button').forEach((button) => {
  button.addEventListener('click', () => setView(button.dataset.view));
});
window.addEventListener('hashchange', () => setView(currentHashView()));
setView(currentHashView());
safeRefresh();
state.timer = setInterval(safeRefresh, 1000);
