# 
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from flask_sock import Sock

try:
    import orjson

    def json_loads(data):
        return orjson.loads(data)

    def json_dumps(data):
        return orjson.dumps(data, option=orjson.OPT_INDENT_2).decode('utf-8')

except ImportError:
    import json

    def json_loads(data):
        return json.loads(data)

    def json_dumps(data):
        return json.dumps(data, indent=2)


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / 'data'
ENV_DASHBOARD = ROOT / '.env.dashboard'
BOT_LOG_FILE = ROOT / 'bot.log'
BOT_CONTROL_FILE = DATA_DIR / 'bot_process.json'
BOT_STATUS_CACHE = {'timestamp': 0.0, 'payload': None}

# Subprocess bot control via PID file
BOT_PID_FILE = DATA_DIR / 'bot.pid'

def _cleanup_stale_pid():
    """Remove PID file if process no longer exists."""
    try:
        if BOT_PID_FILE.exists():
            pid = int(BOT_PID_FILE.read_text().strip())
            os.kill(pid, 0)  # process alive -> keep
    except Exception:
        BOT_PID_FILE.unlink(missing_ok=True)

_cleanup_stale_pid()

load_dotenv(ROOT / '.env', override=True)
load_dotenv(ROOT / '.env.local', override=True)
load_dotenv(ROOT / '.env.dashboard', override=True)

app = Flask(__name__, template_folder='templates', static_folder='static')
sock = Sock(app)


CONFIG_FIELDS = {
    'PAPER_TRADING': {'type': 'bool', 'label': 'Paper trading', 'section': 'Trading', 'restart': 'bot'},
    'TRADE_AMOUNT': {'type': 'float', 'label': 'Montant trade USD', 'section': 'Trading', 'min': 0.5, 'max': 10000, 'restart': 'bot'},
    'MAX_DAILY_TRADES': {'type': 'int', 'label': 'Trades max / jour', 'section': 'Risque', 'min': 0, 'max': 200, 'restart': 'bot'},
    'MAX_DAILY_LOSS': {'type': 'float', 'label': 'Perte max / jour', 'section': 'Risque', 'min': 0, 'max': 100000, 'restart': 'bot'},
    'STOP_LOSS_PERCENT': {'type': 'float', 'label': 'Stop loss %', 'section': 'Risque', 'min': 0.1, 'max': 50, 'restart': 'bot'},
    'TRAILING_STOP_PERCENT': {'type': 'float', 'label': 'Trailing stop %', 'section': 'Risque', 'min': 0.1, 'max': 50, 'restart': 'bot'},
    'SYMBOL_COOLDOWN_SECONDS': {'type': 'int', 'label': 'Cooldown symbole sec.', 'section': 'Risque', 'min': 0, 'max': 86400, 'restart': 'bot'},
    'SYMBOL_FAILURE_COOLDOWN_SECONDS': {'type': 'int', 'label': 'Cooldown Ã©chec sec.', 'section': 'Risque', 'min': 0, 'max': 86400, 'restart': 'bot'},
    'SUPPORT_TOUCH_MIN_TRADES': {'type': 'int', 'label': 'Support Touch trades min.', 'section': 'Support Touch', 'min': 1, 'max': 500, 'restart': 'bot'},
    'SUPPORT_TOUCH_MIN_WINRATE': {'type': 'float', 'label': 'Support Touch win rate min.', 'section': 'Support Touch', 'min': 0, 'max': 100, 'restart': 'bot'},
    'SUPPORT_TOUCH_MIN_TOTAL_PNL': {'type': 'float', 'label': 'Support Touch PnL total min.', 'section': 'Support Touch', 'min': -100, 'max': 1000, 'restart': 'bot'},
    'SUPPORT_TOUCH_MIN_AVG_PNL': {'type': 'float', 'label': 'Support Touch moyenne min.', 'section': 'Support Touch', 'min': -100, 'max': 100, 'restart': 'bot'},
    'SUPPORT_TOUCH_BACKTEST_INTERVAL_HOURS': {'type': 'float', 'label': 'Intervalle backtest h', 'section': 'Support Touch', 'min': 0.25, 'max': 168, 'restart': 'bot'},
    'MARKET_REGIME_FILTER': {'type': 'bool', 'label': 'Filtre rÃ©gime marchÃ©', 'section': 'Bear Mode', 'restart': 'bot'},
    'FALLING_KNIFE_FILTER': {'type': 'bool', 'label': 'Filtre falling knife', 'section': 'Bear Mode', 'restart': 'bot'},
    'REQUIRE_REVERSAL_CONFIRMATION_IN_BEAR': {'type': 'bool', 'label': 'Retournement requis en bear', 'section': 'Bear Mode', 'restart': 'bot'},
    'BEAR_MODE_TRADE_MULTIPLIER': {'type': 'float', 'label': 'Multiplicateur bear', 'section': 'Bear Mode', 'min': 0.05, 'max': 1, 'restart': 'bot'},
    'BEAR_MODE_MIN_CONFIDENCE_BONUS': {'type': 'float', 'label': 'Bonus confiance bear', 'section': 'Bear Mode', 'min': 0, 'max': 80, 'restart': 'bot'},
    'BEAR_MODE_SUPPORT_TOUCH_OVERRIDE': {'type': 'bool', 'label': 'Support override en bear', 'section': 'Bear Mode', 'restart': 'bot'},
    'BEAR_MODE_ALLOWED_PAIRS': {'type': 'pairs', 'label': 'Paires autorisÃ©es en bear', 'section': 'Bear Mode', 'restart': 'bot'},
    'MIN_CRYPTO_SCORE': {'type': 'int', 'label': 'Score crypto min.', 'section': 'Scoring', 'min': 0, 'max': 100, 'restart': 'bot'},
    'DASHBOARD_PORT': {'type': 'int', 'label': 'Port dashboard', 'section': 'Dashboard', 'min': 1024, 'max': 65535, 'restart': 'dashboard'},
    'LIVE_STATUS_INTERVAL_SECONDS': {'type': 'float', 'label': 'Refresh live status sec.', 'section': 'Dashboard', 'min': 0.25, 'max': 60, 'restart': 'bot'},
}

SECRET_KEYS = (
    'API_KEY',
    'API_SECRET',
    'SECRET',
    'TOKEN',
    'CHAT_ID',
)


# Cache pour éviter de retourner un fallback vide si le fichier est temporairement illisible
_read_json_cache = {}

def read_json(path: Path, fallback):
    try:
        if not path.exists():
            return fallback
        data = json_loads(path.read_bytes())
        _read_json_cache[str(path)] = data
        return data
    except Exception:
        # Retourner le dernier état valide si le fichier est corrompu/en cours d'écriture
        return _read_json_cache.get(str(path), fallback)


def read_env_file(path: Path):
    values = {}
    if not path.exists():
        return values
    try:
        for line in path.read_text(encoding='utf-8').splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith('#') or '=' not in stripped:
                continue
            key, value = stripped.split('=', 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    except Exception:
        return {}
    return values


def is_secret_key(name):
    upper = name.upper()
    return any(marker in upper for marker in SECRET_KEYS)


def parse_bool(value):
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in ('true', '1', 'yes', 'oui', 'on'):
        return True
    if normalized in ('false', '0', 'no', 'non', 'off'):
        return False
    raise ValueError('doit Ãªtre True ou False')


def normalize_pairs(value):
    raw = str(value or '').strip()
    if not raw:
        raise ValueError('liste de paires vide')
    pairs = []
    for item in raw.split(','):
        pair = item.strip().upper().replace('-', '/')
        if not pair:
            continue
        if '/' not in pair and pair.endswith('USD'):
            pair = f"{pair[:-3]}/USD"
        if not re.fullmatch(r'[A-Z0-9]{2,12}/[A-Z0-9]{2,12}', pair):
            raise ValueError(f'paire invalide: {item.strip()}')
        pairs.append(pair)
    if not pairs:
        raise ValueError('liste de paires vide')
    return ','.join(dict.fromkeys(pairs))


def normalize_config_value(name, value):
    meta = CONFIG_FIELDS[name]
    kind = meta['type']
    if kind == 'bool':
        return 'True' if parse_bool(value) else 'False'
    if kind == 'int':
        number = int(value)
        if number < meta.get('min', number) or number > meta.get('max', number):
            raise ValueError(f"doit Ãªtre entre {meta.get('min')} et {meta.get('max')}")
        return str(number)
    if kind == 'float':
        number = float(value)
        if number < meta.get('min', number) or number > meta.get('max', number):
            raise ValueError(f"doit Ãªtre entre {meta.get('min')} et {meta.get('max')}")
        return f"{number:g}"
    if kind == 'pairs':
        return normalize_pairs(value)
    raise ValueError('type non supportÃ©')


def write_dashboard_env(updates):
    current = read_env_file(ENV_DASHBOARD)
    current.update(updates)

    lines = [
        '# RÃ©glages modifiables depuis le dashboard Aegis.',
        '# Ne mettez jamais de clÃ© API ou secret dans ce fichier.',
        '',
    ]
    sections = {}
    for name in CONFIG_FIELDS:
        sections.setdefault(CONFIG_FIELDS[name]['section'], []).append(name)

    for section, names in sections.items():
        lines.append(f'# ===== {section.upper()} =====')
        for name in names:
            if name in current:
                lines.append(f'{name}={current[name]}')
        lines.append('')

    ENV_DASHBOARD.write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')
    for key, value in current.items():
        if key in CONFIG_FIELDS:
            os.environ[key] = value


def config_payload():
    dashboard_values = read_env_file(ENV_DASHBOARD)
    fields = []
    for name, meta in CONFIG_FIELDS.items():
        value = dashboard_values.get(name, os.getenv(name, ''))
        fields.append({
            'name': name,
            'label': meta['label'],
            'section': meta['section'],
            'type': meta['type'],
            'value': value,
            'source': 'dashboard' if name in dashboard_values else 'env',
            'restart': meta.get('restart', 'bot'),
            'min': meta.get('min'),
            'max': meta.get('max'),
        })

    secrets = []
    for name in sorted(os.environ):
        if is_secret_key(name):
            secrets.append({'name': name, 'configured': bool(os.getenv(name))})

    return {
        'file': str(ENV_DASHBOARD.relative_to(ROOT)),
        'fields': fields,
        'secrets': secrets,
        'message': 'Les changements sont Ã©crits dans .env.dashboard. RedÃ©marrage requis selon le champ.',
    }


def read_bot_control_file():
    return read_json(BOT_CONTROL_FILE, {})


def process_exists(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def bot_is_running():
    try:
        if not BOT_PID_FILE.exists():
            return False
        pid = int(BOT_PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def bot_status_payload(force=False):
    now = time.time()
    if not force and BOT_STATUS_CACHE['payload'] and now - BOT_STATUS_CACHE['timestamp'] < 2:
        return BOT_STATUS_CACHE['payload']
    running = bot_is_running()
    tracked = read_json(BOT_CONTROL_FILE, {})
    payload = {
        'running': running,
        'started_at': tracked.get('started_at'),
        'mode': 'subprocess',
    }
    BOT_STATUS_CACHE['timestamp'] = now
    BOT_STATUS_CACHE['payload'] = payload
    return payload


def stop_bot_processes():
    stopped = []
    try:
        if BOT_PID_FILE.exists():
            pid = int(BOT_PID_FILE.read_text().strip())
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'],
                               capture_output=True, timeout=10)
            else:
                os.kill(pid, signal.SIGTERM)
                time.sleep(1)
                try:
                    os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass
            stopped.append(pid)
            BOT_PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    return stopped


def start_bot_process():
    if bot_is_running():
        return {'started': False, 'already_running': True}

    command = [sys.executable, str(ROOT / 'run.py')]
    BOT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    creationflags = 0
    if os.name == 'nt':
        creationflags = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
            | subprocess.DETACHED_PROCESS
        )

    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUNBUFFERED'] = '1'

    with open(BOT_LOG_FILE, 'a', encoding='utf-8', errors='replace') as log:
        process = subprocess.Popen(
            command,
            cwd=str(ROOT),
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
            env=env,
        )

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BOT_PID_FILE.write_text(str(process.pid))
    payload = {
        'pid': process.pid,
        'started_at': datetime.now().isoformat(),
        'command': ' '.join(command),
    }
    BOT_CONTROL_FILE.write_text(json_dumps(payload), encoding='utf-8')
    return {'started': True, 'pid': process.pid}


def project_path(value, fallback):
    raw = value or fallback
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def tail_lines(path: Path, limit=80):
    try:
        if not path.exists():
            return []
        with path.open('r', encoding='utf-8', errors='replace') as file:
            return list(deque(file, maxlen=limit))
    except Exception:
        return []


def parse_jsonl(path: Path, limit=50):
    entries = []
    for line in tail_lines(path, limit):
        try:
            entries.append(json_loads(line))
        except Exception:
            continue
    return entries


def env_bool(name, default='False'):
    return os.getenv(name, default).lower() == 'true'


def active_state_file():
    return DATA_DIR / ('paper_bot_state.json' if env_bool('PAPER_TRADING', 'True') else 'bot_state.json')


def trade_stats(positions):
    """Compute PnL, total closed trades, and win rate from buy/sell pairs."""
    buys = {}  # symbol -> list of pending buys [{amount, price}]
    trades = []  # closed trades with pnl
    timestamps = []  # sell timestamps for duration calc

    for pos in sorted(positions, key=lambda p: p.get('timestamp', '')):
        symbol = pos.get('symbol')
        side = pos.get('side')
        amount = float(pos.get('amount') or 0)
        px = float(pos.get('price') or 0)
        if not symbol or amount <= 0 or px <= 0:
            continue

        if side == 'buy':
            buys.setdefault(symbol, []).append({'amount': amount, 'price': px, 'ts': pos.get('timestamp')})
        elif side == 'sell':
            remaining = amount
            queue = buys.get(symbol, [])
            while remaining > 1e-12 and queue:
                entry = queue[0]
                filled = min(remaining, entry['amount'])
                pnl = filled * (px - entry['price'])
                trades.append(pnl)
                if entry.get('ts'):
                    try:
                        timestamps.append(datetime.fromisoformat(entry['ts']))
                    except Exception:
                        pass
                if pos.get('timestamp'):
                    try:
                        timestamps.append(datetime.fromisoformat(pos['timestamp']))
                    except Exception:
                        pass
                entry['amount'] -= filled
                remaining -= filled
                if entry['amount'] <= 1e-12:
                    queue.pop(0)

    total = len(trades)
    wins = sum(1 for t in trades if t > 0)
    total_pnl = sum(trades)
    win_rate = (wins / total * 100) if total else 0

    # Compute trading duration in days from first to last trade
    days_active = 0
    if timestamps and len(timestamps) >= 2:
        first = min(timestamps)
        last = max(timestamps)
        delta = (last - first).total_seconds()
        days_active = delta / 86400 if delta > 0 else 0

    return {
        'total_trades': total,
        'wins': wins,
        'losses': total - wins,
        'win_rate': round(win_rate, 1),
        'total_pnl': round(total_pnl, 4),
        'days_active': round(days_active, 4),
    }


def weighted_positions(positions):
    by_symbol = {}
    for position in sorted(positions, key=lambda item: item.get('timestamp', '')):
        symbol = position.get('symbol')
        side = position.get('side')
        amount = float(position.get('amount') or 0)
        price = float(position.get('price') or 0)
        if not symbol or amount <= 0 or price <= 0:
            continue

        data = by_symbol.setdefault(symbol, {
            'symbol': symbol,
            'amount': 0.0,
            'cost': 0.0,
            'last_update': position.get('timestamp'),
        })

        if side == 'buy':
            data['amount'] += amount
            data['cost'] += amount * price
            data['last_update'] = position.get('timestamp')
        elif side == 'sell' and data['amount'] > 0:
            sold = min(amount, data['amount'])
            average = data['cost'] / data['amount'] if data['amount'] else 0
            data['amount'] -= sold
            data['cost'] -= sold * average
            data['last_update'] = position.get('timestamp')
            if data['amount'] <= 0.00000001:
                data['amount'] = 0.0
                data['cost'] = 0.0

    result = []
    for data in by_symbol.values():
        if data['amount'] <= 0:
            continue
        avg_entry = data['cost'] / data['amount'] if data['amount'] else 0
        result.append({
            'symbol': data['symbol'],
            'amount': data['amount'],
            'avg_entry_price': avg_entry,
            'entry_value': data['amount'] * avg_entry,
            'last_update': data['last_update'],
        })
    return sorted(result, key=lambda item: item['symbol'])


def cooldowns(state):
    now = datetime.now().timestamp()
    items = []
    for symbol, cooldown_until in state.get('symbol_cooldowns', {}).items():
        remaining = max(0, int(float(cooldown_until or 0) - now))
        if remaining > 0:
            items.append({'symbol': symbol, 'remaining_seconds': remaining})
    return sorted(items, key=lambda item: item['symbol'])


def support_touch(state):
    state_filter = state.get('support_touch_filter') or {}
    backtest_path = project_path(os.getenv('SUPPORT_TOUCH_BACKTEST_FILE'), DATA_DIR / 'support_touch_backtest_auto.json')
    backtest = read_json(backtest_path, {})
    pairs = state_filter.get('pairs') or {}

    if not pairs:
        for item in backtest.get('results', []):
            symbol = item.get('symbol')
            if symbol:
                pairs[symbol] = {
                    'allowed': False,
                    'reason': 'not_evaluated',
                    'trades': item.get('trades', 0),
                    'win_rate': item.get('win_rate', 0),
                    'total_pnl_percent': item.get('total_pnl_percent', 0),
                    'avg_pnl_percent': item.get('avg_pnl_percent', 0),
                }

    return {
        'last_run': state_filter.get('last_run') or backtest.get('generated_at'),
        'last_error': state_filter.get('last_error'),
        'pairs': [
            {'symbol': symbol, **data}
            for symbol, data in sorted(pairs.items())
        ],
        'settings': backtest.get('settings', {}),
        'thresholds': {
            'min_trades': int(os.getenv('SUPPORT_TOUCH_MIN_TRADES', '10')),
            'min_winrate': float(os.getenv('SUPPORT_TOUCH_MIN_WINRATE', '50')),
            'min_total_pnl': float(os.getenv('SUPPORT_TOUCH_MIN_TOTAL_PNL', '0')),
            'min_avg_pnl': float(os.getenv('SUPPORT_TOUCH_MIN_AVG_PNL', '0')),
        },
    }


def important_logs():
    keywords = ('â', 'â ï¸', 'error', 'erreur', 'permission denied', 'failed', 'Ã©chou')
    lines = []
    for line in tail_lines(ROOT / 'bot.log', 200):
        if any(keyword in line.lower() for keyword in keywords):
            lines.append(line.strip())
    return lines[-40:]


def live_status():
    path = project_path(os.getenv('LIVE_STATUS_FILE'), DATA_DIR / 'live_status.json')
    return read_json(path, {
        'connected': False,
        'mode': 'unknown',
        'symbols': {},
        'timestamp': None,
    })


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/status')
def api_status():
    state = read_json(active_state_file(), {'positions': []})
    decisions = state.get('decision_journal') or parse_jsonl(DATA_DIR / 'decision_journal.jsonl', 20)
    positions = weighted_positions(state.get('positions', []))

    stats = trade_stats(state.get('positions', []))

    response = jsonify({
        'bot': {
            'name': os.getenv('BOT_NAME', 'Aegis'),
            'mode': 'paper' if env_bool('PAPER_TRADING', 'True') else 'live',
            'exchange': os.getenv('EXCHANGE', 'unknown'),
            'state_file': str(active_state_file().relative_to(ROOT)),
            'last_update': state.get('last_update'),
            'control': bot_status_payload(),
        },
        'balance': {
            'paper_balance': state.get('paper_balance'),
        },
        'stats': stats,
        'positions': positions,
        'cooldowns': cooldowns(state),
        'market_context': state.get('market_context', {}),
        'live': live_status(),
        'support_touch': support_touch(state),
        'decisions': decisions[-20:],
        'logs': important_logs(),
        'config': {
            'file': str(ENV_DASHBOARD.relative_to(ROOT)),
        },
    })
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.route('/api/decisions')
def api_decisions():
    state = read_json(active_state_file(), {'decision_journal': []})
    decisions = state.get('decision_journal') or parse_jsonl(DATA_DIR / 'decision_journal.jsonl', 80)
    return jsonify({'decisions': decisions[-80:]})


@app.route('/api/logs')
def api_logs():
    return jsonify({'logs': important_logs()})


@app.route('/api/config', methods=['GET'])
def api_config():
    return jsonify(config_payload())


@app.route('/api/config', methods=['POST'])
def api_config_update():
    payload = request.get_json(silent=True) or {}
    values = payload.get('values') or {}
    updates = {}
    errors = {}

    for name, value in values.items():
        if name not in CONFIG_FIELDS:
            errors[name] = 'champ non autorisÃ©'
            continue
        if is_secret_key(name):
            errors[name] = 'secret non modifiable depuis le dashboard'
            continue
        try:
            updates[name] = normalize_config_value(name, value)
        except Exception as exc:
            errors[name] = str(exc)

    if errors:
        return jsonify({'ok': False, 'errors': errors, **config_payload()}), 400

    write_dashboard_env(updates)
    load_dotenv(ENV_DASHBOARD, override=True)
    return jsonify({'ok': True, 'updated': sorted(updates), **config_payload()})


@app.route('/api/bot/status')
def api_bot_status():
    return jsonify(bot_status_payload(force=True))


@app.route('/api/bot/start', methods=['POST'])
def api_bot_start():
    result = start_bot_process()
    return jsonify({'ok': True, **result, 'status': bot_status_payload(force=True)})


@app.route('/api/bot/stop', methods=['POST'])
def api_bot_stop():
    stopped = stop_bot_processes()
    return jsonify({'ok': True, 'stopped': stopped, 'status': bot_status_payload(force=True)})


@app.route('/api/bot/restart', methods=['POST'])
def api_bot_restart():
    stopped = stop_bot_processes()
    time.sleep(1)
    started = start_bot_process()
    return jsonify({'ok': True, 'stopped': stopped, **started, 'status': bot_status_payload(force=True)})


@app.route('/api/bot/console')
def api_bot_console():
    lines_count = request.args.get('lines', '500')
    if lines_count == 'all':
        try:
            all_lines = BOT_LOG_FILE.read_text(encoding='utf-8', errors='replace').splitlines() if BOT_LOG_FILE.exists() else []
        except Exception:
            all_lines = []
        return jsonify({'lines': all_lines, 'total': len(all_lines)})
    lines_count = int(lines_count)
    lines = tail_lines(BOT_LOG_FILE, lines_count)
    # Return file size as change indicator (cheap stat)
    try:
        file_size = BOT_LOG_FILE.stat().st_size if BOT_LOG_FILE.exists() else 0
    except Exception:
        file_size = 0
    return jsonify({'lines': [l.rstrip() for l in lines], 'total': file_size})


@app.route('/api/live')
def api_live():
    response = jsonify(live_status())
    response.headers['Cache-Control'] = 'no-store'
    return response


@sock.route('/ws/live')
def ws_live(ws):
    # Push live_status.json to browser via WebSocket whenever it changes
    import json as _json
    path = project_path(os.getenv('LIVE_STATUS_FILE'), DATA_DIR / 'live_status.json')
    last_mtime = 0.0
    last_data = None
    while True:
        try:
            mtime = path.stat().st_mtime if path.exists() else 0.0
            if mtime != last_mtime:
                last_mtime = mtime
                raw = path.read_bytes() if path.exists() else b'{}'
                if raw != last_data:
                    last_data = raw
                    ws.send(raw.decode('utf-8', errors='replace'))
        except Exception:
            pass
        time.sleep(0.2)


if __name__ == '__main__':
    port = int(os.getenv('DASHBOARD_PORT', '8080'))
    app.run(host='127.0.0.1', port=port, debug=False)
