"""
Simulates the exact login flow the api-server uses.
"""
import sys
sys.path.insert(0, "/app")

import asyncio
import asyncmy
from app.core.security import verify_password, hash_password

TEST_EMAIL = "admin@ptm.local"
TEST_PASSWORDS = ["admin1234", "ptm1234", "Passw0rd!", "admin"]

async def main():
    # 1. Check what security module is loaded
    import app.core.security as sec
    import inspect
    print("=== security.py source ===")
    print(inspect.getsource(sec.verify_password))
    print()

    # 2. Check bcrypt version
    import bcrypt
    print(f"bcrypt version: {bcrypt.__version__}")
    print()

    # 3. Connect to DB and get real hash
    conn = await asyncmy.connect(
        host="mysql", port=3306,
        user="ptm_user", password="ptm_dev_pass_2026",
        db="ptm_platform"
    )
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT id, email, password_hash, is_active FROM users WHERE email=%s",
            (TEST_EMAIL,)
        )
        row = await cur.fetchone()

    conn.close()

    if not row:
        print(f"ERROR: {TEST_EMAIL} not found in DB")
        return

    uid, email, pw_hash, is_active = row
    print(f"User: id={uid}, email={email}, is_active={is_active}")
    print(f"Hash (full): {pw_hash}")
    print()

    # 4. Test each password using app's own verify_password
    print("=== Testing passwords ===")
    for pw in TEST_PASSWORDS:
        result = verify_password(pw, pw_hash)
        print(f"  verify_password('{pw}') => {result}")

    print()
    print("=== Generating new hash for admin1234 ===")
    new_hash = hash_password("admin1234")
    print(f"  New hash: {new_hash}")
    verify_new = verify_password("admin1234", new_hash)
    print(f"  Verify new hash: {verify_new}")

asyncio.run(main())
