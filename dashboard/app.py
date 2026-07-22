"""Dashboard Flask pour Aegis Trading Bot"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
from collections import deque, defaultdict
from datetime import datetime, timedelta
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

# Suppression de la bannière Flask au démarrage et du bruit des requêtes HTTP (GET/POST) dans la console
import logging
logging.getLogger('werkzeug').setLevel(logging.WARNING)

import click
click.echo = lambda *args, **kwargs: None
click.secho = lambda *args, **kwargs: None


CONFIG_FIELDS = {
    'PAPER_TRADING': {'type': 'bool', 'label': 'Paper trading', 'section': 'Trading', 'restart': 'bot'},
    'TRADE_AMOUNT': {'type': 'float', 'label': 'Montant trade USD', 'section': 'Trading', 'min': 0.5, 'max': 10000, 'restart': 'bot'},
    'MAX_DAILY_TRADES': {'type': 'int', 'label': 'Trades max / jour', 'section': 'Risque', 'min': 0, 'max': 200, 'restart': 'bot'},
    'MAX_DAILY_LOSS': {'type': 'float', 'label': 'Perte max / jour', 'section': 'Risque', 'min': 0, 'max': 100000, 'restart': 'bot'},
    'STOP_LOSS_PERCENT': {'type': 'float', 'label': 'Stop loss %', 'section': 'Risque', 'min': 0.1, 'max': 50, 'restart': 'bot'},
    'TRAILING_STOP_PERCENT': {'type': 'float', 'label': 'Trailing stop %', 'section': 'Risque', 'min': 0.1, 'max': 50, 'restart': 'bot'},
    'BREAKEVEN_STOP_ENABLED': {'type': 'bool', 'label': 'Activer Stop Zéro Perte (Breakeven)', 'section': 'Risque', 'restart': 'bot'},
    'BREAKEVEN_USE_RESISTANCE': {'type': 'bool', 'label': 'Breakeven basé sur la Résistance (50% R1)', 'section': 'Risque', 'restart': 'bot'},
    'BREAKEVEN_TRIGGER_PROFIT_PCT': {'type': 'float', 'label': 'Seuil d\'activ. Breakeven % (Si résistance inactive)', 'section': 'Risque', 'min': -50.0, 'max': 20, 'restart': 'bot'},
    'BREAKEVEN_LOCK_PROFIT_PCT': {'type': 'float', 'label': 'Verrouillage Profit % (0=Frais, 1=Frais+1%)', 'section': 'Risque', 'min': 0.0, 'max': 10, 'restart': 'bot'},
    'BREAKEVEN_MIN_NET_PROFIT_PCT': {'type': 'float', 'label': 'Profit net min. protégé %', 'section': 'Risque', 'min': 0.0, 'max': 5, 'restart': 'bot'},
    'BREAKEVEN_TRIGGER_BUFFER_PCT': {'type': 'float', 'label': 'Buffer activation frais %', 'section': 'Risque', 'min': 0.0, 'max': 5, 'restart': 'bot'},
    'BREAKEVEN_MIN_STOP_GAP_PCT': {'type': 'float', 'label': 'Écart min stop/prix %', 'section': 'Risque', 'min': 0.0, 'max': 2, 'restart': 'bot'},
    'SYMBOL_COOLDOWN_SECONDS': {'type': 'int', 'label': 'Cooldown symbole sec.', 'section': 'Risque', 'min': 0, 'max': 86400, 'restart': 'bot'},
    'SYMBOL_FAILURE_COOLDOWN_SECONDS': {'type': 'int', 'label': 'Cooldown echec sec.', 'section': 'Risque', 'min': 0, 'max': 86400, 'restart': 'bot'},
    'SUPPORT_TOUCH_MIN_TRADES': {'type': 'int', 'label': 'Support Touch trades min.', 'section': 'Support Touch', 'min': 1, 'max': 500, 'restart': 'bot'},
    'SUPPORT_TOUCH_MIN_WINRATE': {'type': 'float', 'label': 'Support Touch win rate min.', 'section': 'Support Touch', 'min': 0, 'max': 100, 'restart': 'bot'},
    'SUPPORT_TOUCH_MIN_TOTAL_PNL': {'type': 'float', 'label': 'Support Touch PnL total min.', 'section': 'Support Touch', 'min': -100, 'max': 1000, 'restart': 'bot'},
    'SUPPORT_TOUCH_MIN_AVG_PNL': {'type': 'float', 'label': 'Support Touch moyenne min.', 'section': 'Support Touch', 'min': -100, 'max': 100, 'restart': 'bot'},
    'SUPPORT_TOUCH_BACKTEST_INTERVAL_HOURS': {'type': 'float', 'label': 'Intervalle backtest h', 'section': 'Support Touch', 'min': 0.25, 'max': 168, 'restart': 'bot'},
    'MARKET_REGIME_FILTER': {'type': 'bool', 'label': 'Filtre regime marche', 'section': 'Bear Mode', 'restart': 'bot'},
    'FALLING_KNIFE_FILTER': {'type': 'bool', 'label': 'Filtre falling knife', 'section': 'Bear Mode', 'restart': 'bot'},
    'REQUIRE_REVERSAL_CONFIRMATION_IN_BEAR': {'type': 'bool', 'label': 'Retournement requis en bear', 'section': 'Bear Mode', 'restart': 'bot'},
    'BEAR_MODE_TRADE_MULTIPLIER': {'type': 'float', 'label': 'Multiplicateur bear', 'section': 'Bear Mode', 'min': 0.05, 'max': 1, 'restart': 'bot'},
    'BEAR_MODE_MIN_CONFIDENCE_BONUS': {'type': 'float', 'label': 'Bonus confiance bear', 'section': 'Bear Mode', 'min': 0, 'max': 80, 'restart': 'bot'},
    'BEAR_MODE_SUPPORT_TOUCH_OVERRIDE': {'type': 'bool', 'label': 'Support override en bear', 'section': 'Bear Mode', 'restart': 'bot'},
    'BEAR_MODE_ALLOWED_PAIRS': {'type': 'pairs', 'label': 'Paires autorisees en bear', 'section': 'Bear Mode', 'restart': 'bot'},
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


# Cache pour eviter de retourner un fallback vide si le fichier est temporairement illisible
_read_json_cache = {}

def read_json(path: Path, fallback):
    try:
        if not path.exists():
            return fallback
        data = json_loads(path.read_bytes())
        _read_json_cache[str(path)] = data
        return data
    except Exception:
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
    raise ValueError('doit etre True ou False')


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
            raise ValueError(f"doit etre entre {meta.get('min')} et {meta.get('max')}")
        return str(number)
    if kind == 'float':
        number = float(value)
        if number < meta.get('min', number) or number > meta.get('max', number):
            raise ValueError(f"doit etre entre {meta.get('min')} et {meta.get('max')}")
        return f"{number:g}"
    if kind == 'pairs':
        return normalize_pairs(value)
    raise ValueError('type non supporte')


def write_dashboard_env(updates):
    current = read_env_file(ENV_DASHBOARD)
    current.update(updates)

    lines = [
        '# Reglages modifiables depuis le dashboard Aegis.',
        '# Ne mettez jamais de cle API ou secret dans ce fichier.',
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
        'message': 'Les changements sont ecrits dans .env.dashboard. Redemarrage requis selon le champ.',
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
                               capture_output=True, timeout=5)
            else:
                try:
                    os.kill(pid, signal.SIGTERM)
                except Exception:
                    pass
            stopped.append(pid)
            BOT_PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass

    # Tuer également tout processus bot orphelin en arrière-plan
    try:
        if os.name == 'nt':
            cmd = 'cmd /c "taskkill /F /IM pythonw.exe"'
            subprocess.run(cmd, shell=True, capture_output=True, timeout=5)
        else:
            subprocess.run(["pkill", "-f", "run.py"], capture_output=True, timeout=5)
    except Exception:
        pass

    return stopped


def start_bot_process():
    if bot_is_running():
        return {'started': False, 'already_running': True}

    python_exe = sys.executable
    if os.name == 'nt':
        python_exe = python_exe.replace('python.exe', 'pythonw.exe')
    command = [python_exe, str(ROOT / 'run.py')]
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
    trades = []  # closed trades with net pnl
    gross_trades = []
    fees_total = 0.0
    stakes = []  # stake sizes (cost of entry)
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
                pnl_gross = filled * (px - entry['price'])
                fee_rate = pos.get('fee_rate')
                if fee_rate is not None:
                    fees = (entry['price'] * filled * float(fee_rate)) + (px * filled * float(fee_rate))
                else:
                    total_fee = float(pos.get('fee') or 0)
                    fees = total_fee * (filled / amount) if amount > 0 else 0
                pnl_net = pnl_gross - fees
                trades.append(pnl_net)
                gross_trades.append(pnl_gross)
                fees_total += fees
                stakes.append(filled * entry['price'])
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
    wins = sum(1 for t in trades if t >= -0.005)
    total_pnl_gross = sum(gross_trades)
    total_pnl = sum(trades)
    win_rate = (wins / total * 100) if total else 0
    avg_stake = (sum(stakes) / len(stakes)) if stakes else float(os.getenv('TRADE_AMOUNT', '5'))

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
        'total_pnl_gross': round(total_pnl_gross, 4),
        'total_fees': round(fees_total, 4),
        'total_pnl_net': round(total_pnl, 4),
        'total_pnl': round(total_pnl, 4),
        'days_active': round(days_active, 4),
        'avg_stake': round(avg_stake, 2),
    }


def weighted_positions(positions, trailing_stops=None, pending_orders=None, exit_recommendations=None):
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
        
        stop_loss_price = None
        is_trailing = False
        trailing_percent = float(os.getenv('TRAILING_STOP_PERCENT', '2.5'))
        if trailing_stops and data['symbol'] in trailing_stops:
            stop_loss_price = trailing_stops[data['symbol']].get('stop_price')
            is_trailing = True
            trailing_percent = float(trailing_stops[data['symbol']].get('trailing_percent', trailing_percent))
            
        # Chercher le prix de vente cible dans les ordres en attente (Paper / CCXT)
        target_price = None
        if pending_orders:
            for oid, od in pending_orders.items():
                if isinstance(od, dict) and od.get('symbol') == data['symbol'] and od.get('side') == 'sell':
                    order_info = od.get('order', od)
                    target_price = float(order_info.get('price') or 0)
                    break
                    
        # Fallback si aucun ordre de vente n'est encore placé
        if not target_price or target_price <= 0:
            min_profit = float(os.getenv('MIN_PROFIT_THRESHOLD', '0.8')) / 100
            target_price = avg_entry * (1 + min_profit)
            
        fee_pct = float(os.getenv('TRADING_FEE_PERCENT', '0.1')) * 2
        entry_val = data['amount'] * avg_entry
        exit_rec = None
        if exit_recommendations and isinstance(exit_recommendations, dict):
            exit_rec = exit_recommendations.get(data['symbol'])
        if not exit_rec:
            exit_rec = {
                "symbol": data['symbol'],
                "decision": "HOLD",
                "continuation_score": 50,
                "net_pnl_pct": 0.0,
                "reason": "initial_evaluating",
                "shadow_mode": True
            }

        result.append({
            'symbol': data['symbol'],
            'amount': data['amount'],
            'avg_entry_price': avg_entry,
            'entry_value': entry_val,
            'last_update': data['last_update'],
            'stop_loss_price': stop_loss_price,
            'is_trailing': is_trailing,
            'trailing_percent': trailing_percent,
            'target_price': target_price,
            'trading_fee_pct': fee_pct,
            'trading_fee_value': entry_val * (fee_pct / 100.0),
            'exit_recommendation': exit_rec
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
    backtest_path = project_path(os.getenv('SUPPORT_TOUCH_BACKTEST_FILE'), DATA_DIR / 'support_touch_backtest.json')
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
    keywords = ('error', 'erreur', 'permission denied', 'failed', 'echou')
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


# ===== NOUVEAU: Fonctions pour les nouvelles fonctionnalités =====

def compute_advanced_metrics(positions, paper_balance):
    """Calcule les metriques avancees: Sharpe, Profit Factor, Max Drawdown, Kelly, Expectancy"""
    buys = {}
    trades = []  # [{pnl, symbol, buy_price, sell_price, amount, buy_time, sell_time}]

    for pos in sorted(positions, key=lambda p: p.get('timestamp', '')):
        symbol = pos.get('symbol')
        side = pos.get('side')
        amount = float(pos.get('amount') or 0)
        px = float(pos.get('price') or 0)
        if not symbol or amount <= 0 or px <= 0:
            continue

        if side == 'buy':
            buys.setdefault(symbol, []).append({
                'amount': amount, 'price': px, 'ts': pos.get('timestamp')
            })
        elif side == 'sell':
            remaining = amount
            queue = buys.get(symbol, [])
            while remaining > 1e-12 and queue:
                entry = queue[0]
                filled = min(remaining, entry['amount'])
                pnl = filled * (px - entry['price'])
                pnl_pct = ((px - entry['price']) / entry['price']) * 100
                trades.append({
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'symbol': symbol,
                    'buy_price': entry['price'],
                    'sell_price': px,
                    'amount': filled,
                    'buy_time': entry.get('ts'),
                    'sell_time': pos.get('timestamp'),
                })
                entry['amount'] -= filled
                remaining -= filled
                if entry['amount'] <= 1e-12:
                    queue.pop(0)

    total = len(trades)
    if total == 0:
        return {
            'sharpe_ratio': 0,
            'profit_factor': 0,
            'max_drawdown': 0,
            'kelly_percent': 0,
            'expectancy': 0,
            'avg_win': 0,
            'avg_loss': 0,
            'total_trades': 0,
        }

    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    total_pnl = sum(t['pnl'] for t in trades)

    # Profit Factor
    gross_profit = sum(t['pnl'] for t in wins)
    gross_loss = abs(sum(t['pnl'] for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    # Win rate
    win_rate = len(wins) / total if total > 0 else 0

    # Expectancy
    avg_win = gross_profit / len(wins) if wins else 0
    avg_loss = gross_loss / len(losses) if losses else 0
    expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

    # Kelly %
    if avg_loss > 0:
        kelly = win_rate - ((1 - win_rate) / (avg_win / avg_loss)) if avg_win > 0 else 0
    else:
        kelly = win_rate
    kelly = max(0, min(kelly, 0.5))  # Cap at 50%

    # Max Drawdown (simplified: track running PnL)
    running_pnl = 0
    peak = 0
    max_dd = 0
    for t in trades:
        running_pnl += t['pnl']
        if running_pnl > peak:
            peak = running_pnl
        dd = peak - running_pnl
        if dd > max_dd:
            max_dd = dd

    # Sharpe Ratio (simplified: using trade PnL as returns)
    if len(trades) >= 2:
        pnls = [t['pnl'] for t in trades]
        avg_pnl = sum(pnls) / len(pnls)
        variance = sum((p - avg_pnl) ** 2 for p in pnls) / len(pnls)
        std = variance ** 0.5
        sharpe = (avg_pnl / std) * (252 ** 0.5) if std > 0 else 0  # Annualized
    else:
        sharpe = 0

    return {
        'sharpe_ratio': round(sharpe, 2),
        'profit_factor': round(profit_factor, 2) if profit_factor != float('inf') else 999.99,
        'max_drawdown': round(max_dd, 2),
        'kelly_percent': round(kelly * 100, 1),
        'expectancy': round(expectancy, 4),
        'avg_win': round(avg_win, 4),
        'avg_loss': round(avg_loss, 4),
        'total_trades': total,
    }


def compute_trade_history(positions):
    """Extrait l'historique complet des trades (buy/sell pairs)"""
    buys = {}
    trades = []

    for pos in sorted(positions, key=lambda p: p.get('timestamp', '')):
        symbol = pos.get('symbol')
        side = pos.get('side')
        amount = float(pos.get('amount') or 0)
        px = float(pos.get('price') or 0)
        if not symbol or amount <= 0 or px <= 0:
            continue

        if side == 'buy':
            buys.setdefault(symbol, []).append({
                'amount': amount, 'price': px, 'ts': pos.get('timestamp')
            })
        elif side == 'sell':
            remaining = amount
            queue = buys.get(symbol, [])
            while remaining > 1e-12 and queue:
                entry = queue[0]
                filled = min(remaining, entry['amount'])
                entry_value = filled * entry['price']
                pnl_gross = filled * (px - entry['price'])
                fee_rate = pos.get('fee_rate')
                if fee_rate is not None:
                    fees = (entry['price'] * filled * float(fee_rate)) + (px * filled * float(fee_rate))
                else:
                    total_fee = float(pos.get('fee') or 0)
                    fees = total_fee * (filled / amount) if amount > 0 else 0
                pnl_net = pnl_gross - fees
                pnl_gross_pct = (pnl_gross / entry_value) * 100 if entry_value else 0
                pnl_net_pct = (pnl_net / entry_value) * 100 if entry_value else 0
                trades.append({
                    'symbol': symbol,
                    'buy_price': round(entry['price'], 2),
                    'sell_price': round(px, 2),
                    'amount': round(filled, 8),
                    'pnl_gross': round(pnl_gross, 4),
                    'fees': round(fees, 4),
                    'pnl_net': round(pnl_net, 4),
                    'pnl_gross_pct': round(pnl_gross_pct, 2),
                    'pnl_net_pct': round(pnl_net_pct, 2),
                    'fee_rate': float(fee_rate) if fee_rate is not None else None,
                    'pnl': round(pnl_net, 4),
                    'pnl_pct': round(pnl_net_pct, 2),
                    'buy_time': entry.get('ts'),
                    'sell_time': pos.get('timestamp'),
                    'profitable': pnl_net >= -0.005,
                })
                entry['amount'] -= filled
                remaining -= filled
                if entry['amount'] <= 1e-12:
                    queue.pop(0)

    return sorted(trades, key=lambda t: t.get('sell_time', ''), reverse=True)


def compute_heatmap(positions):
    """Calcule les stats par crypto, par jour, par heure"""
    buys = {}
    trades = []

    for pos in sorted(positions, key=lambda p: p.get('timestamp', '')):
        symbol = pos.get('symbol')
        side = pos.get('side')
        amount = float(pos.get('amount') or 0)
        px = float(pos.get('price') or 0)
        if not symbol or amount <= 0 or px <= 0:
            continue

        if side == 'buy':
            buys.setdefault(symbol, []).append({
                'amount': amount, 'price': px, 'ts': pos.get('timestamp')
            })
        elif side == 'sell':
            remaining = amount
            queue = buys.get(symbol, [])
            while remaining > 1e-12 and queue:
                entry = queue[0]
                filled = min(remaining, entry['amount'])
                pnl = filled * (px - entry['price'])
                trades.append({
                    'symbol': symbol,
                    'pnl': pnl,
                    'buy_time': entry.get('ts'),
                    'sell_time': pos.get('timestamp'),
                })
                entry['amount'] -= filled
                remaining -= filled
                if entry['amount'] <= 1e-12:
                    queue.pop(0)

    # Par crypto
    by_crypto = defaultdict(lambda: {'trades': 0, 'wins': 0, 'total_pnl': 0.0})
    # Par jour de semaine
    by_day = defaultdict(lambda: {'trades': 0, 'wins': 0, 'total_pnl': 0.0})
    # Par heure
    by_hour = defaultdict(lambda: {'trades': 0, 'wins': 0, 'total_pnl': 0.0})

    for t in trades:
        crypto = t['symbol'].split('/')[0]
        by_crypto[crypto]['trades'] += 1
        by_crypto[crypto]['total_pnl'] += t['pnl']
        if t['pnl'] > 0:
            by_crypto[crypto]['wins'] += 1

        if t['sell_time']:
            try:
                dt = datetime.fromisoformat(t['sell_time'])
                day_name = dt.strftime('%A')
                hour = dt.hour
                by_day[day_name]['trades'] += 1
                by_day[day_name]['total_pnl'] += t['pnl']
                if t['pnl'] > 0:
                    by_day[day_name]['wins'] += 1
                by_hour[hour]['trades'] += 1
                by_hour[hour]['total_pnl'] += t['pnl']
                if t['pnl'] > 0:
                    by_hour[hour]['wins'] += 1
            except Exception:
                pass

    # Formater
    crypto_stats = [
        {
            'symbol': sym,
            'trades': d['trades'],
            'wins': d['wins'],
            'win_rate': round(d['wins'] / d['trades'] * 100, 1) if d['trades'] else 0,
            'total_pnl': round(d['total_pnl'], 4),
        }
        for sym, d in sorted(by_crypto.items(), key=lambda x: abs(x[1]['total_pnl']), reverse=True)
    ]

    day_stats = [
        {
            'day': day,
            'trades': d['trades'],
            'wins': d['wins'],
            'win_rate': round(d['wins'] / d['trades'] * 100, 1) if d['trades'] else 0,
            'total_pnl': round(d['total_pnl'], 4),
        }
        for day, d in sorted(by_day.items(), key=lambda x: ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'].index(x[0]) if x[0] in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'] else 0)
    ]

    hour_stats = [
        {
            'hour': h,
            'trades': d['trades'],
            'wins': d['wins'],
            'win_rate': round(d['wins'] / d['trades'] * 100, 1) if d['trades'] else 0,
            'total_pnl': round(d['total_pnl'], 4),
        }
        for h, d in sorted(by_hour.items())
    ]

    return {
        'by_crypto': crypto_stats,
        'by_day': day_stats,
        'by_hour': hour_stats,
    }


def compute_capital_breakdown(state, positions, paper_balance):
    """Calcule la repartition detaillee du capital"""
    # Positions ouvertes
    open_positions = weighted_positions(positions, state.get('trailing_stops'), state.get('pending_orders'), state.get('exit_recommendations'))
    total_in_positions = sum(p['entry_value'] for p in open_positions)

    # En ordres limites (pending sell orders)
    pending_orders = state.get('pending_orders') or {}
    pending_sell_value = 0
    if isinstance(pending_orders, dict):
        orders_iterable = pending_orders.values()
    elif isinstance(pending_orders, list):
        orders_iterable = pending_orders
    else:
        orders_iterable = []

    for od in orders_iterable:
        if isinstance(od, dict) and od.get('side') == 'sell':
            order = od.get('order', {})
            amount = float(order.get('amount', 0))
            price = float(order.get('price', 0))
            pending_sell_value += amount * price

    # Reserve (USD libre)
    reserve = paper_balance

    # Capital total
    total_capital = reserve + total_in_positions + pending_sell_value

    return {
        'total_capital': round(total_capital, 2),
        'available': round(reserve, 2),
        'in_positions': round(total_in_positions, 2),
        'in_limit_orders': round(pending_sell_value, 2),
        'allocated_percent': round((total_in_positions + pending_sell_value) / total_capital * 100, 1) if total_capital > 0 else 0,
        'available_percent': round(reserve / total_capital * 100, 1) if total_capital > 0 else 0,
        'positions_detail': [
            {
                'symbol': p['symbol'],
                'value': round(p['entry_value'], 2),
                'percent': round(p['entry_value'] / total_capital * 100, 1) if total_capital > 0 else 0,
            }
            for p in open_positions
        ],
    }


def compute_pnl_history(state):
    """Extrait l'historique P&L sous forme de courbe de P&L réalisé cumulé"""
    positions = state.get('positions', [])
    initial_balance = float(os.getenv('PAPER_BALANCE', '1000'))

    cumulative_pnl = 0.0
    history = [{'time': 'start', 'balance': round(initial_balance, 2), 'pnl': 0.0}]

    buys = {}
    for pos in sorted(positions, key=lambda p: p.get('timestamp', '')):
        symbol = pos.get('symbol')
        side = pos.get('side')
        amount = float(pos.get('amount') or 0)
        px = float(pos.get('price') or 0)
        if not symbol or amount <= 0 or px <= 0:
            continue

        if side == 'buy':
            buys.setdefault(symbol, []).append({
                'amount': amount, 'price': px, 'ts': pos.get('timestamp')
            })
            # Achat : le P&L réalisé ne change pas, on enregistre l'événement au même niveau
            history.append({
                'time': pos.get('timestamp'),
                'balance': round(initial_balance + cumulative_pnl, 2),
                'pnl': round(cumulative_pnl, 2),
                'event': f"Achat {symbol.split('/')[0]} @ {px:.2f}",
            })
        elif side == 'sell':
            remaining = amount
            queue = buys.get(symbol, [])
            trade_pnl = 0.0
            while remaining > 1e-12 and queue:
                entry = queue[0]
                filled = min(remaining, entry['amount'])
                trade_pnl += filled * (px - entry['price'])
                remaining -= filled
                entry['amount'] -= filled
                if entry['amount'] <= 1e-12:
                    queue.pop(0)
            
            cumulative_pnl += trade_pnl
            history.append({
                'time': pos.get('timestamp'),
                'balance': round(initial_balance + cumulative_pnl, 2),
                'pnl': round(cumulative_pnl, 2),
                'event': f"Vente {symbol.split('/')[0]} @ {px:.2f}",
            })

    return {
        'initial_balance': initial_balance,
        'current_balance': round(initial_balance + cumulative_pnl, 2),
        'total_pnl': round(cumulative_pnl, 2),
        'history': history,
    }


# ===== ROUTES =====

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/status')
def api_status():
    state = read_json(active_state_file(), {'positions': []})
    decisions = parse_jsonl(DATA_DIR / 'decision_journal.jsonl', 20)
    positions = weighted_positions(state.get('positions', []), state.get('trailing_stops'), state.get('pending_orders'), state.get('exit_recommendations'))

    stats = trade_stats(state.get('positions', []))
    
    total_decisions = 0
    try:
        with open(DATA_DIR / 'decision_journal.jsonl', 'rb') as f:
            total_decisions = sum(1 for _ in f)
    except Exception:
        total_decisions = len(decisions)

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
        'decisions': decisions,
        'total_decisions': total_decisions,
        'logs': important_logs(),
        'config': {
            'file': str(ENV_DASHBOARD.relative_to(ROOT)),
        },
    })
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.route('/api/decisions')
def api_decisions():
    limit_str = request.args.get('limit', '80')
    if limit_str == 'all':
        limit = 100000
    else:
        try:
            limit = int(limit_str)
        except ValueError:
            limit = 80

    decisions = parse_jsonl(DATA_DIR / 'decision_journal.jsonl', limit)
    
    total_count = 0
    try:
        with open(DATA_DIR / 'decision_journal.jsonl', 'rb') as f:
            total_count = sum(1 for _ in f)
    except Exception:
        total_count = len(decisions)

    return jsonify({
        'decisions': decisions,
        'total_count': total_count
    })


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
            errors[name] = 'champ non autorise'
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


@app.route('/api/bot/command', methods=['POST'])
def api_bot_command():
    try:
        data = request.get_json() or {}
        action = data.get('action')
        symbol = data.get('symbol')
        
        if not action:
            return jsonify({'ok': False, 'error': 'action is required'}), 400
            
        cmd_file = DATA_DIR / 'bot_commands.json'
        
        # Load existing commands
        commands = []
        if cmd_file.exists():
            try:
                commands = json_loads(cmd_file.read_bytes())
                if not isinstance(commands, list):
                    commands = []
            except Exception:
                commands = []
                
        # Append new command
        commands.append({
            'action': action,
            'symbol': symbol,
            'timestamp': time.time(),
            'seconds': data.get('seconds')
        })
        
        # Write back atomically
        tmp_file = DATA_DIR / 'bot_commands.json.tmp'
        tmp_file.write_text(json_dumps(commands), encoding='utf-8')
        os.replace(tmp_file, cmd_file)
        
        return jsonify({'ok': True, 'message': f'Command {action} scheduled for {symbol}'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


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


# ===== NOUVELLES ROUTES =====

@app.route('/api/analytics')
def api_analytics():
    """Endpoint pour les metriques avancees, heatmap, capital breakdown, PnL history"""
    state = read_json(active_state_file(), {'positions': []})
    positions = state.get('positions', [])
    paper_balance = state.get('paper_balance', float(os.getenv('PAPER_BALANCE', '1000')))

    advanced = compute_advanced_metrics(positions, paper_balance)
    heatmap = compute_heatmap(positions)
    capital = compute_capital_breakdown(state, positions, paper_balance)
    pnl_history = compute_pnl_history(state)

    response = jsonify({
        'advanced_metrics': advanced,
        'heatmap': heatmap,
        'capital_breakdown': capital,
        'pnl_history': pnl_history,
    })
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.route('/api/analytics/scores')
def api_analytics_scores():
    """Retourne l'historique des scores crypto pour une paire"""
    symbol = request.args.get('symbol', 'BTC/USD')
    hours = request.args.get('hours', '24')
    try:
        hours = float(hours)
    except:
        hours = 24.0
        
    score_file = DATA_DIR / 'crypto_scores.jsonl'
    if not score_file.exists():
        return jsonify([])
        
    results = []
    cutoff = datetime.now() - timedelta(hours=hours)
    
    try:
        with open(score_file, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json_loads(line.strip())
                    if entry.get('symbol') != symbol:
                        continue
                    ts_str = entry.get('timestamp')
                    if ts_str:
                        # standard fromisoformat
                        ts = datetime.fromisoformat(ts_str)
                        if ts >= cutoff:
                            results.append(entry)
                except Exception:
                    continue
    except Exception as e:
        return jsonify({'error': str(e)}), 500
        
    return jsonify(results)


@app.route('/api/trades')
def api_trades():
    """Endpoint pour l'historique complet des trades"""
    state = read_json(active_state_file(), {'positions': []})
    positions = state.get('positions', [])
    trades = compute_trade_history(positions)

    # Filtres optionnels
    symbol_filter = request.args.get('symbol', '').upper()
    profitable_filter = request.args.get('profitable', '')

    if symbol_filter:
        trades = [t for t in trades if symbol_filter in t['symbol'].upper()]
    if profitable_filter == 'win':
        trades = [t for t in trades if t['profitable']]
    elif profitable_filter == 'loss':
        trades = [t for t in trades if not t['profitable']]

    response = jsonify({
        'trades': trades,
        'total': len(trades),
    })
    response.headers['Cache-Control'] = 'no-store'
    return response
BACKTEST_PROCESS = None

@app.route('/api/support_touch/run_backtest', methods=['POST'])
def api_run_support_touch_backtest():
    global BACKTEST_PROCESS
    if BACKTEST_PROCESS and BACKTEST_PROCESS.poll() is None:
        return jsonify({'ok': False, 'error': 'Backtest is already running'}), 400
        
    python_exe = sys.executable
    command = [
        python_exe,
        str(ROOT / 'scripts' / 'backtest_support_touch.py'),
        '--output',
        str(DATA_DIR / 'support_touch_backtest.json')
    ]
    
    try:
        BACKTEST_PROCESS = subprocess.Popen(
            command,
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return jsonify({'ok': True, 'pid': BACKTEST_PROCESS.pid})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/support_touch/backtest_status', methods=['GET'])
def api_support_touch_backtest_status():
    global BACKTEST_PROCESS
    running = False
    exit_code = None
    if BACKTEST_PROCESS:
        poll_res = BACKTEST_PROCESS.poll()
        if poll_res is None:
            running = True
        else:
            exit_code = poll_res
            BACKTEST_PROCESS = None
            
    return jsonify({
        'running': running,
        'exit_code': exit_code
    })

@sock.route('/ws/live')
def ws_live(ws):
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
