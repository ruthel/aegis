import json, os, glob, datetime

files = glob.glob('data/bot_state*.json')
if not files:
    print('Aucun fichier state JSON trouve.')
else:
    for f in files:
        size = os.path.getsize(f)
        mt = datetime.datetime.fromtimestamp(os.path.getmtime(f)).isoformat()
        print(f'--- {f} ({size} bytes, modifie: {mt}) ---')
        with open(f, encoding='utf-8') as fh:
            state = json.load(fh)
        positions = state.get('positions', [])
        print(f'  positions: {len(positions)}')
        for p in positions:
            sym = p.get('symbol')
            side = p.get('side')
            status = p.get('status')
            price = p.get('price')
            oid = p.get('order_id')
            print(f'    {sym} | {side} | {status} | price={price} | order_id={oid}')
        print(f'  paper_balance: {state.get("paper_balance")}')
        pending = state.get('pending_orders', {})
        print(f'  pending_orders: {len(pending)} cles')
        for k, v in pending.items():
            print(f'    {k}: {v.get("symbol")} {v.get("side")} status={v.get("status")}')
        print()
