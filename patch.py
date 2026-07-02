with open('/home/yz_wang/yz_main/Agora_UI_Run/agora_ui/live_world.py', 'r') as f:
    code = f.read()

import sys

target = """        completed_offer = self._set_trade_offer_status(
            offer,
            status="completed",
            note="trade_settled",
            response_text=response_text,
            completed_at=_now_iso(),
        )"""

replacement = """        completed_offer = self._set_trade_offer_status(
            offer,
            status="completed",
            note="trade_settled",
            response_text=response_text,
            completed_at=_now_iso(),
        )
        import sys
        print(f"DEBUG: Trade completed. Buyer ({buyer_row['agent_id']}) inventory: {[e['item_id'] for e in buyer_state.get('inventory', [])]}. Seller ({seller_row['agent_id']}) inventory: {[e['item_id'] for e in seller_state.get('inventory', [])]}", file=sys.stderr)"""

if target in code:
    code = code.replace(target, replacement)
    with open('/home/yz_wang/yz_main/Agora_UI_Run/agora_ui/live_world.py', 'w') as f:
        f.write(code)
    print("Patched successfully")
else:
    print("Could not find target block")
