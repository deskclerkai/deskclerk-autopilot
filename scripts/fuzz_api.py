#!/usr/bin/env python3
"""接口鲁棒性检查：异常参数、错误类型、越权访问，确认不出现 500。

用法：python3 scripts/fuzz_api.py http://127.0.0.1:7840
"""
import json
import random
import string
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:7840"
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
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def expect_no_500(method, path, body=None, token=None, raw=None):
    global checks
    checks += 1
    st, txt = call(method, path, body=body, token=token, raw=raw)
    if st >= 500:
        fails.append(f"{method} {path} -> {st} {txt[:120]}")


def login(email="owner@demo.com", pwd="demo1234"):
    st, d = call("POST", "/api/login", {"email": email, "password": pwd})
    return json.loads(d)["token"] if st == 200 else None


TOKEN = login()
if not TOKEN:
    print("登录失败，先确认服务已启动")
    sys.exit(1)

junk = ["", "abc", "../../etc/passwd", "-1", "999999", "0", "1e9", "<script>", "\x00", "中文",
        "%00", "null", "None", "true", "{}", "[]", "a" * 500]
rand = "".join(random.choice(string.printable) for _ in range(30))

GETS = [
    "/api/me", "/api/contacts", "/api/contacts/999999", "/api/tags", "/api/segments",
    "/api/segments/facets", "/api/segments/1/contacts", "/api/templates", "/api/campaigns",
    "/api/campaigns/999999", "/api/conversations", "/api/numbers", "/api/numbers/allowed",
    "/api/teams", "/api/team", "/api/analytics", "/api/settings", "/api/audit",
    "/api/export/contacts.csv", "/api/users", "/api/pool/stats", "/api/pool/facets",
    "/api/ai/config", "/api/ai/logs",
]

for path in GETS:
    expect_no_500("GET", path, token=TOKEN)

# 参数注入
PARAM_PATHS = ["/api/contacts", "/api/segments/1/contacts", "/api/audit", "/api/analytics"]
for v in junk:
    for path in PARAM_PATHS:
        sep = "&" if "?" in path else "?"
        expect_no_500("GET", path + sep + "limit=" + urllib.parse.quote(v), token=TOKEN)
        expect_no_500("GET", path + sep + f"offset={urllib.parse.quote(v)}&kw={urllib.parse.quote(v)}", token=TOKEN)

for v in junk:
    expect_no_500("GET", "/api/contacts?limit=5&sort=" + urllib.parse.quote(v) +
                  "&country=" + urllib.parse.quote(v) + "&tag=" + urllib.parse.quote(v), token=TOKEN)
    expect_no_500("GET", "/api/contacts?view=" + urllib.parse.quote(v), token=TOKEN)
    expect_no_500("GET", "/api/contacts?seg=" + urllib.parse.quote(v), token=TOKEN)

# POST 异常 body
BODIES = [None, {}, {"name": None}, {"name": 123}, {"name": []},
          {"rule": "x"}, {"rule": [1]}, {"rule": {"tags": "abc"}},
          {"rule": {"last_contact": "abc"}}, {"rule": {"last_contact": {"days": "abc"}}},
          {"name": rand, "body": rand}, {"name": "x", "rule": {"tags": [1]}}]
for body in BODIES:
    expect_no_500("POST", "/api/tags", body, TOKEN)
    expect_no_500("POST", "/api/segments", body, TOKEN)
    expect_no_500("POST", "/api/templates", body, TOKEN)
    expect_no_500("POST", "/api/campaigns", body, TOKEN)
    expect_no_500("POST", "/api/teams", body, TOKEN)
    expect_no_500("POST", "/api/users", body, TOKEN)
    expect_no_500("POST", "/api/numbers", body, TOKEN)
    expect_no_500("PATCH", "/api/settings", body, TOKEN)
    expect_no_500("POST", "/api/ai/test", body, TOKEN)
    expect_no_500("PATCH", "/api/ai/config", body, TOKEN)

# 设置里塞错误类型
for bad in ([], "x", 1, None):
    expect_no_500("PATCH", "/api/settings", {"pool": bad}, TOKEN)
    expect_no_500("PATCH", "/api/settings", {"inbox": bad}, TOKEN)
    expect_no_500("PATCH", "/api/settings", {"deal_stages": bad}, TOKEN)

# 资源不存在
for method, path in [("GET", "/api/contacts/999999"), ("GET", "/api/segments/999999/contacts"),
                     ("GET", "/api/conversations/999999/messages"), ("GET", "/api/campaigns/999999"),
                     ("POST", "/api/users/999999/transfer"), ("POST", "/api/users/999999/status"),
                     ("POST", "/api/contacts/999999/claim"), ("POST", "/api/conversations/999999/claim")]:
    expect_no_500(method, path, {"to_user_id": 1, "active": 0, "owner_id": 1}, TOKEN)

# webhook 异常负载
for payload in [None, {}, {"entry": "x"}, {"entry": [1]}, {"entry": [{"changes": "x"}]},
                {"entry": [{"changes": [{"value": "x"}]}]},
                {"entry": [{"changes": [{"value": {"metadata": "x"}}]}]},
                {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "nope"},
                                                    "messages": "x"}}]}]}]:
    expect_no_500("POST", "/api/webhooks/whatsapp", payload)

# 未登录访问
NO_AUTH = ["/api/me", "/api/contacts", "/api/conversations", "/api/numbers", "/api/teams",
           "/api/settings", "/api/analytics", "/api/users", "/api/pool/stats",
           "/api/ai/config", "/api/ai/logs"]
for path in NO_AUTH:
    checks += 1
    st, _ = call("GET", path)
    if st != 401:
        fails.append(f"未登录 {path} 返回 {st}（应为 401）")

print(f"\n{checks} 次请求 · {'全部没有 500' if not fails else str(len(fails)) + ' 个问题'}")
for f in fails:
    print("  ✗ " + f)
sys.exit(1 if fails else 0)
