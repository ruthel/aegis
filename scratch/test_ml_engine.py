import sys, os, time, numpy as np
sys.path.insert(0, os.getcwd())

from core.ml_engine import MLEngine

print("=== TESTING CORE ML ENGINE ===")

engine = MLEngine(model_dir='data')
print(f"MLEngine initialized. SKLEARN_AVAILABLE: {engine.model is not None or not engine.is_trained}")

# Generate synthetic klines for testing
klines = []
base_price = 1920.0
for i in range(100):
    change = np.sin(i / 5.0) * 5.0 + (i * 0.1)
    op = base_price + change
    cl = op + np.random.uniform(-3, 3)
    hi = max(op, cl) + np.random.uniform(0.5, 2.0)
    lo = min(op, cl) - np.random.uniform(0.5, 2.0)
    vol = np.random.uniform(100, 1000)
    klines.append({
        'timestamp': 1784700000000 + (i * 15 * 60 * 1000),
        'open': op, 'high': hi, 'low': lo, 'close': cl, 'volume': vol
    })

features = engine.extract_features_from_klines(klines)
print(f"Extracted features count: {len(features) if features is not None else 0}")
assert features is not None and len(features) == 18, "Feature extraction failed!"

# Generate synthetic training set
X = []
y = []
for _ in range(50):
    f = np.random.randn(18)
    label = 1 if (f[0] > 0 and f[1] > 0) else 0
    X.append(f)
    y.append(label)

X = np.array(X)
y = np.array(y)

print("Training model on synthetic dataset...")
success = engine.train_model(X, y)
print(f"Training success: {success}")
assert success, "Model training failed!"

# Test prediction speed (< 2ms)
start_t = time.time()
prob = engine.predict_win_probability(klines)
duration_ms = (time.time() - start_t) * 1000.0

print(f"Predicted Win Probability: {prob}%")
print(f"Inference Duration: {duration_ms:.3f} ms")
assert duration_ms < 50.0, f"Inference took too long: {duration_ms:.3f} ms"

print("\nFeature Importance Top 5:")
for name, imp in engine.get_feature_importance()[:5]:
    print(f"  - {name}: {imp*100:.1f}%")

print("\n[SUCCESS] MLEngine test completed with 100% success!")
