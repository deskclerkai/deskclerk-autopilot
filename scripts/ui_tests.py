#!/usr/bin/env python3
"""深度 UI 回归：真实点击 + 表单 + 角色切换，检查页面、交互和 JS 异常。

用法：
    DB_PATH=/tmp/scrm-ui.db python3 -m uvicorn main:app --app-dir app --port 7841 &
    python3 scripts/ui_tests.py http://127.0.0.1:7841
"""
import asyncio
import sys

from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:7841"
fails = []


def check(name, cond, extra=""):
    if not cond:
        fails.append(name + (f" :: {extra}" if extra else ""))
    return cond


async def login(pg, email, pwd="demo1234"):
    await pg.goto(BASE, wait_until="load")
    await pg.evaluate("localStorage.clear(); localStorage.setItem('lang','zh')")
    await pg.reload(wait_until="load")
    await pg.fill("#email", email)
    await pg.fill("#password", pwd)
    await pg.click("#doLogin")
    await pg.wait_for_timeout(1600)
    check(f"{email} 登录", await pg.is_visible("#app"))


async def go(pg, t, ms=800):
    await pg.evaluate(f"go('{t}')")
    await pg.wait_for_timeout(ms)


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", headless=True)
        ctx = await b.new_context(viewport={"width": 1440, "height": 900})
        pg = await ctx.new_page()
        errs = []
        dialogs = []
        pg.on("pageerror", lambda e: errs.append("pageerror: " + str(e)))
        pg.on("dialog", lambda d: (dialogs.append((d.type, d.message)), asyncio.ensure_future(d.accept())))
        pg.on("console", lambda m: errs.append("console: " + m.text) if m.type == "error" else None)

        # ============ 老板 ============
        await login(pg, "owner@demo.com")

        # 客户池
        await go(pg, "contacts")
        rows_before = await pg.evaluate("document.querySelectorAll('.col-list .row').length")
        check("客户池有数据", rows_before > 0, rows_before)
        await pg.evaluate("cfToggle()")
        await pg.wait_for_timeout(700)
        check("筛选面板打开", await pg.evaluate("!!document.querySelector('.cfpanel')"))
        await pg.evaluate("cfSet('country','UAE')")
        await pg.wait_for_timeout(900)
        rows_uae = await pg.evaluate("document.querySelectorAll('.col-list .row').length")
        check("国家筛选生效", 0 < rows_uae <= rows_before, (rows_before, rows_uae))
        await pg.evaluate("cfClear()")
        await pg.wait_for_timeout(800)
        cid = await pg.evaluate("document.querySelector('.col-list .row') && SEL_CONTACT")
        await pg.evaluate(f"assignPicker({cid})")
        await pg.wait_for_timeout(700)
        check("分配弹窗打开", await pg.evaluate("document.getElementById('mask').classList.contains('on')"))
        check("分配弹窗列出成员", await pg.evaluate("document.querySelectorAll('#modal .btn').length") >= 4)
        await pg.evaluate("[...document.querySelectorAll('#modal .btn')][1].click()")
        await pg.wait_for_timeout(1300)
        check("分配执行成功", "分配" in await pg.inner_text("#toast"), await pg.inner_text("#toast"))
        await pg.wait_for_timeout(300)
        check("负责人下拉存在", await pg.evaluate("!!document.querySelector('#contactPane select')"))

        # 公海
        await go(pg, "pool")
        pool_txt = await pg.inner_text("#body")
        check("公海页有列表", "公海里的客户" in pool_txt or "Contacts in the pool" in pool_txt)
        check("公海有不可领提示", ("保护" in pool_txt) or ("Protected" in pool_txt))
        before_claim = await pg.evaluate("document.querySelectorAll('#body table tbody tr').length")
        clicked = await pg.evaluate("""(() => {
          const b=[...document.querySelectorAll('#body .btn.sm.gold')].find(x=>x.textContent.includes('领取'));
          if(!b) return false; b.click(); return true; })()""")
        await pg.wait_for_timeout(1400)
        if clicked:
            after_claim = await pg.evaluate("document.querySelectorAll('#body table tbody tr').length")
            check("公海领取生效", after_claim < before_claim, (before_claim, after_claim))

        # 分层 + 新建
        await go(pg, "segments")
        before_segs = await pg.evaluate("document.querySelectorAll('.col-list .seg').length")
        check("分层列表", before_segs >= 6, before_segs)
        await pg.evaluate("openSegEditor()")
        await pg.wait_for_timeout(900)
        check("分层编辑器打开", await pg.evaluate("document.getElementById('mask').classList.contains('on')"))
        await pg.fill("#segName", "UI回归分层")
        await pg.evaluate("""() => { const c=[...document.querySelectorAll('input[data-dim="countries"]')][0]; if(c) c.checked=true; }""")
        await pg.click("#modal .btn.gold")
        await pg.wait_for_timeout(1400)
        check("新建分层成功", "UI回归分层" in await pg.inner_text(".col-list"))
        await pg.evaluate("""(() => { const b=[...document.querySelectorAll('.col-main .btn')]
          .find(x=>x.textContent.includes('删除')); if(b) b.click(); })()""")
        await pg.wait_for_timeout(1500)
        check("删除分层生效", "UI回归分层" not in await pg.inner_text(".col-list"))

        # 模板
        await go(pg, "templates")
        check("模板有内容", await pg.evaluate("document.querySelectorAll('.col-list .row').length") >= 5)
        await pg.evaluate("pickTpl(document.querySelector('.col-list .row').getAttribute('onclick').match(/\\d+/)[0])")
        await pg.wait_for_timeout(700)
        check("模板详情", "审核" in await pg.inner_text(".col-main") or "模板" in await pg.inner_text(".col-main"))

        # 触达
        await go(pg, "campaigns")
        camps = await pg.evaluate("(async()=>await api('/api/campaigns'))()")
        before_camps = len(camps["items"])
        await pg.evaluate("document.querySelector('#body .btn.gold[onclick=\"createCampaign()\"]').click()")
        await pg.wait_for_timeout(1600)
        camps2 = await pg.evaluate("(async()=>await api('/api/campaigns'))()")
        check("新建触达成功", len(camps2["items"]) == before_camps + 1, (before_camps, len(camps2["items"])))
        if camps["items"]:
            await pg.evaluate(f"openCampaign({camps['items'][0]['id']})")
            await pg.wait_for_timeout(900)
            check("触达详情弹窗", await pg.evaluate("document.getElementById('mask').classList.contains('on')"))
            await pg.evaluate("closeModal()")
            await pg.wait_for_timeout(300)

        # AI 助手
        await go(pg, "ai", 1200)
        check("AI 页 7 个面板", await pg.evaluate("document.querySelectorAll('.ai-panel').length") == 7)
        check("AI 右侧预览", await pg.evaluate("!!document.querySelector('.ai-phone')"))
        check("AI 接待方式常驻", await pg.evaluate("!!document.querySelector('.ai-modebar')"))
        check("AI 大脑选择器", await pg.evaluate("document.getElementById('aiProvider') && document.getElementById('aiProvider').value === 'deskclerk'"))
        await pg.evaluate("aiRunTest('你们在土耳其有仓库吗？')")
        await pg.wait_for_timeout(1000)
        ai_res = await pg.inner_text("#aiResult")
        check("AI 无依据转人工", ("转人工" in ai_res) or ("handoff" in ai_res), ai_res)
        await pg.evaluate("aiTab('policy')")
        await pg.wait_for_timeout(300)
        await pg.evaluate("document.querySelector('.ai-mode .m[data-mode=\"auto\"]').click()")
        await pg.wait_for_timeout(200)
        check("AI 模式切换", "全自动" in await pg.inner_text(".ai-modebar button.on"))
        await pg.evaluate("aiTab('persona')")
        await pg.wait_for_timeout(300)
        tabs = await pg.eval_on_selector_all(".ai-tab", "els=>els.map(e=>e.textContent.trim())")
        check("AI 多语言人设", "en-US" in tabs and "ar-SA" in tabs, tabs)
        check("AI 人设字段", await pg.evaluate("!!document.getElementById('aiRole')"))
        await pg.evaluate("saveAIAll()")
        await pg.wait_for_timeout(1200)
        check("AI 保存", "保存" in await pg.inner_text("#toast"), await pg.inner_text("#toast"))

        # 团队 / 看板
        await go(pg, "team")
        check("团队页有成员", await pg.evaluate("document.querySelectorAll('#body table tbody tr').length") >= 5)
        await go(pg, "analytics")
        check("看板有 KPI", await pg.evaluate("document.querySelectorAll('.kpi').length") >= 4)

        # 设置各页 + 交互
        await go(pg, "settings")
        await pg.evaluate("setTab('routing')")
        await pg.wait_for_timeout(1200)
        check("号码与团队看板", await pg.evaluate("document.querySelectorAll('#setpanel input[type=checkbox]').length") >= 12)
        first_cb = "document.querySelectorAll('#setpanel input[type=checkbox]')[0]"
        before_checked = await pg.evaluate(f"{first_cb}.checked")
        await pg.evaluate(f"{first_cb}.click()")
        await pg.wait_for_timeout(1400)
        after_checked = await pg.evaluate(f"{first_cb}.checked")
        check("矩阵勾选生效", before_checked != after_checked, (before_checked, after_checked))
        await pg.evaluate(f"{first_cb}.click()")
        await pg.wait_for_timeout(1200)

        await pg.evaluate("setTab('tags')")
        await pg.wait_for_timeout(900)
        await pg.fill("#newTag", "UI回归标签")
        await pg.evaluate("document.querySelector('#setpanel [onclick=\"createTagUI()\"]').click()")
        await pg.wait_for_timeout(1200)
        check("新建标签成功", "UI回归标签" in await pg.inner_text("#setpanel"))

        # XSS：恶意标签名必须原样显示，不能执行
        await pg.evaluate("""(async()=>{ await api('/api/tags',{method:'POST',
          body:JSON.stringify({name:'<img src=x onerror=\"window.__xss=1\">'})}); })()""")
        await pg.evaluate("setTab('tags')")
        await pg.wait_for_timeout(1000)
        check("XSS 未执行", await pg.evaluate("!window.__xss"))
        check("XSS 标签按文字显示", "<img src=x" in await pg.inner_text("#setpanel"))

        await pg.evaluate("setTab('team')")
        await pg.wait_for_timeout(900)
        await pg.fill("#nuName", "UI回归员工")
        await pg.fill("#nuEmail", "uitest@demo.com")
        await pg.fill("#nuPwd", "pass12345")
        await pg.evaluate("createMember()")
        await pg.wait_for_timeout(1400)
        check("新建成员成功", "UI回归员工" in await pg.inner_text("#setpanel"))

        await pg.evaluate("setTab('numbers')")
        await pg.wait_for_timeout(1000)
        await pg.evaluate("syncNumbersUI()")
        await pg.wait_for_timeout(500)
        check("同步号码弹窗", await pg.evaluate("document.getElementById('mask').classList.contains('on')"))
        await pg.evaluate("closeModal()")
        await pg.wait_for_timeout(300)
        check("接入方式下拉存在", await pg.evaluate("document.querySelectorAll('#setpanel select').length") >= 3)
        nums_before = await pg.evaluate("document.querySelectorAll('#setpanel table tbody tr').length")
        await pg.evaluate("newNumber()")
        await pg.wait_for_timeout(400)
        await pg.fill("#nbLabel", "UI回归号码")
        await pg.fill("#nbPhone", "+1 202 000 1234")
        await pg.evaluate("saveNumber()")
        await pg.wait_for_timeout(1500)
        nums_after = await pg.evaluate("document.querySelectorAll('#setpanel table tbody tr').length")
        check("新增号码成功", nums_after == nums_before + 1 and "UI回归号码" in await pg.inner_text("#setpanel"), (nums_before, nums_after))

        # 会话台 + 认领
        await go(pg, "inbox")
        convs = await pg.evaluate("(async()=>await api('/api/conversations'))()")
        check("会话有号码标签", all(c.get("number_label") for c in convs["items"]), [c.get("number_label") for c in convs["items"]])
        await pg.evaluate(f"openConv({convs['items'][0]['id']})")
        await pg.wait_for_timeout(900)
        check("会话输入框或提示", await pg.evaluate("!!document.querySelector('#replyBox') || document.querySelector('#convPane').innerText.includes('只读') || document.querySelector('#convPane').innerText.includes('归')"))
        check("会话 AI 托管开关", "AI 托管" in await pg.inner_text("#convPane"))
        check("会话右侧客户档案", "客户档案" in await pg.inner_text("#convSide"))
        await pg.evaluate("toggleConvSide()")
        await pg.wait_for_timeout(600)
        check("客户档案可收起", await pg.evaluate("document.getElementById('convSide').classList.contains('hidden')"))
        await pg.evaluate("toggleConvSide()")
        await pg.wait_for_timeout(600)
        check("客户档案可展开", "客户档案" in await pg.inner_text("#convSide"))

        # ============ 手机尺寸 ============
        mctx = await b.new_context(viewport={"width": 390, "height": 844})
        mpg = await mctx.new_page()
        await login(mpg, "owner@demo.com")
        overflow = []
        for page in ("inbox", "pool", "contacts", "segments", "templates", "ai", "team", "analytics", "settings"):
            await mpg.evaluate(f"go('{page}')")
            await mpg.wait_for_timeout(700)
            w = await mpg.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
            if w[0] > w[1] + 4:
                overflow.append((page, w))
        check("手机宽度无横向溢出", not overflow, overflow)
        await mctx.close()

        # ============ 销售 ============
        pg2 = await ctx.new_page()
        pg2.on("pageerror", lambda e: errs.append("agent pageerror: " + str(e)))
        pg2.on("console", lambda m: errs.append("agent console: " + m.text) if m.type == "error" else None)
        await login(pg2, "agent@demo.com")
        navs = await pg2.eval_on_selector_all(".rail .nav[data-t]", "els => els.map(e => e.dataset.t)")
        for blocked in ("team", "analytics", "settings", "campaigns"):
            check(f"销售导航隐藏 {blocked}", blocked not in navs, navs)
        for page in ("inbox", "pool", "contacts", "segments", "templates"):
            await pg2.evaluate(f"go('{page}')")
            await pg2.wait_for_timeout(800)
            txt = await pg2.inner_text("#body")
            check(f"销售可访问 {page}", len(txt) > 20 and "forbidden" not in txt.lower(), txt[:40])
        agent_convs = await pg2.evaluate("(async()=>await api('/api/conversations'))()")
        others = [c for c in agent_convs["items"] if c["owner_id"] and c["owner_id"] != 3]
        if others:
            await pg2.evaluate(f"openConv({others[0]['id']})")
            await pg2.wait_for_timeout(900)
            pane = await pg2.inner_text("#convPane")
            check("非负责人被提示不能回复", ("只有 TA 能回复" in pane) or ("Only they can reply" in pane), pane[-120:])
            check("非负责人无输入框", await pg2.evaluate("!document.querySelector('#replyBox')"))

        # ============ 只读账号 ============
        pg3 = await ctx.new_page()
        pg3.on("pageerror", lambda e: errs.append("finance pageerror: " + str(e)))
        await login(pg3, "finance@demo.com")
        await pg3.evaluate("go('inbox')")
        await pg3.wait_for_timeout(900)
        fconvs = await pg3.evaluate("(async()=>await api('/api/conversations'))()")
        if fconvs["items"]:
            await pg3.evaluate(f"openConv({fconvs['items'][0]['id']})")
            await pg3.wait_for_timeout(900)
            pane = await pg3.inner_text("#convPane")
            check("只读提示", ("只读账号" in pane) or ("Read-only account" in pane), pane[-120:])
            check("只读无输入框", await pg3.evaluate("!document.querySelector('#replyBox')"))

        alerts = [x for x in dialogs if x[0] == "alert"]
        if alerts:
            fails.append("出现了 alert 弹窗: " + str(alerts[:3]))
        if errs:
            fails.append("JS 报错: " + " | ".join(errs[:6]))
        await b.close()

    print(f"\nUI 检查完成：{'全部通过' if not fails else str(len(fails)) + ' 项失败'}")
    for f in fails:
        print("  ✗ " + f)
    return 1 if fails else 0


sys.exit(asyncio.run(main()))
