#!/usr/bin/env python3
"""端到端 API 回归测试（无第三方依赖）。

用法：
    DB_PATH=/tmp/scrm-test.db python3 -m uvicorn main:app --app-dir app --port 7840 &
    python3 scripts/api_tests.py http://127.0.0.1:7840

会修改数据，必须跑在独立数据库上。
"""
import datetime
import hashlib
import hmac
import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:7840"
PASS = 0
FAILS = []


def call(method, path, body=None, token=None, raw=None, headers=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if body is not None and raw is None:
        req.add_header("content-type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            txt = r.read().decode()
            ct = r.headers.get("content-type", "")
            return r.status, (json.loads(txt) if "json" in ct and txt else txt)
    except urllib.error.HTTPError as e:
        txt = e.read().decode()
        try:
            return e.code, json.loads(txt)
        except Exception:
            return e.code, txt


def ok(name, cond, extra=""):
    global PASS
    if cond:
        PASS += 1
    else:
        FAILS.append(name + (f" :: {extra}" if extra else ""))
    return cond


def login(email, pwd="demo1234"):
    st, d = call("POST", "/api/login", {"email": email, "password": pwd})
    return d.get("token") if st == 200 else None


# ---------------- 0. 健康检查 / 登录 ----------------
st, d = call("GET", "/healthz")
ok("healthz 200", st == 200 and d.get("ok") is True, (st, d))

OWNER = login("owner@demo.com")
MANAGER = login("manager@demo.com")
AGENT = login("agent@demo.com")
CHEN = login("chen@demo.com")
FIN = login("finance@demo.com")
ok("owner login", bool(OWNER))
ok("manager login", bool(MANAGER))
ok("agent login", bool(AGENT))
ok("chen login", bool(CHEN))
ok("finance login", bool(FIN))

st, d = call("POST", "/api/login", {"email": "owner@demo.com", "password": "wrong"})
ok("wrong password 401", st == 401, (st, d))
st, d = call("GET", "/api/me", token="garbage")
ok("bad token 401", st == 401, st)

st, d = call("GET", "/api/me", token=OWNER)
ok("me role owner", st == 200 and d["role"] == "owner", d)
st, d = call("GET", "/api/me", token=FIN)
ok("me can_reply false", st == 200 and d.get("can_reply") is False, d)

# ---------------- 1. 角色权限门 ----------------
for path in ("/api/users", "/api/team", "/api/analytics", "/api/numbers", "/api/campaigns", "/api/audit"):
    st, _ = call("GET", path, token=AGENT)
    ok(f"agent blocked {path}", st == 403, st)
st, _ = call("GET", "/api/users", token=MANAGER)
ok("manager can list users", st == 200, st)

# ---------------- 2. 客户可见范围 ----------------
st, owner_contacts = call("GET", "/api/contacts?limit=0", token=OWNER)
ok("owner sees all contacts", st == 200 and owner_contacts["total"] >= 40, owner_contacts.get("total"))
st, mgr_contacts = call("GET", "/api/contacts?limit=0", token=MANAGER)
ok("manager sees fewer than owner", st == 200 and mgr_contacts["total"] < owner_contacts["total"], (st, mgr_contacts.get("total")))
st, agent_contacts = call("GET", "/api/contacts?limit=0", token=AGENT)
ok("agent sees only own", st == 200 and agent_contacts["total"] < mgr_contacts["total"], (st, agent_contacts.get("total")))
st, d = call("GET", "/api/contacts?limit=0", token=FIN)
ok("finance sees team contacts", st == 200 and d["total"] <= owner_contacts["total"], d.get("total"))

# ---------------- 3. 筛选 ----------------
st, d = call("GET", "/api/contacts?country=UAE&limit=0", token=OWNER)
ok("filter country=UAE", st == 200 and d["total"] > 0 and all(c["country"] == "UAE" for c in d["items"]), d.get("total"))
st, d = call("GET", "/api/contacts?source=Website&limit=0", token=OWNER)
ok("filter source=Website", st == 200 and all((c["source"] or "") == "Website" for c in d["items"]), d.get("total"))
st, d = call("GET", "/api/contacts?opt=out&limit=0", token=OWNER)
ok("filter opt=out", st == 200 and all(c["opt_out"] for c in d["items"]), d.get("total"))
st, d = call("GET", "/api/contacts?opt=in&limit=0", token=OWNER)
ok("filter opt=in", st == 200 and not any(c["opt_out"] for c in d["items"]), d.get("total"))
st, tags = call("GET", "/api/tags", token=OWNER)
tid = tags["items"][0]["id"]
st, d = call("GET", f"/api/contacts?tag={tid}&limit=0", token=OWNER)
ok("filter tag", st == 200 and d["total"] > 0, d.get("total"))
st, d = call("GET", "/api/contacts?view=won&limit=0", token=OWNER)
ok("view=won uses success states", st == 200 and d["total"] > 0, d.get("total"))
st, d = call("GET", "/api/contacts?view=untagged&limit=0", token=OWNER)
ok("view=untagged", st == 200, d.get("total"))
st, d1 = call("GET", "/api/contacts?limit=5&offset=0", token=OWNER)
st, d2 = call("GET", "/api/contacts?limit=5&offset=5", token=OWNER)
ok("pagination", st == 200 and len(d1["items"]) == 5 and len(d2["items"]) == 5 and d1["items"][0]["id"] != d2["items"][0]["id"])
st, d = call("GET", "/api/contacts?kw=Ahmed&limit=0", token=OWNER)
ok("kw search", st == 200 and any("Ahmed" in c["name"] for c in d["items"]), d.get("total"))
st, d = call("GET", "/api/contacts?sort=newest&limit=2", token=OWNER)
ok("sort newest", st == 200 and len(d["items"]) == 2)

# ---------------- 4. 指派 ----------------
st, d = call("POST", "/api/contacts/1/assign", {"user_id": 3}, token=AGENT)
ok("agent cannot assign", st == 403, st)
st, d = call("POST", "/api/contacts/1/assign", {"user_id": 4}, token=MANAGER)
ok("manager cannot assign cross-team", st == 403, st)
st, d = call("POST", "/api/contacts/1/assign", {"user_id": 3}, token=MANAGER)
ok("manager assigns within team", st == 200 and d.get("owner_id") == 3, d)
st, d = call("GET", "/api/contacts/1", token=OWNER)
ok("assign updates contact", d.get("owner_name") == "Wang Jie", d.get("owner_name"))
st, d = call("POST", "/api/contacts/1/assign", {"user_id": None}, token=OWNER)
ok("unassign ok", st == 200 and d.get("owner_id") is None, d)
st, d = call("GET", "/api/contacts/1", token=OWNER)
ok("unassign returns to pool", d.get("owner_id") is None, d.get("owner_id"))

# ---------------- 5. 公海规则 ----------------
st, d = call("GET", "/api/pool/stats", token=OWNER)
ok("pool stats keys", st == 200 and {"unowned", "claimable", "blocks"} <= set(d), list(d))
ok("pool blocks sum = unowned", sum(d["blocks"].values()) == d["unowned"], (d["unowned"], d["blocks"]))
st, d2 = call("GET", "/api/pool/stats", token=AGENT)
ok("pool stats per user", st == 200 and d2["claimable"] <= d["claimable"], (d["claimable"], d2["claimable"]))

st, pool = call("GET", "/api/contacts?view=pool&limit=100", token=OWNER)
ok("pool list", st == 200 and pool["total"] == d["unowned"], (pool["total"], d["unowned"]))
blocked = [c for c in pool["items"] if not c["claimable"]]
ok("pool has non-claimable rows", len(blocked) > 0, len(blocked))
if blocked:
    st, r = call("POST", f"/api/contacts/{blocked[0]['id']}/claim", {}, token=AGENT)
    ok("claim blocked contact rejected", st == 400 and str(r.get("detail", "")).startswith("blocked:"), (st, r))

free = [c for c in pool["items"] if c["claimable"]]
if free:
    target = free[0]["id"]
    st, r = call("POST", f"/api/contacts/{target}/claim", {}, token=AGENT)
    ok("agent claims free contact", st == 200 and r.get("ok"), (st, r))
    st, r = call("POST", f"/api/contacts/{target}/claim", {}, token=CHEN)
    ok("second claim rejected", st == 400, (st, r))

st, d = call("GET", "/api/pool/facets", token=OWNER)
ok("pool facets", st == 200 and "tags" in d and "countries" in d)

# ---------------- 6. 标签 ----------------
st, r = call("POST", "/api/tags", {"name": "回归测试标签"}, token=OWNER)
ok("create tag", st == 200 and r.get("id"), (st, r))
new_tag = r.get("id") if st == 200 else None
st, r2 = call("POST", "/api/tags", {"name": "回归测试标签"}, token=OWNER)
ok("duplicate tag rejected", st == 400, (st, r2))
st, r3 = call("PATCH", f"/api/tags/{new_tag}", {"name": "回归测试标签2"}, token=OWNER)
ok("rename tag", st == 200, (st, r3))
st, r4 = call("PATCH", f"/api/tags/{new_tag}", {"name": "回归测试标签2"}, token=AGENT)
ok("agent cannot rename tag", st == 403, (st, r4))
st, r5 = call("POST", "/api/tags/merge", {"from_id": new_tag, "to_id": tid}, token=OWNER)
ok("merge tag", st == 200, (st, r5))
st, r6 = call("DELETE", f"/api/tags/{tid}", token=OWNER)
ok("delete tag", st == 200, (st, r6))

# ---------------- 7. 分层 ----------------
st, segs = call("GET", "/api/segments", token=OWNER)
ok("segments list", st == 200 and len(segs["items"]) >= 6, len(segs.get("items", [])))
custom = [s for s in segs["items"] if not s["is_system"]]
ok("custom segments exist", len(custom) >= 2, len(custom))
st, d = call("GET", f"/api/segments/{custom[0]['id']}/contacts", token=OWNER)
ok("segment contacts", st == 200 and "items" in d, st)
st, r = call("POST", "/api/segments", {"name": "x", "rule": {}}, token=OWNER)
ok("empty segment rejected", st == 400, (st, r))
st, r = call("POST", "/api/segments", {"name": "回归分层", "rule": {"sources": ["Website"]}}, token=OWNER)
ok("create custom segment", st == 200 and r.get("id"), (st, r))
seg_new = r.get("id") if st == 200 else None
st, r = call("POST", "/api/segments", {"name": "agent seg", "rule": {"sources": ["Website"]}}, token=AGENT)
ok("agent cannot create segment", st == 403, (st, r))
st, r = call("PATCH", f"/api/segments/{seg_new}", {"name": "回归分层2"}, token=OWNER)
ok("rename segment", st == 200, (st, r))
sys_seg = [s for s in segs["items"] if s["is_system"]][0]["id"]
st, r = call("DELETE", f"/api/segments/{sys_seg}", token=OWNER)
ok("cannot delete system segment", st == 400, (st, r))

# ---------------- 8. 模板 ----------------
st, tpls = call("GET", "/api/templates", token=OWNER)
ok("templates list", st == 200 and len(tpls["items"]) >= 5, len(tpls.get("items", [])))
approved = [t for t in tpls["items"] if t["status"] == "approved"]
pending = [t for t in tpls["items"] if t["status"] == "pending"]
st, r = call("POST", "/api/templates", {"name": "回归模板", "body": "Hi {{1}}"}, token=AGENT)
ok("agent cannot create template", st == 403, (st, r))
st, r = call("POST", "/api/templates", {"name": "回归模板", "body": "Hi {{1}}"}, token=OWNER)
ok("owner creates template", st == 200 and r.get("status") == "pending", (st, r))

# ---------------- 9. 触达 ----------------
st, r = call("POST", "/api/campaigns", {"segment_id": custom[0]["id"], "template_id": approved[0]["id"]}, token=AGENT)
ok("agent cannot create campaign", st == 403, (st, r))
st, r = call("POST", "/api/campaigns", {"segment_id": custom[0]["id"], "template_id": pending[0]["id"]}, token=OWNER)
ok("pending template rejected", st == 400, (st, r))
st, r = call("POST", "/api/campaigns", {"segment_id": custom[0]["id"], "template_id": approved[0]["id"]}, token=OWNER)
ok("campaign with custom segment works", st == 200 and r.get("sent", 0) > 0, (st, r))
camp_id = r.get("id") if st == 200 else None
st, r2 = call("POST", "/api/campaigns", {"segment_id": seg_new, "template_id": approved[0]["id"]}, token=OWNER)
ok("campaign with new custom segment works", st == 200, (st, r2))
st, d = call("GET", f"/api/campaigns/{camp_id}", token=OWNER)
ok("campaign detail", st == 200 and len(d["recipients"]) == d["campaign"]["sent"], st)
ok("campaign summary sums", d["summary"]["replied"] + d["summary"]["delivered"] + d["summary"]["failed"] == len(d["recipients"]), d["summary"])

# ---------------- 10. 会话 / 号码权限 ----------------
st, owner_convs = call("GET", "/api/conversations", token=OWNER)
st, agent_convs = call("GET", "/api/conversations", token=AGENT)
st, chen_convs = call("GET", "/api/conversations", token=CHEN)
st, fin_convs = call("GET", "/api/conversations", token=FIN)
ok("owner sees all conversations", len(owner_convs["items"]) >= 7, len(owner_convs["items"]))
ok("agent sees only team numbers", 0 < len(agent_convs["items"]) < len(owner_convs["items"]), len(agent_convs["items"]))
ok("chen sees support only", len(chen_convs["items"]) == 1, len(chen_convs["items"]))
ok("finance sees support only", len(fin_convs["items"]) == 1, len(fin_convs["items"]))
ok("every conv has number label", all(c.get("number_label") for c in owner_convs["items"]))

# 号码越权：找一条 agent 看不到的会话
hidden = [c for c in owner_convs["items"] if c["id"] not in {x["id"] for x in agent_convs["items"]}]
if hidden:
    st, _ = call("GET", f"/api/conversations/{hidden[0]['id']}/messages", token=AGENT)
    ok("agent blocked from other number conv", st == 403, st)

# ---------------- 11. 强制负责人回复 ----------------
st, r = call("POST", "/api/conversations/1/messages", {"body": "hi"}, token=AGENT)
ok("non-owner cannot send", st == 403 and r.get("detail") == "not_owner", (st, r))
unassigned = [c for c in agent_convs["items"] if not c["owner_id"]]
if unassigned:
    cid = unassigned[0]["id"]
    st, r = call("POST", f"/api/conversations/{cid}/claim", {}, token=AGENT)
    ok("agent claims unassigned conv", st == 200, (st, r))
    st, r = call("POST", f"/api/conversations/{cid}/messages", {"body": "claimed reply"}, token=AGENT)
    ok("owner can send after claim", st == 200, (st, r))
    st, r = call("POST", f"/api/conversations/{cid}/claim", {}, token=CHEN)
    ok("re-claim rejected", st in (400, 403), (st, r))

st, r = call("POST", "/api/conversations/7/messages", {"body": "readonly"}, token=FIN)
ok("read-only cannot send", st == 403 and r.get("detail") == "read_only", (st, r))
st, r = call("POST", "/api/conversations/7/messages", {"body": "x"}, token=CHEN)
ok("support agent can send own", st == 200, (st, r))
st, r = call("POST", "/api/conversations/7/assign", {"owner_id": 5}, token=MANAGER)
ok("manager cannot assign other team's conv", st == 403, (st, r))

# ---------------- 12. 接待组 / 号码 ----------------
st, baseline_nums = call("GET", "/api/numbers/allowed", token=AGENT)
baseline_ids = sorted(n["id"] for n in baseline_nums["items"])
st, teams = call("GET", "/api/teams", token=OWNER)
ok("teams list", st == 200 and len(teams["items"]) >= 2, len(teams.get("items", [])))
st, r = call("POST", "/api/teams", {"name": "回归组"}, token=AGENT)
ok("agent cannot create team", st == 403, (st, r))
st, r = call("POST", "/api/teams", {"name": "回归组"}, token=OWNER)
ok("owner creates team", st == 200 and r.get("id"), (st, r))
new_team = r.get("id") if st == 200 else None
st, r = call("POST", f"/api/teams/{new_team}/members", {"user_ids": [3]}, token=OWNER)
ok("set team members", st == 200, (st, r))
st, r = call("POST", "/api/numbers/2/teams", {"team_ids": [new_team]}, token=OWNER)
ok("assign number to team", st == 200, (st, r))
st, nums = call("GET", "/api/numbers/allowed", token=AGENT)
ok("agent numbers include support after routing", any(n["id"] == 2 for n in nums["items"]), [n["id"] for n in nums.get("items", [])])
st, r = call("POST", "/api/numbers/2/teams", {"team_ids": [2]}, token=OWNER)
ok("number returned to old team", st == 200, (st, r))
st, r = call("DELETE", f"/api/teams/{new_team}", token=OWNER)
ok("delete team", st == 200, (st, r))
st, nums = call("GET", "/api/numbers/allowed", token=AGENT)
ok("agent numbers restored to baseline", sorted(n["id"] for n in nums["items"]) == baseline_ids, [n["id"] for n in nums.get("items", [])])

# ---------------- 13. 号码管理 ----------------
st, r = call("POST", "/api/numbers", {"label": "T", "phone": "+1 000"}, token=AGENT)
ok("agent cannot add number", st == 403, (st, r))
st, r = call("POST", "/api/numbers", {"label": "T", "phone": "+1 000"}, token=OWNER)
ok("owner adds number", st == 200 and r.get("id"), (st, r))
nid = r.get("id") if st == 200 else None
st, r = call("PATCH", f"/api/numbers/{nid}", {"access_mode": "coexist"}, token=OWNER)
ok("set access mode", st == 200, (st, r))
st, r = call("DELETE", f"/api/numbers/{nid}", token=OWNER)
ok("delete number", st == 200, (st, r))
st, r = call("POST", "/api/numbers/sync", {}, token=OWNER)
ok("sync without creds 400", st == 400 and r.get("detail") == "missing_credentials", (st, r))

# ---------------- 14. 设置 ----------------
st, stg = call("GET", "/api/settings", token=OWNER)
ok("settings read", st == 200 and "pool" in stg, st)
wa = stg.get("channels", {}).get("whatsapp", {})
ok("settings masks whatsapp token", (not wa.get("token_set")) or ("*" in str(wa.get("access_token", ""))), wa)
st, r = call("PATCH", "/api/settings", {"workspace": {"name": "hack"}}, token=AGENT)
ok("agent cannot patch settings", st == 403, (st, r))
st, r = call("PATCH", "/api/settings", {"inbox": {"reply_owner_only": False}}, token=OWNER)
ok("owner can switch reply mode", st == 200, (st, r))
st, r = call("POST", "/api/conversations/1/messages", {"body": "shared mode"}, token=AGENT)
ok("shared mode allows non-owner reply", st == 200, (st, r))
call("PATCH", "/api/settings", {"inbox": {"reply_owner_only": True}}, token=OWNER)
st, r = call("POST", "/api/conversations/1/messages", {"body": "strict again"}, token=AGENT)
ok("strict mode re-enabled", st == 403, (st, r))

# ---------------- 15. Webhook ----------------
st, d = call("GET", "/api/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=bad&hub.challenge=x")
ok("webhook bad token 403", st == 403, st)
call("PATCH", "/api/settings/channels", {"whatsapp": {"status": "connected", "waba_id": "W1", "access_token": "TOKEN-1234567890", "verify_token": "vt"}}, token=OWNER)
st, d = call("GET", "/api/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=vt&hub.challenge=abc")
ok("webhook verify ok", st == 200 and d == "abc", (st, d))
call("PATCH", "/api/numbers/1", {"phone_number_id": "PN1"}, token=OWNER)
payload = {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "PN1"},
    "messages": [{"from": "971501112233", "id": "wamid.t1", "timestamp": "1794220000", "text": {"body": "Hello"}}],
    "smb_message_echoes": [{"to": "971501112233", "id": "wamid.t2", "timestamp": "1794220100", "text": {"body": "From app"}}]}}]}]}
st, d = call("POST", "/api/webhooks/whatsapp", payload)
ok("webhook stores inbound+echo", st == 200 and d.get("saved") == 2, (st, d))
st, d = call("POST", "/api/webhooks/whatsapp", payload)
ok("webhook dedupe", st == 200 and d.get("saved") == 0, (st, d))
# 签名校验
secret = "s3cret"
call("PATCH", "/api/settings/channels", {"whatsapp": {"app_secret": secret}}, token=OWNER)
raw = json.dumps(payload).encode()
sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
st, d = call("POST", "/api/webhooks/whatsapp", raw=raw, headers={"X-Hub-Signature-256": sig})
ok("webhook good signature", st == 200, (st, d))
st, d = call("POST", "/api/webhooks/whatsapp", raw=raw, headers={"X-Hub-Signature-256": "sha256=bad"})
ok("webhook bad signature 403", st == 403, (st, d))
call("PATCH", "/api/settings/channels", {"whatsapp": {"app_secret": ""}}, token=OWNER)

# ---------------- 16. 导出 / 审计 / 看板 ----------------
st, csv_owner = call("GET", "/api/export/contacts.csv", token=OWNER)
ok("owner csv", st == 200 and isinstance(csv_owner, str) and csv_owner.count("\n") > 10, st)
st, csv_agent = call("GET", "/api/export/contacts.csv", token=AGENT)
ok("agent csv scoped", st == 200 and csv_agent.count("\n") < csv_owner.count("\n"), (st,))
st, _ = call("GET", "/api/audit", token=OWNER)
ok("owner audit", st == 200, st)
st, _ = call("GET", "/api/audit", token=AGENT)
ok("agent audit 403", st == 403, st)
st, an = call("GET", "/api/analytics", token=OWNER)
ok("analytics owner", st == 200 and {"sent", "funnel", "series"} <= set(an), st)
ok("analytics facets", {"owners", "countries", "sources", "tags", "segments", "teams", "numbers", "stages"} <= set(an.get("facets", {})), an.get("facets"))
ok("analytics boards", {"by_country", "by_owner", "by_team", "by_tag", "by_stage", "by_number", "campaigns", "ai"} <= set(an), sorted(an))
ok("analytics segment names", all(s.get("name") for s in an.get("segments", [])), an.get("segments"))
country = next((c for c in an["facets"]["countries"] if c), None)
st, an2 = call("GET", f"/api/analytics?range=30d&country={country}", token=OWNER)
ok("analytics country filter", st == 200 and 0 < an2["contacts"] <= an["contacts"], (st, an2.get("contacts")))
segid = an["facets"]["segments"][-1]["id"]
st, an3 = call("GET", f"/api/analytics?range=30d&segment={segid}", token=OWNER)
ok("analytics segment filter", st == 200 and an3["contacts"] <= an["contacts"] and len(an3["segments"]) == len(an["segments"]), (st, an3.get("contacts")))
_end = datetime.date.today()
_start = _end - datetime.timedelta(days=11)
st, an4 = call("GET", f"/api/analytics?start={_start}&end={_end}", token=OWNER)
ok("analytics custom dates", st == 200 and len(an4["series"]) == 12, (st, len(an4.get("series", []))))
st, an5 = call("GET", "/api/analytics?range=30d", token=MANAGER)
ok("analytics manager scoped", st == 200 and an5["contacts"] <= an["contacts"], (st, an5.get("contacts") if st == 200 else an5))
st, _ = call("GET", "/api/analytics?range=30d&number=999", token=OWNER)
ok("analytics bad number empty", st == 200, st)
st, _ = call("GET", "/api/analytics", token=AGENT)
ok("analytics agent 403", st == 403, st)

# ---------------- 17. 成员管理 ----------------
st, r = call("POST", "/api/users", {"name": "回归员工", "email": "reg@demo.com", "password": "12345678", "role": "agent"}, token=OWNER)
ok("create user", st == 200 and r.get("id"), (st, r))
uid = r.get("id") if st == 200 else None
st, r = call("POST", "/api/users", {"name": "dup", "email": "reg@demo.com", "password": "12345678"}, token=OWNER)
ok("duplicate email rejected", st == 409, (st, r))
st, r = call("POST", "/api/users", {"name": "short", "email": "s@demo.com", "password": "123"}, token=OWNER)
ok("short password rejected", st == 400, (st, r))
st, r = call("POST", f"/api/users/{uid}/reply", {"can_reply": False}, token=OWNER)
ok("set read-only", st == 200, (st, r))
st, me = call("GET", "/api/me", token=login("reg@demo.com", "12345678"))
ok("read-only reflected", me.get("can_reply") is False, me)
st, r = call("DELETE", f"/api/users/{uid}", token=OWNER)
ok("delete user", st == 200, (st, r))
st, r = call("DELETE", "/api/users/1", token=OWNER)
ok("cannot delete self", st == 400, (st, r))


# ---------------- 18. 补充：登录负载 / 主管客户范围 / 配额 / 领取范围 / 回收 / 触达排除退订 ----------------
st, r = call("POST", "/api/login", {"email": "finance@demo.com", "password": "demo1234"})
ok("login payload has can_reply", st == 200 and r.get("user", {}).get("can_reply") is False, r)

st, all_c = call("GET", "/api/contacts?limit=0", token=OWNER)
other = next((c for c in all_c["items"] if c["owner_id"] == 4), None)
if other:
    st, _ = call("GET", f"/api/contacts/{other['id']}", token=MANAGER)
    ok("manager cannot open other team contact", st == 403, st)
    st, _ = call("PATCH", f"/api/contacts/{other['id']}", {"owner_id": 3}, token=MANAGER)
    ok("manager cannot patch other team contact", st == 403, st)

# 配额
st, q = call("POST", "/api/users", {"name": "Quota Bot", "email": "quota@demo.com",
                                    "password": "12345678", "role": "agent"}, token=OWNER)
quid = q.get("id") if st == 200 else None
QTOK = login("quota@demo.com", "12345678")
ok("quota user login", bool(QTOK))
st, stg = call("GET", "/api/settings", token=OWNER)
pool_cfg = dict(stg.get("pool") or {})
run_cfg = {**pool_cfg, "daily_claim_limit": 1, "recycle_days": 90, "scopes": {}}
call("PATCH", "/api/settings", {"pool": run_cfg}, token=OWNER)
st, pool = call("GET", "/api/contacts?view=pool&limit=100", token=OWNER)
free = [c for c in pool["items"] if c["claimable"]]
if len(free) >= 2:
    st, r1 = call("POST", f"/api/contacts/{free[0]['id']}/claim", {}, token=QTOK)
    ok("quota first claim", st == 200, (st, r1))
    st, r2 = call("POST", f"/api/contacts/{free[1]['id']}/claim", {}, token=QTOK)
    ok("quota second claim rejected", st == 400 and "daily_limit_reached" in str(r2.get("detail")), (st, r2))

# 领取范围
st, tg = call("POST", "/api/tags", {"name": "空标签-回归"}, token=OWNER)
empty_tag = tg.get("id") if st == 200 else None
call("PATCH", "/api/settings", {"pool": {**run_cfg, "scopes": {str(quid): [empty_tag]}}}, token=OWNER)
st, pool2 = call("GET", "/api/contacts?view=pool&limit=100", token=QTOK)
free2 = [c for c in pool2["items"] if c.get("claimable")]
if free2:
    st, r3 = call("POST", f"/api/contacts/{free2[0]['id']}/claim", {}, token=QTOK)
    ok("claim scope blocks", st == 400 and "out_of_scope" in str(r3.get("detail")), (st, r3))
call("PATCH", "/api/settings", {"pool": {**pool_cfg, "scopes": {}}}, token=OWNER)

# 自动回收不碰成功态
st, before = call("GET", "/api/contacts?limit=0", token=OWNER)
succ_before = len([c for c in before["items"] if c["owner_id"] and c["deal_status"] in
                   ("Won", "Signed", "Active", "Enrolled", "Renewed")])
call("PATCH", "/api/settings", {"pool": {**pool_cfg, "recycle_days": 0, "scopes": {}}}, token=OWNER)
st, rec = call("POST", "/api/pool/recycle", {}, token=OWNER)
ok("recycle runs", st == 200, (st, rec))
st, after = call("GET", "/api/contacts?limit=0", token=OWNER)
succ_after = len([c for c in after["items"] if c["owner_id"] and c["deal_status"] in
                  ("Won", "Signed", "Active", "Enrolled", "Renewed")])
ok("recycle keeps won customers", succ_after == succ_before, (succ_before, succ_after))
call("PATCH", "/api/settings", {"pool": {**pool_cfg, "recycle_days": 90, "scopes": {}}}, token=OWNER)

# 触达只发已授权
st, segs2 = call("GET", "/api/segments", token=OWNER)
active_seg = next((x for x in segs2["items"] if x.get("rule", {}).get("type") == "active"), None)
if active_seg:
    st, r = call("POST", "/api/campaigns", {"segment_id": active_seg["id"], "template_id": approved[0]["id"]}, token=OWNER)
    ok("campaign on active segment", st == 200, (st, r))
    if st == 200:
        st, det = call("GET", f"/api/campaigns/{r['id']}", token=OWNER)
        sample = det["recipients"][:5]
        bad = []
        for x in sample:
            st2, cc = call("GET", f"/api/contacts/{x['contact_id']}", token=OWNER)
            if cc.get("opt_out"):
                bad.append(x["contact_id"])
        ok("campaign excludes opted-out", not bad, bad)


# ---------------- 19. 并发抢同一个客户 ----------------
import threading
st, pool3 = call("GET", "/api/contacts?view=pool&limit=100", token=OWNER)
free3 = [c for c in pool3["items"] if c["claimable"]]
if free3 and AGENT and CHEN:
    target = free3[0]["id"]
    results = []
    lock = threading.Lock()

    def grab(tok):
        s2, r2 = call("POST", f"/api/contacts/{target}/claim", {}, token=tok)
        with lock:
            results.append((s2, r2))

    ths = [threading.Thread(target=grab, args=(AGENT if i % 2 == 0 else CHEN,)) for i in range(12)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    wins = [r for r in results if r[0] == 200]
    errs = [r for r in results if r[0] >= 500]
    ok("concurrent claim only one winner", len(wins) == 1, (len(wins), results[:3]))
    ok("concurrent claim no 500", not errs, errs[:2])


# ---------------- 20. 各页面数字与明细一致 ----------------
st, segs3 = call("GET", "/api/segments", token=OWNER)
mismatch = []
for sg in segs3["items"]:
    st2, dd = call("GET", f"/api/contacts?seg={sg['id']}&limit=0", token=OWNER)
    if st2 != 200 or dd["total"] != sg["matched"]:
        mismatch.append((sg["name"], sg["matched"], dd.get("total")))
ok("segment counts match contact filter", not mismatch, mismatch)

st, tags3 = call("GET", "/api/tags", token=OWNER)
tag_bad = []
for tg in tags3["items"]:
    st2, dd = call("GET", f"/api/contacts?tag={tg['id']}&limit=0", token=OWNER)
    if st2 != 200 or dd["total"] != tg["n"]:
        tag_bad.append((tg["name"], tg["n"], dd.get("total")))
ok("tag counts match contact filter", not tag_bad, tag_bad)

st, team3 = call("GET", "/api/team", token=OWNER)
team_bad = []
for m in team3["items"]:
    st2, dd = call("GET", f"/api/contacts?owner={m['id']}&limit=0", token=OWNER)
    if st2 != 200 or dd["total"] != m["contacts"]:
        team_bad.append((m["name"], m["contacts"], dd.get("total")))
ok("team contact counts match", not team_bad, team_bad)

# 移出接待组后立刻看不到会话
st, teams3 = call("GET", "/api/teams", token=OWNER)
me_team = next((t for t in teams3["items"] if 3 in t["members"]), None)
if me_team:
    keep = [u for u in me_team["members"] if u != 3]
    call("POST", f"/api/teams/{me_team['id']}/members", {"user_ids": keep}, token=OWNER)
    st, d = call("GET", "/api/conversations", token=AGENT)
    ok("removing member hides conversations", st == 200 and len(d["items"]) == 0, len(d["items"]))
    call("POST", f"/api/teams/{me_team['id']}/members", {"user_ids": me_team["members"]}, token=OWNER)
    st, d = call("GET", "/api/conversations", token=AGENT)
    ok("restoring member restores conversations", st == 200 and len(d["items"]) > 0, len(d["items"]))

# 停用后立即被踢
kick_email = f"kick{int(__import__('time').time())}@demo.com"
st, u2 = call("POST", "/api/users", {"name": "Kick Me", "email": kick_email,
                                     "password": "12345678", "role": "agent"}, token=OWNER)
kick_tok = login(kick_email, "12345678") if st == 200 else None
if kick_tok:
    call("POST", f"/api/users/{u2['id']}/status", {"active": False}, token=OWNER)
    st, _ = call("GET", "/api/me", token=kick_tok)
    ok("deactivated user kicked immediately", st == 401, st)


# ---------------- 21. 公海客户详情 / 认领带走会话 ----------------
st, pool4 = call("GET", "/api/contacts?view=pool&limit=100", token=OWNER)
if pool4["items"]:
    pid = pool4["items"][0]["id"]
    st, _ = call("GET", f"/api/contacts/{pid}", token=MANAGER)
    ok("manager can open pool contact", st == 200, st)
    st, _ = call("GET", f"/api/contacts/{pid}", token=AGENT)
    ok("agent can open pool contact", st == 200, st)
    st, _ = call("PATCH", f"/api/contacts/{pid}", {"note": "x"}, token=AGENT)
    ok("agent cannot edit pool contact before claiming", st == 403, st)

call("PATCH", "/api/numbers/1", {"phone_number_id": "PN21"}, token=OWNER)
unique_phone = "971507778888"
payload4 = {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "PN21"},
    "messages": [{"from": unique_phone, "id": "wamid.x21", "timestamp": "1794220300",
                  "text": {"body": "brand new"}}]}}]}]}
st, _ = call("POST", "/api/webhooks/whatsapp", payload4)
st, found = call("GET", "/api/contacts?kw=778888&limit=10", token=OWNER)
ok("new inbound contact visible in pool", st == 200 and found["total"] == 1, found)
if found.get("total") == 1:
    nc = found["items"][0]["id"]
    st, cl2 = call("GET", "/api/conversations", token=AGENT)
    conv_row = next((c for c in cl2["items"] if c["contact_id"] == nc), None)
    ok("inbound conversation exists", conv_row is not None, nc)
    st, r = call("POST", f"/api/contacts/{nc}/claim", {}, token=AGENT)
    ok("agent claims new contact", st == 200, (st, r))
    st, cl3 = call("GET", "/api/conversations", token=AGENT)
    row3 = next((c for c in cl3["items"] if c["contact_id"] == nc), None)
    ok("claim brings conversations", row3 is not None and row3["owner_id"] == 3, row3 and row3.get("owner_id"))
    if row3:
        st, _ = call("POST", f"/api/conversations/{row3['id']}/messages", {"body": "hello"}, token=AGENT)
        ok("agent can reply after claiming", st == 200, st)


# ---------------- 22. 客户详情消息按号码隔离 ----------------
call("PATCH", "/api/numbers/1", {"phone_number_id": "PN31"}, token=OWNER)
call("PATCH", "/api/numbers/2", {"phone_number_id": "PN32"}, token=OWNER)
shared_phone = "971506665555"
def wh(pn, wid, text):
    return {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": pn},
            "messages": [{"from": shared_phone, "id": wid, "timestamp": "1794220400",
                          "text": {"body": text}}]}}]}]}
call("POST", "/api/webhooks/whatsapp", wh("PN31", "wamid.m1", "ME ONLY"))
call("POST", "/api/webhooks/whatsapp", wh("PN32", "wamid.m2", "SUPPORT SECRET"))
st, found2 = call("GET", "/api/contacts?kw=665555&limit=5", token=OWNER)
if found2.get("total") == 1:
    sid = found2["items"][0]["id"]
    st, det = call("GET", f"/api/contacts/{sid}", token=AGENT)
    bodies = [m["body"] for m in det.get("messages", [])]
    ok("contact detail only shows allowed number messages",
       st == 200 and "ME ONLY" in bodies and "SUPPORT SECRET" not in bodies, bodies)


# ---------------- 23. 会话可见范围（公司层面开关） ----------------
st, stg2 = call("GET", "/api/settings", token=OWNER)
inbox_cfg = stg2.get("inbox") or {}
st, all_agent = call("GET", "/api/conversations", token=AGENT)
team_count = len(all_agent["items"])
ok("default visibility is team", team_count > 0, team_count)
call("PATCH", "/api/settings", {"inbox": {**inbox_cfg, "visibility": "own"}}, token=OWNER)
st, own_agent = call("GET", "/api/conversations", token=AGENT)
own_ids = {c["id"] for c in own_agent["items"]}
ok("own mode filters to own/unassigned",
   all(c["owner_id"] in (None, 3) for c in own_agent["items"]) and len(own_agent["items"]) <= team_count,
   [(c["id"], c["owner_id"]) for c in own_agent["items"]])
others = [c for c in all_agent["items"] if c["owner_id"] not in (None, 3)]
if others:
    st, _ = call("GET", f"/api/conversations/{others[0]['id']}/messages", token=AGENT)
    ok("own mode blocks other people's chats", st == 403, st)
st, mgr_after = call("GET", "/api/conversations", token=MANAGER)
ok("manager still sees team chats in own mode", len(mgr_after["items"]) >= len(own_agent["items"]), len(mgr_after["items"]))
st, _ = call("PATCH", "/api/settings", {"inbox": {**inbox_cfg, "visibility": "bad"}}, token=OWNER)
ok("bad visibility rejected", st == 400, st)
call("PATCH", "/api/settings", {"inbox": {**inbox_cfg, "visibility": "team"}}, token=OWNER)


# ---------------- 24. AI 配置与测试 ----------------
st, cfg0 = call("GET", "/api/ai/config", token=OWNER)
ok("ai config owner", st == 200 and cfg0.get("mode") in ("off", "draft", "auto"), st)
ok("ai key masked", (not cfg0.get("api_key_set")) or ("*" in (cfg0.get("api_key") or "")), cfg0.get("api_key"))
st, _ = call("GET", "/api/ai/config", token=AGENT)
ok("ai config agent 403", st == 403, st)

st, r = call("PATCH", "/api/ai/config", {"mode": "auto", "threshold": 0.7}, token=AGENT)
ok("ai patch agent 403", st == 403, (st, r))
st, r = call("PATCH", "/api/ai/config", {"mode": "bad"}, token=OWNER)
ok("ai bad mode rejected", st == 400, (st, r))
st, r = call("PATCH", "/api/ai/config", {"threshold": 1.5}, token=OWNER)
ok("ai bad threshold rejected", st == 400, (st, r))
st, r = call("PATCH", "/api/ai/config", {"mode": "auto", "threshold": 0.7}, token=OWNER)
ok("ai patch owner", st == 200 and r.get("mode") == "auto", (st, r))

st, t1 = call("POST", "/api/ai/test", {"question": "这个型号的备件多久能到货？"}, token=OWNER)
ok("ai test known topic", st == 200 and t1.get("decision") == "auto" and t1.get("sources"), (st, t1))
st, t2 = call("POST", "/api/ai/test", {"question": "能不能便宜点？"}, token=OWNER)
ok("ai test blocked topic", st == 200 and t2.get("decision") == "blocked", (st, t2))
st, t3 = call("POST", "/api/ai/test", {"question": "你们在土耳其有仓库吗？"}, token=OWNER)
ok("ai test unknown -> handoff", st == 200 and t3.get("decision") == "handoff" and not t3.get("sources"), (st, t3))
st, t4 = call("POST", "/api/ai/test", {"question": "我要人工"}, token=OWNER)
ok("ai test handoff keyword", st == 200 and t4.get("decision") == "handoff", (st, t4))

st, lg = call("GET", "/api/ai/logs?limit=20", token=OWNER)
ok("ai logs", st == 200 and len(lg.get("items", [])) >= 4, len(lg.get("items", [])))
st, _ = call("GET", "/api/ai/logs", token=AGENT)
ok("ai logs agent 403", st == 403, st)

st, _ = call("POST", "/api/ai/kb/sync", {}, token=AGENT)
ok("ai kb sync agent 403", st == 403, st)
st, kb = call("POST", "/api/ai/kb/sync", {}, token=OWNER)
ok("ai kb sync owner", st == 200 and kb.get("pending") == 0, (st, kb))
call("PATCH", "/api/ai/config", {"mode": "draft"}, token=OWNER)


# ---------------- 25. AI 接待方式与真实来信流水线 ----------------
call("PATCH", "/api/ai/config", {"mode": "draft", "base_url": "", "site_id": ""}, token=OWNER)
call("PATCH", "/api/numbers/1", {"phone_number_id": "PN-AI"}, token=OWNER)

def inbound(phone, wid, text):
    return {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "PN-AI"},
            "messages": [{"from": phone, "id": wid, "timestamp": "1794220500",
                          "text": {"body": text}}]}}]}]}

# 草稿模式：客户来信应生成 AI 草稿
call("POST", "/api/webhooks/whatsapp", inbound("971501230001", "wamid.ai1", "这个型号的备件多久能到货？"))
st, found = call("GET", "/api/contacts?kw=230001&limit=5", token=OWNER)
draft_conv = None
if found.get("total") == 1:
    nc = found["items"][0]["id"]
    st, cl = call("GET", "/api/conversations", token=OWNER)
    row = next((c for c in cl["items"] if c["contact_id"] == nc), None)
    if row:
        draft_conv = row["id"]
        ok("conversation has ai_enabled", row.get("ai_enabled") == 1, row.get("ai_enabled"))
        st, dd = call("GET", f"/api/conversations/{row['id']}/ai-draft", token=OWNER)
        ok("draft mode creates AI draft", st == 200 and dd.get("draft") and dd["draft"].get("content"), (st, dd))
        # 认领会话后可采用草稿
        call("POST", f"/api/conversations/{row['id']}/claim", {}, token=OWNER)
        if dd.get("draft"):
            st, _ = call("POST", f"/api/ai-drafts/{dd['draft']['id']}/accept", {}, token=OWNER)
            ok("accept AI draft sends message", st == 200, st)
            st, msgs = call("GET", f"/api/conversations/{row['id']}/messages", token=OWNER)
            ok("accepted draft stored via ai", any(m.get("via") == "ai" for m in msgs["items"]), [m.get("via") for m in msgs["items"]])

# 全自动模式：客户来信直接产生 AI 去信
call("PATCH", "/api/ai/config", {"mode": "auto"}, token=OWNER)
call("POST", "/api/webhooks/whatsapp", inbound("971501230002", "wamid.ai2", "这个型号的备件多久能到货？"))
st, found2 = call("GET", "/api/contacts?kw=230002&limit=5", token=OWNER)
if found2.get("total") == 1:
    nc2 = found2["items"][0]["id"]
    st, cl2 = call("GET", "/api/conversations", token=OWNER)
    row2 = next((c for c in cl2["items"] if c["contact_id"] == nc2), None)
    if row2:
        st, msgs2 = call("GET", f"/api/conversations/{row2['id']}/messages", token=OWNER)
        ok("auto mode sends AI reply", any(m.get("direction") == "out" and m.get("via") == "ai" for m in msgs2["items"]),
           [(m.get("direction"), m.get("via")) for m in msgs2["items"]])

# 会话级关闭 AI：不再自动回复
if draft_conv:
    st, r = call("POST", f"/api/conversations/{draft_conv}/ai", {"enabled": False}, token=OWNER)
    ok("conversation AI switch", st == 200 and r.get("ai_enabled") is False, (st, r))
    call("POST", "/api/webhooks/whatsapp", inbound("971501230001", "wamid.ai3", "这个型号的备件多久能到货？"))
    st, dd2 = call("GET", f"/api/conversations/{draft_conv}/ai-draft", token=OWNER)
    ok("AI off means no new draft", st == 200 and not dd2.get("draft"), dd2)
call("PATCH", "/api/ai/config", {"mode": "draft"}, token=OWNER)


# ---------------- 26. AI 客户洞察设置 ----------------
st, ins = call("GET", "/api/ai/insights", token=AGENT)
ok("ai insights readable by agent", st == 200 and "auto_tags" in ins, (st, ins))
st, r = call("PATCH", "/api/ai/config", {"insights": {"summary": False, "risk": False}}, token=OWNER)
ok("ai insights saved", st == 200 and r.get("insights", {}).get("summary") is False, r.get("insights"))
st, ins2 = call("GET", "/api/ai/insights", token=OWNER)
ok("ai insights persisted", ins2.get("summary") is False and ins2.get("risk") is False, ins2)
call("PATCH", "/api/ai/config", {"insights": {"summary": True, "risk": True}}, token=OWNER)


# ---------------- 27. 权限矩阵核对 ----------------
# 销售：设置只返回 deal_stages + inbox，不泄露 AI/渠道
st, stg_agent = call("GET", "/api/settings", token=AGENT)
ok("agent settings only inbox+stages", st == 200 and set(stg_agent.keys()) <= {"deal_stages", "inbox"}, list(stg_agent.keys()))
st, _ = call("GET", "/api/teams", token=AGENT)
ok("agent cannot list teams", st == 403, st)
st, _ = call("GET", "/api/campaigns", token=AGENT)
ok("agent cannot list campaigns", st == 403, st)
st, ins_a = call("GET", "/api/ai/insights", token=AGENT)
ok("agent can read AI insights", st == 200 and "auto_tags" in ins_a, (st, ins_a))

# 主管：号码只看到本组授权，审计只看到本组
st, mgr_nums = call("GET", "/api/numbers", token=MANAGER)
ok("manager sees only own numbers", st == 200 and {n["id"] for n in mgr_nums["items"]} <= {1, 3}, [n["id"] for n in mgr_nums.get("items", [])])
st, mgr_audit = call("GET", "/api/audit?limit=200", token=MANAGER)
ok("manager audit scoped", st == 200, st)
st, mgr_settings = call("GET", "/api/settings", token=MANAGER)
ok("manager settings full", st == 200 and "ai" in mgr_settings and "channels" in mgr_settings, list(mgr_settings.keys()))

# 别组客户：主管不能查看/释放/标记退订/修改
st, other_team = call("GET", "/api/contacts?owner=4&limit=1", token=OWNER)
if other_team.get("items"):
    oc = other_team["items"][0]["id"]
    st, _ = call("GET", f"/api/contacts/{oc}", token=MANAGER)
    ok("manager cannot open other team contact", st == 403, st)
    st, _ = call("POST", f"/api/contacts/{oc}/release", {}, token=MANAGER)
    ok("manager cannot release other team contact", st == 403, st)
    st, _ = call("POST", f"/api/contacts/{oc}/optout", {"opt_out": True}, token=MANAGER)
    ok("manager cannot opt-out other team contact", st == 403, st)

# 只读账号：所有写操作都应被拒
st, ro_team = call("GET", "/api/contacts?owner=1&limit=1", token=OWNER)
if not ro_team.get("items"):
    st, ro_team = call("GET", "/api/contacts?view=pool&limit=1", token=OWNER)
ro_cid = ro_team["items"][0]["id"] if ro_team.get("items") else 1
readonly_calls = [
    ("POST", "/api/contacts/1/claim", {}),
    ("POST", "/api/contacts/1/assign", {"user_id": 4}),
    ("POST", "/api/contacts/1/release", {}),
    ("POST", "/api/contacts/1/optout", {"opt_out": True}),
    ("PATCH", f"/api/contacts/{ro_cid}", {"note": "x"}),
    ("POST", "/api/tags", {"name": "只读测试"}),
    ("POST", "/api/segments", {"name": "只读测试", "rule": {"sources": ["Website"]}}),
    ("POST", "/api/conversations/1/ai", {"enabled": False}),
    ("POST", "/api/users/3/transfer", {"to_user_id": 1}),
]
for method, path, body in readonly_calls:
    st, r = call(method, path, body, token=FIN)
    ok(f"read-only blocked {method} {path}", st == 403 and str(r.get("detail")) == "read_only", (st, r))
st, fin_nums = call("GET", "/api/numbers", token=FIN)
ok("read-only numbers scoped", st == 200 and {n["id"] for n in fin_nums["items"]} == {2}, [n["id"] for n in fin_nums.get("items", [])])

# ---------------- 结果 ----------------
total = PASS + len(FAILS)
print(f"\n{total} checks · {PASS} passed · {len(FAILS)} failed")
for f in FAILS:
    print("  ✗ " + f)
if FAILS:
    sys.exit(1)
print("✅ all API tests passed")
