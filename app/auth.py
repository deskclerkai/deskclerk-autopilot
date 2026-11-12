"""认证与权限：PBKDF2 口令 + JWT + 三种角色。"""
import hashlib
import hmac
import os
import secrets
import time

import jwt
from fastapi import Depends, Header, HTTPException

from db import q1

SECRET = os.environ.get("APP_SECRET") or "dev-secret-change-me"
if os.environ.get("APP_ENV", "dev") == "production" and not os.environ.get("APP_SECRET"):
    raise RuntimeError("APP_SECRET is required when APP_ENV=production")
TOKEN_TTL = 60 * 60 * 12
ITER = 200_000


def hash_password(pwd: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", pwd.encode(), salt.encode(), ITER)
    return f"pbkdf2${ITER}${salt}${dk.hex()}"


def verify_password(pwd: str, stored: str) -> bool:
    try:
        _, it, salt, digest = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", pwd.encode(), salt.encode(), int(it))
        return hmac.compare_digest(dk.hex(), digest)
    except Exception:
        return False


def make_token(user):
    payload = {"uid": user["id"], "role": user["role"], "exp": int(time.time()) + TOKEN_TTL}
    return jwt.encode(payload, SECRET, algorithm="HS256")


def decode_token(token: str):
    return jwt.decode(token, SECRET, algorithms=["HS256"])


def current_user(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing token")
    try:
        payload = decode_token(authorization[7:])
    except Exception:
        raise HTTPException(401, "invalid token")
    user = q1("SELECT * FROM users WHERE id=? AND active=1", (payload["uid"],))
    if not user:
        raise HTTPException(401, "user not found")
    return user


def require_roles(*roles):
    def dep(user=Depends(current_user)):
        if user["role"] not in roles:
            raise HTTPException(403, "forbidden")
        return user
    return dep


def scope_owner_ids(user):
    """返回该用户可见的 owner_id 列表；None 表示不受限。"""
    if user["role"] == "owner":
        return None
    if user["role"] == "manager":
        rows = q1("SELECT 1", ())  # noqa
        return "manager"
    return [user["id"]]
