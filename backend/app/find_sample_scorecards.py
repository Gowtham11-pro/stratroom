import asyncio
from app.services.java_bridge import bridge

async def main():
    tables = await bridge._mysql("SHOW TABLES IN orgstructure")
    table_names = [list(t.values())[0] for t in tables]
    
    for t in table_names:
        try:
            # check string columns or json columns
            rows = await bridge._mysql(f"SELECT * FROM `{t}` LIMIT 200")
            for r in rows:
                r_str = str(r).lower()
                if "testr" in r_str or "my test" in r_str or "measure - scorecard" in r_str:
                    print(f"FOUND MATCH IN TABLE '{t}': {r}")
        except Exception as e:
            pass

if __name__ == "__main__":
    asyncio.run(main())
