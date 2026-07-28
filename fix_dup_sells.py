import json, os
from collections import defaultdict

for fname in ['data/bot_state_paper.json', 'data/bot_state.json']:
    if not os.path.exists(fname):
        continue
    with open(fname, 'r', encoding='utf-8') as f:
        state = json.load(f)

    positions = state.get('positions', [])

    by_symbol = defaultdict(list)
    for p in positions:
        if p.get('side') == 'sell':
            by_symbol[p.get('symbol')].append(p)

    to_remove = []
    for symbol, sells in by_symbol.items():
        opened = [s for s in sells if s.get('status') == 'opened']
        executed = [s for s in sells if s.get('status') == 'executed']
        if opened and executed:
            op = opened[0]
            ex = executed[0]
            op['status'] = 'executed'
            op['price'] = ex['price']
            op['order_id'] = ex.get('order_id', op.get('order_id'))
            for k in ('fee', 'pnl', 'fee_rate', 'position_size_usd', 'position_size_crypto'):
                if ex.get(k) is not None:
                    op[k] = ex[k]
            print('Fusionne', symbol, '-> executed @', op['price'])
            to_remove.append(id(ex))

    positions = [p for p in positions if id(p) not in to_remove]
    state['positions'] = positions

    with open(fname, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    print('State mis a jour:', fname)
