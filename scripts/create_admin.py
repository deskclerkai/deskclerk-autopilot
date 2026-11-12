#!/usr/bin/env python3
"""在空库上创建第一个老板账号。

用法：
    DEMO_SEED=0 python3 scripts/create_admin.py you@company.com '强密码至少8位' '你的名字'
"""
import os
import sys

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, APP)

from auth import hash_password  # noqa: E402
from db import init_db, now, q1, run  # noqa: E402


def main():
    if len(sys.argv) < 4:
        print("用法: python3 scripts/create_admin.py <email> <password> <name>")
        return 2
    email, pwd, name = sys.argv[1].strip().lower(), sys.argv[2], sys.argv[3].strip()
    if "@" not in email or len(pwd) < 8 or not name:
        print("邮箱要合法、密码至少 8 位、名字不能为空")
        return 2
    init_db()
    if q1("SELECT id FROM users WHERE email=?", (email,)):
        print("这个邮箱已经存在")
        return 1
    run("""INSERT INTO users(email,name,pwd,role,team,active,can_reply,created_at)
           VALUES(?,?,?,?,?,1,1,?)""",
        (email, name, hash_password(pwd), "owner", "sales", now()))
    print("已创建老板账号：", email)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
