import bcrypt, asyncpg, asyncio

async def check():
    conn = await asyncpg.connect(
        user='stratroom',
        password='stratroom_pw',
        database='stratroom',
        host='db',
        port=5432
    )
    for uid in [1, 91]:
        row = await conn.fetchrow(
            'SELECT id, email, hashed_password FROM users WHERE id = $1', uid
        )
        print(f'User {uid}: email={row["email"]}')
        h = row['hashed_password']
        print(f'  Hash repr: {repr(h)}')
        pw = 'changeme'.encode('utf-8')
        try:
            result = bcrypt.checkpw(pw, h.encode('utf-8'))
            print(f'  Verify changeme: {result}')
        except Exception as e:
            print(f'  Error: {e}')
    await conn.close()

asyncio.run(check())
