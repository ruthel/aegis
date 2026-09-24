import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


class ScriptsAlignmentTests(unittest.TestCase):
    def read(self, name):
        return (SCRIPTS / name).read_text(encoding="utf-8")

    def test_all_scripts_use_unified_env(self):
        for path in SCRIPTS.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn(".env.local", source, path.name)
            self.assertNotIn(".env.ui", source, path.name)

    def test_no_obsolete_fee_fallbacks(self):
        for path in SCRIPTS.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("TRADING_FEE_PERCENT', '0.1'", source, path.name)
            self.assertNotIn('TRADING_FEE_PERCENT", "0.1"', source, path.name)

    def test_training_uses_same_best_signal_as_live(self):
        source = self.read("train_and_evaluate_ml_model.py")
        self.assertIn("best_signal = signal_engine.detect_best", source)
        self.assertNotIn("signals_here = signal_engine.detect_all", source)
        self.assertIn("btc_context_index", source)

    def test_training_delegates_promotion_to_single_policy(self):
        source = self.read("train_and_evaluate_ml_model.py")
        self.assertIn("from scripts.promote_challenger import promote", source)
        self.assertIn("promote(", source)
        self.assertNotIn("PROMOTION DU CHALLENGER EN CHAMPION", source)

    def test_walk_forward_cannot_write_champion(self):
        source = self.read("walk_forward_validation.py")
        self.assertIn("tempfile.TemporaryDirectory", source)
        self.assertIn("window_model.joblib", source)
        self.assertIn("predict_win_probability_from_features", source)
        self.assertIn("predict_expected_net_pnl", source)
        self.assertNotIn("MLEngine(model_dir='data')", source)

    def test_exit_backtest_matches_current_stack(self):
        source = self.read("backtest_ml_exit_comparison.py")
        self.assertIn("SignalEngine", source)
        self.assertIn("predict_win_probability_from_features", source)
        self.assertIn("predict_expected_net_pnl", source)
        self.assertIn("BTC/USD,ETH/USD,SOL/USD,ADA/USD", source)
        self.assertNotIn("/USDT", source)
        self.assertIn("TRADING_FEE_PERCENT", source)
        self.assertIn('"0.4"', source)

    def test_sizing_backtest_is_notional_normalized(self):
        source = self.read("backtest_ml_sizing.py")
        self.assertIn("reference_notional", source)
        self.assertIn("baseline_trade_pnl", source)
        self.assertIn("--notional", source)

    def test_feature_importance_is_normalized_and_includes_edge(self):
        source = self.read("analyze_feature_importance.py")
        self.assertIn("normalized =", source)
        self.assertIn("edge_model", source)
        self.assertIn("EXPECTED NET PNL", source)

    def test_kraken_archive_is_integrated(self):
        archive = self.read("archive_kraken_ohlcv.py")
        training = self.read("train_and_evaluate_ml_model.py")
        env = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("def archive_universe", archive)
        self.assertIn("archive_universe(", training)
        self.assertIn("ML_ARCHIVE_KRAKEN_BEFORE_TRAIN=True", env)
        self.assertIn("ML_PREFER_KRAKEN_ARCHIVE=True", env)
        self.assertIn("ML_KRAKEN_ARCHIVE_REQUIRE_ALL_TIMEFRAMES=True", env)
        self.assertIn("_kraken_archive_symbol_ready", training)

    def test_trade_signal_wrapper_uses_canonical_all_signals(self):
        source = self.read("trade_signals.py")
        wrapper = source[source.index("def detect_trade_signal"):source.index("def detect_all_trade_signals")]
        self.assertIn("detect_all_trade_signals", wrapper)
        self.assertIn("max(", wrapper)

    def test_market_structure_context_uses_live_depth(self):
        training = self.read("train_and_evaluate_ml_model.py")
        self.assertIn("cur_4h - 80", training)
        self.assertIn("cur_1d - 80", training)
        self.assertIn("cur_1h - 40", training)
        self.assertIn("cur_4h - 30", training)
        self.assertIn("cur_1d - 30", training)
        backtest = self.read("backtest_ml_exit_comparison.py")
        self.assertIn('ctx_h4, _ = _slice_until(bundle["4h"], ts, 80)', backtest)
        self.assertIn('ctx_1d, _ = _slice_until(bundle["1d"], ts, 80)', backtest)

    def test_env_example_keys_are_referenced_by_runtime(self):
        env_path = ROOT / ".env.example"
        keys = []
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key = line.split("=", 1)[0].strip()
                if key and key.replace("_", "").isalnum() and key.upper() == key:
                    keys.append(key)

        runtime_chunks = []
        allowed_suffixes = {".py", ".sh", ".bat", ".ps1", ".yml", ".yaml", ".ts", ".tsx", ".js"}
        for path in ROOT.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in allowed_suffixes:
                continue
            rel = path.relative_to(ROOT).as_posix()
            if (
                rel.startswith("tests/")
                or rel.startswith("docs/")
                or rel.startswith("ui/public/spa/")
                or "/node_modules/" in rel
            ):
                continue
            try:
                runtime_chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                pass

        runtime_text = "\n".join(runtime_chunks)
        unused = sorted(key for key in keys if key not in runtime_text)
        self.assertEqual(unused, [], f"Variables .env.example sans référence runtime: {unused}")

    def test_db_checker_is_configurable(self):
        source = self.read("check_db_tables.py")
        self.assertIn("ML_LIVE_SQLITE_FILE", source)
        self.assertIn("--db", source)


if __name__ == "__main__":
    unittest.main()
