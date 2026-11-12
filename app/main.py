"""DeskClerk AI Autopilot — backend API (single tenant)."""
import hashlib
import hmac
import json
import os
import threading
import time
import urllib.parse
import urllib.request
import requests
import uuid
from datetime import datetime, timedelta

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from auth import current_user, hash_password, make_token, verify_password
from db import audit, init_db, now, q, q1, run, run_count, setting_get, setting_set

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(APP_DIR, "static")

app = FastAPI(title="DeskClerk AI Autopilot", version="1.0.0")
_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def no_cache_static(request, call_next):
    """静态资源每次都向服务端确认，避免改了代码浏览器还跑旧版本。"""
    resp = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; "
        "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "connect-src 'self'")
    return resp


@app.on_event("startup")
def _startup():
    init_db()
    recycle_pool()


# ---------------- 工具 ----------------
def mask_secret(v):
    v = str(v or "")
    if not v:
        return ""
    if len(v) <= 12:
        return "*" * len(v)
    return v[:4] + "*" * (len(v) - 8) + v[-4:]


def require_write(user):
    if not user.get("can_reply", 1):
        raise HTTPException(403, "read_only")


def sval(v):
    """安全取字符串：非字符串一律当空。"""
    return v.strip() if isinstance(v, str) else ""


def nameval(v, maxlen=120):
    """名称类输入：必须是字符串且不超过上限。"""
    s_ = sval(v)
    if not s_:
        raise HTTPException(400, "name required")
    if len(s_) > maxlen:
        raise HTTPException(400, f"name too long (max {maxlen})")
    return s_


def ival(v, default=0):
    try:
        return int(v)
    except Exception:
        return default


def days_since(ts):
    if not ts:
        return 9999
    try:
        d = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return 9999
    return (datetime.now() - d).days


def segment_of(contact):
    if contact.get("opt_out"):
        return "opted_out"
    d = days_since(contact.get("last_contact_at"))
    if d < 30:
        return "active"
    if d < 90:
        return "d30"
    if d < 180:
        return "d90"
    return "d180"


SEG_MATCH = {
    "active": lambda c: segment_of(c) == "active",
    "d30": lambda c: segment_of(c) == "d30",
    "d90": lambda c: segment_of(c) == "d90",
    "d180": lambda c: segment_of(c) == "d180",
}


def tags_map():
    """联系人 → 标签 ID 集合，一次查出来给分层用。"""
    m = {}
    for r in q("SELECT contact_id, tag_id FROM contact_tags"):
        m.setdefault(r["contact_id"], set()).add(r["tag_id"])
    return m


def validate_rule(rule):
    if not isinstance(rule, dict):
        raise HTTPException(400, "rule must be an object")
    for k in ("tags", "countries", "sources", "deal_status"):
        v = rule.get(k)
        if v is not None and not isinstance(v, list):
            raise HTTPException(400, f"{k} must be a list")
    for k in ("last_contact", "created"):
        v = rule.get(k)
        if v is not None and not isinstance(v, dict):
            raise HTTPException(400, f"{k} must be an object")
    return rule


def seg_match(rule, c, tag_ids=None):
    """自定义分层：所有条件是 AND；同一个条件里多选是 OR；空条件不参与。"""
    tags = rule.get("tags") or []
    if tags and not (set(tag_ids or ()) & set(tags)):
        return False
    if rule.get("countries") and (c.get("country") or "") not in rule["countries"]:
        return False
    if rule.get("sources") and (c.get("source") or "") not in rule["sources"]:
        return False
    if rule.get("deal_status") and c.get("deal_status") not in rule["deal_status"]:
        return False
    opt = rule.get("opt") or "any"
    if opt == "in" and c.get("opt_out"):
        return False
    if opt == "out" and not c.get("opt_out"):
        return False
    pool = rule.get("pool") or "any"
    if pool == "in" and c.get("owner_id"):
        return False
    if pool == "owned" and not c.get("owner_id"):
        return False
    lc = rule.get("last_contact") or {}
    if lc.get("days"):
        d = days_since(c.get("last_contact_at"))
        if lc.get("op", "gte") == "gte" and d < int(lc["days"]):
            return False
        if lc.get("op") == "lte" and d > int(lc["days"]):
            return False
    cr = rule.get("created") or {}
    if cr.get("days"):
        d = days_since(c.get("created_at"))
        if cr.get("op", "lte") == "lte" and d > int(cr["days"]):
            return False
        if cr.get("op") == "gte" and d < int(cr["days"]):
            return False
    return True


SUCCESS_STATES = ("Won", "Signed", "Active", "Enrolled", "Renewed")


def claim_block(c, user=None, cfg=None):
    """返回不可领取的原因；None 表示可领。"""
    if cfg is None:
        cfg = setting_get("pool", {})
    if not isinstance(cfg, dict):
        cfg = {}
    if c.get("owner_id"):
        return "owned"
    if c.get("opt_out"):
        return "opted_out"
    if cfg.get("exclude_success", True) and c.get("deal_status") in SUCCESS_STATES:
        return "success"
    protect = int(cfg.get("protect_hours", 24))
    if protect and c.get("released_at"):
        try:
            t = datetime.strptime(c["released_at"][:19], "%Y-%m-%d %H:%M:%S")
            if (datetime.now() - t).total_seconds() < protect * 3600:
                return "protected"
        except Exception:
            pass
    if user and user.get("role") == "agent":
        scopes = cfg.get("scopes")
        if not isinstance(scopes, dict):
            scopes = {}
        scope = scopes.get(str(user["id"])) or []
        if scope:
            mine = {r["tag_id"] for r in q("SELECT tag_id FROM contact_tags WHERE contact_id=?", (c["id"],))}
            if not (mine & set(scope)):
                return "out_of_scope"
    return None


def recycle_pool():
    """超过 N 天没联系的客户自动回到公海。"""
    cfg = setting_get("pool", {}) or {}
    if not cfg.get("enabled", True):
        return 0
    days = int(cfg.get("recycle_days", 90))
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    marks = ",".join("?" * len(SUCCESS_STATES))
    rows = q(f"""SELECT id FROM contacts WHERE owner_id IS NOT NULL
                 AND deal_status NOT IN ({marks})
                 AND COALESCE(claimed_at, last_contact_at, created_at) < ?""",
             (*SUCCESS_STATES, cutoff))
    for r in rows:
        run("UPDATE contacts SET owner_id=NULL, claimed_at=NULL WHERE id=?", (r["id"],))
        run("UPDATE conversations SET owner_id=NULL WHERE contact_id=?", (r["id"],))
        audit(None, "pool_recycle", str(r["id"]))
    return len(rows)


def claims_today(uid):
    today = datetime.now().strftime("%Y-%m-%d")
    return q1("SELECT COUNT(*) c FROM audit WHERE action='claim' AND user_id=? AND created_at LIKE ?",
              (uid, today + "%"))["c"]


def visible_contacts(user):
    rows = q("""SELECT c.*, u.name AS owner_name, u.team AS owner_team
                FROM contacts c LEFT JOIN users u ON u.id=c.owner_id ORDER BY c.id""")
    if user["role"] == "owner":
        return rows
    if user["role"] == "manager":
        tids = team_ids_of(user)
        if tids:
            members = {m["user_id"] for m in q("SELECT team_id, user_id FROM team_members") if m["team_id"] in tids}
            return [r for r in rows if r["owner_id"] in members]
        return [r for r in rows if r.get("owner_team") == user["team"]]
    return [r for r in rows if r["owner_id"] == user["id"]]


def team_ids_of(user):
    return {r["team_id"] for r in q("SELECT team_id FROM team_members WHERE user_id=?", (user["id"],))}


def allowed_number_ids(user):
    """返回该用户能看的号码 ID 集合；None 表示不限（老板）。"""
    if user["role"] == "owner":
        return None
    tids = team_ids_of(user)
    if not tids:
        return set()
    return {r["number_id"] for r in q("SELECT number_id, team_id FROM number_teams") if r["team_id"] in tids}


def shares_team(a, b):
    ta, tb = team_ids_of(a), team_ids_of(b)
    if ta and tb:
        return bool(ta & tb)
    return a.get("team") == b.get("team")


def can_see_conv(cv, user):
    allowed = allowed_number_ids(user)
    if allowed is not None and cv.get("number_id") not in allowed:
        return False
    if user["role"] == "agent":
        cfg = setting_get("inbox", {}) or {}
        if cfg.get("visibility") == "own" and cv.get("owner_id") not in (None, user["id"]):
            return False
    return True


def contact_out(c, user, tagmap=None, tagnames=None, pool_cfg=None):
    if tagmap is None:
        tags = q("""SELECT t.id,t.name FROM contact_tags ct JOIN tags t ON t.id=ct.tag_id
                    WHERE ct.contact_id=?""", (c["id"],))
    else:
        ids = sorted(tagmap.get(c["id"], set()))
        tags = [{"id": i, "name": (tagnames or {}).get(i, "#" + str(i))} for i in ids]
    out = {
        "id": c["id"], "name": c["name"], "phone": mask_phone(c["phone"]),
        "country": c["country"], "source": c["source"], "source_detail": c["source_detail"],
        "opt_in_at": c["opt_in_at"], "opt_out": bool(c["opt_out"]),
        "owner_id": c["owner_id"], "owner_name": c.get("owner_name"),
        "deal_status": c["deal_status"], "note": c["note"],
        "last_contact_at": c["last_contact_at"],
        "segment": segment_of(c), "tags": tags,
    }
    # 字段级权限：销售看不到成交金额
    out["deal_value"] = None if user["role"] == "agent" else c["deal_value"]
    if not c.get("owner_id"):
        block = claim_block(c, user, pool_cfg)
        out["claimable"] = block is None
        out["claim_block"] = block
    return out


OPTOUT_WORDS = ["stop", "unsubscribe", "退订", "取消订阅", "不要再发", "别发了", "opt out", "optout"]


def is_optout(text: str) -> bool:
    t = (text or "").strip().lower()
    return any(w in t for w in OPTOUT_WORDS)


def apply_optout(contact_id: int):
    run("UPDATE contacts SET opt_out=1 WHERE id=?", (contact_id,))
    audit(None, "auto_optout", str(contact_id))


def mask_phone(p):
    if not p or len(p) < 6:
        return p
    return p[:3] + "*" * (len(p) - 6) + p[-3:]


def can_see_contact(c, user):
    if user["role"] == "owner":
        return True
    if not c.get("owner_id"):
        return True   # 公海客户是公共资源
    if user["role"] == "manager":
        tids = team_ids_of(user)
        if tids:
            members = {m["user_id"] for m in q("SELECT team_id, user_id FROM team_members") if m["team_id"] in tids}
            return c.get("owner_id") in members
        return c.get("owner_team") == user["team"]
    return c["owner_id"] == user["id"]


# ---------------- 认证 ----------------
LOGIN_FAILS = {}
LOGIN_WINDOW = int(os.environ.get("LOGIN_WINDOW_SECONDS", "300"))
LOGIN_MAX = int(os.environ.get("LOGIN_MAX_FAILS", "8"))


@app.post("/api/login")
def login(request: Request, body: dict = Body(...)):
    email = sval(body.get("email")).lower()
    pwd = sval(body.get("password"))
    ip = request.client.host if request.client else "?"
    key = f"{ip}:{email}"
    now_ts = time.time()
    hist = [t for t in LOGIN_FAILS.get(key, []) if now_ts - t < LOGIN_WINDOW]
    if len(hist) >= LOGIN_MAX:
        raise HTTPException(429, "too_many_attempts")
    user = q1("SELECT * FROM users WHERE email=? AND active=1", (email,))
    if not user or not verify_password(pwd, user["pwd"]):
        hist.append(now_ts)
        LOGIN_FAILS[key] = hist
        raise HTTPException(401, "邮箱或密码不对")
    LOGIN_FAILS.pop(key, None)
    audit(user["id"], "login")
    return {"token": make_token(user),
            "user": {"id": user["id"], "name": user["name"], "role": user["role"],
                     "email": user["email"], "team": user["team"],
                     "can_reply": bool(user.get("can_reply", 1))}}


@app.get("/api/me")
def me(user=Depends(current_user)):
    return {"id": user["id"], "name": user["name"], "role": user["role"],
            "email": user["email"], "team": user["team"],
            "can_reply": bool(user.get("can_reply", 1))}


# ---------------- 客户 ----------------
@app.get("/api/contacts")
def list_contacts(view: str = Query("all"), kw: str = Query(""), limit: int = Query(0, ge=0),
                  offset: int = Query(0, ge=0), owner: int = Query(0), deal: str = Query(""),
                  tag: int = Query(0), country: str = Query(""), source: str = Query(""),
                  opt: str = Query(""), seg: int = Query(0), sort: str = Query(""),
                  user=Depends(current_user)):
    rows = visible_contacts(user)
    if owner:
        rows = [r for r in rows if r["owner_id"] == owner]
    if deal:
        rows = [r for r in rows if r["deal_status"] == deal]
    if view == "active":
        rows = [r for r in rows if segment_of(r) == "active"]
    elif view == "dormant":
        rows = [r for r in rows if segment_of(r) != "active"]
    elif view == "won":
        rows = [r for r in rows if r["deal_status"] in SUCCESS_STATES]
    elif view == "pool":
        # 公海对所有人可见：销售/主管只能看自己的客户，但公海是公共的
        rows = q("""SELECT c.*, u.name AS owner_name, u.team AS owner_team
                    FROM contacts c LEFT JOIN users u ON u.id=c.owner_id
                    WHERE c.owner_id IS NULL ORDER BY c.id""")
    elif view == "untagged":
        ids = {r["contact_id"] for r in q("SELECT contact_id FROM contact_tags")}
        rows = [r for r in rows if r["id"] not in ids]
    # ---- 通用筛选（任何视图都生效）----
    if tag:
        keep = {x["contact_id"] for x in q("SELECT contact_id FROM contact_tags WHERE tag_id=?", (tag,))}
        rows = [r for r in rows if r["id"] in keep]
    if country:
        rows = [r for r in rows if (r["country"] or "") == country]
    if source:
        rows = [r for r in rows if (r["source"] or "") == source]
    if opt == "in":
        rows = [r for r in rows if not r["opt_out"]]
    elif opt == "out":
        rows = [r for r in rows if r["opt_out"]]
    if seg:
        srow = q1("SELECT * FROM segments WHERE id=?", (seg,))
        if srow:
            rule = json.loads(srow["rule"])
            if rule.get("type") in SEG_MATCH:
                rows = [r for r in rows if SEG_MATCH[rule["type"]](r)]
            else:
                tagmap = tags_map()
                rows = [r for r in rows if seg_match(rule, r, tagmap.get(r["id"], set()))]
    if sort == "oldest":
        rows.sort(key=lambda r: r["last_contact_at"] or "")
    elif sort == "newest":
        rows.sort(key=lambda r: r["last_contact_at"] or "", reverse=True)
    elif sort == "created":
        rows.sort(key=lambda r: r["created_at"] or "", reverse=True)

    if kw:
        k = kw.lower()
        rows = [r for r in rows if k in (r["name"] or "").lower()
                or k in (r["country"] or "").lower() or k in (r["phone"] or "")]
    total = len(rows)
    if offset:
        rows = rows[offset:]
    if limit:
        rows = rows[:limit]
    tm = tags_map()
    tnames = {t["id"]: t["name"] for t in q("SELECT id, name FROM tags")}
    pcfg = setting_get("pool", {})
    return {"items": [contact_out(r, user, tm, tnames, pcfg) for r in rows],
            "total": total, "limit": limit, "offset": offset}


@app.get("/api/contacts/{cid}")
def get_contact(cid: int, user=Depends(current_user)):
    c = q1("""SELECT c.*, u.name AS owner_name, u.team AS owner_team
              FROM contacts c LEFT JOIN users u ON u.id=c.owner_id WHERE c.id=?""", (cid,))
    if not c:
        raise HTTPException(404, "not found")
    if not can_see_contact(c, user):
        raise HTTPException(403, "forbidden")
    allowed = allowed_number_ids(user)
    msgs = q("""SELECT m.*, u.name AS sender_name, cv.number_id
                FROM messages m
                LEFT JOIN users u ON u.id=m.sender_id
                JOIN conversations cv ON cv.id=m.conversation_id
                WHERE cv.contact_id=?
                ORDER BY m.created_at DESC LIMIT 200""", (cid,))
    if allowed is not None:
        msgs = [m for m in msgs if m["number_id"] in allowed]
    msgs = msgs[:20]
    return {**contact_out(c, user), "messages": msgs}


@app.post("/api/contacts/{cid}/assign")
def assign_contact(cid: int, body: dict = Body(...), user=Depends(current_user)):
    """主管/老板把客户指派给某个员工；user_id 为空表示放回公海。"""
    if user["role"] == "agent":
        raise HTTPException(403, "forbidden")
    require_write(user)
    c = q1("SELECT * FROM contacts WHERE id=?", (cid,))
    if not c:
        raise HTTPException(404, "not found")
    uid = body.get("user_id")
    if uid in (None, "", 0):
        run("UPDATE contacts SET owner_id=NULL, claimed_at=NULL, released_at=? WHERE id=?", (now(), cid))
        run("UPDATE conversations SET owner_id=NULL WHERE contact_id=?", (cid,))
        audit(user["id"], "unassign", str(cid))
        return {"ok": True, "owner_id": None}
    uid = int(uid)
    target = q1("SELECT * FROM users WHERE id=?", (uid,))
    if not target:
        raise HTTPException(404, "user not found")
    if target["active"] == 0:
        raise HTTPException(400, "user is disabled")
    if user["role"] == "manager" and not shares_team(user, target):
        raise HTTPException(403, "different team")
    run("UPDATE contacts SET owner_id=?, claimed_at=?, released_at=NULL WHERE id=?", (uid, now(), cid))
    run("UPDATE conversations SET owner_id=? WHERE contact_id=?", (uid, cid))
    audit(user["id"], "assign", f"{cid}->{uid}")
    return {"ok": True, "owner_id": uid, "owner_name": target["name"]}


@app.post("/api/contacts/{cid}/claim")
def claim_contact(cid: int, user=Depends(current_user)):
    require_write(user)
    c = q1("SELECT * FROM contacts WHERE id=?", (cid,))
    if not c:
        raise HTTPException(404, "not found")
    if c["owner_id"]:
        raise HTTPException(400, "already_owned")
    reason = claim_block(c, user)
    if reason:
        raise HTTPException(400, "blocked:" + reason)
    cfg = setting_get("pool", {}) or {}
    limit = int(cfg.get("daily_claim_limit", 10))
    used = claims_today(user["id"])
    if user["role"] == "agent" and used >= limit:
        raise HTTPException(400, f"daily_limit_reached:{limit}")
    n = run_count("""UPDATE contacts SET owner_id=?, claimed_at=?, released_at=NULL
                     WHERE id=? AND owner_id IS NULL""", (user["id"], now(), cid))
    if n == 0:
        raise HTTPException(400, "already_owned")
    run("""UPDATE conversations SET owner_id=? WHERE contact_id=? AND owner_id IS NULL""",
        (user["id"], cid))
    audit(user["id"], "claim", str(cid))
    return {"ok": True, "used": used + 1, "limit": limit}


@app.post("/api/contacts/{cid}/release")
def release_contact(cid: int, body: dict = Body(default={}), user=Depends(current_user)):
    require_write(user)
    c = q1("""SELECT c.*, u.team AS owner_team FROM contacts c
              LEFT JOIN users u ON u.id=c.owner_id WHERE c.id=?""", (cid,))
    if not c:
        raise HTTPException(404, "not found")
    if user["role"] == "agent" and c["owner_id"] != user["id"]:
        raise HTTPException(403, "forbidden")
    if user["role"] == "manager" and not can_see_contact(c, user):
        raise HTTPException(403, "forbidden")
    run("UPDATE contacts SET owner_id=NULL, claimed_at=NULL, released_at=? WHERE id=?", (now(), cid))
    run("UPDATE conversations SET owner_id=NULL WHERE contact_id=?", (cid,))
    audit(user["id"], "release", str(cid))
    return {"ok": True}


@app.post("/api/pool/recycle")
def pool_recycle(user=Depends(current_user)):
    if user["role"] != "owner":
        raise HTTPException(403, "forbidden")
    n = recycle_pool()
    return {"recycled": n}


@app.get("/api/pool/stats")
def pool_stats(user=Depends(current_user)):
    cfg = setting_get("pool", {}) or {}
    unowned = q1("SELECT COUNT(*) c FROM contacts WHERE owner_id IS NULL")["c"]
    if not cfg.get("enabled", True):
        due = 0
    else:
        marks = ",".join("?" * len(SUCCESS_STATES))
        due = q1(f"""SELECT COUNT(*) c FROM contacts WHERE owner_id IS NOT NULL
                     AND deal_status NOT IN ({marks})
                     AND COALESCE(claimed_at, last_contact_at, created_at) < ?""",
                 (*SUCCESS_STATES,
                  (datetime.now() - timedelta(days=int(cfg.get("recycle_days", 90))))
                  .strftime("%Y-%m-%d %H:%M:%S")))["c"]
    pool_rows = q("SELECT * FROM contacts WHERE owner_id IS NULL")
    claimable = len([r for r in pool_rows if claim_block(r, user) is None])
    blocks = {}
    for r in pool_rows:
        b = claim_block(r, user) or "claimable"
        blocks[b] = blocks.get(b, 0) + 1
    return {"unowned": unowned, "claimable": claimable, "due_for_recycle": due, "config": cfg,
            "blocks": blocks,
            "claimed_today": claims_today(user["id"]), "claim_limit": int(cfg.get("daily_claim_limit", 10))}


@app.get("/api/pool/facets")
def pool_facets(user=Depends(current_user)):
    """公海的分面：标签 / 国家，每个都数出可领取的数量。"""
    rows = q("SELECT * FROM contacts WHERE owner_id IS NULL")
    ok = {r["id"] for r in rows if claim_block(r, user) is None}
    tags = q("""SELECT t.id, t.name, COUNT(ct.contact_id) AS n
                FROM tags t JOIN contact_tags ct ON ct.tag_id=t.id
                JOIN contacts c ON c.id=ct.contact_id AND c.owner_id IS NULL
                GROUP BY t.id ORDER BY n DESC, t.id""")
    names = {r["id"]: r["name"] for r in rows}
    from collections import Counter
    tag_ok = Counter()
    for r in q("""SELECT ct.tag_id AS tid, ct.contact_id AS cid FROM contact_tags ct
                  JOIN contacts c ON c.id=ct.contact_id AND c.owner_id IS NULL"""):
        if r["cid"] in ok:
            tag_ok[r["tid"]] += 1
    countries = q("""SELECT country, COUNT(*) AS n FROM contacts
                     WHERE owner_id IS NULL AND country IS NOT NULL AND country<>''
                     GROUP BY country ORDER BY n DESC""")
    c_ok = Counter(r["country"] for r in rows if r["id"] in ok)
    return {"tags": [{**t, "claimable": tag_ok[t["id"]]} for t in tags],
            "countries": [{**c, "claimable": c_ok[c["country"]]} for c in countries]}


@app.patch("/api/contacts/{cid}")
def patch_contact(cid: int, body: dict = Body(...), user=Depends(current_user)):
    c = q1("""SELECT c.*, u.team AS owner_team FROM contacts c
              LEFT JOIN users u ON u.id=c.owner_id WHERE c.id=?""", (cid,))
    if not c or not can_see_contact(c, user):
        raise HTTPException(403, "forbidden")
    require_write(user)
    if user["role"] == "agent" and not c.get("owner_id"):
        raise HTTPException(403, "claim_first")
    if "deal_status" in body:
        stages = setting_get("deal_stages", {}).get("stages", [])
        valid = [x["key"] for x in stages] or ["Lead", "Won", "Lost"]
        if body["deal_status"] not in valid:
            raise HTTPException(400, "bad status")
        run("UPDATE contacts SET deal_status=? WHERE id=?", (body["deal_status"], cid))
    if "deal_value" in body and user["role"] != "agent":
        v = body["deal_value"]
        if v in (None, ""):
            run("UPDATE contacts SET deal_value=NULL WHERE id=?", (cid,))
        else:
            try:
                run("UPDATE contacts SET deal_value=? WHERE id=?", (float(v), cid))
            except Exception:
                raise HTTPException(400, "deal_value must be a number")
    if "note" in body:
        run("UPDATE contacts SET note=? WHERE id=?", (body["note"], cid))
    if "owner_id" in body and user["role"] in ("owner", "manager"):
        assign_contact(cid, {"user_id": body["owner_id"]}, user)
    if "tags" in body:
        run("DELETE FROM contact_tags WHERE contact_id=?", (cid,))
        tag_list = body["tags"] if isinstance(body["tags"], list) else []
        for tid in tag_list:
            t = ival(tid, -1)
            if t > 0:
                run("INSERT OR IGNORE INTO contact_tags(contact_id,tag_id) VALUES(?,?)", (cid, t))
    audit(user["id"], "update_contact", str(cid))
    return {"ok": True}


# ---------------- 标签 ----------------
@app.get("/api/tags")
def list_tags(user=Depends(current_user)):
    rows = q("""SELECT t.id,t.name,COUNT(ct.contact_id) AS n FROM tags t
                LEFT JOIN contact_tags ct ON ct.tag_id=t.id GROUP BY t.id ORDER BY t.id""")
    return {"items": rows}


@app.post("/api/tags")
def create_tag(body: dict = Body(...), user=Depends(current_user)):
    require_write(user)
    name = nameval(body.get("name"), 60)
    if q1("SELECT id FROM tags WHERE name=?", (name,)):
        raise HTTPException(400, "exists")
    tid = run("INSERT INTO tags(name) VALUES(?)", (name,))
    return {"id": tid, "name": name, "n": 0}


@app.patch("/api/tags/{tid}")
def rename_tag(tid: int, body: dict = Body(...), user=Depends(current_user)):
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(403, "forbidden")
    require_write(user)
    name = nameval(body.get("name"), 60)
    if q1("SELECT id FROM tags WHERE name=? AND id<>?", (name, tid)):
        raise HTTPException(400, "exists")
    run("UPDATE tags SET name=? WHERE id=?", (name, tid))
    audit(user["id"], "rename_tag", f"{tid}:{name}")
    return {"ok": True}


@app.post("/api/tags/merge")
def merge_tags(body: dict = Body(...), user=Depends(current_user)):
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(403, "forbidden")
    require_write(user)
    src, dst = ival(body.get("from_id")), ival(body.get("to_id"))
    if not src or not dst or src == dst:
        raise HTTPException(400, "bad ids")
    if not q1("SELECT id FROM tags WHERE id=?", (src,)) or not q1("SELECT id FROM tags WHERE id=?", (dst,)):
        raise HTTPException(404, "tag not found")
    for row in q("SELECT contact_id FROM contact_tags WHERE tag_id=?", (src,)):
        run("INSERT OR IGNORE INTO contact_tags(contact_id,tag_id) VALUES(?,?)", (row["contact_id"], dst))
    run("DELETE FROM contact_tags WHERE tag_id=?", (src,))
    run("DELETE FROM tags WHERE id=?", (src,))
    audit(user["id"], "merge_tag", f"{src}->{dst}")
    return {"ok": True}


@app.delete("/api/tags/{tid}")
def delete_tag(tid: int, user=Depends(current_user)):
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(403, "forbidden")
    require_write(user)
    run("DELETE FROM contact_tags WHERE tag_id=?", (tid,))
    run("DELETE FROM tags WHERE id=?", (tid,))
    audit(user["id"], "delete_tag", str(tid))
    return {"ok": True}


# ---------------- 分层 ----------------
@app.get("/api/segments")
def list_segments(user=Depends(current_user)):
    contacts = visible_contacts(user)
    tagmap = tags_map()
    out = []
    for s in q("SELECT * FROM segments ORDER BY is_system DESC, id"):
        rule = json.loads(s["rule"])
        t = rule.get("type")
        if t in SEG_MATCH:
            matched = [c for c in contacts if SEG_MATCH[t](c)]
        else:
            matched = [c for c in contacts if seg_match(rule, c, tagmap.get(c["id"], set()))]
        sendable = [c for c in matched if not c["opt_out"]]
        out.append({
            "id": s["id"], "name": s["name"], "rule": rule, "is_system": bool(s["is_system"]),
            "matched": len(matched), "sendable": len(sendable),
            "opted_out": len(matched) - len(sendable),
            "won": len([c for c in matched if c["deal_status"] in SUCCESS_STATES]),
            "revenue": sum(c["deal_value"] or 0 for c in matched),
        })
    return {"items": out}


@app.get("/api/segments/facets")
def segment_facets(user=Depends(current_user)):
    """新建分层时可选的维度。"""
    contacts = visible_contacts(user)
    def uniq(key):
        vals = sorted({(c.get(key) or "") for c in contacts if c.get(key)})
        return vals
    tags = q("""SELECT t.id, t.name, COUNT(ct.contact_id) AS n FROM tags t
                LEFT JOIN contact_tags ct ON ct.tag_id=t.id GROUP BY t.id ORDER BY t.id""")
    stages = (setting_get("deal_stages", {}) or {}).get("stages", [])
    return {"tags": tags, "countries": uniq("country"), "sources": uniq("source"),
            "deal_status": [{"key": x["key"], "en": x.get("en", x["key"]), "zh": x.get("zh", x["key"])}
                            for x in stages] or [{"key": k, "en": k, "zh": k} for k in
                                                 ["Lead", "Contacted", "Negotiating", "Won", "Lost"]]}


@app.post("/api/segments")
def create_segment(body: dict = Body(...), user=Depends(current_user)):
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(403, "forbidden")
    require_write(user)
    name = nameval(body.get("name"), 80)
    rule = body.get("rule") or {}
    validate_rule(rule)
    if not any(rule.get(k) for k in
                                             ("tags", "countries", "sources", "deal_status", "opt", "pool", "last_contact", "created")):
        raise HTTPException(400, "rule is empty")
    sid = run("INSERT INTO segments(name,rule,is_system) VALUES(?,?,0)", (name, json.dumps(rule, ensure_ascii=False)))
    audit(user["id"], "segment_create", f"{sid}:{name}")
    return {"ok": True, "id": sid}


@app.patch("/api/segments/{sid}")
def update_segment(sid: int, body: dict = Body(...), user=Depends(current_user)):
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(403, "forbidden")
    require_write(user)
    row = q1("SELECT * FROM segments WHERE id=?", (sid,))
    if not row:
        raise HTTPException(404, "not found")
    if row["is_system"]:
        raise HTTPException(400, "system segment cannot be edited")
    name = sval(body.get("name")) or row["name"]
    rule = validate_rule(body.get("rule") or json.loads(row["rule"]))
    run("UPDATE segments SET name=?, rule=? WHERE id=?", (name, json.dumps(rule, ensure_ascii=False), sid))
    audit(user["id"], "segment_update", f"{sid}:{name}")
    return {"ok": True}


@app.delete("/api/segments/{sid}")
def delete_segment(sid: int, user=Depends(current_user)):
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(403, "forbidden")
    require_write(user)
    row = q1("SELECT * FROM segments WHERE id=?", (sid,))
    if not row:
        raise HTTPException(404, "not found")
    if row["is_system"]:
        raise HTTPException(400, "system segment cannot be deleted")
    if q1("SELECT id FROM campaigns WHERE segment_id=? LIMIT 1", (sid,)):
        raise HTTPException(400, "segment used by a campaign")
    run("DELETE FROM segments WHERE id=?", (sid,))
    audit(user["id"], "segment_delete", str(sid))
    return {"ok": True}


@app.get("/api/segments/{sid}/contacts")
def segment_contacts(sid: int, limit: int = Query(300), user=Depends(current_user)):
    row = q1("SELECT * FROM segments WHERE id=?", (sid,))
    if not row:
        raise HTTPException(404, "not found")
    rule = json.loads(row["rule"])
    contacts = visible_contacts(user)
    t = rule.get("type")
    if t in SEG_MATCH:
        matched = [c for c in contacts if SEG_MATCH[t](c)]
    else:
        tm = tags_map()
        matched = [c for c in contacts if seg_match(rule, c, tm.get(c["id"], set()))]
    matched.sort(key=lambda c: c["last_contact_at"] or "")
    return {"items": [contact_out(c, user) for c in matched[:limit]], "total": len(matched)}


# ---------------- 模板 ----------------
@app.get("/api/templates")
def list_templates(user=Depends(current_user)):
    return {"items": q("SELECT * FROM templates ORDER BY id")}


@app.post("/api/templates")
def create_template(body: dict = Body(...), user=Depends(current_user)):
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(403, "forbidden")
    require_write(user)
    name = nameval(body.get("name"), 120)
    tpl_body = sval(body.get("body"))
    if not tpl_body:
        raise HTTPException(400, "body required")
    tid = run("""INSERT INTO templates(name,category,language,status,body,created_at)
                 VALUES(?,?,?,?,?,?)""",
              (name, body.get("category", "Marketing"), body.get("language", "English"),
               "pending", tpl_body, now()))
    audit(user["id"], "create_template", str(tid))
    return {"id": tid, "status": "pending"}


@app.post("/api/templates/sync")
def sync_templates(user=Depends(current_user)):
    if user["role"] != "owner":
        raise HTTPException(403, "forbidden")
    wa = (setting_get("channels", {}) or {}).get("whatsapp", {}) or {}
    waba = wa.get("waba_id")
    token = wa.get("access_token")
    if not waba or not token:
        raise HTTPException(400, "meta_not_configured")
    # 真实实现：GET https://graph.facebook.com/v20.0/{waba}/message_templates
    return {"ok": False, "reason": "not_connected"}


@app.post("/api/templates/{tid}/status")
def set_template_status(tid: int, body: dict = Body(...), user=Depends(current_user)):
    if user["role"] != "owner":
        raise HTTPException(403, "forbidden")
    st = body.get("status")
    if st not in ("pending", "approved", "rejected"):
        raise HTTPException(400, "bad status")
    run("UPDATE templates SET status=? WHERE id=?", (st, tid))
    audit(user["id"], "template_status", f"{tid}:{st}")
    return {"ok": True}


# ---------------- 触达 ----------------
@app.get("/api/campaigns")
def list_campaigns(user=Depends(current_user)):
    if user["role"] == "agent":
        raise HTTPException(403, "forbidden")
    rows = q("""SELECT cm.*, s.name AS segment_name, t.name AS template_name, t.status AS template_status
                FROM campaigns cm JOIN segments s ON s.id=cm.segment_id
                JOIN templates t ON t.id=cm.template_id ORDER BY cm.id DESC""")
    return {"items": rows}


@app.get("/api/campaigns/{cid}")
def campaign_detail(cid: int, user=Depends(current_user)):
    if user["role"] == "agent":
        raise HTTPException(403, "forbidden")
    c = q1("""SELECT cm.*, s.name AS segment_name, t.name AS template_name
              FROM campaigns cm JOIN segments s ON s.id=cm.segment_id
              JOIN templates t ON t.id=cm.template_id WHERE cm.id=?""", (cid,))
    if not c:
        raise HTTPException(404, "not found")
    rows = q("""SELECT cr.status, cr.replied_at, ct.id AS contact_id, ct.name, ct.phone, ct.country,
                       ct.deal_status, cv.id AS conv_id
                FROM campaign_recipients cr
                JOIN contacts ct ON ct.id = cr.contact_id
                LEFT JOIN conversations cv ON cv.contact_id = ct.id
                WHERE cr.campaign_id=? ORDER BY
                  CASE cr.status WHEN 'replied' THEN 0 WHEN 'delivered' THEN 1 WHEN 'failed' THEN 2 ELSE 3 END,
                  ct.id""", (cid,))
    for r in rows:
        r["phone"] = mask_phone(r["phone"])
    return {"campaign": c, "recipients": rows,
            "summary": {
                "replied": len([r for r in rows if r["status"] == "replied"]),
                "delivered": len([r for r in rows if r["status"] == "delivered"]),
                "failed": len([r for r in rows if r["status"] == "failed"]),
            }}


@app.post("/api/campaigns")
def create_campaign(body: dict = Body(...), user=Depends(current_user)):
    if user["role"] == "agent":
        raise HTTPException(403, "forbidden")
    require_write(user)
    seg_id = int(body.get("segment_id") or 0)
    tpl_id = int(body.get("template_id") or 0)
    seg = q1("SELECT * FROM segments WHERE id=?", (seg_id,))
    tpl = q1("SELECT * FROM templates WHERE id=?", (tpl_id,))
    if not seg or not tpl:
        raise HTTPException(400, "segment or template not found")
    if tpl["status"] != "approved":
        raise HTTPException(400, "template not approved")
    contacts = visible_contacts(user)
    rule = json.loads(seg["rule"])
    if rule.get("type") in SEG_MATCH:
        matched = [c for c in contacts if SEG_MATCH[rule["type"]](c)]
    else:
        tm = tags_map()
        matched = [c for c in contacts if seg_match(rule, c, tm.get(c["id"], set()))]
    sendable = [c for c in matched if not c["opt_out"]]
    if not sendable:
        raise HTTPException(400, "no sendable contacts")
    cname = sval(body.get("name")) or f"{tpl['name']} → {seg['name']}"
    if len(cname) > 120:
        raise HTTPException(400, "campaign name too long")
    cid = run("""INSERT INTO campaigns(name,segment_id,template_id,status,created_at)
                 VALUES(?,?,?,?,?)""",
              (cname, seg_id, tpl_id, "sending", now()))
    # 沙盒发送：按可达比例生成回执（不真实发送）
    delivered = int(len(sendable) * 0.96)
    replied = max(1, round(delivered * 0.084)) if delivered else 0
    run("UPDATE campaigns SET status='done',sent=?,delivered=?,replied=? WHERE id=?",
        (len(sendable), delivered, replied, cid))
    for idx, c in enumerate(sendable):
        st = "replied" if idx < replied else ("delivered" if idx < delivered else "failed")
        run("""INSERT INTO campaign_recipients(campaign_id,contact_id,status,replied_at)
               VALUES(?,?,?,?)""", (cid, c["id"], st, now() if st == "replied" else None))
    audit(user["id"], "campaign_send", str(cid))
    return {"id": cid, "sent": len(sendable), "delivered": delivered, "replied": replied}


# ---------------- 会话 ----------------
@app.get("/api/conversations")
def list_conversations(user=Depends(current_user)):
    rows = q("""SELECT cv.*, c.name AS contact_name, c.phone, c.country, c.deal_status,
                       u.name AS owner_name, n.label AS number_label,
                       (SELECT body FROM messages m WHERE m.conversation_id=cv.id
                        ORDER BY m.created_at DESC LIMIT 1) AS last_body
                FROM conversations cv JOIN contacts c ON c.id=cv.contact_id
                LEFT JOIN users u ON u.id=cv.owner_id
                LEFT JOIN numbers n ON n.id=cv.number_id
                ORDER BY cv.last_at DESC""")
    allowed = allowed_number_ids(user)
    if allowed is not None:
        rows = [r for r in rows if r["number_id"] in allowed]
    if user["role"] == "agent" and ((setting_get("inbox", {}) or {}).get("visibility") == "own"):
        rows = [r for r in rows if r["owner_id"] in (None, user["id"])]
    for r in rows:
        r["phone"] = mask_phone(r["phone"])
    return {"items": rows}


def cv_owner_check(cid, user):
    row = q1("SELECT owner_id FROM conversations WHERE id=?", (cid,))
    return bool(row) and row["owner_id"] == user["id"]


@app.post("/api/conversations/{cid}/claim")
def claim_conversation(cid: int, user=Depends(current_user)):
    if not user.get("can_reply", 1):
        raise HTTPException(403, "read_only")
    cv = q1("SELECT * FROM conversations WHERE id=?", (cid,))
    if not cv:
        raise HTTPException(404, "not found")
    if not can_see_conv(cv, user):
        raise HTTPException(403, "forbidden")
    if cv["owner_id"]:
        raise HTTPException(400, "already_owned")
    contact_owner = q1("SELECT owner_id FROM contacts WHERE id=?", (cv["contact_id"],))
    if contact_owner and contact_owner["owner_id"] not in (None, user["id"]):
        raise HTTPException(400, "contact_owned_by_someone_else")
    n = run_count("UPDATE conversations SET owner_id=? WHERE id=? AND owner_id IS NULL", (user["id"], cid))
    if n == 0:
        raise HTTPException(400, "already_owned")
    if cv.get("contact_id"):
        run("UPDATE contacts SET owner_id=?, claimed_at=?, released_at=NULL WHERE id=?",
            (user["id"], now(), cv["contact_id"]))
    audit(user["id"], "claim_conv", str(cid))
    return {"ok": True}


@app.get("/api/conversations/{cid}/messages")
def get_messages(cid: int, user=Depends(current_user)):
    cv = q1("SELECT * FROM conversations WHERE id=?", (cid,))
    if not cv:
        raise HTTPException(404, "not found")
    if not can_see_conv(cv, user):
        raise HTTPException(403, "forbidden")
    rows = q("""SELECT m.*, u.name AS sender_name FROM messages m
                LEFT JOIN users u ON u.id=m.sender_id
                WHERE m.conversation_id=? ORDER BY m.id""", (cid,))
    # 24 小时窗口
    last_in = q1("""SELECT created_at FROM messages WHERE conversation_id=? AND direction='in'
                    ORDER BY id DESC LIMIT 1""", (cid,))
    window_open = False
    if last_in:
        try:
            t = datetime.strptime(last_in["created_at"][:19], "%Y-%m-%d %H:%M:%S")
            window_open = (datetime.now() - t) < timedelta(hours=24)
        except Exception:
            window_open = False
    run("UPDATE conversations SET unread=0 WHERE id=?", (cid,))
    return {"items": rows, "window_open": window_open, "owner_id": cv["owner_id"]}


@app.post("/api/conversations/{cid}/simulate-inbound")
def simulate_inbound(cid: int, body: dict = Body(...), user=Depends(current_user)):
    """沙盒：模拟客户发来一条消息，用于测试退订识别等。"""
    text = sval(body.get("body"))
    if not text:
        raise HTTPException(400, "empty")
    if len(text) > 4096:
        raise HTTPException(400, "message too long (max 4096)")
    cv = q1("SELECT * FROM conversations WHERE id=?", (cid,))
    if not cv:
        raise HTTPException(404, "not found")
    if not can_see_conv(cv, user):
        raise HTTPException(403, "forbidden")
    mid = run("""INSERT INTO messages(conversation_id,direction,body,sender_id,created_at)
                 VALUES(?,?,?,?,?)""", (cid, "in", text, None, now()))
    run("UPDATE conversations SET last_at=?, unread=unread+1 WHERE id=?", (now(), cid))
    opted = False
    if is_optout(text):
        apply_optout(cv["contact_id"])
        opted = True
    return {"id": mid, "opt_out_triggered": opted}


@app.post("/api/contacts/{cid}/optout")
def set_optout(cid: int, body: dict = Body(...), user=Depends(current_user)):
    if user["role"] == "agent":
        raise HTTPException(403, "forbidden")
    require_write(user)
    c = q1("""SELECT c.*, u.team AS owner_team FROM contacts c
              LEFT JOIN users u ON u.id=c.owner_id WHERE c.id=?""", (cid,))
    if not c or not can_see_contact(c, user):
        raise HTTPException(403, "forbidden")
    run("UPDATE contacts SET opt_out=? WHERE id=?", (1 if body.get("opt_out") else 0, cid))
    audit(user["id"], "set_optout", f"{cid}:{body.get('opt_out')}")
    return {"ok": True}


@app.post("/api/conversations/{cid}/messages")
def send_message(cid: int, body: dict = Body(...), user=Depends(current_user)):
    text = sval(body.get("body"))
    if not text:
        raise HTTPException(400, "empty")
    if len(text) > 4096:
        raise HTTPException(400, "message too long (max 4096)")
    if not user.get("can_reply", 1):
        raise HTTPException(403, "read_only")
    cv = q1("SELECT * FROM conversations WHERE id=?", (cid,))
    if not cv:
        raise HTTPException(404, "not found")
    if not can_see_conv(cv, user):
        raise HTTPException(403, "forbidden")
    if (setting_get("inbox", {}) or {}).get("reply_owner_only", True) and cv["owner_id"] != user["id"]:
        raise HTTPException(403, "not_owner")
    mid = run("""INSERT INTO messages(conversation_id,direction,body,sender_id,created_at)
                 VALUES(?,?,?,?,?)""", (cid, "out", text, user["id"], now()))
    run("UPDATE conversations SET last_at=? WHERE id=?", (now(), cid))
    audit(user["id"], "send_message", str(cid))
    return {"id": mid, "sandbox": True}


@app.post("/api/conversations/{cid}/assign")
def assign_conversation(cid: int, body: dict = Body(...), user=Depends(current_user)):
    if user["role"] == "agent":
        raise HTTPException(403, "forbidden")
    require_write(user)
    owner = body.get("owner_id")
    if owner is not None:
        owner = ival(owner, -1)
        if owner <= 0:
            raise HTTPException(400, "bad owner_id")
        if not q1("SELECT id FROM users WHERE id=?", (owner,)):
            raise HTTPException(400, "user not found")
    conv = q1("SELECT contact_id, number_id FROM conversations WHERE id=?", (cid,))
    if not conv:
        raise HTTPException(404, "not found")
    if not can_see_conv(conv, user):
        raise HTTPException(403, "forbidden")
    run("UPDATE conversations SET owner_id=? WHERE id=?", (owner, cid))
    # 会话分给谁，这个客户就归谁；清空会话负责人不动客户归属
    if owner and conv and conv.get("contact_id"):
        run("UPDATE contacts SET owner_id=?, claimed_at=?, released_at=NULL WHERE id=?",
            (owner, now(), conv["contact_id"]))
        audit(user["id"], "assign_conv", f"{cid}->{owner}")
    return {"ok": True}


@app.get("/api/conversations/{cid}/contact-card")
def conversation_contact_card(cid: int, user=Depends(current_user)):
    """会话右侧档案卡：有会话权限就能看基础资料；完整档案仍受客户权限控制。"""
    cv = q1("SELECT * FROM conversations WHERE id=?", (cid,))
    if not cv:
        raise HTTPException(404, "not found")
    if not can_see_conv(cv, user):
        raise HTTPException(403, "forbidden")
    c = q1("""SELECT c.*, u.name AS owner_name, u.team AS owner_team
              FROM contacts c LEFT JOIN users u ON u.id=c.owner_id WHERE c.id=?""", (cv["contact_id"],))
    if not c:
        raise HTTPException(404, "not found")
    if can_see_contact(c, user):
        out = contact_out(c, user)
        out["limited"] = False
        return out
    return {"id": c["id"], "name": c["name"], "phone": mask_phone(c["phone"]),
            "country": c["country"], "deal_status": c["deal_status"],
            "owner_name": c.get("owner_name"), "owner_id": c["owner_id"],
            "opt_out": bool(c["opt_out"]), "tags": [], "segment": segment_of(c),
            "deal_value": None, "limited": True}


@app.post("/api/conversations/{cid}/ai")
def set_conversation_ai(cid: int, body: dict = Body(...), user=Depends(current_user)):
    require_write(user)
    cv = q1("SELECT * FROM conversations WHERE id=?", (cid,))
    if not cv:
        raise HTTPException(404, "not found")
    if not can_see_conv(cv, user):
        raise HTTPException(403, "forbidden")
    enabled = 1 if body.get("enabled") else 0
    run("UPDATE conversations SET ai_enabled=? WHERE id=?", (enabled, cid))
    audit(user["id"], "conv_ai", f"{cid}:{enabled}")
    return {"ok": True, "ai_enabled": bool(enabled)}


@app.get("/api/conversations/{cid}/ai-draft")
def get_ai_draft(cid: int, user=Depends(current_user)):
    cv = q1("SELECT * FROM conversations WHERE id=?", (cid,))
    if not cv:
        raise HTTPException(404, "not found")
    if not can_see_conv(cv, user):
        raise HTTPException(403, "forbidden")
    d = q1("SELECT * FROM ai_drafts WHERE conversation_id=? ORDER BY id DESC LIMIT 1", (cid,))
    if not d:
        return {"draft": None}
    try:
        d["sources"] = json.loads(d.get("sources") or "[]")
    except Exception:
        d["sources"] = []
    return {"draft": d}


@app.post("/api/ai-drafts/{did}/accept")
def accept_ai_draft(did: int, body: dict = Body(default={}), user=Depends(current_user)):
    d = q1("SELECT * FROM ai_drafts WHERE id=?", (did,))
    if not d:
        raise HTTPException(404, "not found")
    cv = q1("SELECT * FROM conversations WHERE id=?", (d["conversation_id"],))
    if not cv or not can_see_conv(cv, user):
        raise HTTPException(403, "forbidden")
    if not user.get("can_reply", 1):
        raise HTTPException(403, "read_only")
    if (setting_get("inbox", {}) or {}).get("reply_owner_only", True) and cv["owner_id"] != user["id"]:
        raise HTTPException(403, "not_owner")
    text = sval(body.get("content")) or d["content"]
    run("""INSERT INTO messages(conversation_id,direction,body,sender_id,via,created_at)
           VALUES(?,?,?,?,?,?)""", (cv["id"], "out", text, user["id"], "ai", now()))
    run("UPDATE conversations SET last_at=? WHERE id=?", (now(), cv["id"]))
    run("DELETE FROM ai_drafts WHERE id=?", (did,))
    audit(user["id"], "ai_draft_accept", str(did))
    return {"ok": True}


@app.post("/api/ai-drafts/{did}/dismiss")
def dismiss_ai_draft(did: int, user=Depends(current_user)):
    d = q1("SELECT * FROM ai_drafts WHERE id=?", (did,))
    if not d:
        raise HTTPException(404, "not found")
    cv = q1("SELECT * FROM conversations WHERE id=?", (d["conversation_id"],))
    if not cv or not can_see_conv(cv, user):
        raise HTTPException(403, "forbidden")
    run("DELETE FROM ai_drafts WHERE id=?", (did,))
    audit(user["id"], "ai_draft_dismiss", str(did))
    return {"ok": True}


# ---------------- 号码 ----------------
@app.get("/api/numbers")
def list_numbers(user=Depends(current_user)):
    if user["role"] == "agent":
        raise HTTPException(403, "forbidden")
    rows = q("SELECT * FROM numbers ORDER BY id")
    if user["role"] == "manager":
        allowed = allowed_number_ids(user)
        rows = [r for r in rows if r["id"] in allowed]
    nt = q("SELECT number_id, team_id FROM number_teams")
    for r in rows:
        r["team_ids"] = [x["team_id"] for x in nt if x["number_id"] == r["id"]]
        r["phone"] = mask_phone(r["phone"].replace(" ", ""))
        if r.get("waba_id"):
            r["waba_id"] = r["waba_id"][:4] + "***"
        if r.get("phone_number_id"):
            r["phone_number_id"] = r["phone_number_id"][:4] + "***"
    return {"items": rows}


@app.post("/api/numbers")
def create_number(body: dict = Body(...), user=Depends(current_user)):
    if user["role"] != "owner":
        raise HTTPException(403, "forbidden")
    if not (sval(body.get("label")) and sval(body.get("phone"))):
        raise HTTPException(400, "label and phone required")
    mode = sval(body.get("access_mode")) or "sandbox"
    status = sval(body.get("status")) or "connected"
    quality = sval(body.get("quality")) or "unknown"
    if mode not in ("sandbox", "cloud", "coexist"):
        raise HTTPException(400, "bad access_mode")
    if status not in ("connected", "cooling", "disconnected"):
        raise HTTPException(400, "bad status")
    if quality not in ("high", "medium", "low", "unknown"):
        raise HTTPException(400, "bad quality")
    nid = run("""INSERT INTO numbers(label,phone,purpose,waba_id,phone_number_id,quality,daily_limit,sent_today,status,access_mode,created_at)
                 VALUES(?,?,?,?,?,?,?,0,?,?,?)""",
              (sval(body.get("label")), sval(body.get("phone")), sval(body.get("purpose")) or "Sales",
               sval(body.get("waba_id")), sval(body.get("phone_number_id")), quality,
               ival(body.get("daily_limit"), 1000) or 1000, status, mode, now()))
    audit(user["id"], "create_number", str(nid))
    return {"id": nid}


@app.patch("/api/numbers/{nid}")
def update_number(nid: int, body: dict = Body(...), user=Depends(current_user)):
    if user["role"] != "owner":
        raise HTTPException(403, "forbidden")
    fields = {k: body[k] for k in ("label", "purpose", "quality", "daily_limit", "status",
                                   "waba_id", "phone_number_id", "access_mode") if k in body}
    if "access_mode" in fields and fields["access_mode"] not in ("sandbox", "cloud", "coexist"):
        raise HTTPException(400, "bad access_mode")
    if "status" in fields and fields["status"] not in ("connected", "cooling", "disconnected"):
        raise HTTPException(400, "bad status")
    if "quality" in fields and fields["quality"] not in ("high", "medium", "low", "unknown"):
        raise HTTPException(400, "bad quality")
    for k, v in fields.items():
        run(f"UPDATE numbers SET {k}=? WHERE id=?", (v, nid))
    audit(user["id"], "update_number", str(nid))
    return {"ok": True}


@app.delete("/api/numbers/{nid}")
def delete_number(nid: int, user=Depends(current_user)):
    if user["role"] != "owner":
        raise HTTPException(403, "forbidden")
    used = q1("SELECT COUNT(*) c FROM conversations WHERE number_id=?", (nid,))["c"]
    if used:
        raise HTTPException(400, f"number has {used} conversations, move them first")
    run("DELETE FROM number_teams WHERE number_id=?", (nid,))
    run("DELETE FROM numbers WHERE id=?", (nid,))
    return {"ok": True}


@app.post("/api/numbers/sync")
def sync_numbers(body: dict = Body(default={}), user=Depends(current_user)):
    """从 Meta Graph API 拉取这个 WABA 下的全部号码，新增/更新到号码表。"""
    if user["role"] != "owner":
        raise HTTPException(403, "forbidden")
    ch = setting_get("channels", {}) or {}
    wa = dict(ch.get("whatsapp") or {})
    waba = (body.get("waba_id") or wa.get("waba_id") or "").strip()
    token = (body.get("access_token") or wa.get("access_token") or "").strip()
    if not waba or not token:
        raise HTTPException(400, "missing_credentials")
    url = ("https://graph.facebook.com/v20.0/" + urllib.parse.quote(waba) +
           "/phone_numbers?fields=id,display_phone_number,verified_name,quality_rating")
    try:
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        raise HTTPException(400, "meta_error: " + str(e)[:140])
    wa.update({"status": "connected", "waba_id": waba, "access_token": token})
    ch["whatsapp"] = wa
    setting_set("channels", ch)
    qmap = {"GREEN": "high", "YELLOW": "medium", "RED": "low"}
    added = updated = 0
    for p in data.get("data", []):
        pnid = p.get("id") or ""
        phone = p.get("display_phone_number") or ""
        label = p.get("verified_name") or ("WhatsApp " + phone[-4:])
        qual = qmap.get((p.get("quality_rating") or "").upper(), "unknown")
        row = q1("SELECT id FROM numbers WHERE phone_number_id=? OR phone=?", (pnid, phone))
        if row:
            run("UPDATE numbers SET label=?, phone=?, quality=?, waba_id=?, phone_number_id=?, status='connected' WHERE id=?",
                (label, phone, qual, waba, pnid, row["id"]))
            updated += 1
        else:
            run("""INSERT INTO numbers(label,phone,purpose,waba_id,phone_number_id,quality,daily_limit,sent_today,status,created_at)
                   VALUES(?,?,?,?,?,?,1000,0,'connected',?)""",
                (label, phone, "Sales", waba, pnid, qual, now()))
            added += 1
    audit(user["id"], "sync_numbers", f"added={added},updated={updated}")
    return {"ok": True, "added": added, "updated": updated, "total": len(data.get("data", []))}


# ---------------- WhatsApp Webhook（接收真实消息 / 共存回显） ----------------
def _wa_verify_token():
    ch = setting_get("channels", {}) or {}
    return ((ch.get("whatsapp") or {}).get("verify_token") or os.environ.get("WA_VERIFY_TOKEN") or "").strip()


def _wa_app_secret():
    ch = setting_get("channels", {}) or {}
    return ((ch.get("whatsapp") or {}).get("app_secret") or os.environ.get("WA_APP_SECRET") or "").strip()


def _digits(phone):
    return "".join(c for c in (phone or "") if c.isdigit())


def _ensure_contact(phone):
    digits = _digits(phone)
    if not digits:
        return None
    row = q1("SELECT id FROM contacts WHERE REPLACE(REPLACE(phone,' ',''),'+','')=?", (digits,))
    if row:
        return row["id"]
    return run("""INSERT INTO contacts(name,phone,country,source,source_detail,opt_in_at,created_at)
                  VALUES(?,?,?,?,?,?,?)""",
               ("WhatsApp " + digits[-4:], "+" + digits, "", "WhatsApp", "Inbound", now(), now()))


def _ensure_conv(contact_id, number_id):
    row = q1("SELECT id FROM conversations WHERE contact_id=? AND number_id=? AND status='open'",
             (contact_id, number_id))
    if row:
        return row["id"]
    return run("""INSERT INTO conversations(contact_id,channel,number_id,owner_id,unread,status,last_at)
                  VALUES(?,?,?,NULL,0,'open',?)""", (contact_id, "+", number_id, now()))


def _inherit_owner(contact_id, conv_id):
    """客户已有负责人时，新会话直接归该负责人。"""
    row = q1("SELECT owner_id FROM contacts WHERE id=?", (contact_id,))
    if row and row["owner_id"]:
        run("UPDATE conversations SET owner_id=? WHERE id=? AND owner_id IS NULL",
            (row["owner_id"], conv_id))


def _store_message(conv_id, direction, body, wa_id, via, ts):
    if wa_id and q1("SELECT id FROM messages WHERE wa_message_id=?", (wa_id,)):
        return 0
    when = now()
    if ts:
        try:
            when = datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    run("""INSERT INTO messages(conversation_id,direction,body,sender_id,wa_message_id,via,created_at)
           VALUES(?,?,?,NULL,?,?,?)""", (conv_id, direction, body, wa_id, via, when))
    run("UPDATE conversations SET last_at=?, unread=unread+? WHERE id=?",
        (when, 1 if direction == "in" else 0, conv_id))
    return 1


@app.get("/api/webhooks/whatsapp")
def wa_verify(hub_mode: str = Query("", alias="hub.mode"),
              hub_token: str = Query("", alias="hub.verify_token"),
              hub_challenge: str = Query("", alias="hub.challenge")):
    expected = _wa_verify_token()
    if hub_mode == "subscribe" and expected and hmac.compare_digest(hub_token, expected):
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(403, "verify failed")


@app.post("/api/webhooks/whatsapp")
async def wa_webhook(request: Request):
    """Meta 回调：客户来信 + 共存模式下手机 App 发出的回显。"""
    raw = await request.body()
    secret = _wa_app_secret()
    if secret:
        sig = request.headers.get("x-hub-signature-256", "")
        want = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, want):
            raise HTTPException(403, "bad signature")
    try:
        payload = json.loads(raw.decode() or "{}")
    except Exception:
        raise HTTPException(400, "bad json")
    saved = 0
    entries = payload.get("entry", []) if isinstance(payload, dict) else []
    if not isinstance(entries, list):
        entries = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        changes = entry.get("changes", [])
        if not isinstance(changes, list):
            continue
        for change in changes:
            if not isinstance(change, dict):
                continue
            v = change.get("value", {}) or {}
            if not isinstance(v, dict):
                continue
            meta = v.get("metadata", {}) or {}
            if not isinstance(meta, dict):
                meta = {}
            pnid = meta.get("phone_number_id")
            number = q1("SELECT * FROM numbers WHERE phone_number_id=? AND phone_number_id<>''", (pnid,)) if pnid else None
            if not number:
                continue
            nid = number["id"]
            for m in v.get("messages", []) or []:
                body = ((m.get("text") or {}).get("body") or "").strip()
                if not body:
                    continue
                cid = _ensure_contact(m.get("from"))
                if not cid:
                    continue
                conv = _ensure_conv(cid, nid)
                _inherit_owner(cid, conv)
                stored = _store_message(conv, "in", body, m.get("id"), "api", m.get("timestamp"))
                saved += stored
                if stored and not is_optout(body):
                    cv_row = q1("SELECT * FROM conversations WHERE id=?", (conv,))
                    if cv_row:
                        # 真实问答可能十几秒，不能阻塞 webhook 的 200 响应
                        threading.Thread(target=ai_inbound_bg,
                                         args=(dict(cv_row), cid, body), daemon=True).start()
                if is_optout(body):
                    apply_optout(cid)
            for m in v.get("smb_message_echoes", []) or []:
                body = ((m.get("text") or {}).get("body") or "").strip()
                if not body:
                    continue
                cid = _ensure_contact(m.get("to"))
                if not cid:
                    continue
                conv = _ensure_conv(cid, nid)
                _inherit_owner(cid, conv)
                saved += _store_message(conv, "out", body, m.get("id"), "app", m.get("timestamp"))
    return {"ok": True, "saved": saved}


@app.get("/api/numbers/allowed")
def allowed_numbers(user=Depends(current_user)):
    """当前账号能看到的号码（会话台筛选用）。"""
    allowed = allowed_number_ids(user)
    rows = q("SELECT id, label, phone, purpose, status FROM numbers ORDER BY id")
    if allowed is not None:
        rows = [r for r in rows if r["id"] in allowed]
    for r in rows:
        r["phone"] = mask_phone(r["phone"].replace(" ", ""))
    return {"items": rows}


# ---------------- 接待组（号码 → 组 → 人） ----------------
@app.get("/api/teams")
def list_teams(user=Depends(current_user)):
    if user["role"] == "agent":
        raise HTTPException(403, "forbidden")
    teams = q("SELECT id, name, created_at FROM teams ORDER BY id")
    members = q("SELECT team_id, user_id FROM team_members")
    nums = q("SELECT number_id, team_id FROM number_teams")
    for t in teams:
        t["members"] = [m["user_id"] for m in members if m["team_id"] == t["id"]]
        t["numbers"] = [x["number_id"] for x in nums if x["team_id"] == t["id"]]
    return {"items": teams}


@app.post("/api/teams")
def create_team(body: dict = Body(...), user=Depends(current_user)):
    if user["role"] != "owner":
        raise HTTPException(403, "forbidden")
    name = nameval(body.get("name"), 60)
    if q1("SELECT id FROM teams WHERE name=?", (name,)):
        raise HTTPException(409, "team exists")
    tid = run("INSERT INTO teams(name,created_at) VALUES(?,?)", (name, now()))
    audit(user["id"], "team_create", f"{tid}:{name}")
    return {"ok": True, "id": tid}


@app.patch("/api/teams/{tid}")
def rename_team(tid: int, body: dict = Body(...), user=Depends(current_user)):
    if user["role"] != "owner":
        raise HTTPException(403, "forbidden")
    name = nameval(body.get("name"), 60)
    if not q1("SELECT id FROM teams WHERE id=?", (tid,)):
        raise HTTPException(400, "bad request")
    run("UPDATE teams SET name=? WHERE id=?", (name, tid))
    audit(user["id"], "team_rename", f"{tid}:{name}")
    return {"ok": True}


@app.delete("/api/teams/{tid}")
def delete_team(tid: int, user=Depends(current_user)):
    if user["role"] != "owner":
        raise HTTPException(403, "forbidden")
    if not q1("SELECT id FROM teams WHERE id=?", (tid,)):
        raise HTTPException(404, "not found")
    run("DELETE FROM team_members WHERE team_id=?", (tid,))
    run("DELETE FROM number_teams WHERE team_id=?", (tid,))
    run("DELETE FROM teams WHERE id=?", (tid,))
    audit(user["id"], "team_delete", str(tid))
    return {"ok": True}


@app.post("/api/teams/{tid}/members")
def set_team_members(tid: int, body: dict = Body(...), user=Depends(current_user)):
    if user["role"] != "owner":
        raise HTTPException(403, "forbidden")
    if not q1("SELECT id FROM teams WHERE id=?", (tid,)):
        raise HTTPException(404, "not found")
    raw = body.get("user_ids")
    if not isinstance(raw, list):
        raise HTTPException(400, "user_ids must be a list")
    ids = [ival(x, -1) for x in raw]
    run("DELETE FROM team_members WHERE team_id=?", (tid,))
    for uid in ids:
        if q1("SELECT id FROM users WHERE id=?", (uid,)):
            run("INSERT OR IGNORE INTO team_members(team_id,user_id) VALUES(?,?)", (tid, uid))
    audit(user["id"], "team_members", f"{tid}:{len(ids)}")
    return {"ok": True}


@app.post("/api/numbers/{nid}/teams")
def set_number_teams(nid: int, body: dict = Body(...), user=Depends(current_user)):
    if user["role"] != "owner":
        raise HTTPException(403, "forbidden")
    if not q1("SELECT id FROM numbers WHERE id=?", (nid,)):
        raise HTTPException(404, "not found")
    raw = body.get("team_ids")
    if not isinstance(raw, list):
        raise HTTPException(400, "team_ids must be a list")
    ids = [ival(x, -1) for x in raw]
    run("DELETE FROM number_teams WHERE number_id=?", (nid,))
    for tid in ids:
        if q1("SELECT id FROM teams WHERE id=?", (tid,)):
            run("INSERT OR IGNORE INTO number_teams(number_id,team_id) VALUES(?,?)", (nid, tid))
    audit(user["id"], "number_teams", f"{nid}:{len(ids)}")
    return {"ok": True}


# ---------------- 团队 ----------------
@app.get("/api/team")
def team(user=Depends(current_user)):
    if user["role"] == "agent":
        raise HTTPException(403, "forbidden")
    users = q("SELECT id,name,email,role,team,active FROM users WHERE active=1 ORDER BY id")
    if user["role"] == "manager":
        tids = team_ids_of(user)
        if tids:
            members = {m["user_id"] for m in q("SELECT team_id, user_id FROM team_members") if m["team_id"] in tids}
            users = [u for u in users if u["id"] in members or u["id"] == user["id"]]
    rows = q("""SELECT cv.owner_id, COUNT(*) AS open_count,
                       SUM(cv.unread) AS unread
                FROM conversations cv WHERE cv.status='open' GROUP BY cv.owner_id""")
    by_owner = {r["owner_id"]: r for r in rows}
    out = []
    for u in users:
        owned = q1("SELECT COUNT(*) c FROM contacts WHERE owner_id=?", (u["id"],))["c"]
        won = q1("SELECT COUNT(*) c FROM contacts WHERE owner_id=? AND deal_status='Won'", (u["id"],))["c"]
        o = by_owner.get(u["id"], {})
        out.append({
            "id": u["id"], "name": u["name"], "email": u["email"], "role": u["role"],
            "open": o.get("open_count") or 0,
            "unread": o.get("unread") or 0,
            "contacts": owned, "won": won,
        })
    return {"items": out,
            "scopes": (setting_get("pool", {}) or {}).get("scopes", {}),
            "totals": {
                "open": sum(x["open"] for x in out),
                "unread": sum(x["unread"] for x in out),
                "unassigned": q1("SELECT COUNT(*) c FROM conversations WHERE owner_id IS NULL")["c"],
            }}


# ---------------- 看板 ----------------
def _parse_day(s):
    try:
        return datetime.strptime((s or "")[:10], "%Y-%m-%d")
    except Exception:
        return None


@app.get("/api/analytics")
def analytics(period: str = Query("30d", alias="range"), agent: str = Query(""), channel: str = Query(""),
              country: str = Query(""), segment: str = Query(""), deal: str = Query(""),
              tag: str = Query(""), team: str = Query(""), number: str = Query(""),
              opt: str = Query(""), start: str = Query(""), end: str = Query(""),
              user=Depends(current_user)):
    if user["role"] == "agent":
        raise HTTPException(403, "forbidden")

    now_dt = datetime.now()
    if start or end:
        sd = _parse_day(start) or (now_dt - timedelta(days=30))
        ed = _parse_day(end) or now_dt
        if ed < sd:
            sd, ed = ed, sd
        since_dt = datetime(sd.year, sd.month, sd.day)
        until_dt = datetime(ed.year, ed.month, ed.day, 23, 59, 59)
        days = max(1, (ed - sd).days + 1)
    else:
        days = {"7d": 7, "30d": 30, "90d": 90}.get(period, 30)
        until_dt = now_dt
        since_dt = now_dt - timedelta(days=days)
    since = since_dt.strftime("%Y-%m-%d %H:%M:%S")
    until = until_dt.strftime("%Y-%m-%d %H:%M:%S")
    prev_since = (since_dt - (until_dt - since_dt) - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")
    prev_until = (since_dt - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")

    base_contacts = visible_contacts(user)
    tagmap = tags_map()
    tag_names = {t["id"]: t["name"] for t in q("SELECT id,name FROM tags")}
    teams = q("SELECT * FROM teams ORDER BY id")
    team_names = {t["id"]: t["name"] for t in teams}
    team_members = q("SELECT team_id,user_id FROM team_members")
    team_users = {}
    for m in team_members:
        team_users.setdefault(m["team_id"], set()).add(m["user_id"])
    allowed_numbers = allowed_number_ids(user)
    numbers = [n for n in q("SELECT * FROM numbers ORDER BY id")
               if allowed_numbers is None or n["id"] in allowed_numbers]

    all_convs = [cv for cv in q("SELECT * FROM conversations")
                 if allowed_numbers is None or cv.get("number_id") in allowed_numbers]
    conv_contact_ids = {cv["contact_id"] for cv in all_convs}

    contacts = base_contacts
    contact_filtered = False
    if agent:
        contacts = [c for c in contacts if str(c.get("owner_id")) == str(agent)]
        contact_filtered = True
    if channel:
        contacts = [c for c in contacts if (c.get("source") or "") == channel]
        contact_filtered = True
    if country:
        contacts = [c for c in contacts if (c.get("country") or "") == country]
        contact_filtered = True
    if deal:
        contacts = [c for c in contacts if (c.get("deal_status") or "") == deal]
        contact_filtered = True
    if tag:
        try:
            tid = int(tag)
        except Exception:
            tid = None
        contacts = [c for c in contacts if tid in tagmap.get(c["id"], set())]
        contact_filtered = True
    if team:
        try:
            tid = int(team)
        except Exception:
            tid = None
        members = team_users.get(tid, set())
        contacts = [c for c in contacts if c.get("owner_id") in members]
        contact_filtered = True
    if number:
        try:
            nid = int(number)
        except Exception:
            nid = None
        ids = {cv["contact_id"] for cv in all_convs if cv.get("number_id") == nid}
        contacts = [c for c in contacts if c["id"] in ids]
        contact_filtered = True
    if opt == "in":
        contacts = [c for c in contacts if not c.get("opt_out")]
        contact_filtered = True
    elif opt == "out":
        contacts = [c for c in contacts if c.get("opt_out")]
        contact_filtered = True
    seg_row = None
    if segment:
        try:
            seg_row = q1("SELECT * FROM segments WHERE id=?", (int(segment),))
        except Exception:
            seg_row = None
        if seg_row:
            srule = json.loads(seg_row["rule"] or "{}")
            st = srule.get("type")
            if st in SEG_MATCH:
                contacts = [c for c in contacts if SEG_MATCH[st](c)]
            else:
                contacts = [c for c in contacts if seg_match(srule, c, tagmap.get(c["id"], set()))]
        else:
            contacts = []
        contact_filtered = True

    contact_ids = {c["id"] for c in contacts}
    convs = [cv for cv in all_convs if cv["contact_id"] in contact_ids]
    if number:
        try:
            nid = int(number)
            convs = [cv for cv in convs if cv.get("number_id") == nid]
        except Exception:
            convs = []
    conv_ids = {cv["id"] for cv in convs}

    cms = [c for c in q("SELECT * FROM campaigns WHERE status='done' AND created_at>=? AND created_at<=?",
                        (since, until))]
    if seg_row:
        cms = [c for c in cms if c.get("segment_id") == seg_row["id"]]
    sent = sum(c["sent"] for c in cms)
    delivered = sum(c["delivered"] for c in cms)
    replied = sum(c["replied"] for c in cms)
    prev_cms = q("SELECT * FROM campaigns WHERE status='done' AND created_at>=? AND created_at<=?",
                 (prev_since, prev_until))
    if seg_row:
        prev_cms = [c for c in prev_cms if c.get("segment_id") == seg_row["id"]]

    won = len([c for c in contacts if c.get("deal_status") in SUCCESS_STATES])
    rev = sum(c.get("deal_value") or 0 for c in contacts if c.get("deal_status") in SUCCESS_STATES)
    opted = len([c for c in contacts if c.get("opt_out")])
    new_contacts = len([c for c in contacts if since <= (c.get("created_at") or "") <= until])
    prev_new = len([c for c in contacts if prev_since <= (c.get("created_at") or "") <= prev_until])
    pool_count = len([c for c in contacts if not c.get("owner_id") and not c.get("opt_out")])

    msgs = [m for m in q("""SELECT m.id,m.conversation_id,m.direction,m.created_at,m.via
                            FROM messages m WHERE m.created_at>=? AND m.created_at<=?
                            ORDER BY m.created_at,m.id""", (since, until))
            if m["conversation_id"] in conv_ids]
    msg_in = len([m for m in msgs if m["direction"] == "in"])
    msg_out = len([m for m in msgs if m["direction"] == "out"])
    ai_sent = len([m for m in msgs if m["direction"] == "out" and (m.get("via") or "") == "ai"])

    all_conv_msgs = [m for m in q("""SELECT id,conversation_id,direction,created_at FROM messages
                                     WHERE created_at>=? AND created_at<=?
                                     ORDER BY conversation_id,created_at,id""", (since, until))
                     if m["conversation_id"] in conv_ids]
    latencies, pending = [], {}
    for m in all_conv_msgs:
        cid = m["conversation_id"]
        if m["direction"] == "in":
            pending.setdefault(cid, m["created_at"])
        elif cid in pending:
            try:
                t0 = datetime.strptime(pending[cid][:19], "%Y-%m-%d %H:%M:%S")
                t1 = datetime.strptime(m["created_at"][:19], "%Y-%m-%d %H:%M:%S")
                latencies.append(max(0, (t1 - t0).total_seconds() / 60))
            except Exception:
                pass
            pending.pop(cid, None)
    avg_reply_min = round(sum(latencies) / len(latencies), 1) if latencies else 0

    ai_logs = [x for x in q("""SELECT * FROM ai_logs WHERE created_at>=? AND created_at<=?""",
                            (since, until))]
    if contact_filtered or user["role"] != "owner":
        ai_logs = [x for x in ai_logs if x.get("contact_id") in contact_ids]
    ai_total = len(ai_logs)
    ai_auto = len([x for x in ai_logs if x.get("decision") == "auto"])
    ai_draft = len([x for x in ai_logs if x.get("decision") == "draft"])
    ai_handoff = len([x for x in ai_logs if x.get("decision") == "handoff"])
    ai_blocked = len([x for x in ai_logs if x.get("decision") == "blocked"])
    ai_hit = len([x for x in ai_logs if (x.get("sources") or "[]") not in ("", "[]")])
    ai_lat = [x["latency_ms"] for x in ai_logs if x.get("latency_ms")]
    ai_avg_ms = round(sum(ai_lat) / len(ai_lat)) if ai_lat else 0
    prev_ai = [x for x in q("SELECT id,contact_id FROM ai_logs WHERE created_at>=? AND created_at<=?",
                            (prev_since, prev_until))]
    if contact_filtered or user["role"] != "owner":
        prev_ai = [x for x in prev_ai if x.get("contact_id") in contact_ids]

    day_list = []
    dcur = since_dt.date()
    dend = min(until_dt.date(), now_dt.date())
    while dcur <= dend:
        day_list.append(dcur)
        dcur += timedelta(days=1)
    if len(day_list) > 120:
        day_list = day_list[-120:]
    series_map = {d.strftime("%m-%d"): {"d": d.strftime("%m-%d"), "out": 0, "in": 0, "new": 0}
                  for d in day_list}
    for m in msgs:
        k = (m.get("created_at") or "")[5:10]
        if k in series_map:
            series_map[k]["out" if m["direction"] == "out" else "in"] += 1
    for c in contacts:
        k = (c.get("created_at") or "")[5:10]
        if k in series_map:
            series_map[k]["new"] += 1

    channel_split = {}
    for c in contacts:
        k = c.get("source") or "Other"
        channel_split[k] = channel_split.get(k, 0) + 1

    segs = []
    for s in q("SELECT * FROM segments ORDER BY is_system DESC, id"):
        rule = json.loads(s["rule"] or "{}")
        st = rule.get("type")
        if st in SEG_MATCH:
            matched = [c for c in contacts if SEG_MATCH[st](c)]
        else:
            matched = [c for c in contacts if seg_match(rule, c, tagmap.get(c["id"], set()))]
        sendable = [c for c in matched if not c.get("opt_out")]
        segs.append({"id": s["id"], "name": s["name"], "rule": rule,
                     "is_system": bool(s["is_system"]), "matched": len(matched),
                     "sendable": len(sendable), "opted_out": len(matched) - len(sendable),
                     "won": len([c for c in matched if c.get("deal_status") in SUCCESS_STATES]),
                     "revenue": sum(c.get("deal_value") or 0 for c in matched
                                    if c.get("deal_status") in SUCCESS_STATES)})

    country_map = {}
    for c in contacts:
        k = c.get("country") or "—"
        o = country_map.setdefault(k, {"k": k, "n": 0, "won": 0, "revenue": 0, "opt_out": 0})
        o["n"] += 1
        o["opt_out"] += 1 if c.get("opt_out") else 0
        if c.get("deal_status") in SUCCESS_STATES:
            o["won"] += 1
            o["revenue"] += c.get("deal_value") or 0
    by_country = sorted(country_map.values(), key=lambda x: (-x["n"], x["k"]))[:15]

    owner_map = {}
    for c in contacts:
        oid = c.get("owner_id")
        o = owner_map.setdefault(oid, {"id": oid, "name": c.get("owner_name") or "",
                                       "n": 0, "won": 0, "revenue": 0, "opt_out": 0})
        o["n"] += 1
        o["opt_out"] += 1 if c.get("opt_out") else 0
        if c.get("deal_status") in SUCCESS_STATES:
            o["won"] += 1
            o["revenue"] += c.get("deal_value") or 0
    by_owner = sorted(owner_map.values(), key=lambda x: (-x["won"], -x["n"]))

    by_team = []
    for t in teams:
        members = team_users.get(t["id"], set())
        if user["role"] == "manager" and t["id"] not in team_ids_of(user):
            continue
        rows = [c for c in contacts if c.get("owner_id") in members]
        by_team.append({"id": t["id"], "name": t["name"], "n": len(rows),
                        "won": len([c for c in rows if c.get("deal_status") in SUCCESS_STATES]),
                        "revenue": sum(c.get("deal_value") or 0 for c in rows
                                       if c.get("deal_status") in SUCCESS_STATES)})

    by_tag_map = {}
    for c in contacts:
        for tid in tagmap.get(c["id"], set()):
            o = by_tag_map.setdefault(tid, {"id": tid, "name": tag_names.get(tid, "#" + str(tid)),
                                             "n": 0, "won": 0, "opt_out": 0})
            o["n"] += 1
            o["opt_out"] += 1 if c.get("opt_out") else 0
            o["won"] += 1 if c.get("deal_status") in SUCCESS_STATES else 0
    by_tag = sorted(by_tag_map.values(), key=lambda x: (-x["n"], x["name"]))[:15]

    stages = (setting_get("deal_stages", {}) or {}).get("stages", [])
    if not stages:
        stages = [{"key": k, "en": k, "zh": k} for k in ("Lead", "Contacted", "Negotiating", "Won", "Lost")]
    by_stage = []
    for st in stages:
        rows = [c for c in contacts if (c.get("deal_status") or "") == st["key"]]
        by_stage.append({"key": st["key"], "en": st.get("en", st["key"]), "zh": st.get("zh", st["key"]),
                         "n": len(rows),
                         "revenue": sum(c.get("deal_value") or 0 for c in rows
                                        if c.get("deal_status") in SUCCESS_STATES)})

    msg_by_conv = {}
    for m in msgs:
        o = msg_by_conv.setdefault(m["conversation_id"], {"in": 0, "out": 0, "ai": 0})
        o["in" if m["direction"] == "in" else "out"] += 1
        if m["direction"] == "out" and (m.get("via") or "") == "ai":
            o["ai"] += 1
    by_number = []
    for n in numbers:
        ncvs = [cv for cv in convs if cv.get("number_id") == n["id"]]
        nm = [msg_by_conv.get(cv["id"], {}) for cv in ncvs]
        by_number.append({
            "id": n["id"], "label": n["label"], "phone": mask_phone(n["phone"]),
            "quality": n["quality"], "status": n["status"],
            "conversations": len(ncvs), "unread": sum(cv.get("unread") or 0 for cv in ncvs),
            "out": sum((x or {}).get("out", 0) for x in nm),
            "in": sum((x or {}).get("in", 0) for x in nm),
            "ai": sum((x or {}).get("ai", 0) for x in nm),
        })

    campaigns = [{"id": c["id"], "name": c["name"], "sent": c["sent"], "delivered": c["delivered"],
                  "replied": c["replied"],
                  "reply_rate": round((c["replied"] or 0) / (c["delivered"] or 1) * 100, 1),
                  "created_at": c["created_at"]}
                 for c in sorted(cms, key=lambda x: -x["sent"])[:10]]

    base_countries = sorted({(c.get("country") or "") for c in base_contacts if c.get("country")})
    base_sources = sorted({(c.get("source") or "") for c in base_contacts if c.get("source")})
    owners = [u for u in q("SELECT id,name,role,team FROM users WHERE active=1 ORDER BY id")]
    if user["role"] == "manager":
        tids = team_ids_of(user)
        members = {m["user_id"] for m in team_members if m["team_id"] in tids}
        owners = [u for u in owners if u["id"] in members or u["id"] == user["id"]]
    facets = {
        "countries": base_countries, "sources": base_sources,
        "tags": [{"id": t["id"], "name": t["name"]} for t in q("SELECT id,name FROM tags ORDER BY id")],
        "segments": [{"id": s["id"], "name": s["name"]} for s in q("SELECT id,name FROM segments ORDER BY is_system DESC,id")],
        "teams": [{"id": t["id"], "name": t["name"]} for t in teams
                  if user["role"] == "owner" or t["id"] in team_ids_of(user)],
        "numbers": [{"id": n["id"], "label": n["label"]} for n in numbers],
        "stages": [{"key": x["key"], "en": x.get("en", x["key"]), "zh": x.get("zh", x["key"])}
                   for x in stages],
        "owners": [{"id": u["id"], "name": u["name"], "role": u["role"]} for u in owners],
    }

    return {
        "range": {"days": days, "since": since, "until": until, "start": start, "end": end},
        "series": list(series_map.values()),
        "channel_split": [{"k": k, "v": v} for k, v in sorted(channel_split.items(), key=lambda x: -x[1])],
        "sent": sent, "delivered": delivered, "replied": replied,
        "reply_rate": round(replied / delivered * 100, 1) if delivered else 0,
        "won": won, "revenue": rev,
        "contacts": len(contacts), "new_contacts": new_contacts,
        "opt_out": opted, "opt_out_rate": round(opted / len(contacts) * 100, 1) if contacts else 0,
        "pool_count": pool_count,
        "conversations": len(convs),
        "open_conversations": len([cv for cv in convs if cv.get("status") == "open"]),
        "unread": sum(cv.get("unread") or 0 for cv in convs),
        "messages_in": msg_in, "messages_out": msg_out, "ai_messages": ai_sent,
        "avg_reply_min": avg_reply_min,
        "funnel": [sent, delivered, replied, won],
        "segments": segs, "by_country": by_country, "by_owner": by_owner,
        "by_team": by_team, "by_tag": by_tag, "by_stage": by_stage, "by_number": by_number,
        "campaigns": campaigns, "campaign_scope": "filtered" if contact_filtered else "all",
        "ai": {"total": ai_total, "auto": ai_auto, "draft": ai_draft, "handoff": ai_handoff,
               "blocked": ai_blocked, "source_hit": ai_hit, "avg_latency_ms": ai_avg_ms,
               "auto_rate": round(ai_auto / ai_total * 100, 1) if ai_total else 0,
               "handoff_rate": round(ai_handoff / ai_total * 100, 1) if ai_total else 0},
        "prev": {"new_contacts": prev_new,
                 "sent": sum(c["sent"] for c in prev_cms),
                 "replied": sum(c["replied"] for c in prev_cms),
                 "ai_total": len(prev_ai)},
        "facets": facets,
        "templates": [{"name": t["name"], "status": t["status"]} for t in q("SELECT * FROM templates")],
    }


# ---------------- AI 助手（知识库配置与测试） ----------------
AI_DEFAULTS = {
    "enabled": True, "provider": "deskclerk", "mode": "draft", "base_url": "", "api_key": "", "site_id": "",
    "locales": ["zh-CN", "en-US", "ar-SA"], "threshold": 0.70,
    "window_only": True, "no_source_handoff": True, "badge": True, "daily_limit": 50,
    "persona": {
        "system_role": "", "company_intro": "", "product_scope": "", "policy_boundaries": "",
        "tone": "professional", "reply_max_words": 180,
        "timezone": "Asia/Riyadh", "business_hours": "",
    },
    "personas": {},
    "insights": {"auto_tags": True, "summary": True, "status": True,
                 "next_action": True, "risk": True},
    "safety": {"blocked_topics": ["价格", "交期承诺", "合同", "法律"],
               "complaint_keywords": ["投诉", "退款", "骗子", "律师"],
               "handoff_keywords": ["人工", "真人", "客服"]},
    "kb": {"indexed": 0, "pending": 0, "failed": 0, "last_sync": None, "callback_url": ""},
}


def get_ai_cfg():
    cfg = setting_get("ai", {})
    if not isinstance(cfg, dict):
        cfg = {}
    out = {**AI_DEFAULTS, **cfg}
    for k in ("persona", "safety", "kb", "insights"):
        out[k] = {**AI_DEFAULTS[k], **(cfg.get(k) if isinstance(cfg.get(k), dict) else {})}
    if not isinstance(out.get("personas"), dict) or not out["personas"]:
        out["personas"] = {"zh-CN": dict(out["persona"])}
    return out


def ai_public(cfg):
    out = dict(cfg)
    key = out.get("api_key") or ""
    env_key = os.environ.get("AICHAT_KEY", "")
    out["api_key"] = mask_secret(key) if key else ""
    out["api_key_set"] = bool(key or env_key)
    out["key_from_env"] = bool(not key and env_key)
    return out


AI_TOPICS = [
    (["moq", "起订", "最小订"], "MOQ 与起订量说明",
     "M12 螺栓标准件 MOQ 为 2,000 件/规格；混装订单合计需达到 8,000 件。", 0.86),
    (["备件", "到货", "多久", "物流", "发货", "几天"], "备件交付周期说明",
     "标准件 3–5 个工作日到货，非标件 7–10 个工作日；具体以订单确认后的排产为准。", 0.82),
    (["退换", "退货", "维修", "售后"], "退换与维修流程",
     "收到货 7 天内可申请退换；维修件需提供订单号与故障照片，48 小时内响应。", 0.78),
    (["付款", "账期", "付款方式"], "付款方式说明",
     "支持 T/T 与信用证；首次合作默认 30% 定金、70% 发货前付清。", 0.75),
]

AI_BLOCK_WORDS = ["最低价", "报价", "便宜", "折扣", "优惠", "合同", "律师", "索赔",
                  "保证交期", "承诺交期"]


def ai_decide(question, cfg):
    mode = cfg.get("mode", "draft")
    if not cfg.get("enabled", True) or mode == "off":
        return {"answer": "", "sources": [], "top_score": None, "decision": "off", "escalation": None}
    safety = cfg.get("safety", {})
    for kw in AI_BLOCK_WORDS:
        if kw in question:
            return {"answer": "价格问题已转给销售同事，稍后与您联系。", "sources": [],
                    "top_score": None, "decision": "blocked", "escalation": None,
                    "blocked_by": kw}
    for kw in safety.get("complaint_keywords", []):
        if kw in question:
            return {"answer": "收到您的反馈，我马上请同事跟进。", "sources": [], "top_score": None,
                    "decision": "handoff",
                    "escalation": {"event": "complaint_escalation", "type": "complaint",
                                   "matchedKeyword": kw}}
    for kw in safety.get("handoff_keywords", []):
        if kw in question:
            return {"answer": "好的，正在为您转接同事。", "sources": [], "top_score": None,
                    "decision": "handoff",
                    "escalation": {"event": "human_pending"}}
    q = question.lower()
    for kws, title, body, score in AI_TOPICS:
        if any(k in q for k in kws):
            if cfg.get("no_source_handoff", True) and not title:
                break
            sources = [{"title": title, "score": score, "chunkPreview": body[:60]}]
            decision = "handoff" if score < float(cfg.get("threshold", 0.7)) else (
                "draft" if mode == "draft" else "auto")
            esc = {"event": "escalation_prompt", "type": "knowledge_gap"} if decision == "handoff" else None
            return {"answer": body, "sources": sources, "top_score": score,
                    "decision": decision, "escalation": esc}
    return {"answer": "这个问题我需要请同事确认，稍后回复您。", "sources": [], "top_score": None,
            "decision": "handoff",
            "escalation": {"event": "escalation_prompt", "type": "knowledge_gap"}}


AI_REMOTE_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")


def ai_remote_ask(question, cfg, key):
    """调用第三方知识库：建会话 → 提问。返回与 ai_decide 同结构。"""
    base = (cfg.get("base_url") or "").rstrip("/")
    site = cfg.get("site_id") or ""
    if not (base and site and key):
        return None
    headers = {"X-Integration-Api-Key": key, "Content-Type": "application/json",
               "Accept": "application/json", "Accept-Language": "en-US,en;q=0.9",
               "User-Agent": AI_REMOTE_UA}

    def post(url, body):
        idem = "deskclerk-" + uuid.uuid4().hex
        last = None
        for attempt in range(3):
            try:
                r = requests.post(url, json=body,
                                  headers={**headers, "Idempotency-Key": idem},
                                  timeout=(10, 55))
                if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                if r.status_code >= 400:
                    raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
                return r.json()
            except (requests.exceptions.SSLError, requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout) as e:
                last = e
                time.sleep(0.8 * (attempt + 1))
        raise RuntimeError(f"network: {last}")

    # 站点只启用了部分语言：按配置顺序尝试，遇到 locale 未启用就换下一个
    conv, cid, last_err = None, None, None
    for locale in (cfg.get("locales") or ["en-US"]):
        try:
            conv = post(base + f"/sites/{site}/conversations",
                        {"channel": "whatsapp", "external_user_id": "deskclerk-test",
                         "user_name": "DeskClerk Test", "locale": locale, "timezone": "Asia/Riyadh"})
            cid = (conv.get("data") or {}).get("id")
            if cid:
                break
        except RuntimeError as e:
            last_err = e
            if "Locale must be enabled" not in str(e):
                raise
    if not cid:
        raise last_err or RuntimeError("no conversation id")
    d = post(base + f"/sites/{site}/conversations/{cid}/messages", {"content": question})
    data = d.get("data") or {}
    ai = data.get("aiMessage")
    esc = data.get("escalation")
    sources = (ai or {}).get("sources") or []
    score = max([float(x.get("score") or 0) for x in sources], default=None)
    if ai is None:
        return {"answer": "", "sources": [], "top_score": None, "decision": "handoff",
                "escalation": esc or {"event": "human_pending"}, "remote": True}
    if esc:
        decision = "handoff"
    elif not sources and cfg.get("no_source_handoff", True):
        decision = "handoff"
    elif score is not None and score < float(cfg.get("threshold", 0.7)):
        decision = "handoff"
    else:
        decision = "draft" if cfg.get("mode") == "draft" else "auto"
    return {"answer": ai.get("content") or "",
            "sources": [{"title": x.get("title"), "score": x.get("score")} for x in sources],
            "top_score": score, "decision": decision, "escalation": esc, "remote": True}


def ai_generate(question, cfg):
    """统一入口：有真实配置走远程，否则本地规则；记录耗时，错误不抛给调用方。"""
    t0 = time.time()
    key = cfg.get("api_key") or os.environ.get("AICHAT_KEY", "")
    res = None
    err = None
    if cfg.get("base_url") and cfg.get("site_id") and key:
        try:
            res = ai_remote_ask(question, cfg, key)
        except Exception as e:
            err = str(e)[:200]
    if res is None:
        res = ai_decide(question, cfg)
    res["latency_ms"] = max(1, int((time.time() - t0) * 1000))
    if err:
        res["error"] = err
        res.update({"answer": "", "sources": [], "top_score": None,
                    "decision": "handoff", "escalation": {"event": "escalation_prompt", "type": "ai_error"}})
    return res


def ai_log(question, res, contact_id=None, conversation_id=None):
    run("""INSERT INTO ai_logs(contact_id,conversation_id,locale,question,answer,sources,
                             top_score,decision,escalation,latency_ms,created_at)
           VALUES(?,?,NULL,?,?,?,?,?,?,?,?)""",
        (contact_id, conversation_id, question, res.get("answer", ""),
         json.dumps(res.get("sources") or [], ensure_ascii=False),
         res.get("top_score"), res.get("decision", "handoff"),
         json.dumps(res["escalation"], ensure_ascii=False) if res.get("escalation") else None,
         res.get("latency_ms") or 0, now()))


def ai_inbound_bg(conv, contact_id, text):
    try:
        handle_ai_inbound(conv, contact_id, text)
    except Exception:
        pass


def handle_ai_inbound(conv, contact_id, text):
    """客户来信时按接待方式处理：人工 / AI 草稿 / AI 全自动托管。"""
    cfg = get_ai_cfg()
    if not cfg.get("enabled") or cfg.get("mode") == "off":
        return
    if not conv.get("ai_enabled", 1):
        return
    res = ai_generate(text, cfg)
    ai_log(text, res, contact_id, conv["id"])
    if res.get("error"):
        return
    mode = cfg.get("mode")
    if mode == "auto" and res.get("decision") == "auto" and res.get("answer"):
        run("""INSERT INTO messages(conversation_id,direction,body,sender_id,via,created_at)
               VALUES(?,?,?,NULL,?,?)""", (conv["id"], "out", res["answer"], "ai", now()))
        run("UPDATE conversations SET last_at=? WHERE id=?", (now(), conv["id"]))
    elif mode == "draft" and res.get("decision") == "draft" and res.get("answer"):
        run("""INSERT INTO ai_drafts(conversation_id,content,sources,top_score,decision,escalation,created_at)
               VALUES(?,?,?,?,?,?,?)""",
            (conv["id"], res["answer"], json.dumps(res.get("sources") or [], ensure_ascii=False),
             res.get("top_score"), res.get("decision"),
             json.dumps(res["escalation"], ensure_ascii=False) if res.get("escalation") else None,
             now()))
        run("UPDATE conversations SET unread=unread+1 WHERE id=?", (conv["id"],))


@app.get("/api/ai/config")
def ai_config(user=Depends(current_user)):
    if user["role"] == "agent":
        raise HTTPException(403, "forbidden")
    return ai_public(get_ai_cfg())


def validate_persona(p):
    p = {**AI_DEFAULTS["persona"], **(p or {})}
    for k, limit in (("system_role", 2400), ("company_intro", 3000),
                     ("product_scope", 3000), ("policy_boundaries", 3000)):
        p[k] = sval(p.get(k))
        if len(p[k]) > limit:
            raise HTTPException(400, f"{k} too long")
    if p.get("tone") not in ("professional", "friendly", "direct", "consultative"):
        raise HTTPException(400, "bad tone")
    w = ival(p.get("reply_max_words"), 180)
    if not (30 <= w <= 500):
        raise HTTPException(400, "reply_max_words out of range")
    p["reply_max_words"] = w
    p["timezone"] = sval(p.get("timezone")) or "UTC"
    p["business_hours"] = sval(p.get("business_hours"))
    return p


@app.get("/api/ai/insights")
def ai_insights(user=Depends(current_user)):
    return get_ai_cfg().get("insights", {})


@app.patch("/api/ai/config")
def ai_config_save(body: dict = Body(...), user=Depends(current_user)):
    if user["role"] != "owner":
        raise HTTPException(403, "forbidden")
    cur = get_ai_cfg()
    if "provider" in body:
        if body["provider"] not in ("deskclerk", "custom"):
            raise HTTPException(400, "bad provider")
        cur["provider"] = body["provider"]
    if "mode" in body:
        if body["mode"] not in ("off", "draft", "auto"):
            raise HTTPException(400, "bad mode")
        cur["mode"] = body["mode"]
    if "threshold" in body:
        try:
            th = float(body["threshold"])
        except Exception:
            raise HTTPException(400, "threshold must be number")
        if not (0 <= th <= 1):
            raise HTTPException(400, "threshold out of range")
        cur["threshold"] = th
    if "daily_limit" in body:
        dl = ival(body["daily_limit"], -1)
        if dl < 0 or dl > 500:
            raise HTTPException(400, "daily_limit out of range")
        cur["daily_limit"] = dl
    for k in ("enabled", "window_only", "no_source_handoff", "badge"):
        if k in body:
            cur[k] = bool(body[k])
    for k in ("base_url", "site_id"):
        if k in body:
            cur[k] = sval(body[k])[:500]
    if "api_key" in body:
        key = sval(body["api_key"])
        if key and "*" not in key:
            cur["api_key"] = key
    if "locales" in body:
        if not isinstance(body["locales"], list):
            raise HTTPException(400, "locales must be a list")
        cur["locales"] = [sval(x) for x in body["locales"] if sval(x)][:10]
    if isinstance(body.get("persona"), dict):
        cur["persona"] = validate_persona({**cur["persona"], **body["persona"]})
    if isinstance(body.get("personas"), dict):
        cleaned = {}
        for loc, persona in body["personas"].items():
            if not isinstance(persona, dict):
                raise HTTPException(400, "bad persona")
            cleaned[sval(loc)[:20]] = validate_persona(persona)
        cur["personas"] = cleaned
        if "zh-CN" in cleaned:
            cur["persona"] = cleaned["zh-CN"]
    if isinstance(body.get("insights"), dict):
        cur["insights"] = {k: bool(v) for k, v in {**cur["insights"], **body["insights"]}.items()
                           if k in ("auto_tags", "summary", "status", "next_action", "risk")}
    if isinstance(body.get("safety"), dict):
        cur["safety"] = {**cur["safety"], **body["safety"]}
    if isinstance(body.get("kb"), dict):
        cur["kb"] = {**cur["kb"], **body["kb"]}
    setting_set("ai", cur)
    audit(user["id"], "ai_config", cur.get("mode", ""))
    return ai_public(cur)


@app.post("/api/ai/test")
def ai_test(body: dict = Body(...), user=Depends(current_user)):
    if user["role"] == "agent":
        raise HTTPException(403, "forbidden")
    question = sval(body.get("question"))[:2000]
    if not question:
        raise HTTPException(400, "question required")
    cfg = get_ai_cfg()
    res = ai_generate(question, cfg)
    if res.get("error"):
        raise HTTPException(502, "ai_remote_error: " + res["error"])
    ai_log(question, res)
    latency = res.get("latency_ms") or 0
    return {"question": question, "mode": cfg.get("mode", "draft"),
            "threshold": cfg.get("threshold", 0.7), "latency_ms": latency, **res}


@app.get("/api/ai/logs")
def ai_logs(limit: int = Query(50, ge=1, le=200), user=Depends(current_user)):
    if user["role"] == "agent":
        raise HTTPException(403, "forbidden")
    rows = q("""SELECT al.*, c.name AS contact_name FROM ai_logs al
                LEFT JOIN contacts c ON c.id=al.contact_id
                ORDER BY al.id DESC LIMIT ?""", (limit,))
    for r in rows:
        try:
            r["sources"] = json.loads(r["sources"] or "[]")
        except Exception:
            r["sources"] = []
        try:
            r["escalation"] = json.loads(r["escalation"]) if r["escalation"] else None
        except Exception:
            r["escalation"] = None
    return {"items": rows}


@app.post("/api/ai/kb/sync")
def ai_kb_sync(user=Depends(current_user)):
    if user["role"] != "owner":
        raise HTTPException(403, "forbidden")
    cfg = get_ai_cfg()
    kb = dict(cfg.get("kb") or {})
    kb.update({"pending": 0, "failed": 0, "last_sync": now()})
    cfg["kb"] = kb
    setting_set("ai", cfg)
    audit(user["id"], "ai_kb_sync")
    return kb


# ---------------- 设置 ----------------
@app.patch("/api/settings/channels")
def patch_channels(body: dict = Body(...), user=Depends(current_user)):
    if user["role"] != "owner":
        raise HTTPException(403, "forbidden")
    ch = setting_get("channels", {}) or {}
    for key, val in (body or {}).items():
        if key in ch and isinstance(val, dict):
            safe = {k: v for k, v in val.items()
                    if not (k in ("secret", "access_token", "app_secret", "verify_token") and "*" in str(v))}
            ch[key] = {**ch[key], **safe}
    setting_set("channels", ch)
    audit(user["id"], "update_channels", ",".join(body.keys()))
    return {"ok": True}


@app.get("/api/settings")
def get_settings(user=Depends(current_user)):
    keys = ("workspace", "compliance", "ai", "notify", "channels", "deal_stages", "pool", "inbox")
    out = {k: setting_get(k) for k in keys}
    if user["role"] == "agent":
        return {"deal_stages": out.get("deal_stages"), "inbox": out.get("inbox")}
    ai = dict(out.get("ai") or {})
    if ai.get("api_key"):
        ai["api_key"] = mask_secret(ai["api_key"])
        ai["api_key_set"] = True
    else:
        ai["api_key_set"] = False
    out["ai"] = ai
    ib = dict(out.get("inbox") or {})
    ib.setdefault("reply_owner_only", True)
    ib.setdefault("visibility", "team")
    out["inbox"] = ib
    ch = dict(out.get("channels") or {})
    wa = dict(ch.get("whatsapp") or {})
    if wa.get("access_token"):
        wa["access_token"] = mask_secret(wa["access_token"])
        wa["token_set"] = True
    if wa.get("app_secret"):
        wa["app_secret"] = mask_secret(wa["app_secret"])
    if wa.get("verify_token"):
        wa["verify_token"] = mask_secret(wa["verify_token"])
    else:
        wa["token_set"] = False
    if wa:
        ch["whatsapp"] = wa
    out["channels"] = ch
    return out


@app.patch("/api/settings")
def patch_settings(body: dict = Body(...), user=Depends(current_user)):
    if user["role"] != "owner":
        raise HTTPException(403, "forbidden")
    for k, v in body.items():
        if k in ("workspace", "compliance", "ai", "notify", "channels", "deal_stages", "pool", "inbox"):
            if not isinstance(v, dict):
                raise HTTPException(400, f"{k} must be an object")
            if k == "pool":
                if "scopes" in v and not isinstance(v["scopes"], dict):
                    raise HTTPException(400, "scopes must be an object")
                for key, lo, hi in (("recycle_days", 1, 3650), ("daily_claim_limit", 0, 1000),
                                    ("protect_hours", 0, 720)):
                    if key in v:
                        try:
                            iv = int(v[key])
                        except Exception:
                            raise HTTPException(400, f"{key} must be a number")
                        if not (lo <= iv <= hi):
                            raise HTTPException(400, f"{key} out of range")
                        v[key] = iv
            if k == "inbox" and "visibility" in v and v["visibility"] not in ("team", "own"):
                raise HTTPException(400, "bad visibility")
            if k == "deal_stages" and "stages" in v:
                stages = v["stages"]
                if not isinstance(stages, list) or not all(
                        isinstance(x, dict) and isinstance(x.get("key"), str) and x["key"] for x in stages):
                    raise HTTPException(400, "stages must be a list of objects with key")
            if k == "ai" and isinstance(v, dict) and v.get("api_key", "").find("*") >= 0:
                v.pop("api_key")           # 前端回传的是脱敏值，忽略
                v = {**(setting_get("ai") or {}), **v}
            setting_set(k, v)
    audit(user["id"], "update_settings", ",".join(body.keys()))
    return {"ok": True}


@app.post("/api/users")
def create_user(body: dict = Body(...), user=Depends(current_user)):
    if user["role"] != "owner":
        raise HTTPException(403, "forbidden")
    name = nameval(body.get("name"), 60)
    email = sval(body.get("email")).lower()
    pwd = sval(body.get("password"))
    role = sval(body.get("role")) or "agent"
    team = sval(body.get("team")) or "sales"
    if not name or "@" not in email:
        raise HTTPException(400, "name and email required")
    if len(pwd) < 8:
        raise HTTPException(400, "password too short (8+)")
    if role not in ("owner", "manager", "agent"):
        raise HTTPException(400, "bad role")
    if q1("SELECT id FROM users WHERE email=?", (email,)):
        raise HTTPException(409, "email already exists")
    can_reply = 1 if body.get("can_reply", True) else 0
    uid = run("INSERT INTO users(email,name,pwd,role,team,active,can_reply,created_at) VALUES(?,?,?,?,?,1,?,?)",
              (email, name, hash_password(pwd), role, team, can_reply, now()))
    audit(user["id"], "user_create", f"{uid}:{email}")
    return {"ok": True, "id": uid}


@app.post("/api/users/{uid}/reply")
def set_user_reply(uid: int, body: dict = Body(...), user=Depends(current_user)):
    if user["role"] != "owner":
        raise HTTPException(403, "forbidden")
    if not q1("SELECT id FROM users WHERE id=?", (uid,)):
        raise HTTPException(404, "not found")
    can = 1 if body.get("can_reply") else 0
    run("UPDATE users SET can_reply=? WHERE id=?", (can, uid))
    audit(user["id"], "user_reply", f"{uid}:{can}")
    return {"ok": True}


@app.post("/api/users/{uid}/status")
def set_user_status(uid: int, body: dict = Body(...), user=Depends(current_user)):
    if user["role"] != "owner":
        raise HTTPException(403, "forbidden")
    if not q1("SELECT id FROM users WHERE id=?", (uid,)):
        raise HTTPException(404, "not found")
    if uid == user["id"]:
        raise HTTPException(400, "cannot disable yourself")
    active = 1 if body.get("active") else 0
    run("UPDATE users SET active=? WHERE id=?", (active, uid))
    audit(user["id"], "user_status", f"{uid}:{active}")
    return {"ok": True}


@app.post("/api/users/{uid}/transfer")
def transfer_contacts(uid: int, body: dict = Body(...), user=Depends(current_user)):
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(403, "forbidden")
    require_write(user)
    src_user = q1("SELECT * FROM users WHERE id=?", (uid,))
    if not src_user:
        raise HTTPException(404, "not found")
    if user["role"] == "manager" and not shares_team(user, src_user):
        raise HTTPException(403, "different team")
    to = body.get("to_user_id")
    target = q1("SELECT * FROM users WHERE id=?", (to,)) if to else None
    if not target:
        raise HTTPException(400, "target user not found")
    if target["active"] == 0:
        raise HTTPException(400, "target user is disabled")
    if user["role"] == "manager" and not shares_team(user, target):
        raise HTTPException(403, "different team")
    n1 = len(q("SELECT id FROM contacts WHERE owner_id=?", (uid,)))
    run("UPDATE contacts SET owner_id=? WHERE owner_id=?", (to, uid))
    run("UPDATE conversations SET owner_id=? WHERE owner_id=?", (to, uid))
    audit(user["id"], "transfer_contacts", f"{uid}->{to}")
    return {"ok": True, "moved": n1}


@app.delete("/api/users/{uid}")
def delete_user(uid: int, user=Depends(current_user)):
    if user["role"] != "owner":
        raise HTTPException(403, "forbidden")
    if uid == user["id"]:
        raise HTTPException(400, "cannot delete yourself")
    target = q1("SELECT * FROM users WHERE id=?", (uid,))
    if not target:
        raise HTTPException(404, "not found")
    if target["role"] == "owner":
        owners = q1("SELECT COUNT(*) c FROM users WHERE role='owner' AND active=1")["c"]
        if owners <= 1:
            raise HTTPException(400, "cannot delete the last owner")
    left = len(q("SELECT id FROM contacts WHERE owner_id=?", (uid,)))
    if left:
        raise HTTPException(400, f"user still owns {left} contacts, transfer first")
    run("DELETE FROM users WHERE id=?", (uid,))
    run("DELETE FROM team_members WHERE user_id=?", (uid,))
    run("UPDATE conversations SET owner_id=NULL WHERE owner_id=?", (uid,))
    audit(user["id"], "delete_user", str(uid))
    return {"ok": True}


@app.get("/api/audit")
def list_audit(limit: int = Query(100), user=Depends(current_user)):
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(403, "forbidden")
    rows = q("""SELECT a.*, u.name AS user_name FROM audit a
                LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT ?""", (limit,))
    if user["role"] == "manager":
        tids = team_ids_of(user)
        members = {m["user_id"] for m in q("SELECT team_id, user_id FROM team_members") if m["team_id"] in tids}
        rows = [r for r in rows if r["user_id"] is None or r["user_id"] in members]
    return {"items": rows}


@app.get("/api/export/contacts.csv")
def export_contacts(user=Depends(current_user)):
    import csv as _csv
    import io
    rows = visible_contacts(user)
    buf = io.StringIO()
    w = _csv.writer(buf)
    w.writerow(["name", "phone", "country", "source", "segment", "deal_status",
                "deal_value", "owner", "opt_in", "opt_out"])
    for r in rows:
        w.writerow([
            r["name"] or "", mask_phone(r["phone"]), r["country"] or "", r["source"] or "",
            segment_of(r), r["deal_status"],
            "" if (r["deal_value"] is None or user["role"] == "agent") else r["deal_value"],
            r.get("owner_name") or "", (r["opt_in_at"] or "")[:10],
            "1" if r["opt_out"] else "0"])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="contacts.csv"'})


@app.get("/api/users")
def list_users(user=Depends(current_user)):
    if user["role"] == "agent":
        raise HTTPException(403, "forbidden")
    rows = q("""SELECT u.id,u.name,u.email,u.role,u.team,u.active,u.can_reply,
                                 (SELECT COUNT(*) FROM contacts c WHERE c.owner_id=u.id) AS contacts
                          FROM users u ORDER BY u.id""")
    if user["role"] == "manager":
        tids = team_ids_of(user)
        if tids:
            members = {m["user_id"] for m in q("SELECT team_id, user_id FROM team_members") if m["team_id"] in tids}
            rows = [r for r in rows if r["id"] in members or r["id"] == user["id"]]
    return {"items": rows}


# ---------------- 静态文件 ----------------
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


@app.get("/healthz")
def healthz():
    return {"ok": True, "ts": int(time.time())}
