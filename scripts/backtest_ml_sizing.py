"""Replay du sizing ML sur les trades fermes.

Compare une taille fixe 1.0x avec le facteur propose par le modele sizing
actif, puis stocke un resume dans ml_sizing_backtests.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.ml_engine import MLEngine


def init_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ml_sizing_backtests (
            run_id TEXT PRIMARY KEY,
            generated_at TEXT NOT NULL,
            model_path TEXT,
            samples INTEGER,
            baseline_pnl_usd REAL,
            sizing_pnl_usd REAL,
            pnl_delta_usd REAL,
            avg_sizing_factor REAL,
            min_sizing_factor REAL,
            max_sizing_factor REAL,
            positive_samples INTEGER,
            negative_samples INTEGER,
            details_json TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ml_sizing_backtests_time ON ml_sizing_backtests (generated_at)")


def fetch_features(conn: sqlite3.Connection, entry_id: str) -> dict[str, float]:
    rows = conn.execute(
        """
        SELECT feature_name, feature_value
        FROM ml_feature_values
        WHERE event_id=?
        """,
        (entry_id,),
    ).fetchall()
    return {
        str(name): float(value)
        for name, value in rows
        if value is not None
    }


def replay(db_path: Path, model_path: Path, limit: int) -> dict:
    engine = MLEngine()
    engine.model_path = str(model_path)
    engine.load_model()
    if not getattr(engine, "is_sizing_trained", False):
        raise RuntimeError("Le modele actif ne contient pas de sizing_model entraine.")

    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    init_table(conn)

    rows = conn.execute(
        """
        SELECT event_id, timestamp, symbol, entry_id, pnl, pnl_pct, buy_price, sell_price, amount,
               'closed_trade' AS source
        FROM ml_trade_outcomes
        WHERE entry_id IS NOT NULL
          AND pnl IS NOT NULL
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()

    details = []
    baseline_pnl = 0.0
    sizing_pnl = 0.0
    factors = []
    positive = 0
    negative = 0

    replay_rows = conn.execute(
        """
        SELECT entry_id AS event_id, timestamp, symbol, entry_id,
               (? * (pnl_pct / 100.0)) AS pnl, pnl_pct,
               entry_price AS buy_price, exit_price AS sell_price,
               NULL AS amount, 'rejected_replay' AS source
        FROM ml_rejected_replay_results
        WHERE replay_status='replayed'
          AND entry_id IS NOT NULL
          AND pnl_pct IS NOT NULL
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (float(os.getenv("TRADE_AMOUNT", "50")), int(limit)),
    ).fetchall()

    for row in list(rows) + list(replay_rows):
        pnl = float(row["pnl"] or 0.0)
        features = fetch_features(conn, row["entry_id"])
        if not features:
            continue
        ordered_features = getattr(engine, "sizing_feature_names", getattr(engine, "feature_names", []))
        feature_vector = np.array([float(features.get(name, 0.0) or 0.0) for name in ordered_features], dtype=np.float64)
        pred = engine.predict_position_size_factor(features=feature_vector)
        factor = float(pred.get("sizing_factor") or 1.0)
        baseline_pnl += pnl
        sizing_pnl += pnl * factor
        factors.append(factor)
        if pnl >= 0:
            positive += 1
        else:
            negative += 1
        details.append(
            {
                "event_id": row["event_id"],
                "entry_id": row["entry_id"],
                "source": row["source"],
                "timestamp": row["timestamp"],
                "symbol": row["symbol"],
                "pnl_usd": round(pnl, 4),
                "pnl_pct": row["pnl_pct"],
                "sizing_factor": round(factor, 3),
                "sizing_pnl_usd": round(pnl * factor, 4),
                "reason": pred.get("reason"),
            }
        )

    generated_at = datetime.now().isoformat()
    summary = {
        "run_id": f"sizing_backtest_{generated_at.replace(':', '').replace('.', '')}",
        "generated_at": generated_at,
        "model_path": str(model_path),
        "samples": len(details),
        "baseline_pnl_usd": round(baseline_pnl, 4),
        "sizing_pnl_usd": round(sizing_pnl, 4),
        "pnl_delta_usd": round(sizing_pnl - baseline_pnl, 4),
        "avg_sizing_factor": round(sum(factors) / len(factors), 4) if factors else None,
        "min_sizing_factor": round(min(factors), 4) if factors else None,
        "max_sizing_factor": round(max(factors), 4) if factors else None,
        "positive_samples": positive,
        "negative_samples": negative,
        "details": details[:100],
    }

    conn.execute(
        """
        INSERT OR REPLACE INTO ml_sizing_backtests (
            run_id, generated_at, model_path, samples, baseline_pnl_usd, sizing_pnl_usd,
            pnl_delta_usd, avg_sizing_factor, min_sizing_factor, max_sizing_factor,
            positive_samples, negative_samples, details_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            summary["run_id"],
            summary["generated_at"],
            summary["model_path"],
            summary["samples"],
            summary["baseline_pnl_usd"],
            summary["sizing_pnl_usd"],
            summary["pnl_delta_usd"],
            summary["avg_sizing_factor"],
            summary["min_sizing_factor"],
            summary["max_sizing_factor"],
            summary["positive_samples"],
            summary["negative_samples"],
            json.dumps(summary["details"], ensure_ascii=False),
            generated_at,
            generated_at,
        ),
    )
    conn.commit()
    conn.close()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest/replay du sizing ML.")
    parser.add_argument("--db", default=os.getenv("ML_LIVE_SQLITE_FILE", "data/aegis_db.sqlite3"))
    parser.add_argument("--model", default="data/aegis_model.joblib")
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()

    summary = replay(Path(args.db), Path(args.model), args.limit)
    print("======================================================================")
    print("REPLAY SIZING ML")
    print("======================================================================")
    print(f"Samples: {summary['samples']}")
    print(f"Baseline PnL: {summary['baseline_pnl_usd']:.2f} USD")
    print(f"Sizing ML PnL: {summary['sizing_pnl_usd']:.2f} USD")
    print(f"Delta: {summary['pnl_delta_usd']:+.2f} USD")
    print(f"Facteur moyen: {summary['avg_sizing_factor']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
