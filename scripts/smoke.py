#!/usr/bin/env python3
"""冒烟测试：登录 → 走遍所有页面与设置子页 → 查 JS 报错 / 死元素 / 关键区块。
用法：python3 scripts/smoke.py [http://127.0.0.1:8000]
"""
import asyncio, sys
from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:7830"
PAGES = ["inbox", "pool", "contacts", "segments", "templates", "campaigns", "ai", "team", "analytics"]
SET_TABS = ["workspace", "pool", "team", "routing", "compliance", "ai", "notify", "channels", "stages", "numbers", "tags", "audit"]

JS_DEAD = """
() => {
  const root = document.getElementById('body');
  const bad = [];
  for (const e of root.querySelectorAll('*')) {
    const cs = getComputedStyle(e);
    const clickable = cs.cursor === 'pointer' || e.tagName === 'BUTTON' ||
      ['btn','pill','tab','seg','row'].some(c => e.classList.contains(c)) || e.getAttribute('onclick');
    if (!clickable) continue;
    if (['INPUT','SELECT','OPTION'].includes(e.tagName)) continue;
    if (e.getAttribute('onclick') || e.getAttribute('onchange') || e.getAttribute('oninput')) continue;
    if (e.closest('[onclick]')) continue;
    if (e.querySelector('a,button,[onclick]')) continue;
    if ((e.innerText || '').trim()) bad.push(e.tagName + ':' + e.innerText.trim().slice(0, 20));
  }
  return [...new Set(bad)];
}
"""

async def main():
    fails = []
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", headless=True)
        pg = await (await b.new_context(viewport={"width": 1440, "height": 900})).new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(BASE, wait_until="load")
        await pg.evaluate("localStorage.clear()")
        await pg.reload(wait_until="load")
        await pg.fill("#email", "owner@demo.com")
        await pg.fill("#password", "demo1234")
        await pg.click("#doLogin")
        await pg.wait_for_timeout(1500)
        if await pg.is_hidden("#app"):
            fails.append("登录失败")
        navs = await pg.eval_on_selector_all(".rail .nav[data-t]", "els => els.map(e => e.dataset.t)")
        for need in PAGES:
            if need not in navs:
                fails.append(f"导航里缺少 {need}")
        for p_ in PAGES:
            await pg.evaluate(f"go('{p_}')")
            await pg.wait_for_timeout(700)
            txt = await pg.inner_text("#body")
            if any(k in txt for k in ("is not defined", "Cannot read", "undefined is not", "is not a function")):
                fails.append(f"{p_} 渲染报错: {txt[:60]}")
            if len(txt) < 20:
                fails.append(f"{p_} 内容为空")
        await pg.evaluate("go('settings')")
        await pg.wait_for_timeout(500)
        for t in SET_TABS:
            await pg.evaluate(f"setTab('{t}')")
            await pg.wait_for_timeout(600)
            txt = await pg.inner_text("#body")
            if any(k in txt for k in ("is not defined", "Cannot read", "undefined is not", "is not a function")):
                fails.append(f"settings:{t} 渲染报错")
        await pg.evaluate("go('inbox')")
        await pg.wait_for_timeout(600)
        dead = await pg.evaluate(JS_DEAD)
        if dead:
            fails.append(f"死元素: {dead}")
        if errs:
            fails.append(f"JS 异常: {errs[:3]}")
        await b.close()
    print("✅ 全部通过" if not fails else "❌ 失败:\n- " + "\n- ".join(fails))
    return 1 if fails else 0

sys.exit(asyncio.run(main()))
