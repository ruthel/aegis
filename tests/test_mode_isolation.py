import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


class ModeIsolationAndCheckpointTests(unittest.TestCase):
    def read(self, rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_grid_checkpoint_survives_completed_search_and_resumes_without_rescoring(self):
        from core.ml_engine import MLEngine

        rng = np.random.default_rng(991)
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {
            "ML_GRID_CACHE_ENABLED": "True",
            "ML_GRID_CACHE_DIR": td,
            "ML_GRID_RESUME": "True",
            "ML_GRID_REUSE_BEST": "False",
            "ML_GRID_RESEARCH_ON_DRIFT": "False",
            "ML_GRID_FORCE_SEARCH": "False",
        }, clear=False):
            engine = MLEngine(model_dir=td)
            X = rng.normal(size=(140, 5))
            y = (X[:, 0] > 0).astype(int)
            grid = {
                "n_estimators": [10, 20],
                "max_depth": [2],
                "min_samples_split": [2],
                "min_samples_leaf": [1],
            }

            calls = []
            def fake_score(model_type, params, X_train, y_train, sample_weight, splits):
                calls.append(dict(params))
                score = 0.70 if params["n_estimators"] == 10 else 0.75
                return score, [score, score]

            with patch.object(engine, "_score_grid_candidate", side_effect=fake_score):
                best, _, mode, tested, total = engine._select_entry_grid_params(
                    X, y, None, "random_forest", grid, 2
                )

            checkpoint_path, best_path = engine._grid_cache_paths("random_forest")
            self.assertTrue(Path(checkpoint_path).exists())
            self.assertTrue(Path(best_path).exists())
            self.assertEqual(mode, "full_search")
            self.assertEqual(tested, 2)
            self.assertEqual(total, 2)
            self.assertEqual(best["n_estimators"], 20)

            checkpoint = json.loads(Path(checkpoint_path).read_text(encoding="utf-8"))
            self.assertEqual(checkpoint.get("status"), "completed")
            self.assertEqual(len(checkpoint.get("completed") or {}), 2)

            with patch.object(
                engine,
                "_score_grid_candidate",
                side_effect=AssertionError("completed candidates must remain checkpointed"),
            ):
                best2, _, mode2, tested2, total2 = engine._select_entry_grid_params(
                    X, y, None, "random_forest", grid, 2
                )
            self.assertEqual(mode2, "resume_search")
            self.assertEqual(tested2, 0)
            self.assertEqual(total2, 2)
            self.assertEqual(best2["n_estimators"], 20)
            self.assertTrue(Path(checkpoint_path).exists())
            self.assertTrue(Path(best_path).exists())

    def test_dashboard_has_single_server_owned_trading_mode(self):
        store = self.read("ui/app/src/store/dashboard-store.ts")
        types = self.read("ui/app/src/types/dashboard.ts")
        app = self.read("ui/app/src/App.tsx")
        live_view = self.read("ui/app/src/views/LiveView.tsx")

        self.assertNotIn("VIEW_MODE_STORAGE_KEY", store)
        self.assertNotIn("localStorage.getItem", store)
        self.assertNotIn("?view_mode=", store)
        self.assertNotIn("?view_mode=", app)
        self.assertNotIn("| 'all'", types)
        self.assertNotIn("=== 'all'", live_view)
        self.assertIn("serverViewMode", store)
        self.assertIn("Vue {asString(bot?.view_mode ?? bot?.mode", app)

    def test_server_never_merges_operational_paper_and_live_views(self):
        server = self.read("ui/server.py")
        self.assertIn("PAPER_BOT_LOG_FILE", server)
        self.assertIn("LIVE_BOT_LOG_FILE", server)
        self.assertIn("PAPER_REPLAY_LOG_FILE", server)
        self.assertIn("LIVE_REPLAY_LOG_FILE", server)
        self.assertIn("return [active_trading_mode()]", server)
        self.assertIn("WHERE mode=?", server)
        self.assertNotIn("selected_view != 'all'", server)
        self.assertIn("arretez le replay ML du mode actif avant de changer de mode", server)
        self.assertIn("attendez la fin du retraining/promotion avant de changer de mode", server)

    def test_telegram_status_and_history_are_scoped_to_notifier_mode(self):
        notification = self.read("core/managers/notification.py")
        self.assertNotIn("view_mode='live'", notification)
        self.assertNotIn("get_live_market_data", notification)
        self.assertNotIn("target_model", notification)
        self.assertIn("def _active_mode(self):", notification)
        self.assertIn("telegram_last_daily_status_day:{self._active_mode()}", notification)
        self.assertIn("mode=self._active_mode()", notification)
        self.assertIn("if trading_mode == 'live':", notification)

    def test_safe_fallback_drift_is_mode_scoped(self):
        source = self.read("core/trading_bot.py")
        start = source.index("def _collect_safe_fallback_signals")
        block = source[start:start + 5000]
        self.assertIn("WHERE mode=?", block)
        self.assertIn("(active_mode,)", block)

    def test_telegram_and_governance_rows_have_mode(self):
        orm = self.read("core/db_orm.py")
        logger = self.read("core/ml_live_logger.py")
        notification_block = orm[orm.index("class Notification"):orm.index("class MlShadowPrediction")]
        governance_block = orm[orm.index("class GovernanceLog"):orm.index("Index('idx_sys_audit")]
        self.assertIn("mode:", notification_block)
        self.assertIn("mode:", governance_block)
        self.assertIn("def record_telegram_message", logger)
        self.assertIn("mode=None", logger[logger.index("def record_telegram_message"):logger.index("def _insert_telegram_message")])
        self.assertIn("def record_governance_event", logger)

    def test_ui_server_logger_calls_reference_existing_logger_methods(self):
        server = self.read("ui/server.py")
        logger = self.read("core/ml_live_logger.py")
        called = set(re.findall(r"\blogger\.([A-Za-z_]\w*)\s*\(", server))
        defined = set(re.findall(r"^\s*def\s+([A-Za-z_]\w*)\s*\(", logger, re.MULTILINE))
        missing = sorted(called - defined)
        self.assertEqual(missing, [], f"ui/server.py appelle des méthodes logger absentes: {missing}")

    def test_removed_target_head_does_not_reappear_in_runtime_surfaces(self):
        for rel in (
            "core/ml_engine.py",
            "core/trading_bot.py",
            "core/managers/notification.py",
            "scripts/train_and_evaluate_ml_model.py",
            "ui/server.py",
        ):
            source = self.read(rel)
            self.assertNotIn("train_target_model", source, rel)
            self.assertNotIn("target_model", source, rel)


if __name__ == "__main__":
    unittest.main()
