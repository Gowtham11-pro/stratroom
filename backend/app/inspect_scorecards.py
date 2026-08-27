import asyncio
import json
from app.services.java_bridge import bridge

async def main():
    rows = await bridge._mysql(
        "SELECT id, page_id, score_name, owner, active, score_card_val FROM score_card ORDER BY id ASC"
    )
    print(f"Total rows in score_card: {len(rows)}")
    groups = {}
    for r in rows:
        pid = r["page_id"]
        if pid not in groups:
            groups[pid] = []
        groups[pid].append(r)
    
    print(f"Total page_id groups: {len(groups)}")
    for pid, g in groups.items():
        first = g[0]
        name = first.get("score_name") or ""
        val = first.get("score_card_val") or ""
        val_name = ""
        if val:
            try:
                vdict = json.loads(val) if isinstance(val, str) else val
                val_name = vdict.get("name") or vdict.get("score_name") or ""
            except:
                pass
        print(f"Page ID: {pid} | Min ID: {first['id']} | score_name: '{name}' | val_name: '{val_name}' | owner: {first['owner']} | active: {first['active']}")

if __name__ == "__main__":
    asyncio.run(main())
