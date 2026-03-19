import bcrypt, asyncio, asyncmy

async def main():
    conn = await asyncmy.connect(
        host="mysql", port=3306,
        user="ptm_user", password="ptm_dev_pass_2026",
        db="ptm_platform"
    )
    async with conn.cursor() as cur:
        # 현재 users 확인
        await cur.execute("SELECT id, email, name, role, LEFT(password_hash,30) FROM users")
        rows = await cur.fetchall()
        print("=== Current users ===")
        for r in rows:
            print(r)

        # admin@ptm.local 비밀번호 리셋
        pw = bcrypt.hashpw(b"admin1234", bcrypt.gensalt()).decode()
        await cur.execute(
            "UPDATE users SET password_hash=%s WHERE email='admin@ptm.local'", (pw,)
        )
        await conn.commit()
        print(f"\nUpdated rows: {cur.rowcount}")
        print("Password reset to: admin1234")

    conn.close()

asyncio.run(main())
