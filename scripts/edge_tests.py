#!/usr/bin/env python3
"""边界 / 安全 / 性能测试。

用法：
    DB_PATH=/tmp/scrm-edge.db python3 -m uvicorn main:app --app-dir app --port 7842 &
    python3 scripts/edge_tests.py http://127.0.0.1:7842 /tmp/scrm-edge.db
"""
import base64
import hashlib
import hmac
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:7842"
DB = sys.argv[2] if len(sys.argv) > 2 else "/tmp/scrm-edge.db"
fails = []
checks = 0


def call(method, path, body=None, token=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if body is not None and raw is None:
        req.add_header("content-type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            txt = r.read().decode()
            return r.status, txt
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def ok(name, cond, extra=""):
    global checks
    checks += 1
    if not cond:
        fails.append(name + (f" :: {extra}" if extra else ""))


def j(method, path, body=None, token=None):
    st, txt = call(method, path, body, token)
    try:
        return st, json.loads(txt)
    except Exception:
        return st, txt


def login(email, pwd="demo1234"):
    st, d = j("POST", "/api/login", {"email": email, "password": pwd})
    return d.get("token") if st == 200 else None


OWNER = login("owner@demo.com")
ok("owner login", bool(OWNER))

# ---------------- 安全 ----------------
# 1. JWT 篡改
head, payload, sig = OWNER.split(".")
pad = lambda x: x + "=" * (-len(x) % 4)
p = json.loads(base64.urlsafe_b64decode(pad(payload)))
p["role"] = "owner"
p["uid"] = 1
forged = head + "." + base64.urlsafe_b64encode(json.dumps(p).encode()).decode().rstrip("=") + "." + sig
st, _ = call("GET", "/api/me", token=forged)
ok("JWT tampering rejected", st == 401, st)

# 2. 错误密钥签名
b64h = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).decode().rstrip("=")
b64p = base64.urlsafe_b64encode(json.dumps({"uid": 1, "role": "owner", "exp": 9999999999}).encode()).decode().rstrip("=")
bad_sig = hmac.new(b"wrong-secret", f"{b64h}.{b64p}".encode(), hashlib.sha256).digest()
bad = f"{b64h}.{b64p}." + base64.urlsafe_b64encode(bad_sig).decode().rstrip("=")
st, _ = call("GET", "/api/me", token=bad)
ok("wrong-secret token rejected", st == 401, st)

# 2.5 过期 token
exp_p = base64.urlsafe_b64encode(json.dumps({"uid": 1, "role": "owner", "exp": 1}).encode()).decode().rstrip("=")
exp_sig = hmac.new(b"dev-secret-change-me", f"{b64h}.{exp_p}".encode(), hashlib.sha256).digest()
exp_tok = f"{b64h}.{exp_p}." + base64.urlsafe_b64encode(exp_sig).decode().rstrip("=")
st, _ = call("GET", "/api/me", token=exp_tok)
ok("expired token rejected", st == 401, st)

# 3. alg=none
none_tok = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).decode().rstrip("=") + "." + b64p + "."
st, _ = call("GET", "/api/me", token=none_tok)
ok("alg=none rejected", st == 401, st)

# 4. 停用账号令牌失效
tmp_email = f"temp{int(time.time())}@demo.com"
st, u = j("POST", "/api/users", {"name": "Temp User", "email": tmp_email,
                                 "password": "12345678", "role": "agent"}, token=OWNER)
tmp_uid = u.get("id") if st == 200 else None
TMP = login(tmp_email, "12345678")
ok("temp user login", bool(TMP))
call("POST", f"/api/users/{tmp_uid}/status", {"active": False}, token=OWNER)
st, _ = call("GET", "/api/me", token=TMP)
ok("disabled user token rejected", st == 401, st)

# 5. SQL 注入 / XSS 原样返回
st, d = j("GET", "/api/contacts?kw=" + urllib.parse.quote("' OR 1=1 --"), token=OWNER)
ok("SQL injection in kw harmless", st == 200 and d.get("total", 1) == 0, (st, d.get("total")))
xss = f'<img src=x onerror=alert(1)>{int(time.time())}'
st, d = j("POST", "/api/tags", {"name": xss}, token=OWNER)
ok("XSS tag accepted as text", st == 200 and d.get("name") == xss, (st, d))
xss_tag = d.get("id") if st == 200 else None

# 6. 静态目录穿越
st, _ = call("GET", "/static/../app/main.py")
ok("static traversal blocked", st in (403, 404), st)

# 7. 大字段长度
st, _ = j("POST", "/api/tags", {"name": "x" * 61}, token=OWNER)
ok("tag name length capped", st == 400, st)
st, _ = j("POST", "/api/teams", {"name": "x" * 61}, token=OWNER)
ok("team name length capped", st == 400, st)

# ---------------- 边界 ----------------
st, _ = j("GET", "/api/contacts?limit=-1", token=OWNER)
ok("negative limit rejected", st == 422, st)
st, _ = j("GET", "/api/contacts?offset=-1", token=OWNER)
ok("negative offset rejected", st == 422, st)
st, d = j("GET", "/api/contacts?limit=999999", token=OWNER)
ok("huge limit works", st == 200 and len(d.get("items", [])) >= 40, st)
st, d = j("GET", "/api/contacts?offset=999999", token=OWNER)
ok("huge offset empty", st == 200 and d.get("items") == [] and d.get("total", 0) > 0, st)

st, _ = j("POST", "/api/tags/merge", {"from_id": 1, "to_id": 999999}, token=OWNER)
ok("merge to missing tag rejected", st == 404, st)

st, d = j("GET", "/api/numbers", token=OWNER)
num_with_conv = None
convs = j("GET", "/api/conversations", token=OWNER)[1]["items"]
if convs:
    num_with_conv = convs[0]["number_id"]
if num_with_conv:
    st, _ = j("DELETE", f"/api/numbers/{num_with_conv}", token=OWNER)
    ok("cannot delete number with conversations", st == 400, st)

st, _ = j("POST", "/api/teams/1/members", {"user_ids": "12"}, token=OWNER)
ok("team members must be list", st == 400, st)
st, _ = j("POST", "/api/numbers/1/teams", {"team_ids": "12"}, token=OWNER)
ok("number teams must be list", st == 400, st)

# 无接待组的账号：什么都看不到
st, u = j("POST", "/api/users", {"name": "No Team", "email": "noteam@demo.com",
                                 "password": "12345678", "role": "agent"}, token=OWNER)
NT = login("noteam@demo.com", "12345678")
st, d = j("GET", "/api/conversations", token=NT)
ok("no-team user sees no conversations", st == 200 and d["items"] == [], st)
st, d = j("GET", "/api/numbers/allowed", token=NT)
ok("no-team user sees no numbers", st == 200 and d["items"] == [], st)

# 只读账号不能认领
st, pool = j("GET", "/api/contacts?view=pool&limit=100", token=OWNER)
unowned_conv = next((c for c in convs if not c["owner_id"]), None)
FIN = login("finance@demo.com")
if unowned_conv:
    st, _ = j("POST", f"/api/conversations/{unowned_conv['id']}/claim", {}, token=FIN)
    ok("read-only cannot claim conversation", st in (400, 403), st)

# 回收后会话负责人同步清空
st, stg = j("GET", "/api/settings", token=OWNER)
pool_cfg = stg["pool"]
# 找一条有负责人且有会话的客户
owned_conv = next((c for c in convs if c["owner_id"] and c["deal_status"] not in
                   ("Won", "Signed", "Active", "Enrolled", "Renewed")), None)
if owned_conv:
    call("PATCH", "/api/settings", {"pool": {**pool_cfg, "recycle_days": 1, "scopes": {}}}, token=OWNER)
    j("POST", "/api/pool/recycle", {}, token=OWNER)
    st, d = j("GET", f"/api/conversations/{owned_conv['id']}/messages", token=OWNER)
    # 会话可能仍存在但负责人应为空
    st2, cl = j("GET", "/api/conversations", token=OWNER)
    row = next((x for x in cl["items"] if x["id"] == owned_conv["id"]), None)
    ok("recycle clears conversation owner", row is None or row["owner_id"] is None, row and row["owner_id"])
    call("PATCH", "/api/settings", {"pool": {**pool_cfg, "recycle_days": 90, "scopes": {}}}, token=OWNER)


# ---------------- 设置 / 字段校验 ----------------
st, stg = j("GET", "/api/settings", token=OWNER)
base_pool = stg["pool"]
st, _ = j("PATCH", "/api/settings", {"pool": {**base_pool, "recycle_days": -1}}, token=OWNER)
ok("negative recycle days rejected", st == 400, st)
st, _ = j("PATCH", "/api/settings", {"pool": {**base_pool, "daily_claim_limit": 99999}}, token=OWNER)
ok("huge claim limit rejected", st == 400, st)
st, _ = j("PATCH", "/api/settings", {"deal_stages": {"stages": "bad"}}, token=OWNER)
ok("bad deal stages rejected", st == 400, st)

# 会话分配：字符串 id 也要能用
st, cl = j("GET", "/api/conversations", token=OWNER)
if cl["items"]:
    cid0 = cl["items"][0]["id"]
    st, _ = j("POST", f"/api/conversations/{cid0}/assign", {"owner_id": "3"}, token=OWNER)
    ok("assign with string id accepted", st == 200, st)
    st, _ = j("POST", f"/api/conversations/{cid0}/assign", {"owner_id": "abc"}, token=OWNER)
    ok("assign with junk id rejected", st == 400, st)

# 成交金额
st, d = j("GET", "/api/contacts?limit=1", token=OWNER)
if d["items"]:
    ccid = d["items"][0]["id"]
    st, _ = j("PATCH", f"/api/contacts/{ccid}", {"deal_value": "abc"}, token=OWNER)
    ok("bad deal value rejected", st == 400, st)
    st, _ = j("PATCH", f"/api/contacts/{ccid}", {"deal_value": "123.5"}, token=OWNER)
    ok("numeric deal value accepted", st == 200, st)

# 消息长度（挑一条老板负责的会话）
mine = [c for c in cl["items"] if c["owner_id"] == 1]
if mine:
    st, _ = j("POST", f"/api/conversations/{mine[0]['id']}/messages", {"body": "x" * 5000}, token=OWNER)
    ok("oversized message rejected", st == 400, st)

# Webhook 号码格式去重
call("PATCH", "/api/numbers/1", {"phone_number_id": "PN9"}, token=OWNER)
p1 = {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "PN9"},
      "messages": [{"from": "+971 50 222 3344", "id": "wamid.e1", "timestamp": "1794220000",
                    "text": {"body": "first"}}]}}]}]}
p2 = {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "PN9"},
      "messages": [{"from": "971502223344", "id": "wamid.e2", "timestamp": "1794220001",
                    "text": {"body": "second"}}]}}]}]}
j("POST", "/api/webhooks/whatsapp", p1)
j("POST", "/api/webhooks/whatsapp", p2)
st, d = j("GET", "/api/contacts?kw=3344&limit=10", token=OWNER)
ok("webhook phone formats dedupe", st == 200 and d["total"] == 1, d.get("total"))


# 登录暴力尝试限制
brute = {"email": "brute@example.com", "password": "wrong-pass"}
codes = [call("POST", "/api/login", brute)[0] for _ in range(9)]
ok("login brute force limited", codes[:8] == [401] * 8 and codes[8] == 429, codes)
st, _ = j("POST", "/api/login", {"email": "owner@demo.com", "password": "demo1234"})
ok("normal login unaffected", st == 200, st)

# 安全头
import urllib.request as _ur
with _ur.urlopen(BASE + "/healthz", timeout=10) as r:
    h = r.headers
ok("security headers present",
   h.get("X-Content-Type-Options") == "nosniff" and h.get("X-Frame-Options") == "DENY"
   and "default-src" in (h.get("Content-Security-Policy") or ""), dict(h))


# 短密钥打码
call("PATCH", "/api/settings/channels", {"whatsapp": {"access_token": "abc", "verify_token": "vt",
                                                      "app_secret": "ss"}}, token=OWNER)
st, stg = j("GET", "/api/settings", token=OWNER)
wa = (stg.get("channels") or {}).get("whatsapp") or {}
ok("short secrets fully masked",
   wa.get("access_token") == "***" and wa.get("verify_token") == "**" and wa.get("app_secret") == "**", wa)

# 24 小时窗口按真实时间
conn = sqlite3.connect(DB)
row = conn.execute("""SELECT cv.id, cv.contact_id FROM conversations cv
                      JOIN messages m ON m.conversation_id=cv.id AND m.direction='in'
                      GROUP BY cv.id LIMIT 1""").fetchone()
if row:
    cvid, _ = row
    from datetime import datetime, timedelta
    old = (datetime.now() - timedelta(hours=25)).strftime("%Y-%m-%d %H:%M:%S")
    new = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("""UPDATE messages SET created_at=? WHERE conversation_id=? AND direction='in'""", (old, cvid))
    conn.commit()
    st, d = j("GET", f"/api/conversations/{cvid}/messages", token=OWNER)
    ok("window closed after 25h", st == 200 and d.get("window_open") is False, d.get("window_open"))
    conn.execute("""UPDATE messages SET created_at=? WHERE conversation_id=? AND direction='in'""", (new, cvid))
    conn.commit()
    st, d = j("GET", f"/api/conversations/{cvid}/messages", token=OWNER)
    ok("window open within 24h", st == 200 and d.get("window_open") is True, d.get("window_open"))
conn.close()


# 数据库完整性 / 备份恢复
import os as _os
import shutil as _shutil
conn = sqlite3.connect(DB)
try:
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.commit()
except Exception:
    pass
conn.close()
tmpdb = DB + ".bakcheck"
for suf in ("", "-wal", "-shm"):
    src = DB + suf
    if _os.path.exists(src):
        _shutil.copyfile(src, tmpdb + suf)
c2 = sqlite3.connect(tmpdb)
integrity = c2.execute("PRAGMA integrity_check").fetchone()[0]
cnt = c2.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
tables = {r[0] for r in c2.execute("SELECT name FROM sqlite_master WHERE type='table'")}
c2.close()
st, d = j("GET", "/api/contacts?limit=0", token=OWNER)
ok("db integrity ok", integrity == "ok", integrity)
ok("backup copy matches API count", cnt == d.get("total"), (cnt, d.get("total")))
ok("core tables exist", {"users", "contacts", "conversations", "messages", "numbers",
                          "teams", "team_members", "number_teams"} <= tables, tables)
for suf in ("", "-wal", "-shm"):
    if _os.path.exists(tmpdb + suf):
        _os.remove(tmpdb + suf)

# ---------------- 性能 ----------------
conn = sqlite3.connect(DB)
conn.execute("BEGIN")
for i in range(2000):
    conn.execute("""INSERT INTO contacts(name,phone,country,source,opt_in_at,created_at,last_contact_at)
                    VALUES(?,?,?,?,?,?,?)""",
                 (f"Bulk {i}", f"9999{i:08d}", "UAE", "Website",
                  "2026-01-01 00:00:00", "2026-01-01 00:00:00", "2026-09-01 00:00:00"))
conn.commit()
conn.close()

t0 = time.time()
st, d = j("GET", "/api/contacts?limit=0", token=OWNER)
dt = time.time() - t0
ok("bulk contacts loaded", st == 200 and d["total"] >= 2000, d.get("total"))
ok("contacts list under 3s for 2k rows", dt < 3.0, round(dt, 2))

t0 = time.time()
st, d = j("GET", "/api/segments", token=OWNER)
dt = time.time() - t0
ok("segments under 3s for 2k rows", st == 200 and dt < 3.0, round(dt, 2))

t0 = time.time()
st, d = j("GET", "/api/pool/facets", token=OWNER)
dt = time.time() - t0
ok("pool facets under 3s", st == 200 and dt < 3.0, round(dt, 2))

# 大批量触达
st, segs = j("GET", "/api/segments", token=OWNER)
big_seg = next((x for x in segs["items"] if x.get("rule", {}).get("type") == "d30"), None)
st, tpls = j("GET", "/api/templates", token=OWNER)
appr = next((t for t in tpls["items"] if t["status"] == "approved"), None)
if big_seg and appr:
    t0 = time.time()
    st, camp = j("POST", "/api/campaigns", {"segment_id": big_seg["id"], "template_id": appr["id"]}, token=OWNER)
    dt = time.time() - t0
    ok("bulk campaign created", st == 200 and camp.get("sent", 0) > 1000, (st, camp))
    ok("bulk campaign under 10s", dt < 10.0, round(dt, 2))
    if st == 200:
        t0 = time.time()
        st, det = j("GET", f"/api/campaigns/{camp['id']}", token=OWNER)
        dt = time.time() - t0
        ok("bulk campaign detail under 3s", st == 200 and dt < 3.0, round(dt, 2))
        ok("bulk recipients count matches sent",
           len(det["recipients"]) == det["campaign"]["sent"], (len(det["recipients"]), det["campaign"]["sent"]))

print(f"\n{checks} 项 · {'全部通过' if not fails else str(len(fails)) + ' 项失败'}")
for f in fails:
    print("  ✗ " + f)
sys.exit(1 if fails else 0)
