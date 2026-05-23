import bcrypt, asyncio, asyncmy

TARGET_EMAIL = "joseph@kbsi.re.kr"
NEW_PASSWORD = "ptm1234"

async def main():
    conn = await asyncmy.connect(
        host="mysql", port=3306,
        user="ptm_user", password="ptm_dev_pass_2026",
        db="ptm_platform"
    )
    async with conn.cursor() as cur:
        await cur.execute("SELECT id, email, name FROM users WHERE email=%s", (TARGET_EMAIL,))
        row = await cur.fetchone()
        if not row:
            print(f"ERROR: {TARGET_EMAIL} not found")
            conn.close()
            return
        uid, email, name = row
        print(f"Found: id={uid}, email={email}, name={name}")

        pw_hash = bcrypt.hashpw(NEW_PASSWORD.encode(), bcrypt.gensalt()).decode()
        await cur.execute(
            "UPDATE users SET password_hash=%s, must_change_password=1 WHERE email=%s",
            (pw_hash, TARGET_EMAIL)
        )
        await conn.commit()
        print(f"Password reset to '{NEW_PASSWORD}' (must_change_password=True)")
    conn.close()

asyncio.run(main())
