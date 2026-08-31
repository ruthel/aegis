"""Backtest public-data for the Support Touch Pro entry rule.

Détection des signaux d'entrée (support touch, breakout de range, pullback EMA20 15m,
croisement EMA9/EMA20 15m) + simulation de sortie réaliste (stop/breakeven/trailing).
Sert au training (génération de samples), au replay des refus et au backtest support-touch.

Usage (backtest support-touch):
    python scripts/trade_signals.py

Optional:
    python scripts/trade_signals.py --pairs BTC/USD,ETH/USD --limit 1000
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

import ccxt
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.pattern_analyzer import PatternAnalyzer


def normalize_symbol(pair):
    pair = pair.strip()
    if '/' in pair:
        return pair
    if pair.endswith('USD'):
        return f"{pair[:-3]}/USD"
    return pair


def to_kline(row):
    return {
        'timestamp': row[0],
        'open': float(row[1]),
        'high': float(row[2]),
        'low': float(row[3]),
        'close': float(row[4]),
        'volume': float(row[5]),
    }


def create_public_exchange(exchange_name):
    exchange_class = getattr(ccxt, exchange_name)
    exchange = exchange_class({'enableRateLimit': True})
    exchange.load_markets()
    return exchange


def detect_trade_signal(pattern_analyzer, history, current_price):
    if len(history) < 15:
        return None

    closes = [k['close'] for k in history]
    
    # 1. Filtre de Pente (Bloquer si pente baissière SIDEWAYS_DOWN)
    if len(closes) >= 12:
        ema10_curr = sum(closes[-10:]) / 10.0
        ema10_prev = sum(closes[-13:-3]) / 10.0
        slope = (ema10_curr - ema10_prev) / ema10_prev if ema10_prev else 0
        if slope < -0.0002:  # Pente descendante -> REJET !
            return None

    # 2. Filtre Anti-Couteau qui tombe (Falling Knife)
    last_candle = history[-1]
    open_px = float(last_candle.get('open', current_price))
    close_px = float(last_candle.get('close', current_price))
    if close_px < open_px:
        drop_pct = (open_px - close_px) / open_px
        if drop_pct >= 0.006:  # Baisse rapide sur bougie rouge -> REJET !
            return None

    # 3A. SIGNAL 1 : Support Touch PRO (Rebond sur support)
    levels = pattern_analyzer.find_support_resistance_levels(history)
    for support in levels.get('support_levels', [])[:3]:
        support_price = float(support['price'])
        rebounds = int(support.get('strength', 1))
        if current_price <= support_price * 1.001 and rebounds >= 2:
            confidence = min(85, 60 + (rebounds - 2) * 10)
            nearest_resistance = None
            for res in levels.get('resistance_levels', []):
                r_price = float(res['price'])
                if r_price > current_price * 1.002:
                    if nearest_resistance is None or r_price < nearest_resistance:
                        nearest_resistance = r_price
            
            return {
                'type': 'support_touch',
                'support_price': support_price,
                'resistance_price': nearest_resistance,
                'rebounds': rebounds,
                'confidence': confidence,
                'reason': f"Support {rebounds} rebonds @ {support_price:.2f}",
            }

    # 3B. SIGNAL 2 : Cassure Haussière de Range / Pattern Breakout
    if len(closes) >= 20:
        recent_range_high = max([k['high'] for k in history[-10:-1]])
        recent_range_low = min([k['low'] for k in history[-10:-1]])
        range_size_pct = (recent_range_high - recent_range_low) / recent_range_low
        
        # Si compression de range (< 1.8%) et la bougie actuelle casse le haut du range avec impulsion verte
        if range_size_pct < 0.018 and current_price > recent_range_high * 1.001 and close_px > open_px:
            return {
                'type': 'pattern_breakout',
                'support_price': recent_range_low,
                'resistance_price': recent_range_high * 1.02,
                'rebounds': 1,
                'confidence': 75,
                'reason': f"Cassure Haussière de Range ({recent_range_high:.2f})",
            }

    # ── SIGNAUX RAPIDES NATIFS 15m (DURCIS pour réduire les faux positifs) ──
    # Objectif: générer des samples sur des concepts qui se lisent sur le 15m lui-même
    # (pente/EMA 15m). Version stricte: pente forte + confirmation VOLUME + bougie de
    # reprise nette, pour éviter le bruit qui dégradait la précision du modèle.
    if len(closes) >= 25:
        ema9 = sum(closes[-9:]) / 9.0
        ema20 = sum(closes[-20:]) / 20.0
        ema9_prev = sum(closes[-10:-1]) / 9.0
        ema20_prev = sum(closes[-21:-1]) / 20.0
        # Pente EMA20 15m sur les 5 dernières bougies (tendance de fond COURT terme)
        ema20_older = sum(closes[-25:-5]) / 20.0 if len(closes) >= 25 else ema20_prev
        ema20_slope = (ema20 - ema20_older) / ema20_older if ema20_older else 0.0

        # Confirmation VOLUME: la bougie actuelle doit avoir un volume nettement
        # supérieur à la moyenne des 20 dernières (acheteurs réellement présents).
        vols = [float(k.get('volume', 0.0) or 0.0) for k in history[-20:]]
        avg_vol = (sum(vols) / len(vols)) if vols else 0.0
        cur_vol = float(history[-1].get('volume', 0.0) or 0.0)
        volume_confirmed = avg_vol > 0 and cur_vol >= avg_vol * 1.3

        # Corps de bougie verte NET (reprise franche, pas une micro-bougie verte)
        candle_range = float(history[-1].get('high', close_px)) - float(history[-1].get('low', close_px))
        body = close_px - open_px
        strong_green = close_px > open_px and candle_range > 0 and (body / candle_range) >= 0.5

        # SIGNAL 3 : PULLBACK SUR EMA20 15m EN TENDANCE HAUSSIÈRE (STRICT)
        # Tendance 15m FORTE (EMA9>EMA20, pente EMA20 > 0.15%), pullback SERRÉ sur l'EMA20
        # (±0.2%), reprise verte NETTE confirmée par le VOLUME.
        near_ema20 = abs(current_price - ema20) / ema20 <= 0.002 if ema20 else False
        if (ema9 > ema20 and ema20_slope > 0.0015 and near_ema20
                and strong_green and volume_confirmed):
            return {
                'type': 'ema_pullback_15m',
                'support_price': ema20 * 0.997,   # stop juste sous l'EMA20
                'resistance_price': None,
                'rebounds': 1,
                'confidence': 74,
                'reason': f"Pullback EMA20 15m fort+volume ({ema20:.4f})",
            }

        # SIGNAL 4 : CROISEMENT FRAIS EMA9/EMA20 15m (STRICT)
        # Croisement FRANC (écart EMA9-EMA20 >= 0.15%, pas un frôlement), prix AU-DESSUS
        # des deux EMA, bougie verte nette + confirmation VOLUME.
        fresh_cross = ema9 > ema20 and ema9_prev <= ema20_prev
        cross_gap = (ema9 - ema20) / ema20 if ema20 else 0.0
        price_above_emas = current_price > ema9 and current_price > ema20
        if (fresh_cross and cross_gap >= 0.0015 and price_above_emas
                and strong_green and volume_confirmed):
            recent_low_10 = min([k['low'] for k in history[-10:]])
            return {
                'type': 'ema_cross_15m',
                'support_price': recent_low_10,   # stop sous le plus bas récent
                'resistance_price': None,
                'rebounds': 1,
                'confidence': 72,
                'reason': f"Croisement EMA9>EMA20 15m ({ema9:.4f})",
            }

    return None


def detect_all_trade_signals(pattern_analyzer, history, current_price):
    """Comme detect_trade_signal, mais retourne la LISTE de TOUS les signaux qui matchent
    à cet index (au lieu du premier seulement).

    Utilisé par l'entraînement pour NE PAS écraser les signaux 15m sous support_touch:
    chaque signal applicable génère son propre sample. Les mêmes filtres (pente baissière,
    falling knife) s'appliquent globalement.
    """
    if len(history) < 15:
        return []

    closes = [k['close'] for k in history]

    # Filtres globaux (identiques à detect_trade_signal)
    if len(closes) >= 12:
        ema10_curr = sum(closes[-10:]) / 10.0
        ema10_prev = sum(closes[-13:-3]) / 10.0
        slope = (ema10_curr - ema10_prev) / ema10_prev if ema10_prev else 0
        if slope < -0.0002:
            return []

    last_candle = history[-1]
    open_px = float(last_candle.get('open', current_price))
    close_px = float(last_candle.get('close', current_price))
    if close_px < open_px:
        drop_pct = (open_px - close_px) / open_px
        if drop_pct >= 0.006:
            return []

    signals = []

    # SIGNAL 1 : Support Touch
    levels = pattern_analyzer.find_support_resistance_levels(history)
    for support in levels.get('support_levels', [])[:3]:
        support_price = float(support['price'])
        rebounds = int(support.get('strength', 1))
        if current_price <= support_price * 1.001 and rebounds >= 2:
            confidence = min(85, 60 + (rebounds - 2) * 10)
            nearest_resistance = None
            for res in levels.get('resistance_levels', []):
                r_price = float(res['price'])
                if r_price > current_price * 1.002:
                    if nearest_resistance is None or r_price < nearest_resistance:
                        nearest_resistance = r_price
            signals.append({
                'type': 'support_touch', 'support_price': support_price,
                'resistance_price': nearest_resistance, 'rebounds': rebounds,
                'confidence': confidence,
                'reason': f"Support {rebounds} rebonds @ {support_price:.2f}",
            })
            break  # un seul support suffit

    # SIGNAL 2 : Pattern Breakout
    if len(closes) >= 20:
        recent_range_high = max([k['high'] for k in history[-10:-1]])
        recent_range_low = min([k['low'] for k in history[-10:-1]])
        range_size_pct = (recent_range_high - recent_range_low) / recent_range_low
        if range_size_pct < 0.018 and current_price > recent_range_high * 1.001 and close_px > open_px:
            signals.append({
                'type': 'pattern_breakout', 'support_price': recent_range_low,
                'resistance_price': recent_range_high * 1.02, 'rebounds': 1,
                'confidence': 75,
                'reason': f"Cassure Haussière de Range ({recent_range_high:.2f})",
            })

    # SIGNAUX 15m (pullback + croisement) — mêmes conditions durcies que detect_trade_signal
    if len(closes) >= 25:
        ema9 = sum(closes[-9:]) / 9.0
        ema20 = sum(closes[-20:]) / 20.0
        ema9_prev = sum(closes[-10:-1]) / 9.0
        ema20_prev = sum(closes[-21:-1]) / 20.0
        ema20_older = sum(closes[-25:-5]) / 20.0 if len(closes) >= 25 else ema20_prev
        ema20_slope = (ema20 - ema20_older) / ema20_older if ema20_older else 0.0
        vols = [float(k.get('volume', 0.0) or 0.0) for k in history[-20:]]
        avg_vol = (sum(vols) / len(vols)) if vols else 0.0
        cur_vol = float(history[-1].get('volume', 0.0) or 0.0)
        volume_confirmed = avg_vol > 0 and cur_vol >= avg_vol * 1.3
        candle_range = float(history[-1].get('high', close_px)) - float(history[-1].get('low', close_px))
        body = close_px - open_px
        strong_green = close_px > open_px and candle_range > 0 and (body / candle_range) >= 0.5

        near_ema20 = abs(current_price - ema20) / ema20 <= 0.002 if ema20 else False
        if (ema9 > ema20 and ema20_slope > 0.0015 and near_ema20 and strong_green and volume_confirmed):
            signals.append({
                'type': 'ema_pullback_15m', 'support_price': ema20 * 0.997,
                'resistance_price': None, 'rebounds': 1, 'confidence': 74,
                'reason': f"Pullback EMA20 15m fort+volume ({ema20:.4f})",
            })

        fresh_cross = ema9 > ema20 and ema9_prev <= ema20_prev
        cross_gap = (ema9 - ema20) / ema20 if ema20 else 0.0
        price_above_emas = current_price > ema9 and current_price > ema20
        if (fresh_cross and cross_gap >= 0.0015 and price_above_emas and strong_green and volume_confirmed):
            recent_low_10 = min([k['low'] for k in history[-10:]])
            signals.append({
                'type': 'ema_cross_15m', 'support_price': recent_low_10,
                'resistance_price': None, 'rebounds': 1, 'confidence': 72,
                'reason': f"Croisement EMA9>EMA20 15m ({ema9:.4f})",
            })

    return signals


def _ema(values, period):
    """EMA simple sur une liste de closes. Retourne None si pas assez de données."""
    if not values or len(values) < period:
        return None
    k = 2.0 / (period + 1.0)
    ema = sum(values[:period]) / period  # seed = SMA des premières valeurs
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema


def simulate_trade(klines, entry_index, entry_price, support_price, stop_percent, max_hold, trailing_percent, breakeven_stop=False, breakeven_trigger=1.5, breakeven_lock=0.0, fee_rate=None, resistance_price=None, use_resistance=False, trend_exit=False, trend_confirm_bars=2):
    """Simule un trade.

    trend_exit: si True, active une SORTIE CONDITIONNELLE (basée sur les conditions de marché
    plutôt que sur une durée fixe). On sort quand la tendance haussière est invalidée:
      close(15m) < EMA20(15m)  ET  close(1h) < EMA50(1h)
    confirmé sur `trend_confirm_bars` clôtures 15m consécutives. Le stop-loss / breakeven /
    trailing restent actifs comme protection à la baisse. `max_hold` devient un simple filet
    de sécurité (rarement atteint). klines sont supposées être en 15m.
    """
    if fee_rate is None:
        fee_rate = float(os.getenv('TRADING_FEE_PERCENT', '0.4')) / 100.0
    highest_price = entry_price
    initial_percent = trailing_percent
    stop_price = entry_price * (1 - initial_percent / 100)

    # Si support technique, caler le stop initial dessous s'il est plus protecteur (1% sous le support par défaut)
    if support_price is not None:
        technical_stop = float(support_price) * (1 - stop_percent / 100)
        if technical_stop > stop_price:
            stop_price = technical_stop

    last_index = min(len(klines) - 1, entry_index + max_hold)
    current_stop_price = stop_price
    be_active = False
    trend_broken_streak = 0  # nb de clôtures 15m consécutives avec tendance cassée (EMA20-15m ET EMA50-1h)

    for exit_index in range(entry_index + 1, last_index + 1):
        candle = klines[exit_index]

        # Sortie Stop Loss dynamique
        if candle['low'] <= current_stop_price:
            return exit_index, current_stop_price, 'loss'

        # === SORTIE CONDITIONNELLE (tendance cassée) ===
        # Ne se déclenche qu'en profit-taking: le stop gère déjà la baisse. Ici on décide
        # de LAISSER COURIR (tendance intacte) vs PRENDRE LES GAINS (tendance retournée).
        if trend_exit:
            closes_hist = [float(k['close']) for k in klines[max(0, exit_index - 220):exit_index + 1]]
            close_now = closes_hist[-1]
            ema20_15m = _ema(closes_hist[-40:], 20) if len(closes_hist) >= 20 else None
            # EMA50 en 1h approximée: 1 close 15m toutes les 4 bougies (4×15m = 1h)
            closes_1h = closes_hist[::4]
            ema50_1h = _ema(closes_1h[-120:], 50) if len(closes_1h) >= 50 else None
            trend_broken = (
                ema20_15m is not None and ema50_1h is not None
                and close_now < ema20_15m and close_now < ema50_1h
            )
            if trend_broken:
                trend_broken_streak += 1
            else:
                trend_broken_streak = 0
            # Confirmé sur N clôtures consécutives -> sortie au close courant
            if trend_broken_streak >= trend_confirm_bars:
                exit_px = close_now
                outcome = 'win' if exit_px > entry_price else 'loss'
                return exit_index, exit_px, outcome

        # Mise à jour du plus haut et du trailing stop
        if candle['high'] > highest_price:
            highest_price = candle['high']
            profit_pct = ((highest_price - entry_price) / entry_price) * 100

            # SYSTEM ZÉRO PERTE (BREAKEVEN STOP)
            if breakeven_stop:
                roundtrip_fee_pct = (fee_rate * 2) * 100
                
                if use_resistance and resistance_price and resistance_price > entry_price:
                    res_dist_pct = ((resistance_price - entry_price) / entry_price) * 100
                    # Déclencher à 50% de la distance vers la résistance (au minimum les frais)
                    effective_trigger = max(roundtrip_fee_pct + 0.1, res_dist_pct * 0.5)
                    net_res_gain = max(0.0, res_dist_pct - roundtrip_fee_pct)
                    lock_profit = net_res_gain * 0.5
                    be_target_stop = entry_price * (1 + (roundtrip_fee_pct + lock_profit) / 100)
                else:
                    if breakeven_trigger == 0.0:
                        effective_trigger = roundtrip_fee_pct
                    elif breakeven_trigger < 0:
                        effective_trigger = roundtrip_fee_pct + abs(breakeven_trigger)
                    else:
                        effective_trigger = breakeven_trigger
                    be_target_stop = entry_price * (1 + (roundtrip_fee_pct + breakeven_lock) / 100)

                if profit_pct >= effective_trigger and not be_active:
                    if be_target_stop > current_stop_price:
                        current_stop_price = be_target_stop
                        be_active = True

            # Resserrement par paliers du pourcentage de trailing
            if profit_pct >= 8.0:
                percent = initial_percent * 0.4
            elif profit_pct >= 5.0:
                percent = initial_percent * 0.6
            elif profit_pct >= 3.0:
                percent = initial_percent * 0.8
            else:
                percent = initial_percent

            new_stop = highest_price * (1 - percent / 100)
            if new_stop > current_stop_price:
                current_stop_price = new_stop

    exit_price = klines[last_index]['close']
    outcome = 'win' if exit_price > entry_price else 'loss'
    return last_index, exit_price, outcome


def backtest_symbol(exchange, symbol, args):
    raw = exchange.fetch_ohlcv(symbol, args.timeframe, limit=args.limit)
    klines = [to_kline(row) for row in raw]
    analyzer = PatternAnalyzer(bot=None)
    trades = []

    # Déterminer les frais de transaction réels (Taker)
    fee_rate = float(os.getenv('TRADING_FEE_PERCENT', '0.4')) / 100.0
    try:
        market = exchange.markets.get(symbol)
        if market and market.get('taker') is not None:
            fee_rate = float(market['taker'])
    except Exception:
        pass

    next_allowed_index = 0

    for index in range(args.lookback, len(klines) - 1):
        if index < next_allowed_index:
            continue

        history = klines[:index]
        current_price = klines[index]['close']
        signal = detect_trade_signal(analyzer, history, current_price)
        if not signal:
            continue

        # Calcul dynamique max_hold
        if args.dynamic_hold:
            prices = [k['close'] for k in klines[max(0, index - 20):index]]
            if len(prices) >= 5:
                returns = [abs(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
                volatility = (sum(returns) / len(returns)) * 100
            else:
                volatility = 2.5

            if volatility >= 4.5:
                hold_hours = 3
            elif volatility >= 3.5:
                hold_hours = 5
            elif volatility >= 2.5:
                hold_hours = 7.5
            else:
                hold_hours = 12
            
            tf = args.timeframe
            if tf.endswith('m'):
                tf_mins = int(tf[:-1])
            elif tf.endswith('h'):
                tf_mins = int(tf[:-1]) * 60
            else:
                tf_mins = 15
            max_hold = int((hold_hours * 60) / tf_mins)
        else:
            max_hold = args.max_hold_candles

        exit_index, exit_price, outcome_raw = simulate_trade(
            klines,
            index,
            current_price,
            signal.get('support_price'),
            args.stop_percent,
            max_hold,
            args.trailing_percent,
            breakeven_stop=args.breakeven_stop,
            breakeven_trigger=args.breakeven_trigger,
            breakeven_lock=args.breakeven_lock,
            fee_rate=fee_rate
        )
        
        # Calculer le P&L net après frais de transaction (achat + vente)
        pnl_percent = ((exit_price * (1 - fee_rate) - current_price * (1 + fee_rate)) / current_price) * 100
        outcome = 'win' if pnl_percent > 0 else 'loss'

        trades.append({
            'entry_time': datetime.fromtimestamp(klines[index]['timestamp'] / 1000, timezone.utc).isoformat(),
            'exit_time': datetime.fromtimestamp(klines[exit_index]['timestamp'] / 1000, timezone.utc).isoformat(),
            'entry_price': current_price,
            'exit_price': exit_price,
            'pnl_percent': pnl_percent,
            'outcome': outcome,
            'hold_candles': exit_index - index,
            **signal,
        })
        next_allowed_index = exit_index + args.cooldown_candles

    wins = [trade for trade in trades if trade['outcome'] == 'win']
    losses = [trade for trade in trades if trade['outcome'] != 'win']
    total_pnl = sum(trade['pnl_percent'] for trade in trades)
    return {
        'symbol': symbol,
        'timeframe': args.timeframe,
        'candles': len(klines),
        'trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': (len(wins) / len(trades) * 100) if trades else 0,
        'total_pnl_percent': total_pnl,
        'avg_pnl_percent': (total_pnl / len(trades)) if trades else 0,
        'best_trade_percent': max((trade['pnl_percent'] for trade in trades), default=0),
        'worst_trade_percent': min((trade['pnl_percent'] for trade in trades), default=0),
        'trades_detail': trades[-20:],
    }


def parse_args():
    load_dotenv('.env.local', override=True)
    load_dotenv('.env.ui', override=True)

    parser = argparse.ArgumentParser(description='Backtest Support Touch Pro.')
    parser.add_argument('--exchange', default=os.getenv('EXCHANGE', 'kraken').lower())
    parser.add_argument('--pairs', default=os.getenv('TRADING_PAIRS', 'BTCUSD,ETHUSD'))
    parser.add_argument('--timeframe', default=os.getenv('BACKTEST_TIMEFRAME', '15m'))
    parser.add_argument('--limit', type=int, default=int(os.getenv('BACKTEST_LIMIT', '720')))
    parser.add_argument('--lookback', type=int, default=int(os.getenv('BACKTEST_LOOKBACK', '50')))
    parser.add_argument('--max-hold-candles', type=int, default=int(os.getenv('BACKTEST_MAX_HOLD_CANDLES', '96')))
    parser.add_argument('--target-percent', type=float, default=float(os.getenv('BACKTEST_TARGET_PERCENT', '1.5')))
    parser.add_argument('--stop-percent', type=float, default=float(os.getenv('BACKTEST_STOP_PERCENT', '1.0')))
    parser.add_argument('--trailing-percent', type=float, default=float(os.getenv('TRAILING_STOP_PERCENT', '2.5')))
    parser.add_argument('--cooldown-candles', type=int, default=int(os.getenv('BACKTEST_COOLDOWN_CANDLES', '4')))
    parser.add_argument('--dynamic-hold', action='store_true', help='Use dynamic max hold time based on historical volatility')
    
    be_enabled_default = os.getenv('BREAKEVEN_STOP_ENABLED', 'True').lower() == 'true'
    be_use_res_default = os.getenv('BREAKEVEN_USE_RESISTANCE', 'True').lower() == 'true'
    parser.add_argument('--breakeven-stop', action='store_true', default=be_enabled_default, help='Enable Breakeven Stop')
    parser.add_argument('--no-breakeven-stop', action='store_false', dest='breakeven_stop', help='Disable Breakeven Stop')
    parser.add_argument('--breakeven-trigger', type=float, default=float(os.getenv('BREAKEVEN_TRIGGER_PROFIT_PCT', '1.5')), help='Breakeven trigger profit %')
    parser.add_argument('--breakeven-lock', type=float, default=float(os.getenv('BREAKEVEN_LOCK_PROFIT_PCT', '1.0')), help='Breakeven lock profit % (0=fees, 1=fees+1%)')
    parser.add_argument('--breakeven-use-resistance', action='store_true', default=be_use_res_default, help='Use dynamic Resistance level for Breakeven Stop')
    
    parser.add_argument('--output', default='data/aegis_db.sqlite3')
    return parser.parse_args()


def main():
    args = parse_args()
    exchange = create_public_exchange(args.exchange)
    symbols = [normalize_symbol(pair) for pair in args.pairs.split(',') if pair.strip()]

    results = []
    for symbol in symbols:
        try:
            if symbol not in exchange.markets:
                print(f"SKIP {symbol}: market not found on {args.exchange}")
                continue
            result = backtest_symbol(exchange, symbol, args)
            results.append(result)
            print(
                f"{symbol}: {result['trades']} trades | "
                f"win {result['win_rate']:.1f}% | "
                f"avg {result['avg_pnl_percent']:+.2f}% | "
                f"total {result['total_pnl_percent']:+.2f}%"
            )
        except Exception as exc:
            print(f"ERROR {symbol}: {exc}")

    summary = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'exchange': args.exchange,
        'settings': {
            'timeframe': args.timeframe,
            'limit': args.limit,
            'lookback': args.lookback,
            'max_hold_candles': args.max_hold_candles,
            'target_percent': args.target_percent,
            'stop_percent': args.stop_percent,
            'trailing_percent': args.trailing_percent,
            'cooldown_candles': args.cooldown_candles,
        },
        'results': results,
    }

    run_id = None
    try:
        from core.ml_live_logger import MLLiveLogger
        data_dir = os.path.dirname(args.output) or 'data'
        with MLLiveLogger(
            data_dir=data_dir,
            sqlite_file=os.getenv('ML_LIVE_SQLITE_FILE', os.path.join(data_dir, 'aegis_db.sqlite3'))
        ) as logger:
            run_id = logger.record_support_touch_backtest(summary)
    except Exception:
        pass

    total_trades = sum(item['trades'] for item in results)
    total_wins = sum(item['wins'] for item in results)
    total_pnl = sum(item['total_pnl_percent'] for item in results)
    print(
        f"TOTAL: {total_trades} trades | "
        f"win {(total_wins / total_trades * 100) if total_trades else 0:.1f}% | "
        f"total {total_pnl:+.2f}%"
    )
    print(f"Saved DB: {run_id or 'aegis_db.sqlite3'}")


if __name__ == '__main__':
    main()
