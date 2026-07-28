import sqlite3, os, shutil

# 1. Vider toutes les tables de la BD
conn = sqlite3.connect('data/aegis_db.sqlite3', timeout=10)
c = conn.cursor()
tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
for t in tables:
    try:
        c.execute(f'DELETE FROM {t}')
        print(f'  Cleared: {t}')
    except Exception as e:
        print(f'  Skip {t}: {e}')
conn.commit()
conn.close()
print('✅ BD vidée.')

# 2. Supprimer les fichiers JSON de state (cache bot)
state_files = [
    'data/bot_state_paper.json',
    'data/bot_state_live.json',
    'data/bot_state.json',
]
for f in state_files:
    if os.path.exists(f):
        os.remove(f)
        print(f'  Deleted: {f}')

# 3. Supprimer les caches Python __pycache__
for root, dirs, files in os.walk('.'):
    for d in dirs:
        if d == '__pycache__':
            path = os.path.join(root, d)
            shutil.rmtree(path)
            print(f'  Cache supprimé: {path}')

print('✅ Reset complet.')
