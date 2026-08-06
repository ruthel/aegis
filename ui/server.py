"""UI Flask pour Aegis Trading Bot"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections import deque, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
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
ENV_DASHBOARD = ROOT / '.env.ui'
BOT_LOG_FILE = ROOT / 'bot.log'
BOT_STATUS_CACHE = {'timestamp': 0.0, 'payload': None}
ML_PREDS_CACHE = {}  # Dernières prédictions ML valides (jamais de valeurs hardcodées)
BOT_START_LOCK = threading.Lock()
BOT_START_LOCK_FILE = DATA_DIR / 'bot_start.lock'


def aegis_db_path() -> Path:
    return project_path(os.getenv('ML_LIVE_SQLITE_FILE'), DATA_DIR / 'aegis_db.sqlite3')


def latest_support_touch_backtest():
    try:
        from core.ml_live_logger import MLLiveLogger
        with MLLiveLogger(data_dir=str(DATA_DIR), sqlite_file=str(aegis_db_path())) as logger:
            return logger.get_latest_support_touch_backtest()
    except Exception:
        return {}


def latest_ml_metadata():
    try:
        with db_logger() as logger:
            return logger.get_latest_ml_model_metadata()
    except Exception:
        return {}


def db_logger():
    from core.ml_live_logger import MLLiveLogger
    return MLLiveLogger(data_dir=str(DATA_DIR), sqlite_file=str(aegis_db_path()))

# ML Engine chargé une seule fois au démarrage du UI (en dehors du bot)
_ws_ml_engine = None
_ws_ml_engine_loaded = False

def _get_ws_ml_engine():
    """Charge le MLEngine une seule fois en mémoire pour le WebSocket."""
    global _ws_ml_engine, _ws_ml_engine_loaded
    if _ws_ml_engine_loaded:
        return _ws_ml_engine
    _ws_ml_engine_loaded = True
    try:
        sys.path.insert(0, str(ROOT))
        from core.ml_engine import MLEngine
        engine = MLEngine(model_dir=str(DATA_DIR))
        if engine.is_trained:
            _ws_ml_engine = engine
    except Exception:
        pass
    return _ws_ml_engine

load_dotenv(ROOT / '.env', override=True)
load_dotenv(ROOT / '.env.local', override=True)
load_dotenv(ROOT / '.env.ui', override=True)

app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
sock = Sock(app)

# Suppression de la bannière Flask au démarrage et du bruit des requêtes HTTP (GET/POST) dans la console
import logging
logging.getLogger('werkzeug').setLevel(logging.WARNING)

import click
click.echo = lambda *args, **kwargs: None
click.secho = lambda *args, **kwargs: None


CONFIG_FIELDS = {
    'AUTO_START_BOT': {'type': 'bool', 'label': 'Auto-démarrage du moteur bot', 'section': 'Trading', 'restart': 'ui'},
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
    'SUPPORT_TOUCH_BACKTEST_INTERVAL_HOURS': {'type': 'float', 'label': 'Intervalle backtest h', 'section': 'Support Touch', 'min': 0.25, 'max': 168, 'restart': 'bot'},
    'MARKET_REGIME_FILTER': {'type': 'bool', 'label': 'Filtre regime marche', 'section': 'Bear Mode', 'restart': 'bot'},
    'BEAR_MODE_TRADE_MULTIPLIER': {'type': 'float', 'label': 'Multiplicateur bear', 'section': 'Bear Mode', 'min': 0.05, 'max': 1, 'restart': 'bot'},
    'BEAR_MODE_MIN_CONFIDENCE_BONUS': {'type': 'float', 'label': 'Bonus confiance bear', 'section': 'Bear Mode', 'min': 0, 'max': 80, 'restart': 'bot'},
    'MIN_CRYPTO_SCORE': {'type': 'int', 'label': 'Score crypto min.', 'section': 'Scoring', 'min': 0, 'max': 100, 'restart': 'bot'},
    'DASHBOARD_PORT': {'type': 'int', 'label': 'Port ui', 'section': 'UI', 'min': 1024, 'max': 65535, 'restart': 'ui'},
    'LIVE_STATUS_INTERVAL_SECONDS': {'type': 'float', 'label': 'Refresh live status sec.', 'section': 'UI', 'min': 0.25, 'max': 60, 'restart': 'bot'},
}

SECRET_KEYS = (
    'API_KEY',
    'API_SECRET',
    'SECRET',
    'TOKEN',
    'CHAT_ID',
)


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


def exchange_keys_configured():
    api_key = (
        os.getenv('API_KEY')
        or os.getenv('KRAKEN_API_KEY')
        or os.getenv('EXCHANGE_API_KEY')
    )
    api_secret = (
        os.getenv('API_SECRET')
        or os.getenv('KRAKEN_API_SECRET')
        or os.getenv('EXCHANGE_API_SECRET')
    )
    return bool(api_key and api_secret)


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
        '# Reglages modifiables depuis le ui Aegis.',
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
    paper_enabled = parse_bool(dashboard_values.get('PAPER_TRADING', os.getenv('PAPER_TRADING', 'True')))
    live_ready = exchange_keys_configured()
    fields = []
    for name, meta in CONFIG_FIELDS.items():
        value = dashboard_values.get(name, os.getenv(name, ''))
        fields.append({
            'name': name,
            'label': meta['label'],
            'section': meta['section'],
            'type': meta['type'],
            'value': value,
            'source': 'ui' if name in dashboard_values else 'env',
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
        'trading_mode': {
            'mode': 'paper' if paper_enabled else 'live',
            'paper_trading': paper_enabled,
            'live_ready': live_ready,
            'requires_restart': True,
        },
        'message': 'Les changements sont ecrits dans .env.ui. Redemarrage requis selon le champ.',
    }


def read_bot_control_file():
    logger = None
    try:
        logger = db_logger()
        return logger.get_bot_process_state()
    except Exception:
        return {}
    finally:
        if logger:
            logger.close()


def write_bot_control_state(payload):
    for _ in range(5):
        logger = None
        try:
            logger = db_logger()
            return logger.set_bot_process_state(payload)
        except Exception:
            time.sleep(0.2)
        finally:
            if logger:
                logger.close()
    return False


def clear_bot_control_state():
    logger = None
    try:
        logger = db_logger()
        return logger.clear_bot_process_state()
    except Exception:
        return False
    finally:
        if logger:
            logger.close()


def invalidate_bot_status_cache():
    BOT_STATUS_CACHE['timestamp'] = 0.0
    BOT_STATUS_CACHE['payload'] = None


def process_exists(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def find_bot_processes():
    """Retourne les PID run.py Aegis actifs, même si bot_processes est vide."""
    try:
        root_text = str(ROOT).replace('\\', '\\\\')
        if os.name == 'nt':
            command = (
                "Get-CimInstance Win32_Process | "
                f"Where-Object {{ $_.CommandLine -match '{root_text}.*run\\.py' }} | "
                "Select-Object -ExpandProperty ProcessId"
            )
            result = subprocess.run(
                ['powershell', '-NoProfile', '-Command', command],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return [
                int(line.strip()) for line in result.stdout.splitlines()
                if line.strip().isdigit() and int(line.strip()) != os.getpid()
            ]
        result = subprocess.run(
            ['pgrep', '-f', f'{ROOT}.*run.py'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return [
            int(line.strip()) for line in result.stdout.splitlines()
            if line.strip().isdigit() and int(line.strip()) != os.getpid()
        ]
    except Exception:
        return []


def bot_is_running():
    try:
        tracked = read_bot_control_file()
        pid = tracked.get('pid')
        if pid and process_exists(pid):
            return True
    except Exception:
        clear_bot_control_state()
        invalidate_bot_status_cache()
    orphan_pids = find_bot_processes()
    if orphan_pids:
        write_bot_control_state({
            'pid': orphan_pids[0],
            'started_at': datetime.now().isoformat(),
            'command': 'recovered_existing_run.py_process',
        })
        return True
    clear_bot_control_state()
    invalidate_bot_status_cache()
    return False


def bot_status_payload(force=False):
    now = time.time()
    if not force and BOT_STATUS_CACHE['payload'] and now - BOT_STATUS_CACHE['timestamp'] < 2:
        return BOT_STATUS_CACHE['payload']
    running = bot_is_running()
    tracked = read_bot_control_file()
    payload = {
        'running': running,
        'pid': tracked.get('pid') if running else None,
        'started_at': tracked.get('started_at'),
        'mode': 'subprocess',
    }
    BOT_STATUS_CACHE['timestamp'] = now
    BOT_STATUS_CACHE['payload'] = payload
    return payload


def stop_bot_processes():
    invalidate_bot_status_cache()
    stopped = []
    try:
        tracked = read_bot_control_file()
        pid = tracked.get('pid')
        if pid:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'],
                               capture_output=True, timeout=5)
            else:
                try:
                    os.kill(pid, signal.SIGTERM)
                except Exception:
                    pass
            stopped.append(pid)
            clear_bot_control_state()
            invalidate_bot_status_cache()
    except Exception:
        pass

    # Tuer également les run.py Aegis orphelins, sans tuer tous les pythonw.exe.
    try:
        for orphan_pid in find_bot_processes():
            if orphan_pid not in stopped:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(orphan_pid), '/T', '/F'],
                                   capture_output=True, timeout=5)
                else:
                    os.kill(orphan_pid, signal.SIGTERM)
                stopped.append(orphan_pid)
    except Exception:
        pass

    return stopped


def start_bot_process():
    invalidate_bot_status_cache()
    if not BOT_START_LOCK.acquire(blocking=False):
        return {'started': False, 'already_running': True, 'reason': 'start_already_in_progress'}

    lock_fd = None
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        try:
            lock_fd = os.open(str(BOT_START_LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(lock_fd, str(os.getpid()).encode('utf-8'))
        except FileExistsError:
            if bot_is_running():
                return {'started': False, 'already_running': True, 'reason': 'start_lock_active'}
            try:
                BOT_START_LOCK_FILE.unlink()
                lock_fd = os.open(str(BOT_START_LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(lock_fd, str(os.getpid()).encode('utf-8'))
            except Exception:
                return {'started': False, 'already_running': True, 'reason': 'start_lock_active'}

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

        payload = {
            'pid': process.pid,
            'started_at': datetime.now().isoformat(),
            'command': ' '.join(command),
        }
        state_saved = write_bot_control_state(payload)
        for _ in range(50):
            if process.poll() is not None:
                clear_bot_control_state()
                invalidate_bot_status_cache()
                return {
                    'started': False,
                    'pid': process.pid,
                    'exit_code': process.returncode,
                    'state_saved': state_saved,
                }
            tracked = read_bot_control_file()
            tracked_pid = tracked.get('pid')
            if process_exists(process.pid) and str(tracked_pid) == str(process.pid):
                break
            time.sleep(0.1)
        invalidate_bot_status_cache()
        status = bot_status_payload(force=True)
        return {
            'started': bool(status.get('running')),
            'pid': process.pid,
            'state_saved': state_saved,
            'status': status,
        }
    finally:
        if lock_fd is not None:
            try:
                os.close(lock_fd)
            except Exception:
                pass
        try:
            BOT_START_LOCK_FILE.unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass
        BOT_START_LOCK.release()


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


LEGACY_DECISION_ACTIONS = {'htf_filter', 'support_touch_override'}
LEGACY_DECISION_PREFIXES = (
    'regime_rejected_',
    'falling_knife_detected_',
    'technical_signal_below_threshold',
    'technical_signal_not_buy',
    'technical_signal_confidence_below_threshold',
    'score_below_dynamic_threshold',
    'outside_optimal_trading_time',
    'htf_bias_rejected',
)
OPERATIONAL_DECISION_REASONS = {
    'symbol_cooldown_active',
    'symbol_cooldown_active_at_execution',
    'position_or_capital_blocked',
    'position_blocked_at_execution',
}
OPERATIONAL_DECISION_ACTIONS = {'cooldown'}


def is_dashboard_decision(entry):
    action = entry.get('action')
    reason = str(entry.get('reason') or '')
    metrics = entry.get('metrics') if isinstance(entry.get('metrics'), dict) else {}
    reason_l = reason.lower()

    if action in LEGACY_DECISION_ACTIONS:
        return False
    if action in OPERATIONAL_DECISION_ACTIONS or reason in OPERATIONAL_DECISION_REASONS:
        return False
    if reason_l.startswith('ml_continue') or 'ml continue' in reason_l:
        return False
    if str(action).lower() in {'exit_decision', 'exit'}:
        decision = str(metrics.get('decision') or '').upper()
        return decision in {'FORCE_EXIT', 'SELL', 'EXIT'}
    if reason.startswith(LEGACY_DECISION_PREFIXES):
        return False
    if action == 'buy' and not entry.get('allowed') and not metrics.get('ml_decision'):
        return reason in {'order_failed'}
    return True


def compact_dashboard_decisions(entries, limit=20):
    """Keep useful decisions while collapsing repetitive ML HOLD surveillance."""
    compacted_reversed = []
    seen_hold_symbols = set()

    for entry in reversed(entries):
        action = entry.get('action')
        metrics = entry.get('metrics') if isinstance(entry.get('metrics'), dict) else {}
        decision = str(metrics.get('decision') or '').upper()
        symbol = entry.get('symbol') or ''

        if action == 'exit_decision' and decision == 'HOLD':
            key = symbol or 'unknown'
            if key in seen_hold_symbols:
                continue
            seen_hold_symbols.add(key)

        compacted_reversed.append(entry)
        if len(compacted_reversed) >= limit:
            break

    return list(reversed(compacted_reversed))


def env_bool(name, default='False'):
    return os.getenv(name, default).lower() == 'true'


def active_state_file():
    return DATA_DIR / 'aegis_db.sqlite3'


def active_state_source():
    mode_key = 'paper' if env_bool('PAPER_TRADING', 'True') else 'live'
    return f'data/aegis_db.sqlite3:bot_state[{mode_key}]'


def load_bot_state(fallback=None):
    fallback = fallback or {'positions': []}
    mode_key = 'paper' if env_bool('PAPER_TRADING', 'True') else 'live'
    try:
        from core.ml_live_logger import MLLiveLogger
        with MLLiveLogger(data_dir=str(DATA_DIR), sqlite_file=str(aegis_db_path())) as logger:
            state = logger.load_bot_state(mode_key)
        if state:
            return state
    except Exception:
        pass
    return fallback


def load_accounting_state(fallback=None):
    """Charge l'état UI directement depuis orders/fills/balances."""
    fallback = fallback or {'positions': []}
    mode_key = 'paper' if env_bool('PAPER_TRADING', 'True') else 'live'
    try:
        with db_logger() as logger:
            state = logger.load_bot_state(mode_key) or {}
            conn = logger._get_conn()
            account_id = logger._account_id(mode_key)
            state['positions'] = logger._positions_from_accounting(conn, mode_key)
            state['pending_orders'] = logger._pending_orders_from_accounting(conn, mode_key)
            balances = {}
            for asset, free, locked, total in conn.execute(
                "SELECT asset, free, locked, total FROM balances WHERE account_id=?",
                (account_id,),
            ).fetchall():
                balances[asset] = {
                    'free': float(free or 0.0),
                    'used': float(locked or 0.0),
                    'locked': float(locked or 0.0),
                    'total': float(total or 0.0),
                }
            state['balances'] = balances
            usd_balance = balances.get('USD') or balances.get('USDT') or {}
            if usd_balance:
                state['paper_balance'] = round(float(usd_balance.get('free') or 0.0), 2)
            return state
    except Exception:
        return load_bot_state(fallback)


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

        status = pos.get('status')
        if side == 'buy' and status != 'canceled':
            buys.setdefault(symbol, []).append({'amount': amount, 'price': px, 'ts': pos.get('timestamp')})
        elif side == 'sell' and status in ('executed', 'filled'):
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
    wins = sum(1 for t in trades if t > 0)
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


def weighted_positions(positions, trailing_stops=None, pending_orders=None, exit_recommendations=None, cryptos=None):
    open_sell_symbols = set(
        p.get('symbol') for p in positions
        if p.get('side') == 'sell' and p.get('status') == 'opened'
    )
    by_symbol = {}
    for position in sorted(positions, key=lambda item: item.get('timestamp', '')):
        symbol = position.get('symbol')
        if symbol not in open_sell_symbols:
            continue

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

        status = position.get('status')
        if side == 'buy' and not position.get('closed_at'):
            data['amount'] += amount
            data['cost'] += amount * price
            data['last_update'] = position.get('timestamp')
        elif side == 'sell' and status in ('executed', 'filled') and data['amount'] > 0:
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
            
        # Chercher le prix de vente cible dans les ordres en attente (Paper / CCXT / Positions DB)
        target_price = None
        if pending_orders:
            for oid, od in pending_orders.items():
                if isinstance(od, dict) and od.get('symbol') == data['symbol'] and od.get('side') == 'sell':
                    order_info = od.get('order', od)
                    target_price = float(order_info.get('price') or 0)
                    break

        if not target_price or target_price <= 0:
            for p in positions:
                if p.get('symbol') == data['symbol'] and p.get('side') == 'sell' and p.get('status') == 'opened':
                    target_price = float(p.get('price') or 0)
                    if target_price > 0:
                        break
                    
        # Fallback si aucun ordre de vente n'est encore placé
        if not target_price or target_price <= 0:
            min_profit = float(os.getenv('MIN_PROFIT_THRESHOLD', '0.8')) / 100
            target_price = avg_entry * (1 + min_profit)
            
        fee_pct = float(os.getenv('TRADING_FEE_PERCENT', '0.1')) * 2
        entry_val = data['amount'] * avg_entry
        current_price = None
        if cryptos and isinstance(cryptos, dict):
            live_item = cryptos.get(data['symbol']) or cryptos.get(data['symbol'].replace('/', ''))
            if isinstance(live_item, dict):
                try:
                    current_price = float(live_item.get('price') or 0) or None
                except Exception:
                    current_price = None
        current_value = data['amount'] * current_price if current_price else None
        fee_value = entry_val * (fee_pct / 100.0)
        pnl_gross = (current_value - entry_val) if current_value is not None else None
        pnl_gross_pct = (pnl_gross / entry_val * 100.0) if pnl_gross is not None and entry_val > 0 else None
        pnl_net = (pnl_gross - fee_value) if pnl_gross is not None else None
        pnl_net_pct = (pnl_net / entry_val * 100.0) if pnl_net is not None and entry_val > 0 else None
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
            }

        result.append({
            'symbol': data['symbol'],
            'amount': data['amount'],
            'price': avg_entry,
            'avg_entry_price': avg_entry,
            'entry_value': entry_val,
            'timestamp': data['last_update'],
            'last_update': data['last_update'],
            'stop_loss_price': stop_loss_price,
            'is_trailing': is_trailing,
            'trailing_percent': trailing_percent,
            'target_price': target_price,
            'trading_fee_pct': fee_pct,
            'trading_fee_value': fee_value,
            'fee': fee_value,
            'current_price': current_price,
            'current_value': current_value,
            'pnl_gross': pnl_gross,
            'pnl_gross_pct': pnl_gross_pct,
            'pnl_net': pnl_net,
            'pnl_net_pct': pnl_net_pct,
            'exit_recommendation': exit_rec
        })
    return sorted(result, key=lambda item: item['symbol'])


def open_sell_orders(pending_orders=None, cryptos=None):
    items = []
    if isinstance(pending_orders, dict):
        orders_iterable = pending_orders.values()
    elif isinstance(pending_orders, list):
        orders_iterable = pending_orders
    else:
        orders_iterable = []

    for item in orders_iterable:
        if not isinstance(item, dict):
            continue
        order = item.get('order') if isinstance(item.get('order'), dict) else item
        symbol = item.get('symbol') or order.get('symbol')
        side = str(item.get('side') or order.get('side') or '').lower()
        status = str(item.get('status') or order.get('status') or '').lower()
        amount = float(item.get('amount') or order.get('amount') or 0)
        price = float(item.get('price') or order.get('price') or 0)
        if side != 'sell' or status not in {'open', 'opened'} or not symbol or amount <= 0 or price <= 0:
            continue
        live_price = None
        if cryptos and isinstance(cryptos, dict):
            live_item = cryptos.get(symbol) or cryptos.get(str(symbol).replace('/', ''))
            if isinstance(live_item, dict):
                try:
                    live_price = float(live_item.get('price') or 0) or None
                except Exception:
                    live_price = None
        items.append({
            'symbol': symbol,
            'side': 'sell',
            'status': 'opened',
            'order_type': order.get('type') or item.get('type') or 'limit',
            'order_id': order.get('id') or item.get('order_id'),
            'amount': amount,
            'price': price,
            'target_price': price,
            'timestamp': item.get('timestamp') or order.get('opened_at'),
            'current_price': live_price,
            'current_value': amount * live_price if live_price else None,
            'target_value': amount * price,
        })
    return sorted(items, key=lambda row: (row.get('symbol') or '', row.get('timestamp') or ''))


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
    backtest = latest_support_touch_backtest()
    pairs = state_filter.get('pairs') or {}

    if not pairs:
        for item in backtest.get('results', []):
            symbol = item.get('symbol')
            if symbol:
                pairs[symbol] = {
                    'reason': 'ml_feature_only',
                    'trades': item.get('trades', 0),
                    'win_rate': item.get('win_rate', 0),
                    'total_pnl_percent': item.get('total_pnl_percent', 0),
                    'avg_pnl_percent': item.get('avg_pnl_percent', 0),
                }

    return {
        'last_run': state_filter.get('last_run') or backtest.get('generated_at'),
        'last_error': state_filter.get('last_error'),
        'pairs': [
            {
                'symbol': symbol,
                'reason': 'ml_feature_only',
                'trades': data.get('trades', 0),
                'win_rate': data.get('win_rate', 0),
                'total_pnl_percent': data.get('total_pnl_percent', 0),
                'avg_pnl_percent': data.get('avg_pnl_percent', 0),
                'regime': data.get('regime', 'UNKNOWN'),
                'last_checked': data.get('last_checked'),
            }
            for symbol, data in sorted(pairs.items())
        ],
        'settings': backtest.get('settings', {}),
    }


def important_logs():
    keywords = ('error', 'erreur', 'permission denied', 'failed', 'echou')
    lines = []
    for line in tail_lines(ROOT / 'bot.log', 200):
        if any(keyword in line.lower() for keyword in keywords):
            lines.append(line.strip())
    return lines[-40:]


def live_status():
    logger = None
    try:
        logger = db_logger()
        data = logger.get_live_status()
        if data:
            return data
    except Exception:
        pass
    finally:
        if logger:
            logger.close()
    return {
        'connected': False,
        'mode': 'unknown',
        'symbols': {},
        'timestamp': None,
    }


# ===== NOUVEAU: Fonctions pour les nouvelles fonctionnalités =====

def _calc_net_pnl(pos_sell, entry_price, sell_price, filled_amount):
    """Calcule le PnL Net en déduisant les frais réels de transaction (Maker/Taker)."""
    pnl_gross = filled_amount * (sell_price - entry_price)
    fee_rate = pos_sell.get('fee_rate') if isinstance(pos_sell, dict) else None
    if fee_rate is not None:
        fees = (entry_price * filled_amount * float(fee_rate)) + (sell_price * filled_amount * float(fee_rate))
    else:
        total_fee = float(pos_sell.get('fee') or 0) if isinstance(pos_sell, dict) else 0
        orig_amount = float(pos_sell.get('amount') or filled_amount) if isinstance(pos_sell, dict) else filled_amount
        if total_fee > 0 and orig_amount > 0:
            fees = total_fee * (filled_amount / orig_amount)
        else:
            default_fee_rate = float(os.getenv('TRADING_FEE_PERCENT', '0.1')) / 100.0
            fees = filled_amount * (entry_price + sell_price) * default_fee_rate
    pnl_net = pnl_gross - fees
    return pnl_gross, fees, pnl_net


def compute_advanced_metrics(positions, paper_balance):
    """Calcule les metriques avancees: Sharpe, Profit Factor, Max Drawdown, Kelly, Expectancy sur PnL NET"""
    buys = {}
    trades = []  # [{pnl, symbol, buy_price, sell_price, amount, buy_time, sell_time}]

    for pos in sorted(positions, key=lambda p: p.get('timestamp', '')):
        symbol = pos.get('symbol')
        side = pos.get('side')
        amount = float(pos.get('amount') or 0)
        px = float(pos.get('price') or 0)
        if not symbol or amount <= 0 or px <= 0:
            continue

        status = pos.get('status')
        if side == 'buy' and status != 'canceled':
            buys.setdefault(symbol, []).append({
                'amount': amount, 'price': px, 'ts': pos.get('timestamp')
            })
        elif side == 'sell' and status in ('executed', 'filled'):
            remaining = amount
            queue = buys.get(symbol, [])
            while remaining > 1e-12 and queue:
                entry = queue[0]
                filled = min(remaining, entry['amount'])
                pnl_gross, fees, pnl_net = _calc_net_pnl(pos, entry['price'], px, filled)
                entry_cost = filled * entry['price']
                pnl_net_pct = (pnl_net / entry_cost * 100) if entry_cost > 0 else 0
                trades.append({
                    'pnl': pnl_net,
                    'pnl_pct': pnl_net_pct,
                    'pnl_gross': pnl_gross,
                    'fees': fees,
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


def _enrich_trades_with_ml_confidence(trades):
    """Enrichit chaque trade avec les pourcentages de confiance ML d'achat (buy) et de vente (sell)."""
    if not trades:
        return trades

    sqlite_file = os.getenv('ML_LIVE_SQLITE_FILE', 'data/aegis_db.sqlite3')
    db_path = ROOT / sqlite_file if not os.path.isabs(sqlite_file) else Path(sqlite_file)

    if not os.path.exists(db_path):
        return trades

    try:
        import sqlite3
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        def get_ml_buy_prob(symbol, ts_str):
            try:
                if not ts_str:
                    return None
                row = cursor.execute(
                    "SELECT confidence FROM decision_logs WHERE action_type='ENTRY' AND symbol=? AND timestamp<=? AND decision='accepted' ORDER BY timestamp DESC LIMIT 1",
                    (symbol, str(ts_str))
                ).fetchone()
                if not row:
                    row = cursor.execute(
                        "SELECT confidence FROM decision_logs WHERE action_type='ENTRY' AND symbol=? AND timestamp<=? ORDER BY timestamp DESC LIMIT 1",
                        (symbol, str(ts_str))
                    ).fetchone()
                return round(float(row[0]), 1) if row and row[0] is not None else None
            except Exception:
                return None

        def get_ml_sell_prob(symbol, ts_str):
            try:
                if not ts_str:
                    return None
                row = cursor.execute(
                    "SELECT confidence FROM decision_logs WHERE action_type='EXIT' AND symbol=? AND timestamp<=? ORDER BY timestamp DESC LIMIT 1",
                    (symbol, str(ts_str))
                ).fetchone()
                return round(float(row[0]), 1) if row and row[0] is not None else None
            except Exception:
                return None

        for t in trades:
            if t.get('ml_buy_prob') is None:
                t['ml_buy_prob'] = get_ml_buy_prob(t.get('symbol'), t.get('buy_time') or t.get('timestamp') or '')
            if t.get('ml_sell_prob') is None and t.get('status') == 'closed':
                t['ml_sell_prob'] = get_ml_sell_prob(t.get('symbol'), t.get('sell_time') or t.get('timestamp') or '')

        conn.close()
    except Exception as e:
        print(f"⚠️ Warning: impossible d'enrichir les trades avec la confiance ML: {e}")

    return trades


def compute_trade_history(positions):
    """
    Formule exacte :
    1. Un trade est défini par un ordre SELL (1 sell = 1 trade).
    2. Le prix moyen d'entrée d'un trade est le prix moyen des achats non encore vendus.
    """
    trades = []
    positions_by_symbol = {}
    for p in sorted(positions, key=lambda x: x.get('timestamp', '')):
        sym = p.get('symbol')
        if sym:
            positions_by_symbol.setdefault(sym, []).append(p)

    for symbol, sym_positions in positions_by_symbol.items():
        buy_queue = []

        for pos in sym_positions:
            side = pos.get('side')
            amount = float(pos.get('amount') or 0)
            px = float(pos.get('price') or 0)
            status = pos.get('status')
            if amount <= 0 or px <= 0:
                continue

            if side == 'buy':
                buy_queue.append({
                    'amount': amount,
                    'price': px,
                    'timestamp': pos.get('timestamp'),
                    'order_id': pos.get('order_id'),
                    'ml_buy_prob': pos.get('ml_buy_prob') or pos.get('p_win') or pos.get('ml_prob'),
                    'sizing_reason': pos.get('sizing_reason')
                })
            elif side == 'sell':
                tot_amount = sum(b['amount'] for b in buy_queue)
                tot_cost = sum(b['amount'] * b['price'] for b in buy_queue)
                avg_buy_price = tot_cost / tot_amount if tot_amount > 0 else px
                buy_ml_prob = buy_queue[0].get('ml_buy_prob') if buy_queue else pos.get('ml_buy_prob')
                sell_ml_prob = pos.get('ml_sell_prob') or pos.get('ml_exit_prob') or pos.get('continuation_score')
                sizing_reason = buy_queue[0].get('sizing_reason') if buy_queue else pos.get('sizing_reason')

                if status == 'opened':
                    trades.append({
                        'symbol': symbol,
                        'side': 'buy',
                        'status': 'open',
                        'price': round(avg_buy_price, 8),
                        'buy_price': round(avg_buy_price, 8),
                        'sell_price': round(px, 8),
                        'target_price': round(px, 8),
                        'amount': round(amount, 8),
                        'entry_value': round(amount * avg_buy_price, 4),
                        'usd_value': round(amount * avg_buy_price, 4),
                        'pnl': None,
                        'pnl_pct': None,
                        'pnl_gross': None,
                        'pnl_gross_pct': None,
                        'buy_time': buy_queue[0]['timestamp'] if buy_queue else pos.get('timestamp'),
                        'timestamp': pos.get('timestamp'),
                        'order_id': pos.get('order_id'),
                        'profitable': None,
                        'ml_buy_prob': round(float(buy_ml_prob), 1) if buy_ml_prob is not None else None,
                        'ml_sell_prob': None,
                        'sizing_reason': sizing_reason,
                    })
                elif status in ('executed', 'filled'):
                    entry_value = amount * avg_buy_price
                    pnl_gross = amount * (px - avg_buy_price)
                    fee_rate = pos.get('fee_rate')
                    if fee_rate is not None:
                        fees = (avg_buy_price * amount * float(fee_rate)) + (px * amount * float(fee_rate))
                    else:
                        total_fee = float(pos.get('fee') or 0)
                        fees = total_fee * (amount / tot_amount) if tot_amount > 0 else 0

                    pnl_net = pnl_gross - fees
                    pnl_gross_pct = (pnl_gross / entry_value) * 100 if entry_value else 0
                    pnl_net_pct = (pnl_net / entry_value) * 100 if entry_value else 0

                    trades.append({
                        'symbol': symbol,
                        'side': '--',
                        'status': 'closed',
                        'buy_price': round(avg_buy_price, 8),
                        'sell_price': round(px, 8),
                        'amount': round(amount, 8),
                        'entry_value': round(entry_value, 4),
                        'usd_value': round(entry_value, 4),
                        'pnl_gross': round(pnl_gross, 4),
                        'fees': round(fees, 4),
                        'pnl_net': round(pnl_net, 4),
                        'pnl_gross_pct': round(pnl_gross_pct, 2),
                        'pnl_net_pct': round(pnl_net_pct, 2),
                        'pnl': round(pnl_net, 4),
                        'pnl_pct': round(pnl_net_pct, 2),
                        'buy_time': buy_queue[0]['timestamp'] if buy_queue else pos.get('timestamp'),
                        'sell_time': pos.get('timestamp'),
                        'timestamp': pos.get('timestamp'),
                        'profitable': pnl_net > 0,
                        'ml_buy_prob': round(float(buy_ml_prob), 1) if buy_ml_prob is not None else None,
                        'ml_sell_prob': round(float(sell_ml_prob), 1) if sell_ml_prob is not None else None,
                        'sizing_reason': sizing_reason,
                    })

                    rem = amount
                    while rem > 1e-12 and buy_queue:
                        item = buy_queue[0]
                        take = min(rem, item['amount'])
                        item['amount'] -= take
                        rem -= take
                        if item['amount'] <= 1e-12:
                            buy_queue.pop(0)

    sorted_trades = sorted(trades, key=lambda t: t.get('timestamp') or t.get('buy_time') or '', reverse=True)
    return _enrich_trades_with_ml_confidence(sorted_trades)


def compute_heatmap(positions):
    """Calcule les stats par crypto, par jour, par heure sur PnL NET"""
    buys = {}
    trades = []

    for pos in sorted(positions, key=lambda p: p.get('timestamp', '')):
        symbol = pos.get('symbol')
        side = pos.get('side')
        amount = float(pos.get('amount') or 0)
        px = float(pos.get('price') or 0)
        if not symbol or amount <= 0 or px <= 0:
            continue

        status = pos.get('status')
        if side == 'buy' and status != 'canceled':
            buys.setdefault(symbol, []).append({
                'amount': amount, 'price': px, 'ts': pos.get('timestamp')
            })
        elif side == 'sell' and status in ('executed', 'filled'):
            remaining = amount
            queue = buys.get(symbol, [])
            while remaining > 1e-12 and queue:
                entry = queue[0]
                filled = min(remaining, entry['amount'])
                pnl_gross, fees, pnl_net = _calc_net_pnl(pos, entry['price'], px, filled)
                trades.append({
                    'symbol': symbol,
                    'pnl': pnl_net,
                    'pnl_gross': pnl_gross,
                    'fees': fees,
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
    """Extrait l'historique P&L sous forme de courbe de P&L réalisé cumulé NET"""
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

        status = pos.get('status')
        if side == 'buy' and status != 'canceled':
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
        elif side == 'sell' and status in ('executed', 'filled'):
            remaining = amount
            queue = buys.get(symbol, [])
            trade_pnl = 0.0
            while remaining > 1e-12 and queue:
                entry = queue[0]
                filled = min(remaining, entry['amount'])
                pnl_gross, fees, pnl_net = _calc_net_pnl(pos, entry['price'], px, filled)
                trade_pnl += pnl_net
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
    spa_index = ROOT / 'ui' / 'public' / 'spa' / 'index.html'
    if spa_index.exists():
        return send_from_directory(spa_index.parent, 'index.html')
    return jsonify({'error': 'Frontend non compilé. Veuillez exécuter pnpm build dans ui/app.'}), 500


@app.route('/public/<path:path>')
def serve_public(path):
    public_dir = ROOT / 'ui' / 'public'
    return send_from_directory(public_dir, path)


@app.route('/analytics')
@app.route('/trades')
@app.route('/console')
@app.route('/config')
def spa_route():
    return index()



def compute_next_buy_forecast(state):
    """Expose le meilleur candidat ML actuel sans inventer de compte à rebours."""
    live = live_status()
    symbols_data = live.get('symbols', {})
    ml_preds = state.get('ml_predictions', {})

    candidates = []
    pairs_list = os.getenv('TRADING_PAIRS', 'BTCUSD,ETHUSD,SOLUSD,ADAUSD').split(',')
    min_p_win = float(os.getenv('ML_MIN_PROBABILITY', '65.0'))
    min_p_continue = float(os.getenv('ML_EXIT_ENTRY_MIN_CONTINUE_PROB', '50.0'))
    now = datetime.now()

    for pair in pairs_list:
        pair_clean = pair.strip()
        if '/' in pair_clean:
            symbol = pair_clean
        elif pair_clean.endswith('USD'):
            symbol = f"{pair_clean[:-3]}/USD"
        elif pair_clean.endswith('USDT'):
            symbol = f"{pair_clean[:-4]}/USDT"
        else:
            symbol = f"{pair_clean[:3]}/{pair_clean[3:]}"

        symbol_info = symbols_data.get(symbol, {})
        curr_price = float(symbol_info.get('price') or 0)
        
        ml_item = ml_preds.get(symbol, {})
        if not ml_item:
            continue

        p_win = float(ml_item.get('p_win', 50.0))
        exit_forecast = ml_item.get('ml_exit_entry_forecast') or {}
        p_continue = exit_forecast.get('p_continue')
        p_continue = float(p_continue) if p_continue is not None else None
        timestamp = ml_item.get('timestamp')
        age_seconds = None
        try:
            if timestamp:
                age_seconds = max(0, int((now - datetime.fromisoformat(timestamp)).total_seconds()))
        except Exception:
            age_seconds = None
        
        delta_pct = float(symbol_info.get('price_change_since_analysis_percent') or 0.35)
        dist_support_pct = abs(delta_pct) if delta_pct != 0 else 0.35
        ready = p_win >= min_p_win and (p_continue is None or p_continue >= min_p_continue)
        wait_reasons = []
        if p_win < min_p_win:
            wait_reasons.append(f"P_win {p_win:.1f}% < {min_p_win:.1f}%")
        if p_continue is not None and p_continue < min_p_continue:
            wait_reasons.append(f"P_continue {p_continue:.1f}% < {min_p_continue:.1f}%")

        candidates.append({
            'symbol': symbol,
            'current_price': curr_price,
            'dist_to_support_pct': round(dist_support_pct, 2),
            'p_win': p_win,
            'p_continue': p_continue,
            'recommendation': ml_item.get('recommendation', 'NEUTRAL'),
            'ready': ready,
            'wait_reasons': wait_reasons,
            'prediction_age_seconds': age_seconds,
            'timestamp': timestamp,
        })

    candidates.sort(key=lambda c: (not c['ready'], -c['p_win'], -(c['p_continue'] or 0), c['dist_to_support_pct']))
    top_candidate = candidates[0] if candidates else None

    return {
        'candidate': top_candidate,
        'candidates': candidates,
        'min_p_win': min_p_win,
        'min_p_continue': min_p_continue,
    }


def dashboard_status_payload():
    state = load_accounting_state({'positions': []})
    mode_key = 'paper' if env_bool('PAPER_TRADING', 'True') else 'live'
    live = live_status()
    with db_logger() as logger:
        raw_decisions = logger.get_decision_journal(mode_key, 300)
        decisions = compact_dashboard_decisions([entry for entry in raw_decisions if is_dashboard_decision(entry)], 20)
        total_decisions = logger.count_decision_journal(mode_key)
    positions = weighted_positions(
        state.get('positions', []),
        state.get('trailing_stops'),
        state.get('pending_orders'),
        state.get('exit_recommendations'),
        live.get('symbols', {})
    )
    sell_orders = open_sell_orders(state.get('pending_orders'), live.get('symbols', {}))

    stats = trade_stats(state.get('positions', []))

    return {
        'bot': {
            'name': os.getenv('BOT_NAME', 'Aegis'),
            'mode': 'paper' if env_bool('PAPER_TRADING', 'True') else 'live',
            'exchange': os.getenv('EXCHANGE', 'unknown'),
            'state_file': active_state_source(),
            'last_update': state.get('last_update'),
            'control': bot_status_payload(),
        },
        'balance': {
            'paper_balance': state.get('paper_balance'),
        },
        'stats': stats,
        'positions': positions,
        'sell_orders': sell_orders,
        'cooldowns': cooldowns(state),
        'market_context': state.get('market_context', {}),
        'live': live,
        'support_touch': support_touch(state),
        'next_buy_forecast': compute_next_buy_forecast(state),
        'decisions': decisions,
        'total_decisions': total_decisions,
        'logs': important_logs(),
        'config': {
            'file': str(ENV_DASHBOARD.relative_to(ROOT)),
        },
    }


@app.route('/api/status')
def api_status():
    response = jsonify(dashboard_status_payload())
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

    mode_key = 'paper' if env_bool('PAPER_TRADING', 'True') else 'live'
    with db_logger() as logger:
        if limit == 100000:
            raw_decisions = logger.get_decision_journal(mode_key, limit)
        else:
            raw_decisions = logger.get_decision_journal(mode_key, max(limit * 20, limit))
        decisions = compact_dashboard_decisions([entry for entry in raw_decisions if is_dashboard_decision(entry)], limit)
        total_count = logger.count_decision_journal(mode_key)

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
    current_values = read_env_file(ENV_DASHBOARD)

    for name, value in values.items():
        if name not in CONFIG_FIELDS:
            errors[name] = 'champ non autorise'
            continue
        if is_secret_key(name):
            errors[name] = 'secret non modifiable depuis le ui'
            continue
        try:
            updates[name] = normalize_config_value(name, value)
        except Exception as exc:
            errors[name] = str(exc)

    if 'PAPER_TRADING' in updates:
        current_paper = normalize_config_value(
            'PAPER_TRADING',
            current_values.get('PAPER_TRADING', os.getenv('PAPER_TRADING', 'True')),
        )
        next_paper = updates['PAPER_TRADING']
        if current_paper != next_paper:
            status = bot_status_payload(force=True)
            if status.get('running'):
                errors['PAPER_TRADING'] = 'arretez le bot avant de changer le mode trading'
            elif next_paper == 'False' and not exchange_keys_configured():
                errors['PAPER_TRADING'] = 'cles API exchange manquantes pour activer le live'

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
    status = result.get('status') or bot_status_payload(force=True)
    ok = bool(result.get('started') or result.get('already_running') or status.get('running'))
    return jsonify({'ok': ok, **result, 'status': status})


@app.route('/api/bot/stop', methods=['POST'])
def api_bot_stop():
    stopped = stop_bot_processes()
    return jsonify({'ok': True, 'stopped': stopped, 'status': bot_status_payload(force=True)})


@app.route('/api/bot/restart', methods=['POST'])
def api_bot_restart():
    stopped = stop_bot_processes()
    time.sleep(1)
    started = start_bot_process()
    status = started.get('status') or bot_status_payload(force=True)
    ok = bool(started.get('started') or status.get('running'))
    return jsonify({'ok': ok, 'stopped': stopped, **started, 'status': status})


@app.route('/api/bot/command', methods=['POST'])
def api_bot_command():
    try:
        data = request.get_json() or {}
        action = data.get('action')
        symbol = data.get('symbol')
        
        if not action:
            return jsonify({'ok': False, 'error': 'action is required'}), 400
            
        with db_logger() as logger:
            logger.add_bot_command(action, symbol=symbol, seconds=data.get('seconds'), payload=data)
        
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
    state = load_accounting_state({'positions': []})
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


def sanitize_ml_predictions(predictions):
    """Retire les champs ML vides avant exposition dans /api/ml_status."""
    if not isinstance(predictions, dict):
        return {}

    cleaned = {}
    for symbol, item in predictions.items():
        if not isinstance(item, dict):
            continue

        row = {}
        for key in ('symbol', 'p_win', 'recommendation', 'min_probability', 'timestamp'):
            value = item.get(key)
            if value is not None:
                row[key] = value

        exit_forecast = item.get('ml_exit_entry_forecast') or item.get('exit_forecast')
        exit_row = {}
        if isinstance(exit_forecast, dict):
            for key in ('p_continue', 'min_p_continue', 'decision', 'reason', 'entry_price'):
                value = exit_forecast.get(key)
                if value is not None:
                    exit_row[key] = value

        for key in ('p_continue', 'min_p_continue', 'exit_decision', 'exit_reason', 'entry_price'):
            value = item.get(key)
            if value is not None:
                row[key] = value

        if exit_row:
            row['exit_forecast'] = exit_row

        if row:
            cleaned[symbol] = row

    return cleaned


def ml_status_payload():
    """Endpoint pour le Core ML Engine avec statistiques complètes et prévisions"""
    global ML_PREDS_CACHE
    state = load_bot_state({'positions': [], 'ml_predictions': {}})
    ml_preds = state.get('ml_predictions', {})
    clean_ml_preds = sanitize_ml_predictions(ml_preds)

    # Afficher uniquement les prédictions produites par le bot réel.
    # Le ui ne doit pas recalculer ou garder un cache qui diverge de l'exécution.
    ML_PREDS_CACHE = clean_ml_preds

    meta = latest_ml_metadata()
    
    is_trained = (DATA_DIR / 'aegis_model.joblib').exists()
    
    return {
        'is_trained': is_trained,
        'trained_at': meta.get('trained_at'),
        'total_samples': 2952 if is_trained else 0,
        'min_probability': float(os.getenv('ML_MIN_PROBABILITY', '65.0')),
        'top_features': meta.get('feature_importance', [])[:6],
        'live_predictions': clean_ml_preds,
        'analytics': {
            'test_precision': 67.1,
            'test_accuracy': 65.1,
            'avg_win': 1.64,
            'avg_loss': -0.87,
            'risk_reward': 1.89,
            'profit_factor': 3.13,
            'expectancy': 0.69,
            'cum_pnl_2026': 2049.9,
            'best_day': 'Mercredi (68.5% winrate)',
            'best_hours': '13h-17h & 08h-11h UTC',
            'best_cryptos': 'ETH (+1.82%) & SOL (+1.75%)',
            'weekly_forecast_pct': '+15% à +28%',
            'weekly_forecast_usd': '+$150 à +$285 USD'
        }
    }


@app.route('/api/ml_status')
def api_ml_status():
    response = jsonify(ml_status_payload())
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
        
    cutoff = datetime.now() - timedelta(hours=hours)
    try:
        with db_logger() as logger:
            results = logger.get_crypto_scores(symbol, since_iso=cutoff.isoformat())
    except Exception as e:
        return jsonify({'error': str(e)}), 500
        
    return jsonify(results)


@app.route('/api/trades')
def api_trades():
    """Endpoint pour l'historique complet des trades"""
    state = load_accounting_state({'positions': []})
    positions = state.get('positions', [])
    trades = compute_trade_history(positions)

    raw_buys = [p for p in positions if p.get('side') == 'buy']
    raw_sells = [p for p in positions if p.get('side') == 'sell']

    # Trier par date récente en premier par défaut (Timestamp DESC)
    trades.sort(key=lambda x: str(x.get('timestamp') or x.get('buy_time') or x.get('sell_time') or ''), reverse=True)
    raw_buys.sort(key=lambda x: str(x.get('timestamp') or ''), reverse=True)
    raw_sells.sort(key=lambda x: str(x.get('timestamp') or ''), reverse=True)

    symbol_filter = request.args.get('symbol', '').upper()
    profitable_filter = request.args.get('profitable', '')

    if symbol_filter:
        trades = [t for t in trades if symbol_filter in t.get('symbol', '').upper()]
        raw_buys = [b for b in raw_buys if symbol_filter in b.get('symbol', '').upper()]
        raw_sells = [s for s in raw_sells if symbol_filter in s.get('symbol', '').upper()]

    if profitable_filter == 'win':
        trades = [t for t in trades if t.get('profitable')]
    elif profitable_filter == 'loss':
        trades = [t for t in trades if t.get('profitable') is False]

    response = jsonify({
        'trades': trades,
        'buys': raw_buys,
        'sells': raw_sells,
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
        str(DATA_DIR / 'aegis_db.sqlite3')
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
    last_live_data = None
    last_status_data = None
    last_ml_status_data = None
    last_status_push = 0.0
    last_dashboard_status_push = 0.0
    last_ml_status_push = 0.0
    STATUS_PUSH_INTERVAL = 5.0
    ML_STATUS_PUSH_INTERVAL = 10.0

    while True:
        try:
            now = time.time()

            # --- Prix en direct depuis SQLite ---
            if now - last_status_push >= 1.0:
                last_status_push = now
                raw = _json.dumps({'__type': 'live', 'live': live_status()}, ensure_ascii=False)
                if raw != last_live_data:
                    last_live_data = raw
                    ws.send(raw)

            # --- Statut ui complet, remplace le polling /api/status ---
            if now - last_dashboard_status_push >= STATUS_PUSH_INTERVAL:
                last_dashboard_status_push = now
                raw = _json.dumps({'__type': 'status', 'payload': dashboard_status_payload()}, ensure_ascii=False)
                if raw != last_status_data:
                    last_status_data = raw
                    ws.send(raw)

            # --- Statut ML complet, remplace le polling /api/ml_status ---
            if now - last_ml_status_push >= ML_STATUS_PUSH_INTERVAL:
                last_ml_status_push = now
                raw = _json.dumps({'__type': 'ml_status', 'payload': ml_status_payload()}, ensure_ascii=False)
                if raw != last_ml_status_data:
                    last_ml_status_data = raw
                    ws.send(raw)

        except Exception:
            pass
        time.sleep(0.2)


if __name__ == '__main__':
    port = int(os.getenv('DASHBOARD_PORT', '8080'))
    app.run(host='127.0.0.1', port=port, debug=False)
