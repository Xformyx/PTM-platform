import bcrypt, asyncio, asyncmy

TEST_PASSWORD = "admin1234"

async def main():
    conn = await asyncmy.connect(
        host="mysql", port=3306,
        user="ptm_user", password="ptm_dev_pass_2026",
        db="ptm_platform"
    )
    async with conn.cursor() as cur:
        await cur.execute("SELECT id, email, name, role, password_hash FROM users WHERE email='admin@ptm.local'")
        row = await cur.fetchone()
        if not row:
            print("ERROR: admin@ptm.local 계정이 DB에 없습니다!")
            conn.close()
            return

        uid, email, name, role, pw_hash = row
        print(f"Found user: id={uid}, email={email}, name={name}, role={role}")
        print(f"Hash prefix: {pw_hash[:30]}")

        # bcrypt로 검증
        ok = bcrypt.checkpw(TEST_PASSWORD.encode(), pw_hash.encode())
        print(f"\nbcrypt.checkpw('{TEST_PASSWORD}', hash) => {ok}")

        if not ok:
            print("\n→ 비밀번호가 틀림. 지금 리셋합니다...")
            new_hash = bcrypt.hashpw(TEST_PASSWORD.encode(), bcrypt.gensalt()).decode()
            await cur.execute(
                "UPDATE users SET password_hash=%s WHERE email='admin@ptm.local'", (new_hash,)
            )
            await conn.commit()
            print(f"→ 리셋 완료! Updated rows: {cur.rowcount}")
            print(f"→ 이제 Admin / {TEST_PASSWORD} 로 로그인하세요.")
        else:
            print(f"\n→ DB 비밀번호는 정상입니다. api-server 로그를 확인하세요.")

    conn.close()

asyncio.run(main())
