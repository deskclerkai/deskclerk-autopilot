"""数据层：SQLite，纯标准库，无 ORM。"""
import json
import os
import sqlite3
from datetime import datetime, timedelta

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "app.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  pwd TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'agent',   -- owner | manager | agent
  team TEXT NOT NULL DEFAULT 'sales',
  active INTEGER NOT NULL DEFAULT 1,
  can_reply INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS teams(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS team_members(
  team_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  PRIMARY KEY(team_id, user_id)
);
CREATE TABLE IF NOT EXISTS number_teams(
  number_id INTEGER NOT NULL,
  team_id INTEGER NOT NULL,
  PRIMARY KEY(number_id, team_id)
);
CREATE TABLE IF NOT EXISTS tags(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS contacts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  phone TEXT NOT NULL,
  country TEXT,
  source TEXT,
  source_detail TEXT,
  opt_in_at TEXT,
  opt_out INTEGER NOT NULL DEFAULT 0,
  owner_id INTEGER,
  deal_status TEXT NOT NULL DEFAULT 'Lead',
  deal_value REAL,
  note TEXT,
  last_contact_at TEXT,
  claimed_at TEXT,
  released_at TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS contact_tags(
  contact_id INTEGER NOT NULL,
  tag_id INTEGER NOT NULL,
  PRIMARY KEY(contact_id, tag_id)
);
CREATE TABLE IF NOT EXISTS segments(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  rule TEXT NOT NULL,          -- json
  is_system INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS templates(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  category TEXT NOT NULL,      -- Marketing | Utility
  language TEXT NOT NULL,
  status TEXT NOT NULL,        -- pending | approved | rejected
  body TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaigns(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  segment_id INTEGER NOT NULL,
  template_id INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',   -- draft | sending | done | failed
  sent INTEGER NOT NULL DEFAULT 0,
  delivered INTEGER NOT NULL DEFAULT 0,
  replied INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaign_recipients(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  campaign_id INTEGER NOT NULL,
  contact_id INTEGER NOT NULL,
  status TEXT NOT NULL,        -- queued | delivered | replied | failed
  replied_at TEXT
);
CREATE TABLE IF NOT EXISTS conversations(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  contact_id INTEGER NOT NULL,
  channel TEXT NOT NULL,
  number_id INTEGER,
  owner_id INTEGER,
  ai_enabled INTEGER NOT NULL DEFAULT 1,
  unread INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'open',
  last_at TEXT
);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id INTEGER NOT NULL,
  direction TEXT NOT NULL,     -- in | out
  body TEXT NOT NULL,
  sender_id INTEGER,
  wa_message_id TEXT,
  via TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS numbers(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  label TEXT NOT NULL,
  phone TEXT NOT NULL,
  purpose TEXT,
  waba_id TEXT,
  phone_number_id TEXT,
  quality TEXT NOT NULL DEFAULT 'unknown',   -- high | medium | low | unknown
  daily_limit INTEGER NOT NULL DEFAULT 1000,
  sent_today INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'connected',  -- connected | cooling | disconnected
  access_mode TEXT NOT NULL DEFAULT 'sandbox',  -- sandbox | cloud | coexist
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings(
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_drafts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id INTEGER NOT NULL,
  content TEXT NOT NULL,
  sources TEXT,
  top_score REAL,
  decision TEXT,
  escalation TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_logs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  contact_id INTEGER,
  conversation_id INTEGER,
  locale TEXT,
  question TEXT NOT NULL,
  answer TEXT,
  sources TEXT,
  top_score REAL,
  decision TEXT NOT NULL,
  escalation TEXT,
  latency_ms INTEGER,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  action TEXT NOT NULL,
  target TEXT,
  created_at TEXT NOT NULL
);
"""


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db():
    conn = connect()
    conn.executescript(SCHEMA)
    ucols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    if "can_reply" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN can_reply INTEGER NOT NULL DEFAULT 1")
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(contacts)")}
    if "released_at" not in cols:
        conn.execute("ALTER TABLE contacts ADD COLUMN released_at TEXT")
    cv_cols = {r["name"] for r in conn.execute("PRAGMA table_info(conversations)")}
    if "number_id" not in cv_cols:
        conn.execute("ALTER TABLE conversations ADD COLUMN number_id INTEGER")
    if "ai_enabled" not in cv_cols:
        conn.execute("ALTER TABLE conversations ADD COLUMN ai_enabled INTEGER NOT NULL DEFAULT 1")
    ncols = {r["name"] for r in conn.execute("PRAGMA table_info(numbers)")}
    if "access_mode" not in ncols:
        conn.execute("ALTER TABLE numbers ADD COLUMN access_mode TEXT NOT NULL DEFAULT 'sandbox'")
    mcols = {r["name"] for r in conn.execute("PRAGMA table_info(messages)")}
    if "wa_message_id" not in mcols:
        conn.execute("ALTER TABLE messages ADD COLUMN wa_message_id TEXT")
    if "via" not in mcols:
        conn.execute("ALTER TABLE messages ADD COLUMN via TEXT")
    empty = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] == 0
    conn.commit()
    conn.close()
    if empty and os.environ.get("DEMO_SEED", "1") != "0":
        seed()


def q(sql, args=()):
    conn = connect()
    rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
    conn.close()
    return rows


def q1(sql, args=()):
    rows = q(sql, args)
    return rows[0] if rows else None


def run(sql, args=()):
    conn = connect()
    cur = conn.execute(sql, args)
    conn.commit()
    last = cur.lastrowid
    conn.close()
    return last


def run_count(sql, params=()):
    """执行并返回受影响行数（用于并发安全的条件更新）。"""
    conn = connect()
    try:
        cur = conn.execute(sql, params)
        n = cur.rowcount
        conn.commit()
        return n
    finally:
        conn.close()


def setting_get(key, default=None):
    row = q1("SELECT value FROM settings WHERE key=?", (key,))
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except Exception:
        return row["value"]


def setting_set(key, value):
    run("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value, ensure_ascii=False)))


def audit(user_id, action, target=""):
    run("INSERT INTO audit(user_id,action,target,created_at) VALUES(?,?,?,?)", (user_id, action, target, now()))


# ---------------- 种子数据 ----------------
def seed():
    from auth import hash_password  # 延迟导入避免循环

    t0 = now()
    def days_ago(n):
        return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d %H:%M:%S")

    users = [
        ("owner@demo.com", "Li Wei", hash_password("demo1234"), "owner", "sales"),
        ("manager@demo.com", "Zhang Min", hash_password("demo1234"), "manager", "sales"),
        ("agent@demo.com", "Wang Jie", hash_password("demo1234"), "agent", "sales"),
        ("chen@demo.com", "Chen Yu", hash_password("demo1234"), "agent", "sales"),
        ("finance@demo.com", "Song Li", hash_password("demo1234"), "manager", "sales"),
    ]
    for e, n, p, r, tm in users:
        run("INSERT INTO users(email,name,pwd,role,team,created_at) VALUES(?,?,?,?,?,?)",
            (e, n, p, r, tm, t0))
    # 只读账号演示：能看数据，不能回复
    run("UPDATE users SET can_reply=0 WHERE email='finance@demo.com'")

    for name in ["Auto parts", "Hardware", "Tier A", "Canton Fair", "Price asked"]:
        run("INSERT INTO tags(name) VALUES(?)", (name,))

    contacts = [
        ("Ahmed Al-Farsi", "971500000412", "UAE", "Website", "/products/bolts", 120, "Negotiating", 12400, 1, 95, [1, 3]),
        ("Kwame Mensah", "233200000907", "Ghana", "Facebook", "Lead ad", 55, "Won", 6800, 2, 45, [2]),
        ("Carlos Rivera", "525500000338", "Mexico", "Website", "/products/bolts", 236, "Won", 18400, 1, 3, [3, 5]),
        ("Fatima Zahra", "212600000156", "Morocco", "Instagram", "DM", 190, "Lead", None, 3, 200, []),
        ("Rustam Karimov", "998900000221", "Uzbekistan", "Ads", "Meta campaign", 100, "Contacted", None, 2, 100, [1]),
        ("Diego Souza", "551100000074", "Brazil", "Website", "/products/bolts", 12, "Won", 4100, 1, 5, [3]),
        ("Yusuf Demir", "905300000612", "Türkiye", "Facebook", "Lead ad", 38, "Negotiating", 9200, 3, 40, [4]),
    ]
    FIRST = ["Omar","Ibrahim","Mohammed","Youssef","Hassan","Tariq","Samir","Karim","Rashid","Ali",
             "Emeka","Chinedu","Kofi","Tunde","Abebe","Jean","Pierre","Lucas","Mateo","Santiago",
             "Dmitry","Ivan","Alexei","Sergey","Timur","Bekzod","Aziz","Wei","Ming","Hao"]
    LAST = ["Haddad","Nasser","Mansour","Saleh","Karimi","Rahimi","Okonkwo","Adeyemi","Mensah","Okafor",
            "Dubois","Moreau","Silva","Lopez","Garcia","Petrov","Ivanov","Sokolov","Kim","Chen"]
    REGIONS = [("UAE","Website","971"),("Saudi Arabia","Facebook","966"),("Ghana","Facebook","233"),
               ("Morocco","Instagram","212"),("Uzbekistan","Ads","998"),("Brazil","Website","55"),
               ("Mexico","Website","52"),("Türkiye","Facebook","90"),("Kenya","Instagram","254"),
               ("Egypt","Ads","20")]
    import random
    random.seed(20261109)
    DEALS = ["Lead","Contacted","Negotiating","Won","Lost"]
    for i in range(35):
        nm = f"{FIRST[i % len(FIRST)]} {LAST[(i * 7) % len(LAST)]}"
        country, src, cc = REGIONS[i % len(REGIONS)]
        phone = f"{cc}5{random.randint(10000000, 99999999)}"
        opt = random.randint(10, 300)
        last = [3, 12, 45, 70, 95, 130, 200][i % 7]
        deal = DEALS[i % 5]
        val = random.choice([3200, 4800, 6100, 8900, 12500]) if deal == "Won" else None
        owner = None if i % 5 == 0 else (i % 3) + 1
        contacts.append((nm, phone, country, src, "auto", opt, deal, val, owner, last, []))

    for name, phone, country, src, detail, opt_days, deal, val, owner, last_days, tags in contacts:
        cid = run("""INSERT INTO contacts(name,phone,country,source,source_detail,opt_in_at,owner_id,
                     deal_status,deal_value,last_contact_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                  (name, phone, country, src, detail, days_ago(opt_days), owner, deal, val, days_ago(last_days), t0))
        for tid in tags:
            run("INSERT OR IGNORE INTO contact_tags(contact_id,tag_id) VALUES(?,?)", (cid, tid))
    # 客户标签：每个还没标签的客户挂一个，这样回收进公海后也能按标签筛
    POOL_TAGS = [1, 2, 3, 4, 5]
    for k, r in enumerate(q("""SELECT id FROM contacts
                               WHERE id NOT IN (SELECT contact_id FROM contact_tags) ORDER BY id""")):
        run("INSERT OR IGNORE INTO contact_tags(contact_id,tag_id) VALUES(?,?)", (r["id"], POOL_TAGS[k % 5]))

    # 公海演示：退订的、刚退回（保护期）、离职交接的成交客户，都不能再被领
    for k, r in enumerate(q("SELECT id FROM contacts WHERE owner_id IS NULL ORDER BY id")):
        if k in (2, 8):
            run("UPDATE contacts SET opt_out=1 WHERE id=?", (r["id"],))
        elif k in (4, 11):
            run("UPDATE contacts SET released_at=? WHERE id=?", (days_ago(0), r["id"]))
        elif k == 6:
            run("UPDATE contacts SET deal_status='Won', deal_value=6800 WHERE id=?", (r["id"],))

    segs = [
        ("Active", {"type": "active"}),
        ("Dormant 30d", {"type": "d30"}),
        ("Dormant 90d", {"type": "d90"}),
        ("Dormant 180d", {"type": "d180"}),
    ]
    for n, rule in segs:
        run("INSERT INTO segments(name,rule,is_system) VALUES(?,?,1)", (n, json.dumps(rule)))
    # 两个自定义分层，演示"自己定规则"
    custom = [
        ("阿联酋 · 30 天没联系", {"countries": ["UAE"], "last_contact": {"op": "gte", "days": 30}}),
        ("公海 · 汽配线索", {"tags": [1], "pool": "in"}),
    ]
    for n, rule in custom:
        run("INSERT INTO segments(name,rule,is_system) VALUES(?,?,0)", (n, json.dumps(rule, ensure_ascii=False)))

    tpls = [
        ("Win-back · Generic", "Marketing", "English", "approved",
         "Hi {{1}},\n\nWe noticed your last order of {{2}} was a while ago. This month's batch is in stock and priced 6% below your last purchase.\n\nShall I send you the specs and lead time?"),
        ("Auto parts · New arrivals", "Marketing", "Arabic", "approved",
         "Hi {{1}}, new arrivals in {{2}} just landed. Want the price list?"),
        ("Dormant 90d · Discount", "Marketing", "English", "pending",
         "Hi {{1}}, a one-time discount on {{2}} is available this month."),
        ("Order confirmed · Shipment", "Utility", "Multi", "approved",
         "Hi {{1}}, your order is confirmed and ships on {{2}}."),
        ("Black Friday promo", "Marketing", "Spanish", "rejected",
         "¡Hola {{1}}! Ofertas de Black Friday en {{2}}."),
    ]
    for n, cat, lang, st, body in tpls:
        run("INSERT INTO templates(name,category,language,status,body,created_at) VALUES(?,?,?,?,?,?)",
            (n, cat, lang, st, body, t0))

    ALL_C = q("SELECT id, deal_status FROM contacts ORDER BY id")
    camps = [
        ("Win-back · Dormant 90d", 3, 1, [c["id"] for c in ALL_C], 6),
        ("Auto parts · New arrivals", 2, 2, [c["id"] for c in ALL_C[::2]], 5),
        ("Win-back · Dormant 180d", 4, 1, [c["id"] for c in ALL_C[1::3]], 9),
    ]
    for name, seg_id, tpl_id, recips, days in camps:
        delivered = int(len(recips) * 0.92)
        replied = max(1, int(delivered * 0.18))
        camp_id = run("""INSERT INTO campaigns(name,segment_id,template_id,status,sent,delivered,replied,created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (name, seg_id, tpl_id, "done", len(recips), delivered, replied, days_ago(days)))
        for idx, cid in enumerate(recips):
            st = "replied" if idx < replied else ("delivered" if idx < delivered else "failed")
            run("""INSERT INTO campaign_recipients(campaign_id,contact_id,status,replied_at)
                   VALUES(?,?,?,?)""", (camp_id, cid, st, days_ago(days - 1) if st == "replied" else None))
    # 号码 1=Middle East sales, 2=Support, 3=Africa sales
    NUM_BY_CH = {"+971": 1, "+233": 3, "+212": 3, "+998": 1, "+90": 1, "+86": 2}
    convs = [
        (3, "+971", 1, 2, days_ago(0)),
        (1, "+971", 1, 0, days_ago(1)),
        (2, "+233", 2, 5, days_ago(0)),
        (4, "+212", None, 1, days_ago(1)),
        (5, "+998", 2, 0, days_ago(2)),
        (7, "+90", 3, 3, days_ago(1)),
        (6, "+86", 4, 2, days_ago(0)),
    ]
    for cid_, ch, owner, unread, last in convs:
        cv = run("INSERT INTO conversations(contact_id,channel,number_id,owner_id,unread,status,last_at) VALUES(?,?,?,?,?,?,?)",
                 (cid_, ch, NUM_BY_CH.get(ch, 1), owner, unread, "open", last))

    msgs = [
        (1, "in", "Hi, we received the samples. Quality looks good. What is your MOQ for the M12 bolts?", None, days_ago(0)),
        (1, "out", "Hi Carlos — MOQ is 2,000 pcs per size. For mixed sizes the total needs to reach 8,000. I'll send the spec sheet now.", 1, days_ago(0)),
        (1, "in", "Thanks. Can we move the shipping date one week earlier?", None, days_ago(0)),
        (2, "in", "Can you send the spec sheet for the 20ft container?", None, days_ago(1)),
        (5, "in", "Thanks, will check with my boss and come back to you.", None, days_ago(2)),
    (7, "in", "The spare parts arrived but two boxes are damaged. Can you check the shipping photos?", None, days_ago(0)),
    (7, "out", "Sorry to hear that. Please send the photos and the box labels — we will file the claim with the forwarder today.", 4, days_ago(0)),
]
    for cv, d, body, sender, at in msgs:
        run("INSERT INTO messages(conversation_id,direction,body,sender_id,created_at) VALUES(?,?,?,?,?)",
            (cv, d, body, sender, at))

    ai_logs = [
        (3, 1, "zh-CN", "M12 螺栓的 MOQ 是多少？",
         "M12 螺栓标准件 MOQ 为 2,000 件/规格；混装订单合计需达到 8,000 件。",
         '[{"title": "MOQ 与起订量说明", "score": 0.86}]', 0.86, "auto", None, 2100),
        (6, 7, "zh-CN", "能不能便宜点？",
         "价格问题已转给销售同事，稍后与您联系。", "[]", None, "blocked", None, 100),
        (2, 3, "en-US", "How many days for spare parts?",
         "Standard parts arrive in 3–5 working days; non-standard parts take 7–10 working days.",
         '[{"title": "备件交付周期说明", "score": 0.82}]', 0.82, "draft", None, 3400),
        (5, 5, "zh-CN", "你们在土耳其有仓库吗？",
         "这个问题我需要请同事确认，稍后回复您。", "[]", None, "handoff", None, 1900),
    ]
    for cid_, conv_id, loc, q_, a_, src_, sc_, dec_, esc_, ms_ in ai_logs:
        run("""INSERT INTO ai_logs(contact_id,conversation_id,locale,question,answer,sources,
                                 top_score,decision,escalation,latency_ms,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (cid_, conv_id, loc, q_, a_, src_, sc_, dec_, esc_, ms_, days_ago(0)))

    nums = [
        ("Middle East sales", "+971 50 000 0412", "Sales", "", "", "high", 10000, 2400, "connected"),
        ("Support", "+86 138 0000 0907", "Support", "", "", "high", 10000, 860, "connected"),
        ("Africa sales", "+212 6 00 000 156", "Sales", "", "", "medium", 1000, 0, "cooling"),
    ]
    for label, phone, purpose, waba, pnid, qual, lim, sent, st in nums:
        run("""INSERT INTO numbers(label,phone,purpose,waba_id,phone_number_id,quality,daily_limit,sent_today,status,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""", (label, phone, purpose, waba, pnid, qual, lim, sent, st, t0))

    # 接待组：号码 → 组 → 人（用户 1=老板, 2=主管, 3/4=销售）
    teams = [("中东组", [1, 2, 3], [1, 3]), ("售后组", [1, 4, 5], [2])]
    for name, members, number_ids in teams:
        tid = run("INSERT INTO teams(name,created_at) VALUES(?,?)", (name, t0))
        for uid in members:
            run("INSERT INTO team_members(team_id,user_id) VALUES(?,?)", (tid, uid))
        for nid in number_ids:
            run("INSERT INTO number_teams(number_id,team_id) VALUES(?,?)", (nid, tid))

    setting_set("inbox", {"reply_owner_only": True, "visibility": "team"})
    setting_set("pool", {"recycle_days": 90, "daily_claim_limit": 10, "enabled": True,
                         "protect_hours": 24, "exclude_success": True})

    setting_set("deal_stages", {
        "preset": "trade",
        "stages": [
            {"key": "Lead", "en": "Lead", "zh": "线索", "color": "gray"},
            {"key": "Contacted", "en": "Contacted", "zh": "已联系", "color": "blue"},
            {"key": "Quoted", "en": "Quoted", "zh": "已报价", "color": "info"},
            {"key": "Negotiating", "en": "Negotiating", "zh": "谈判中", "color": "warn"},
            {"key": "Won", "en": "Closed", "zh": "已成交", "color": "ok"},
            {"key": "Lost", "en": "Lost", "zh": "已丢单", "color": "bad"},
        ],
    })
    setting_set("workspace", {"name": "DeskClerk Demo Co", "timezone": "Asia/Shanghai",
                              "hours": "09:00 – 18:00, Mon–Fri", "lang": "en"})
    setting_set("compliance", {"opt_in_required": True, "optout_permanent": True,
                               "retention_months": 24, "window_hours": 24})
    setting_set("ai", {
        "enabled": True,
        "provider": "deskclerk",
        "mode": "draft",                     # off | draft | auto
        "base_url": "",
        "api_key": "",
        "site_id": "",
        "locales": ["zh-CN", "en-US", "ar-SA"],
        "threshold": 0.70,
        "window_only": True,
        "no_source_handoff": True,
        "badge": True,
        "daily_limit": 50,
        "persona": {
            "system_role": "You are a support agent for a B2B industrial supplier. Answer briefly and professionally: conclusion first, then steps.",
            "company_intro": "DeskClerk Demo Co supplies industrial parts to customers in the Middle East and Africa.",
            "product_scope": "只回答产品质量、规格、物流进度、退换与维修流程。",
            "policy_boundaries": "不报价、不承诺具体交期、不解释合同条款；不确定时明确说“我帮你转给同事确认”，不猜测。",
            "tone": "professional",
            "reply_max_words": 180,
            "timezone": "Asia/Riyadh",
            "business_hours": "周一至周六 09:00–18:00",
        },
        "safety": {
            "blocked_topics": ["价格", "交期承诺", "合同", "法律"],
            "complaint_keywords": ["投诉", "退款", "骗子", "律师"],
            "handoff_keywords": ["人工", "真人", "客服"],
        },
        "kb": {
            "indexed": 1284,
            "pending": 0,
            "failed": 2,
            "last_sync": days_ago(0),
            "callback_url": "",
        },
    })
    setting_set("notify", {"template_review": True, "quality_drop": True,
                           "daily_digest": True, "new_reply": True, "campaign_done": False})
    setting_set("channels", {
        "whatsapp":  {"status": "none", "waba_id": "", "access_token": "", "verify_token": "", "note": "Cloud API credentials"},
        "website":   {"status": "connected", "app_id": "", "secret": "", "note": "Leads posted from your site forms"},
        "facebook":  {"status": "connected", "app_id": "", "secret": "", "note": "Meta Lead Ads"},
        "instagram": {"status": "pending",   "app_id": "", "secret": "", "note": "Instagram DMs"},
        "webhook":   {"status": "none",      "url": "", "secret": "", "note": "Push events to your ERP"},
    })
