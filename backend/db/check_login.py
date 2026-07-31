import bcrypt, asyncpg, asyncio

async def check():
    conn = await asyncpg.connect(
        user='stratroom',
        password='stratroom_pw',
        database='stratroom',
        host='db',
        port=5432
    )
    # This is exactly what the login endpoint does
    email = 'AADH@DEMO.COM'
    row = await conn.fetchrow(
        'SELECT hashed_password FROM users WHERE email = $1',
        email
    )
    print(f'Looking up: {repr(email)}')
    print('Row found:', row is not None)
    if row:
        h = row['hashed_password']
        print('Hash:', repr(h))
        result = bcrypt.checkpw(b'changeme', h.encode('utf-8'))
        print('Verify:', result)
    await conn.close()

asyncio.run(check())
