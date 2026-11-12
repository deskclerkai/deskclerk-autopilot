/* DeskClerk AI Autopilot — frontend */
let LANG = localStorage.getItem('lang') || 'en';
const T = (en, zh) => (LANG === 'en' ? en : zh);

let TOKEN = localStorage.getItem('token') || '';
let ME = null;
let CUR = 'inbox';
let INBOX_TAB = 'open', INBOX_OWNER = 0, INBOX_NUMBER = 0;
let CONV_SIDE_OPEN = localStorage.getItem('convSideOpen') !== '0';
let CUR_VIEW = 'all';
let SEL_CONTACT = null;
let SEL_CONV = null;
let CACHE = {};

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...(TOKEN ? { Authorization: 'Bearer ' + TOKEN } : {}), ...(opts.headers || {}) },
  });
  if (res.status === 401) { logout(); throw new Error('unauthorized'); }
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = j.detail || msg; } catch (e) {}
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}

function toast(msg) {
  const t = $('toast'); t.textContent = msg; t.classList.add('on');
  setTimeout(() => t.classList.remove('on'), 2200);
}

/* ---------------- 登录 ---------------- */
$('doLogin').onclick = async () => {
  $('err').textContent = '';
  try {
    const r = await api('/api/login', { method: 'POST', body: JSON.stringify({ email: $('email').value, password: $('password').value }) });
    TOKEN = r.token; localStorage.setItem('token', TOKEN); ME = r.user;
    try { ME = await api('/api/me'); } catch (e) {}
    startApp();
  } catch (e) { $('err').textContent = e.message; }
};
$('password').addEventListener('keydown', e => { if (e.key === 'Enter') $('doLogin').click(); });

function logout() {
  TOKEN = ''; ME = null; localStorage.removeItem('token');
  $('app').style.display = 'none'; $('login').style.display = 'flex';
}

/* ---------------- 骨架 ---------------- */
const NAV = [
  { t: 'inbox', ico: '✉', en: 'Inbox', zh: '会话台' },
  { t: 'pool', ico: '◎', en: 'Pool', zh: '公海' },
  { t: 'contacts', ico: '◧', en: 'Contacts', zh: '客户池' },
  { t: 'segments', ico: '◍', en: 'Segments', zh: '分层' },
  { t: 'templates', ico: '▤', en: 'Templates', zh: '模板' },
  { t: 'campaigns', ico: '➤', en: 'Campaigns', zh: '触达' },
  { t: 'ai', ico: '✦', en: 'AI assistant', zh: 'AI 助手' },
  { t: 'team', ico: '◉', en: 'Team', zh: '团队' },
  { t: 'analytics', ico: '▦', en: 'Analytics', zh: '看板' },
  { t: 'settings', ico: '⚙', en: 'Settings', zh: '设置' },
];
const LOGO = `<img class="logo" src="/static/logo.svg" alt="">`;

const AGENT_BLOCKED = ['team', 'analytics', 'settings', 'campaigns', 'ai'];
function drawRail() {
  const allowed = NAV.filter(n => !(ME.role === 'agent' && AGENT_BLOCKED.includes(n.t)));
  $('rail').innerHTML = LOGO + allowed.map(n =>
    `<div class="nav ${n.t === CUR ? 'on' : ''}" data-t="${n.t}"><span class="ico">${n.ico}</span><span class="lb">${T(n.en, n.zh)}</span></div>`
  ).join('') + '<div class="sp"></div>';
  document.querySelectorAll('.rail .nav').forEach(n => n.onclick = () => go(n.dataset.t));
}

async function loadStages() {
  try {
    const st = await api('/api/settings');
    if (st.deal_stages && st.deal_stages.stages) STAGES = st.deal_stages.stages;
  } catch (e) {}
}

async function startApp() {
  await loadStages();
  $('login').style.display = 'none';
  $('app').style.display = 'flex';
  $('meAvatar').textContent = (ME.name || 'U')[0];
  await go('inbox');
}

function updateBrandLine() {
  const el = $('aiBrandLine'); if (!el) return;
  el.innerHTML = LANG === 'en'
    ? 'AI powered by <a href="https://deskclerkai.com" target="_blank" rel="noopener">DeskClerk AI</a> · Learn more →'
    : 'AI 能力由 <a href="https://deskclerkai.com" target="_blank" rel="noopener">DeskClerk AI</a> 提供 · 了解知识库 →';
}
$('langBtn').onclick = () => { LANG = LANG === 'en' ? 'zh' : 'en'; localStorage.setItem('lang', LANG); updateBrandLine(); go(CUR); };
$('newCampBtn').onclick = () => go('campaigns');

async function go(t) {
  if (ME.role === 'agent' && AGENT_BLOCKED.includes(t)) t = 'inbox';
  CUR = t; drawRail();
  $('langBtn').textContent = LANG === 'en' ? '中文' : 'EN';
  $('roleBtn').textContent = '👤 ' + T({ owner: 'Owner', manager: 'Manager', agent: 'Agent' }[ME.role],
                                        { owner: '老板', manager: '主管', agent: '销售' }[ME.role]);
  $('newCampBtn').textContent = '＋ ' + T('New campaign', '新建触达');
  $('newCampBtn').style.display = (ME.role === 'agent') ? 'none' : '';
  $('body').innerHTML = `<div class="loading">${T('Loading…', '加载中…')}</div>`;
  try {
    const fn = resolveView(t);
    if (typeof fn !== 'function') throw new Error('unknown view: ' + t);
    await fn();
  } catch (e) {
    if (e.message !== 'unauthorized') $('body').innerHTML = `<div class="loading">${esc(e.message)}</div>`;
  }
}

/* ---------------- 通用组件 ---------------- */
let STAGES = [
  { key:'Lead', en:'Lead', zh:'线索', color:'gray' },
  { key:'Contacted', en:'Contacted', zh:'已联系', color:'blue' },
  { key:'Quoted', en:'Quoted', zh:'已报价', color:'info' },
  { key:'Negotiating', en:'Negotiating', zh:'谈判中', color:'warn' },
  { key:'Won', en:'Closed', zh:'已成交', color:'ok' },
  { key:'Lost', en:'Lost', zh:'已丢单', color:'bad' },
];
const STAGE_FALLBACK = {
  Lead:['Lead','线索','gray'], Contacted:['Contacted','已联系','blue'], Quoted:['Quoted','已报价','info'],
  Negotiating:['Negotiating','谈判中','warn'], Won:['Closed','已成交','ok'], Lost:['Lost','已丢单','bad'],
  Signed:['Signed','已签约','warn'], Active:['Active','合作中','ok'], Renewed:['Renewed','已续约','ok'],
  Proposal:['Proposal','方案中','info'], Trial:['Trial','已试听','info'], Enrolled:['Enrolled','已报名','warn'],
  Qualified:['Qualified','已确认','info'],
};
const stageOf = (k) => STAGES.find(s => s.key === k) ||
  (STAGE_FALLBACK[k] ? { key:k, en:STAGE_FALLBACK[k][0], zh:STAGE_FALLBACK[k][1], color:STAGE_FALLBACK[k][2] }
                     : { key:k, en:k, zh:k, color:'gray' });
const chipDeal = (d) => {
  const st = stageOf(d);
  const cls = { ok:'c-ok', bad:'c-bad', warn:'c-warn', info:'c-info', blue:'c-info', gray:'c-gray' }[st.color] || 'c-gray';
  return `<span class="chip ${cls}">${T(st.en, st.zh)}</span>`;
};
const roleName = (r) => T({ owner: 'Owner', manager: 'Manager', agent: 'Sales' }[r],
                           { owner: '老板', manager: '主管', agent: '销售' }[r]);
const chipTpl = (s) => s === 'approved' ? `<span class="chip c-ok">● ${T('Approved', '已通过')}</span>`
  : s === 'pending' ? `<span class="chip c-warn">● ${T('In review', '审核中')}</span>`
  : `<span class="chip c-bad">● ${T('Rejected', '被拒')}</span>`;
const segName = (id) => ({ active: T('Active', '最近成交'), d30: T('Dormant 30d', '沉默 30 天'),
  d90: T('Dormant 90d', '沉默 90 天'), d180: T('Dormant 180d', '沉默 180 天'), opted_out: T('Opted out', '已退订') }[id] || id);

/* ---------------- 会话台 ---------------- */
async function viewInbox() {
  const [{ items }, numRes] = await Promise.all([api('/api/conversations'), api('/api/numbers/allowed')]);
  const nums = numRes.items || [];
  if (ME.role !== 'agent' && !CACHE.users) CACHE.users = (await api('/api/users')).items;
  const users = CACHE.users || [];
  $('hTitle').textContent = T('Inbox', '会话台');
  $('hSub').textContent = T('All numbers in one window · each chat shows who owns it', '多个号码一个窗口 · 每条会话都标着归谁');
  const shown = (INBOX_TAB === 'unassigned' ? items.filter(c => !c.owner_id)
              : INBOX_TAB === 'mine' ? items.filter(c => c.owner_id === ME.id) : items)
              .filter(c => !INBOX_OWNER || c.owner_id === INBOX_OWNER)
              .filter(c => !INBOX_NUMBER || c.number_id === INBOX_NUMBER);
  if (!SEL_CONV || !shown.find(c => c.id === SEL_CONV)) SEL_CONV = shown[0] ? shown[0].id : null;
  const sel = shown.find(c => c.id === SEL_CONV) || shown[0];

  $('body').innerHTML = `
    <div class="col-list">
      <div class="toolbar">
        <div class="searchbox">🔍 ${T('Search messages, contacts', '搜索消息、客户')}</div>
        <div class="tabs">
          ${[['open', T('Open', '进行中'), items.length],
             ['unassigned', T('Unassigned', '未分配'), items.filter(i => !i.owner_id).length],
             ['mine', T('Mine', '我的'), items.filter(i => i.owner_id === ME.id).length]]
            .map(([k, n, c]) => `<span class="tab ${INBOX_TAB === k ? 'on' : ''}" onclick="setInboxTab('${k}')">${n} <span style="opacity:.55">${c}</span></span>`).join('')}
        </div>
        ${nums.length > 1 ? `<div class="rows" style="display:flex;align-items:center;gap:8px">
          <span style="font-size:11.5px;color:var(--sub);font-weight:700">${T('Number', '号码')}</span>
          <select class="inp" style="height:30px;border:1px solid var(--line);border-radius:8px;font-size:12px;background:#fff"
            onchange="setInboxNumber(this.value)">
            <option value="0">${T('All numbers', '全部号码')}</option>
            ${nums.map(n => `<option value="${n.id}" ${INBOX_NUMBER === n.id ? 'selected' : ''}>${esc(n.label)}</option>`).join('')}
          </select>
        </div>` : ''}
        ${ME.role === 'agent' ? '' : `<div class="rows" style="display:flex;align-items:center;gap:8px">
          <span style="font-size:11.5px;color:var(--sub);font-weight:700">${T('Owner', '负责人')}</span>
          <select class="inp" style="height:30px;border:1px solid var(--line);border-radius:8px;font-size:12px;background:#fff"
            onchange="setInboxOwner(this.value)">
            <option value="0">${T('Everyone', '全部销售')}</option>
            ${users.map(u => `<option value="${u.id}" ${INBOX_OWNER === u.id ? 'selected' : ''}>${esc(u.name)}</option>`).join('')}
          </select>
        </div>`}
      </div>
      ${shown.map(c => `
        <div class="row ${sel && c.id === sel.id ? 'on' : ''}" onclick="openConv(${c.id})">
          <div class="avatar">${esc((c.contact_name || '?')[0])}</div>
          <div style="min-width:0;flex:1">
            <div class="nm">${esc(c.contact_name)} <span class="src">${esc(c.number_label || c.channel)}</span>
              ${c.owner_id ? '' : `<span class="chip c-warn" style="height:18px;font-size:10.5px">${T('unassigned', '未分配')}</span>`}</div>
            <div class="mt">${esc(c.last_body || '')}</div>
            <div style="font-size:11px;margin-top:3px">${c.owner_name
              ? `<span style="color:var(--sub)">👤 ${esc(c.owner_name)}</span>`
              : `<span style="color:#B26B00;font-weight:600">${T('no owner — unassigned', '无负责人 · 未分配')}</span>`}</div>
          </div>
          <div style="text-align:right;flex:none">
            <div style="font-size:11px;color:#8794A3">${esc((c.last_at || '').slice(5, 16))}</div>
            ${c.unread ? `<div style="margin-top:5px;background:var(--gold);color:#2B2200;font-size:11px;font-weight:800;border-radius:99px;padding:1px 7px;display:inline-block">${c.unread}</div>` : ''}
          </div>
        </div>`).join('') || `<div class="loading">${T('No conversations', '暂无会话')}</div>`}
    </div>
    <div class="col-main" id="convPane" style="padding:0;display:flex;flex-direction:column"></div>
    <aside class="col-side conv-side ${CONV_SIDE_OPEN ? '' : 'hidden'}" id="convSide"></aside>`;
  if (sel) await renderConv(sel.id);
  else $('convPane').innerHTML = `<div class="loading">${T('Pick a conversation', '选择一个会话')}</div>`;
}

window.openConv = async (id) => { SEL_CONV = id; await viewInbox(); };
window.setInboxTab = (k) => { INBOX_TAB = k; INBOX_OWNER = 0; SEL_CONV = null; viewInbox(); };
window.setInboxOwner = (v) => { INBOX_OWNER = +v; SEL_CONV = null; viewInbox(); };
window.setInboxNumber = (v) => { INBOX_NUMBER = +v; SEL_CONV = null; viewInbox(); };

async function renderConv(id) {
  const [data, convs, st, draftRes] = await Promise.all([
    api(`/api/conversations/${id}/messages`), api('/api/conversations'),
    api('/api/settings'), api(`/api/conversations/${id}/ai-draft`)]);
  const c = convs.items.find(x => x.id === id);
  if (!c) return;
  const pane = $('convPane');
  if (!pane) return;
  const users = ME.role === 'agent' ? { items: [] } : await api('/api/users');
  const strict = ((st.inbox || {}).reply_owner_only !== false);
  const mine = c.owner_id === ME.id;
  const aiOn = c.ai_enabled !== 0;
  const draft = draftRes && draftRes.draft;
  const replyBlock = !ME.can_reply
    ? `<div style="padding:10px 12px;background:#FFF8E6;border:1px solid #F3E0AE;border-radius:8px;font-size:12.5px;color:#7A5B00">
        🔒 ${T('Read-only account: you can view conversations and data, but not send replies.', '只读账号：可以看会话和数据，不能发送回复。')}</div>`
    : (strict && !c.owner_id)
    ? `<div style="padding:10px 12px;background:#EEF4FF;border:1px solid #CFDDF5;border-radius:8px;font-size:12.5px;color:#1B3A5C;display:flex;align-items:center;gap:10px">
        ${T('This conversation has no owner yet. Claim it first, then you can reply.', '这条会话还没有负责人。先认领，才能回复。')}
        <span class="btn sm gold" style="margin-left:auto" onclick="claimConv(${id})">${T('Claim it', '认领')}</span></div>`
    : (strict && !mine)
    ? `<div style="padding:10px 12px;background:#FFF1F0;border:1px solid #F5C8C4;border-radius:8px;font-size:12.5px;color:#8C2B22">
        🔒 ${T('This conversation belongs to ', '这条会话归 ')}<b>${esc(c.owner_name || '')}</b>${T('. Only they can reply; ask a manager to hand it over.', ' 负责，只有 TA 能回复；需要接手请让主管转给你。')}</div>`
    : `<textarea class="inp" id="replyBox" placeholder="${data.window_open ? T('Type a reply…', '输入回复…') : T('Window closed — pick an approved template', '窗口已关闭，请选择已审模板')}"></textarea>
      <div style="display:flex;gap:8px;margin-top:10px">
        <span class="btn sm" onclick="simulateInbound(${id})">${T('Test inbound', '测试来信')}</span>
        <span class="btn sm" onclick="aiDraft(${id})">${T('AI draft', 'AI 起草')}</span>
        <span class="btn sm" onclick="go('templates')">${T('Insert template', '插入模板')}</span>
        <span style="margin-left:auto" class="btn sm gold" onclick="sendMsg(${id})">${T('Send', '发送')}</span>
      </div>
      <div style="font-size:11.5px;color:var(--sub);margin-top:8px">${T('Sandbox mode: messages are stored, not delivered to WhatsApp.', '沙盒模式：消息只入库，不会真的发到 WhatsApp。')}</div>`;
  pane.innerHTML = `
    <div style="padding:14px 20px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:12px;background:#fff">
      <div class="avatar">${esc((c.contact_name || '?')[0])}</div>
      <div><div style="font-weight:700">${esc(c.contact_name)}</div>
        <div style="font-size:12px;color:var(--sub)">${esc(c.country || '')} · ${esc(c.phone)} · ${esc(c.number_label || '')} · ${T('assigned to', '负责人')} ${esc(c.owner_name || T('nobody', '无'))}</div></div>
      <div style="margin-left:auto;display:flex;gap:8px">
        <span class="btn sm" onclick="toggleConvSide()">${CONV_SIDE_OPEN ? '收起档案' : '客户档案'}</span>
        <span class="chip ${aiOn ? 'c-ok' : 'c-gray'}" style="cursor:pointer" onclick="toggleConvAI(${id}, ${aiOn ? 1 : 0})">AI 托管：${aiOn ? '开' : '关'}</span>
        ${!c.owner_id ? `<span class="btn sm gold" onclick="claimConv(${id})">${T('Claim', '认领')}</span>` : ''}
        ${ME.role === 'agent' ? '' : `<select onchange="assignConv(${id}, this.value)" style="height:28px;border:1px solid var(--line);border-radius:7px;font-size:12px">
            <option value="">${T('Assign to…', '分配给…')}</option>
            ${users.items.map(u => `<option value="${u.id}" ${u.id === c.owner_id ? 'selected' : ''}>${esc(u.name)}</option>`).join('')}
          </select>`}
        <span class="btn sm" onclick="openDeal(${c.contact_id})">${T('Update status', '更新状态')}</span>
      </div>
    </div>
    <div style="flex:1;overflow:auto;padding:20px;background:#F7F9FC">
      <div style="max-width:640px;margin:0 auto;display:flex;flex-direction:column;gap:14px">
        ${data.items.map(m => m.direction === 'in'
          ? `<div style="align-self:flex-start;max-width:78%">
               <div class="bubble" style="max-width:none">${esc(m.body)}</div>
               <div style="font-size:11px;color:var(--sub);margin-top:4px">${esc(m.created_at.slice(5, 16))}</div></div>`
          : `<div style="align-self:flex-end;max-width:78%;text-align:right">
               <div class="bubble" style="max-width:none;background:#E7F0FB;text-align:left">${esc(m.body)}</div>
               <div style="font-size:11px;color:var(--sub);margin-top:4px">${esc(m.created_at.slice(5, 16))} · ${m.via === 'app' ? `<span class="chip c-warn" style="height:17px;font-size:10px">${T('via Phone App', '手机 App 回复')}</span>` : esc(m.sender_name || '')}</div></div>`).join('')
          || `<div class="loading">${T('No messages', '暂无消息')}</div>`}
        <div style="align-self:center;font-size:11.5px;color:var(--sub);background:#EEF2F7;padding:4px 12px;border-radius:99px">
          ${data.window_open ? T('24-hour service window open · free-form replies allowed', '24 小时客服窗口开启 · 可自由回复')
                             : T('Window closed · approved template only', '窗口已关闭 · 只能发送已审模板')}
        </div>
      </div>
    </div>
    <div style="border-top:1px solid var(--line);padding:12px 20px;background:#fff">
      ${draft ? `<div class="ai-draft">
        <div class="hd">AI 草稿 <span>${draft.top_score == null ? '无知识依据' : '置信度 ' + Number(draft.top_score).toFixed(2)}</span></div>
        <div class="bd">${esc(draft.content)}</div>
        <div class="acts">
          <span class="btn sm" onclick="dismissAIDraft(${draft.id})">丢弃</span>
          <span class="btn sm gold" onclick="acceptAIDraft(${draft.id})">采用并发送</span>
        </div></div>` : ''}
      ${replyBlock}
    </div>`;
  renderConvSide(c, data.items);
}

window.toggleConvSide = () => {
  CONV_SIDE_OPEN = !CONV_SIDE_OPEN;
  localStorage.setItem('convSideOpen', CONV_SIDE_OPEN ? '1' : '0');
  const el = $('convSide'); if (el) el.classList.toggle('hidden', !CONV_SIDE_OPEN);
  if (SEL_CONV) renderConv(SEL_CONV);
};

async function renderConvSide(c, messages) {
  const el = $('convSide'); if (!el) return;
  if (!CONV_SIDE_OPEN) { el.innerHTML = ''; return; }
  if (!CACHE.aiIns) { try { CACHE.aiIns = await api('/api/ai/insights'); } catch (e) { CACHE.aiIns = null; } }
  let contact = null;
  try { contact = await api(`/api/conversations/${c.id}/contact-card`); } catch (e) { contact = null; }
  const d = contact || c;
  const ai = CACHE.aiIns ? aiInsightOf(d) : null;
  const tags = (contact && contact.tags) || [];
  const money = contact && contact.deal_value != null ? '$' + Number(contact.deal_value).toLocaleString() : '—';
  const list = (messages || []).slice(-6).reverse();
  el.innerHTML = `
    <div class="side-hd"><b>${T('Customer profile', '客户档案')}</b><span onclick="toggleConvSide()" title="${T('Collapse', '收起')}">×</span></div>
    <div class="side-body">
      <div class="side-name"><div class="avatar">${esc((d.name || c.contact_name || '?')[0])}</div>
        <div><div class="nm">${esc(d.name || c.contact_name)}</div>
          <div class="sub">${esc(d.country || c.country || '')} · ${esc(d.source || '')}</div></div></div>
      ${ai ? `<div class="side-ai"><span class="chip ${ai.cls}">${esc(ai.status)}</span>
        <div class="s">${esc(ai.summary)}</div><div class="n"><b>${T('Next step', '下一步')}：</b>${esc(ai.next)}</div></div>` : ''}
      <dl class="dl side-dl">
        <dt>WhatsApp</dt><dd class="mono">${esc(d.phone || c.phone || '')}</dd>
        <dt>${T('Opt-in', '授权')}</dt><dd>${contact && contact.opt_out ? `<span class="chip c-bad">${T("Opted out", "已退订")}</span>` : `<span class="chip c-ok">${T("Opted in", "已授权")}</span>`}</dd>
        <dt>${T('Segment', '所在分层')}</dt><dd>${contact ? segName(contact.segment) : '—'}</dd>
        <dt>${T('Deal status', '成交状态')}</dt><dd>${chipDeal(d.deal_status || c.deal_status)}</dd>
        ${ME.role === 'agent' ? '' : `<dt>${T('Deal value', '成交金额')}</dt><dd>${money}</dd>`}
        <dt>${T('Owner', '负责人')}</dt><dd>${d.owner_name ? '👤 ' + esc(d.owner_name) : `<span style="color:#B26B00">${T('No owner · in pool', '无主 · 在公海')}</span>`}</dd>
      </dl>
      <div class="side-sec"><div class="sec-hd">${T('Tags', '标签')}</div>
        <div class="side-tags">${tags.map(t => `<span class="chip c-info">${esc(t.name)}</span>`).join('') || `<span class="sub">${T('No tags', '无标签')}</span>`}
          ${contact && !contact.limited ? `<span class="chip c-gray" style="cursor:pointer" onclick="tagPicker(${d.id})">＋ ${T('Add', '添加')}</span>` : ''}</div>
      </div>
      <div class="side-sec"><div class="sec-hd">${T('Recent activity', '最近沟通')} <small>${list.length} ${T('messages', '条')}</small></div>
        <div class="timeline">${list.map(m => `<div class="tl">
          <span class="dot ${m.direction === 'in' ? 'in' : 'out'}"></span>
          <div><div class="who">${m.direction === 'in' ? T('Customer', '客户') : (m.via === 'ai' ? 'AI' : T('Us', '我方'))} · ${esc((m.created_at || '').slice(5, 16))}</div>
            <div class="txt">${esc(m.body)}</div></div></div>`).join('') || `<div class="sub">${T('No messages', '暂无消息')}</div>`}
        </div>
      </div>
      <div style="margin-top:12px"><span class="btn sm" onclick="openContact(${c.contact_id})">${T('Open full profile', '打开完整档案')}</span></div>
    </div>`;
  applyAITranslations(el);
}

window.toggleConvAI = async (id, current) => {
  try {
    await api(`/api/conversations/${id}/ai`, { method: 'POST', body: JSON.stringify({ enabled: !current }) });
    toast(!current ? 'AI 托管已开启' : 'AI 托管已关闭，改为人工');
    viewInbox();
  } catch (e) { toast(e.message); }
};
window.acceptAIDraft = async (did) => {
  try {
    await api(`/api/ai-drafts/${did}/accept`, { method: 'POST', body: '{}' });
    toast('已采用 AI 草稿并发出'); viewInbox();
  } catch (e) { toast(e.message); }
};
window.dismissAIDraft = async (did) => {
  try {
    await api(`/api/ai-drafts/${did}/dismiss`, { method: 'POST', body: '{}' });
    toast('已丢弃'); viewInbox();
  } catch (e) { toast(e.message); }
};
window.claimConv = async (id) => {
  try { await api(`/api/conversations/${id}/claim`, { method: 'POST', body: '{}' });
    toast(T('Claimed — you can reply now', '已认领，现在可以回复了')); viewInbox();
  } catch (e) {
    toast(e.message === 'already_owned' ? T('Someone already claimed it', '已经有人认领了') : e.message);
  }
};
window.assignConv = async (id, uid) => {
  await api(`/api/conversations/${id}/assign`, { method: 'POST', body: JSON.stringify({ owner_id: uid ? +uid : null }) });
  toast(T('Assigned', '已分配')); viewInbox();
};
window.sendMsg = async (id) => {
  const box = $('replyBox'); const body = box.value.trim();
  if (!body) return;
  try {
    await api(`/api/conversations/${id}/messages`, { method: 'POST', body: JSON.stringify({ body }) });
    box.value = ''; renderConv(id);
  } catch (e) {
    const m = e.message || '';
    toast(m === 'not_owner' ? T('Only the owner of this conversation can reply', '这条会话只有负责人能回复')
      : m === 'read_only' ? T('Your account is read-only', '你的账号是只读账号')
      : m);
  }
};
window.aiDraft = async (id) => {
  const box = $('replyBox');
  box.value = T('Hi, thanks for your message. Let me check the lead time and send you the spec sheet today.',
                '您好，感谢来信。我确认一下交期，今天把规格书发您。');
  box.focus();
};

/* ---------------- 客户池 ---------------- */
let CONTACT_KW = '', CONTACT_PAGE = 0, PAGE_SIZE = 20, CONTACT_OWNER = 0, CONTACT_DEAL = '';
let CF = { tag: 0, country: '', source: '', opt: '', sort: '' }, CF_OPEN = false;
let CONTACT_SEG = 0, CONTACT_SEG_NAME = '';
let CF_FACETS = null;

async function viewContacts() {
  const qs = `view=${CUR_VIEW}&kw=${encodeURIComponent(CONTACT_KW)}&limit=${PAGE_SIZE}&offset=${CONTACT_PAGE * PAGE_SIZE}`
           + (CONTACT_OWNER ? `&owner=${CONTACT_OWNER}` : '') + (CONTACT_DEAL ? `&deal=${encodeURIComponent(CONTACT_DEAL)}` : '')
           + (CF.tag ? `&tag=${CF.tag}` : '') + (CF.country ? `&country=${encodeURIComponent(CF.country)}` : '')
           + (CF.source ? `&source=${encodeURIComponent(CF.source)}` : '') + (CF.opt ? `&opt=${CF.opt}` : '')
           + (CF.sort ? `&sort=${CF.sort}` : '') + (CONTACT_SEG ? `&seg=${CONTACT_SEG}` : '');
  const [{ items, total }, tagRes, facets] = await Promise.all([
    api('/api/contacts?' + qs), api('/api/tags'),
    CF_OPEN ? api('/api/segments/facets') : Promise.resolve(CF_FACETS || { tags: [], countries: [], sources: [] })]);
  if (CF_OPEN) CF_FACETS = facets;
  CACHE.tags = tagRes.items;
  if (!CACHE.aiIns) { try { CACHE.aiIns = await api('/api/ai/insights'); } catch (e) { CACHE.aiIns = null; } }
  if (CONTACT_OWNER && !CACHE.users && ME.role !== 'agent') CACHE.users = (await api('/api/users')).items;
  CACHE.contactTotal = total;
  $('hTitle').textContent = T('Contacts', '客户池');
  $('hSub').textContent = T('All contacts', '全部联系人') + ` · ${items.length}`;
  if (!SEL_CONTACT || !items.find(c => c.id === SEL_CONTACT)) SEL_CONTACT = items[0] ? items[0].id : null;
  const sel = items.find(c => c.id === SEL_CONTACT) || items[0];
  const views = [['all', T('All', '全部')], ['active', T('Active', '活跃')], ['dormant', T('Dormant', '沉默')],
                 ['won', T('Won', '已成交')], ['untagged', T('Untagged', '未打标')], ['pool', T('Pool', '公海')]];
  const counts = await Promise.all(views.map(v => api('/api/contacts?view=' + v[0]).then(r => r.total)));

  $('body').innerHTML = `
    <div class="col-list">
      ${CONTACT_SEG ? `<div style="padding:10px 14px;background:#EEF4FF;border-bottom:1px solid #CFDDF5;font-size:12.5px;color:#1B3A5C;display:flex;justify-content:space-between;align-items:center">
        <span>${T('Segment', '分层')}: <b>${esc(CONTACT_SEG_NAME || '#' + CONTACT_SEG)}</b></span>
        <span style="cursor:pointer;font-weight:700" onclick="clearSegFilter()">× ${T('Clear', '清除')}</span></div>` : ''}
      ${(CONTACT_OWNER || CONTACT_DEAL) ? `<div style="padding:10px 14px;background:#FFF8E6;border-bottom:1px solid #F3E0AE;font-size:12.5px;color:#7A5B00;display:flex;justify-content:space-between;align-items:center">
        <span>${T('Filtered by', '筛选')}: ${[CONTACT_OWNER ? esc((CACHE.users || []).find(u => u.id === CONTACT_OWNER)?.name || '#' + CONTACT_OWNER) : '', CONTACT_DEAL ? chipDeal(CONTACT_DEAL) : ''].filter(Boolean).join(' · ')}</span>
        <span style="cursor:pointer;font-weight:700" onclick="clearContactFilter()">× ${T('Clear', '清除')}</span></div>` : ''}
      ${ME.role !== 'agent' ? `<div style="padding:8px 14px;background:#EEF7F0;border-bottom:1px solid #D6EBDC;font-size:11.5px;color:#2E6B45">
        ${T('To hand a contact to a colleague: click the 👤 name (or "assign") on the row, or open the contact and use the Owner dropdown.', '要把客户交给同事：点这一行的 👤 名字（或「分配」），或点开客户在「负责人」下拉里选。')}</div>` : ''}
      <div class="toolbar">
        <input class="searchbox" style="width:100%;border:1px solid var(--line)" id="cSearch"
          placeholder="🔍 ${T('Search name, number, country', '搜索姓名、号码、国家')}"
          value="${esc(CONTACT_KW)}" oninput="searchContacts(this.value)">
        <div class="tabs">${views.map((v, i) =>
          `<span class="tab ${CUR_VIEW === v[0] ? 'on' : ''}" onclick="setView('${v[0]}')">${v[1]} <span style="opacity:.55">${counts[i]}</span></span>`).join('')}</div>
        <div class="tabs">
          <span class="tab ${CF_OPEN ? 'on' : ''}" onclick="cfToggle()">⚙ ${T('Filters', '筛选')}${
            cfActive() ? ` <span style="opacity:.7">${cfActive()}</span>` : ''}</span>
          ${cfActive() ? `<span class="tab" onclick="cfClear()" style="color:var(--red)">× ${T('Clear', '清除')}</span>` : ''}
        </div>
        ${CF_OPEN ? `<div class="cfpanel">
          <div class="cfrow"><label>${T('Tag', '标签')}</label>
            <select onchange="cfSet('tag', this.value)">
              <option value="0">${T('Any', '不限')}</option>
              ${(facets.tags || []).map(t => `<option value="${t.id}" ${CF.tag === t.id ? 'selected' : ''}>${esc(t.name)} (${t.n})</option>`).join('')}
            </select></div>
          <div class="cfrow"><label>${T('Country', '国家')}</label>
            <select onchange="cfSet('country', this.value)">
              <option value="">${T('Any', '不限')}</option>
              ${(facets.countries || []).map(c => `<option value="${esc(c)}" ${CF.country === c ? 'selected' : ''}>${esc(c)}</option>`).join('')}
            </select></div>
          <div class="cfrow"><label>${T('Source', '来源')}</label>
            <select onchange="cfSet('source', this.value)">
              <option value="">${T('Any', '不限')}</option>
              ${(facets.sources || []).map(c => `<option value="${esc(c)}" ${CF.source === c ? 'selected' : ''}>${esc(c)}</option>`).join('')}
            </select></div>
          <div class="cfrow"><label>${T('Opt-in', '授权')}</label>
            <select onchange="cfSet('opt', this.value)">
              <option value="">${T('Any', '不限')}</option>
              <option value="in" ${CF.opt === 'in' ? 'selected' : ''}>${T('Opted in only', '只要已授权')}</option>
              <option value="out" ${CF.opt === 'out' ? 'selected' : ''}>${T('Opted out only', '只要已退订')}</option>
            </select></div>
          <div class="cfrow"><label>${T('Sort', '排序')}</label>
            <select onchange="cfSet('sort', this.value)">
              <option value="">${T('Default', '默认')}</option>
              <option value="newest" ${CF.sort === 'newest' ? 'selected' : ''}>${T('Recently contacted', '最近联系优先')}</option>
              <option value="oldest" ${CF.sort === 'oldest' ? 'selected' : ''}>${T('Longest untouched', '最久未联系优先')}</option>
              <option value="created" ${CF.sort === 'created' ? 'selected' : ''}>${T('Newest added', '最新加入优先')}</option>
            </select></div>
        </div>` : ''}
      </div>
      ${items.map(c => `
        <div class="row ${sel && c.id === sel.id ? 'on' : ''}" onclick="openContact(${c.id})">
          <div class="avatar">${esc(c.name[0])}</div>
          <div style="min-width:0;flex:1">
            <div class="nm">${esc(c.name)} <span class="src">${esc(c.source || '')}</span></div>
            <div class="mt">${esc(c.country || '')} · ${esc((c.tags || []).map(t => t.name).join(', ') || T('no tags', '无标签'))}
              · ${ME.role === 'agent'
                ? (c.owner_name ? '👤 ' + esc(c.owner_name) : `<span style="color:#B26B00;font-weight:600">${T('no owner', '无主')}</span>`)
                : `<span style="color:var(--blue);font-weight:600;cursor:pointer" onclick="event.stopPropagation();assignPicker(${c.id})">👤 ${c.owner_name ? esc(c.owner_name) : T('assign', '分配')} ▾</span>`}</div>
          </div>
          <div style="text-align:right;flex:none">${chipDeal(c.deal_status)}
            <div style="font-size:11px;color:#8794A3;margin-top:4px">${esc((c.last_contact_at || '').slice(0, 10))}</div></div>
        </div>`).join('') || `<div class="loading">${T('No contacts in this view', '这个视图里没有客户')}</div>`}
    </div>
    <div class="col-main" id="contactPane"></div>`;
  const pager = document.createElement('div');
  pager.style.cssText = 'position:absolute;left:0;right:0;bottom:0;display:flex;justify-content:center;gap:8px;padding:10px;background:#fff;border-top:1px solid var(--line)';
  pager.innerHTML = total > PAGE_SIZE
    ? `<span class="btn sm" onclick="pageContacts(-1)">← ${T('Prev', '上一页')}</span>
       <span style="font-size:12.5px;color:var(--sub);align-self:center">${CONTACT_PAGE + 1} / ${Math.ceil(total / PAGE_SIZE)} · ${total} ${T('total', '人')}</span>
       <span class="btn sm" onclick="pageContacts(1)">${T('Next', '下一页')} →</span>`
    : `<span style="font-size:12.5px;color:var(--sub)">${total} ${T('contacts', '人')}</span>`;
  const list = document.querySelector('.col-list');
  if (list) list.appendChild(pager);
  if (sel) await renderContact(sel.id);
  else { const pane = $('contactPane'); if (pane) pane.innerHTML = `<div class="loading">${T('No contacts in this view', '这个视图里没有客户')}</div>`; }
}

window.setView = (v) => { CUR_VIEW = v; CONTACT_PAGE = 0; SEL_CONTACT = null; viewContacts(); };
const cfActive = () => ['tag', 'country', 'source', 'opt', 'sort'].filter(k => CF[k]).length;
window.cfToggle = () => { CF_OPEN = !CF_OPEN; viewContacts(); };
window.cfSet = (k, v) => { CF[k] = k === 'tag' ? +v : v; CONTACT_PAGE = 0; viewContacts(); };
window.cfClear = () => { CF = { tag: 0, country: '', source: '', opt: '', sort: '' }; CONTACT_PAGE = 0; viewContacts(); };
let SEARCH_T = null;
window.searchContacts = (v) => { CONTACT_KW = v; CONTACT_PAGE = 0;
  clearTimeout(SEARCH_T); SEARCH_T = setTimeout(() => viewContacts(), 300); };
window.clearContactFilter = () => { CONTACT_OWNER = 0; CONTACT_DEAL = ''; CONTACT_PAGE = 0; viewContacts(); };
window.openContactsByOwner = (id) => { CONTACT_OWNER = id; CONTACT_DEAL = ''; CONTACT_PAGE = 0; CF = { tag: 0, country: '', source: '', opt: '', sort: '' }; go('contacts'); };
window.openContactsByDeal = (key) => { CONTACT_DEAL = key; CONTACT_OWNER = 0; CONTACT_PAGE = 0; go('contacts'); };
window.pageContacts = (d) => {
  const max = Math.max(0, Math.ceil((CACHE.contactTotal || 0) / PAGE_SIZE) - 1);
  CONTACT_PAGE = Math.min(max, Math.max(0, CONTACT_PAGE + d));
  viewContacts();
};
window.openContact = (id) => { SEL_CONTACT = id; viewContacts(); };
window.openContactConversation = async (cid) => {
  try {
    const { items } = await api('/api/conversations');
    const conv = items.find(x => x.contact_id === cid);
    if (!conv) return toast(T('This contact has no conversation yet', '这个客户还没有会话'));
    SEL_CONV = conv.id; INBOX_TAB = 'open'; INBOX_OWNER = 0; INBOX_NUMBER = 0;
    await go('inbox');
  } catch (e) { toast(e.message); }
};

window.assignPicker = async (cid) => {
  if (ME.role === 'agent') return;
  if (!CACHE.users) CACHE.users = (await api('/api/users')).items;
  const c = await api('/api/contacts/' + cid);
  const users = (CACHE.users || []).filter(u => u.active !== 0);
  $('modal').innerHTML = `
    <h2>${T('Assign this contact', '把客户分配给谁')}</h2>
    <p class="s">${esc(c.name)} · ${esc(c.country || '')}</p>
    <div style="display:flex;flex-direction:column;gap:8px;max-height:320px;overflow:auto">
      <span class="btn ${!c.owner_id ? 'gold' : ''}" style="justify-content:flex-start" onclick="pickOwner(${cid}, '')">
        ${T('Nobody — put back in the public pool', '不指定 — 放回公海')}</span>
      ${users.map(u => `<span class="btn ${u.id === c.owner_id ? 'gold' : ''}" style="justify-content:flex-start"
        onclick="pickOwner(${cid}, ${u.id})">${esc(u.name)} · ${roleName(u.role)}
        <span style="margin-left:auto;color:var(--sub);font-size:11.5px">${u.contacts != null ? u.contacts + ' ' + T('contacts', '个客户') : ''}</span></span>`).join('')}
    </div>
    <div class="acts"><span class="btn" onclick="closeModal()">${T('Cancel', '取消')}</span></div>`;
  $('mask').classList.add('on');
};
window.pickOwner = async (cid, uid) => {
  closeModal();
  await assignContact(cid, uid);
};
window.assignContact = async (cid, uid) => {
  try {
    const r = await api(`/api/contacts/${cid}/assign`, { method: 'POST', body: JSON.stringify({ user_id: uid ? +uid : null }) });
    toast(r.owner_id ? T(`Assigned to ${r.owner_name}`, `已分配给 ${r.owner_name}`) : T('Sent back to the public pool', '已放回公海'));
    CACHE.users = null; viewContacts();
  } catch (e) { toast(e.message); }
};

async function renderContact(id) {
  const c = await api('/api/contacts/' + id);
  if (!CACHE.aiIns) { try { CACHE.aiIns = await api('/api/ai/insights'); } catch (e) { CACHE.aiIns = null; } }
  const pane = $('contactPane'); if (!pane) return;
  if (ME.role !== 'agent' && !CACHE.users) CACHE.users = (await api('/api/users')).items;
  const users = CACHE.users || [];
  const tags = CACHE.tags || [];
  pane.innerHTML = `
    <div style="display:flex;align-items:center;gap:14px;margin-bottom:16px">
      <div class="avatar" style="width:52px;height:52px;font-size:20px">${esc(c.name[0])}</div>
      <div><div style="font-size:19px;font-weight:800">${esc(c.name)}</div>
        <div style="color:var(--sub);font-size:12.5px">${esc(c.country || '')} · ${esc(c.source || '')} · ${T('Last contact', '最后联系')} ${esc((c.last_contact_at || '').slice(0, 10))}</div></div>
      <div style="margin-left:auto;display:flex;gap:8px;align-items:center">
        <span class="btn" onclick="openContactConversation(${c.id})">${T('Open conversation', '进入会话')}</span>
        ${chipDeal(c.deal_status)}
        ${!c.owner_id
          ? `<span class="btn gold" onclick="claimFromDetail(${c.id})">${T('Claim', '领取')}</span>`
          : `<span class="btn" onclick="releaseContact(${c.id})">${T('Release to pool', '放回公海')}</span>`}
        <span class="btn" onclick="toggleOptOut(${c.id}, ${c.opt_out ? 1 : 0})">${c.opt_out ? T('Restore opt-in', '恢复授权') : T('Mark opt-out', '标记退订')}</span>
        <span class="btn" onclick="openDeal(${c.id})">${T('Update status', '更新状态')}</span>
      </div>
    </div>
    ${CACHE.aiIns ? (() => {
      const ai = aiInsightOf(c);
      return `<div class="card" style="margin-bottom:14px"><h3>AI 洞察 <small>按规则实时判断</small></h3>
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <span class="chip ${ai.cls}">${esc(ai.status)}</span>
          ${(ai.tags||[]).map(t => `<span class="chip c-info">${esc(t)}</span>`).join('')}
          <span style="font-size:12px;color:var(--sub)">${esc(ai.summary)}</span>
        </div>
        <div style="margin-top:6px;font-size:12.5px;color:#33475C"><b>${T('Next step', '下一步')}：</b>${esc(ai.next)}</div>
      </div>`;
    })() : ''}
    <div class="grid2">
      <div class="card"><h3>${T('Profile', '客户档案')}</h3>
        <dl class="dl">
          <dt>WhatsApp</dt><dd class="mono">${esc(c.phone)}</dd>
          <dt>${T('Source', '来源')}</dt><dd>${esc(c.source || '')} ${esc(c.source_detail || '')}</dd>
          <dt>${T('Opt-in', '授权时间')}</dt><dd>${esc(c.opt_in_at || '—')}</dd>
          <dt>${T('Segment', '所在分层')}</dt><dd>${segName(c.segment)}</dd>
          <dt>${T('Opt-in status', '授权状态')}</dt><dd>${c.opt_out
            ? `<span class="chip c-bad">${T('Opted out', '已退订')}</span>`
            : `<span class="chip c-ok">${T('Opted in', '已授权')}</span>`}</dd>
          <dt>${T('Deal value', '成交金额')}</dt><dd>${ME.role === 'agent' ? T('hidden by permission', '无权限查看') : (c.deal_value == null ? '—' : '$' + Number(c.deal_value).toLocaleString())}</dd>
          <dt>${T('Owner', '负责人')}</dt><dd>${ME.role === 'agent'
            ? (c.owner_name ? esc(c.owner_name) : `<span class="chip c-warn">${T('In public pool', '在公海')}</span>`)
            : `<select class="inp" style="height:30px;padding:0 8px" onchange="assignContact(${c.id}, this.value)">
                 <option value="">${T('Unassigned — public pool', '未分配 — 放公海')}</option>
                 ${users.filter(u => u.active !== 0).map(u => `<option value="${u.id}" ${u.id === c.owner_id ? 'selected' : ''}>${esc(u.name)} · ${roleName(u.role)}</option>`).join('')}
               </select>`}</dd>
        </dl>
      </div>
      <div class="card"><h3>${T('Tags', '标签')}</h3>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
          ${(c.tags || []).map(t => `<span class="chip c-info">${esc(t.name)} <span style="opacity:.55;margin-left:3px;cursor:pointer" onclick="removeTag(${c.id},${t.id})">×</span></span>`).join('')}
          <span class="chip c-gray" style="cursor:pointer" onclick="tagPicker(${c.id})">＋ ${T('Add tag', '添加标签')}</span>
        </div>
        <div class="hr"></div>
        <div style="font-size:12.5px;color:var(--sub);line-height:1.9">
          ${T('Deal status is logged by your team — the system never guesses it.', '成交状态由团队人工标记，系统不做猜测。')}
        </div>
      </div>
    </div>
    <div class="card" style="margin-top:14px"><h3>${T('Recent activity', '最近沟通')}</h3>
      <table><thead><tr><th style="width:120px">${T('Time', '时间')}</th><th style="width:90px">${T('Direction', '方向')}</th><th>${T('Message', '内容')}</th></tr></thead>
      <tbody>${(c.messages || []).map(m => `<tr><td class="mono">${esc(m.created_at.slice(5, 16))}</td>
        <td><span class="chip ${m.direction === 'in' ? 'c-ok' : 'c-info'}">${m.direction === 'in' ? T('Inbound', '客户') : T('Outbound', '我方')}</span></td>
        <td>${esc(m.body)}</td></tr>`).join('') || `<tr><td colspan="3" style="color:var(--sub)">${T('No messages yet', '暂无消息')}</td></tr>`}</tbody></table>
    </div>`;
}

window.removeTag = async (cid, tid) => {
  const c = await api('/api/contacts/' + cid);
  const ids = (c.tags || []).filter(t => t.id !== tid).map(t => t.id);
  await api('/api/contacts/' + cid, { method: 'PATCH', body: JSON.stringify({ tags: ids }) });
  viewContacts();
};
window.addTag = async (cid, val) => {
  if (!val) return;
  let tid = val;
  if (val === '__new') {
    const name = prompt(T('New tag name:', '新标签名称：'));
    if (!name) return;
    const t = await api('/api/tags', { method: 'POST', body: JSON.stringify({ name }) });
    tid = t.id;
  }
  const c = await api('/api/contacts/' + cid);
  const ids = [...(c.tags || []).map(t => t.id), +tid];
  await api('/api/contacts/' + cid, { method: 'PATCH', body: JSON.stringify({ tags: ids }) });
  viewContacts();
};

/* ---------------- 成交状态弹窗 ---------------- */
window.openDeal = async (cid) => {
  const c = await api('/api/contacts/' + cid);
  $('modal').innerHTML = `
    <h2>${T('Update status', '更新状态')}</h2>
    <p class="s">${T('WhatsApp cannot see what closes offline. Your team logs it here.', 'WhatsApp 看不到线下成交，这一步由团队人工记录。')}</p>
    <div class="field"><label>${T('Contact', '客户')}</label><div class="inp">${esc(c.name)}</div></div>
    <div class="grid2">
      <div class="field"><label>${T('Status', '状态')}</label>
        <select id="dealStatus" class="inp" style="width:100%">
          ${['Lead','Contacted','Negotiating','Won','Lost'].map(s => `<option value="${s}" ${c.deal_status === s ? 'selected' : ''}>${s}</option>`).join('')}
        </select></div>
      <div class="field"><label>${T('Deal value (optional)', '成交金额（可选）')}</label>
        <input id="dealValue" class="inp" style="width:100%" value="${c.deal_value ?? ''}" ${ME.role === 'agent' ? 'disabled' : ''}></div>
    </div>
    <div class="field"><label>${T('Note (optional)', '备注（可选）')}</label><input id="dealNote" class="inp" style="width:100%" value="${esc(c.note || '')}"></div>
    <div class="acts"><span class="btn" onclick="closeDeal()">${T('Cancel', '取消')}</span>
      <span class="btn gold" onclick="saveDeal(${cid})">${T('Save', '保存')}</span></div>`;
  $('mask').classList.add('on');
};
window.closeDeal = () => { $('mask').classList.remove('on'); $('modal').classList.remove('wide'); };
window.closeModal = window.closeDeal;
$('mask').onclick = (e) => { if (e.target.id === 'mask') closeDeal(); };
window.saveDeal = async (cid) => {
  const body = { deal_status: $('dealStatus').value, note: $('dealNote').value };
  if (ME.role !== 'agent') { const v = $('dealValue').value; body.deal_value = v === '' ? null : Number(v); }
  try {
    await api('/api/contacts/' + cid, { method: 'PATCH', body: JSON.stringify(body) });
    closeDeal(); toast(T('Saved', '已保存'));
    CUR === 'contacts' ? viewContacts() : viewInbox();
  } catch (e) { toast(e.message); }
};

/* ---------------- 分层 ---------------- */
let CUR_SEG = null;

const tagNameOf = (id) => ((CACHE.segFacets && CACHE.segFacets.tags) || CACHE.tags || []).find(t => t.id === id)?.name || '#' + id;
function segRuleText(rule) {
  if (rule.type) return ruleText(rule);
  const out = [];
  if ((rule.tags || []).length) out.push(T('Tags', '标签') + ': ' + rule.tags.map(tagNameOf).join(' / '));
  if ((rule.countries || []).length) out.push(rule.countries.join(' / '));
  if ((rule.sources || []).length) out.push(rule.sources.join(' / '));
  if ((rule.deal_status || []).length) out.push(rule.deal_status.map(k => { const st = stageOf(k); return T(st.en, st.zh); }).join(' / '));
  if (rule.opt === 'in') out.push(T('opt-in only', '只要已授权'));
  if (rule.opt === 'out') out.push(T('opted out only', '只要已退订'));
  if (rule.pool === 'in') out.push(T('in pool only', '只在公海'));
  if (rule.pool === 'owned') out.push(T('owner assigned', '已有负责人'));
  if (rule.last_contact && rule.last_contact.days) out.push(T('last contact ', '最后联系 ') +
    (rule.last_contact.op === 'lte' ? T('within ', '在 ') : T('over ', '超过 ')) + rule.last_contact.days + T(' days', ' 天'));
  return out.join(' · ') || T('no conditions', '没有条件');
}
const ruleText = (r) => ({ active: T('Contacted in the last 30 days', '30 天内有联系'),
  d30: T('Last contact 30–89 days ago', '最后联系 30–89 天'), d90: T('Last contact 90–179 days ago', '最后联系 90–179 天'),
  d180: T('No contact for 180+ days', '180 天以上未联系') }[r.type] || T('Custom rule', '自定义规则'));

async function viewSegments() {
  const [{ items }, facets] = await Promise.all([api('/api/segments'), api('/api/segments/facets')]);
  CACHE.segFacets = facets; CACHE.segList = items;
  if (!items.length) { $('body').innerHTML = `<div class="col-main"><div class="loading">${T('No segments yet', '还没有分层')}</div></div>`; return; }
  const on = items.find(x => x.id === CUR_SEG) || items[0];
  CUR_SEG = on.id;
  $('hTitle').textContent = T('Segments', '客户分层');
  $('hSub').textContent = T('Built-in behaviour groups + your own rules · recalculated live', '系统自带的行为分组 + 你自己定的规则 · 实时计算');
  const canEdit = ME.role === 'owner' || ME.role === 'manager';
  $('body').innerHTML = `
    <div class="col-list">
      <div class="toolbar" style="flex-direction:row;align-items:center">
        <div style="font-size:12.5px;color:var(--sub);font-weight:700;flex:1">${T('All segments', '全部分层')} · ${items.length}</div>
        ${canEdit ? `<span class="btn sm gold" onclick="openSegEditor()">＋ ${T('New segment', '新建分层')}</span>` : ''}
      </div>
      <div style="overflow:auto;flex:1">
        ${items.map(s => `<div class="seg ${s.id === on.id ? 'on' : ''}" onclick="pickSeg(${s.id})">
          <div style="min-width:0"><div class="n">${esc(s.name)} ${s.is_system ? '' : `<span style="font-size:10px;color:var(--blue);font-weight:700">${T('custom', '自定义')}</span>`}</div>
            <div class="d">${segRuleText(s.rule)}</div></div>
          <div class="v">${s.matched}<small>${T('ppl', '人')}</small></div></div>`).join('')}
      </div>
    </div>
    <div class="col-main">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px">
        <div style="font-size:18px;font-weight:800">${esc(on.name)}</div>
        ${on.is_system ? `<span class="chip c-gray">${T('built-in', '系统自带')}</span>` : `<span class="chip c-info">${T('custom', '自定义')}</span>`}
        <div style="margin-left:auto;display:flex;gap:8px">
          <span class="btn sm" onclick="openSegmentContacts(${on.id})">${T('Open in contacts', '去客户池看')}</span>
          ${canEdit && !on.is_system ? `<span class="btn sm" onclick="openSegEditor(${on.id})">${T('Edit', '编辑')}</span>
            <span class="btn sm" onclick="deleteSeg(${on.id})">${T('Delete', '删除')}</span>` : ''}
        </div>
      </div>
      <div class="kpis" style="grid-template-columns:repeat(5,1fr)">
        <div class="kpi"><div class="k">${T('Matched', '命中')}</div><div class="v">${on.matched}</div><div class="d">${T('contacts', '人')}</div></div>
        <div class="kpi"><div class="k">${T('Sendable', '可发送')}</div><div class="v" style="color:var(--green)">${on.sendable}</div><div class="d">${T('valid opt-in', '有有效授权')}</div></div>
        <div class="kpi"><div class="k">${T('Opted out', '已退订')}</div><div class="v" style="color:var(--sub)">${on.opted_out}</div><div class="d">${T('excluded automatically', '发送时自动排除')}</div></div>
        <div class="kpi"><div class="k">${T('Won', '已成交')}</div><div class="v">${on.won}</div><div class="d">${T('logged manually', '人工标记')}</div></div>
        <div class="kpi"><div class="k">${T('Revenue', '成交金额')}</div><div class="v">$${Number(on.revenue || 0).toLocaleString()}</div><div class="d">${T('from won deals', '来自已成交')}</div></div>
      </div>
      <div class="card"><h3>${T('Rule', '规则')}</h3>
        <div style="font-size:13px;line-height:1.9;color:#33475C">${esc(segRuleText(on.rule))}</div>
        <div class="note" style="margin-top:10px">${T(
          'Segments are computed every time you open the page — nobody has to maintain a static list.',
          '分层是每次打开页面实时算出来的，不需要有人去维护名单。')}</div>
      </div>
      <div class="card" style="margin-top:14px"><h3>${T('Who is in this segment', '这一层里都有谁')}<small>${T('first 300', '最多 300 条')}</small></h3>
        <div id="segPeople" class="loading">${T('Loading…', '加载中…')}</div>
      </div>
    </div>`;
  const { items: people, total } = await api(`/api/segments/${on.id}/contacts?limit=300`);
  const holder = $('segPeople');
  if (!holder) return;
  holder.outerHTML = `<table><thead><tr><th>${T('Contact', '客户')}</th><th>${T('Country', '国家')}</th>
    <th>${T('Owner', '负责人')}</th><th>${T('Tags', '标签')}</th><th>${T('Deal', '状态')}</th><th>${T('Last contact', '最后联系')}</th></tr></thead><tbody>
    ${people.map(c => `<tr><td><b>${esc(c.name)}</b></td><td>${esc(c.country || '')}</td>
      <td>${c.owner_name ? '👤 ' + esc(c.owner_name) : `<span style="color:#B26B00">${T('no owner', '无主')}</span>`}</td>
      <td>${(c.tags || []).map(t => `<span class="chip c-info" style="height:19px;font-size:10.5px">${esc(t.name)}</span>`).join(' ') || '—'}</td>
      <td>${chipDeal(c.deal_status)}</td><td class="mono">${esc((c.last_contact_at || '').slice(0, 10))}</td></tr>`).join('')}
    </tbody></table>${total > people.length ? `<div class="note" style="margin-top:10px">${T('Showing', '只显示')} ${people.length} / ${total}</div>` : ''}`;
}
window.pickSeg = (id) => { CUR_SEG = id; viewSegments(); };
window.openSegmentContacts = (id) => {
  CONTACT_SEG = id;
  CONTACT_SEG_NAME = (CACHE.segList || []).find(x => x.id === id)?.name || '';
  CUR_VIEW = 'all'; CONTACT_PAGE = 0;
  CF = { tag: 0, country: '', source: '', opt: '', sort: '' };
  go('contacts');
};
window.clearSegFilter = () => { CONTACT_SEG = 0; CONTACT_SEG_NAME = ''; CONTACT_PAGE = 0; viewContacts(); };

/* ---------- 新建 / 编辑分层 ---------- */
window.openSegEditor = async (id) => {
  const facets = CACHE.segFacets || await api('/api/segments/facets');
  CACHE.segFacets = facets;
  let cur = null;
  if (id) cur = (await api('/api/segments')).items.find(x => x.id === id);
  const rule = cur && !cur.rule.type ? cur.rule : {};
  const has = (dim, v) => (rule[dim] || []).includes(v);
  const chip = (dim, val, label) => `<label class="pick"><input type="checkbox" data-dim="${dim}" data-val="${esc(String(val))}" ${has(dim, val) ? 'checked' : ''}><span>${esc(label)}</span></label>`;
  $('modal').innerHTML = `
    <h2>${cur ? T('Edit segment', '编辑分层') : T('New segment', '新建分层')}</h2>
    <p class="s">${T('All conditions below are combined with AND. Values inside one group are OR.', '下面所有条件同时满足才命中；同一组里选多个是“或”。')}</p>
    <div class="field"><label>${T('Name', '分层名称')}</label>
      <input id="segName" class="inp" style="width:100%" value="${esc(cur ? cur.name : '')}" placeholder="${T('e.g. UAE website leads, no contact 30d', '例如：阿联酋网站线索 · 30 天未联系')}"></div>
    <span class="picklbl">${T('Tags', '标签')}</span>
    <div class="pickgrp">${(facets.tags || []).map(t => chip('tags', t.id, `${t.name} (${t.n})`)).join('') || `<span class="ln">${T('No tags', '没有标签')}</span>`}</div>
    <span class="picklbl">${T('Countries', '国家')}</span>
    <div class="pickgrp">${(facets.countries || []).map(c => chip('countries', c, c)).join('')}</div>
    <span class="picklbl">${T('Sources', '来源')}</span>
    <div class="pickgrp">${(facets.sources || []).map(c => chip('sources', c, c)).join('')}</div>
    <span class="picklbl">${T('Deal status', '成交状态')}</span>
    <div class="pickgrp">${(facets.deal_status || []).map(d => chip('deal_status', d.key, T(d.en, d.zh))).join('')}</div>
    <div class="grid2">
      <div class="field"><label>${T('Opt-in', '授权')}</label>
        <select id="segOpt" class="inp" style="width:100%">
          <option value="any" ${!rule.opt || rule.opt === 'any' ? 'selected' : ''}>${T('Any', '不限')}</option>
          <option value="in" ${rule.opt === 'in' ? 'selected' : ''}>${T('Opted in only', '只要已授权')}</option>
          <option value="out" ${rule.opt === 'out' ? 'selected' : ''}>${T('Opted out only', '只要已退订')}</option>
        </select></div>
      <div class="field"><label>${T('Owner', '归属')}</label>
        <select id="segPool" class="inp" style="width:100%">
          <option value="any" ${!rule.pool || rule.pool === 'any' ? 'selected' : ''}>${T('Any', '不限')}</option>
          <option value="in" ${rule.pool === 'in' ? 'selected' : ''}>${T('In public pool', '只在公海')}</option>
          <option value="owned" ${rule.pool === 'owned' ? 'selected' : ''}>${T('Has an owner', '已有负责人')}</option>
        </select></div>
    </div>
    <div class="field"><label>${T('Last contact', '最后联系')}</label>
      <div style="display:flex;gap:8px;align-items:center">
        <select id="segDaysOp" class="inp" style="width:120px">
          <option value="gte" ${(rule.last_contact || {}).op !== 'lte' ? 'selected' : ''}>${T('over N days ago', '超过 N 天没联系')}</option>
          <option value="lte" ${(rule.last_contact || {}).op === 'lte' ? 'selected' : ''}>${T('within N days', 'N 天内联系过')}</option>
        </select>
        <input id="segDays" class="inp" type="number" min="0" style="width:90px" value="${(rule.last_contact || {}).days || ''}" placeholder="30">
        <span style="font-size:12px;color:var(--sub)">${T('days', '天')}</span>
      </div></div>
    <div class="acts"><span class="btn" onclick="closeModal()">${T('Cancel', '取消')}</span>
      <span class="btn gold" onclick="saveSeg(${id || 0})">${T('Save', '保存')}</span></div>`;
  $('mask').classList.add('on');
};
window.saveSeg = async (id) => {
  const name = $('segName').value.trim();
  if (!name) return toast(T('Give it a name', '先起个名字'));
  const pick = (dim) => [...document.querySelectorAll(`input[data-dim="${dim}"]:checked`)].map(i => i.dataset.val);
  const rule = {
    tags: pick('tags').map(Number), countries: pick('countries'),
    sources: pick('sources'), deal_status: pick('deal_status'),
  };
  const opt = $('segOpt').value; if (opt !== 'any') rule.opt = opt;
  const pool = $('segPool').value; if (pool !== 'any') rule.pool = pool;
  const days = +$('segDays').value; if (days) rule.last_contact = { op: $('segDaysOp').value, days };
  const any = rule.tags.length || rule.countries.length || rule.sources.length ||
              rule.deal_status.length || rule.opt || rule.pool || rule.last_contact;
  if (!any) return toast(T('Pick at least one condition', '至少选一个条件'));
  try {
    if (id) await api(`/api/segments/${id}`, { method: 'PATCH', body: JSON.stringify({ name, rule }) });
    else { const r = await api('/api/segments', { method: 'POST', body: JSON.stringify({ name, rule }) }); CUR_SEG = r.id; }
    closeModal(); toast(T('Saved', '已保存')); viewSegments();
  } catch (e) { toast(e.message); }
};
window.deleteSeg = async (id) => {
  if (!confirm(T('Delete this segment? Contacts are not affected.', '删除这个分层？客户本身不受影响。'))) return;
  try { await api(`/api/segments/${id}`, { method: 'DELETE' }); CUR_SEG = null; toast(T('Deleted', '已删除')); viewSegments(); }
  catch (e) { toast(e.message); }
};

/* ---------------- 模板 ---------------- */
async function viewTemplates() {
  const { items } = await api('/api/templates');
  $('hTitle').textContent = T('Templates', '模板库');
  $('hSub').textContent = T('Only approved templates can be sent', '审核通过的模板才能发送');
  if (!CACHE.tpl || !items.find(t => t.id === CACHE.tpl)) CACHE.tpl = items[0] ? items[0].id : null;
  const sel = items.find(t => t.id === CACHE.tpl) || items[0];
  $('body').innerHTML = `
    <div class="col-list">
      <div class="toolbar"><div class="searchbox">🔍 ${T('Search templates', '搜索模板')}</div></div>
      ${items.map(t => `<div class="row ${sel && t.id === sel.id ? 'on' : ''}" onclick="pickTpl(${t.id})">
        <div style="min-width:0;flex:1"><div class="nm">${esc(t.name)}</div>
          <div class="mt">${esc(t.category)} · ${esc(t.language)}</div></div>
        <div style="flex:none">${chipTpl(t.status)}</div></div>`).join('')}
    </div>
    <div class="col-main">
      ${sel ? `
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
        <div style="font-size:19px;font-weight:800">${esc(sel.name)}</div>${chipTpl(sel.status)}
        <div style="margin-left:auto;display:flex;gap:8px">
          ${ME.role === 'owner' ? `
            <span class="btn" onclick="setTplStatus(${sel.id},'approved')">${T('Mark approved', '标为通过')}</span>
            <span class="btn" onclick="setTplStatus(${sel.id},'rejected')">${T('Mark rejected', '标为被拒')}</span>` : ''}
          ${ME.role === 'owner' ? `<span class="btn" onclick="syncTemplates()">${T('Sync from Meta', '同步 Meta 状态')}</span>` : ''}
          <span class="btn gold" onclick="useTpl(${sel.id})">${T('Use this template', '用它发一批')}</span>
        </div>
      </div>
      <div class="grid2">
        <div class="card"><h3>${T('Preview', '模板内容')}</h3>
          <div class="phone"><div class="bubble">${esc(sel.body).replace(/\{\{(\d)\}\}/g, '<span class="var">{{$1}}</span>')}</div></div>
          <div style="margin-top:13px;font-size:12px;color:var(--sub);line-height:1.9">
            ${T('Variables are filled per contact at send time.', '变量在发送时按客户自动填充。')}</div>
        </div>
        <div class="card"><h3>${T('Details', '详情')}</h3>
          <dl class="dl"><dt>${T('Category', '分类')}</dt><dd>${esc(sel.category)}</dd>
            <dt>${T('Language', '语言')}</dt><dd>${esc(sel.language)}</dd>
            <dt>${T('Status', '状态')}</dt><dd>${chipTpl(sel.status)}</dd>
            <dt>${T('Created', '创建')}</dt><dd>${esc((sel.created_at || '').slice(0, 10))}</dd></dl>
          <div class="note" style="margin-top:12px">${T("Review happens in Meta's WhatsApp Manager. This page records the outcome." , '审核在 Meta 后台进行，这里只记录结果。')}</div>
        </div>
      </div>` : `<div class="loading">${T('No templates', '暂无模板')}</div>`}
    </div>`;
}
window.pickTpl = (id) => { CACHE.tpl = id; viewTemplates(); };
window.setTplStatus = async (id, st) => {
  await api(`/api/templates/${id}/status`, { method: 'POST', body: JSON.stringify({ status: st }) });
  toast(T('Updated', '已更新')); viewTemplates();
};
window.useTpl = (id) => { CACHE.useTpl = id; go('campaigns'); };

/* ---------------- 触达 ---------------- */
async function viewCampaigns() {
  const [{ items: segs }, { items: tpls }, { items: camps }] = await Promise.all([
    api('/api/segments'), api('/api/templates'), api('/api/campaigns')]);
  $('hTitle').textContent = T('Campaigns', '批量触达');
  $('hSub').textContent = T('Pick a segment · use an approved template · send in batches', '按分层选人 · 用审核过的模板 · 分批发送');
  const okTpls = tpls.filter(t => t.status === 'approved');
  const pre = CACHE.useTpl;
  $('body').innerHTML = `
    <div class="col-main">
      ${pre ? `<div class="warnbar">${T('Template pre-selected:', '已选模板：')}<b>${esc((tpls.find(t => t.id === pre) || {}).name || '')}</b></div>` : ''}
      <div class="grid2" style="grid-template-columns:1.12fr 1fr">
        <div class="card"><h3>${T('New campaign', '新建触达任务')}</h3>
          <div class="field"><label>${T('Audience', '发给谁')}</label>
            <select id="cpSeg" class="inp" style="width:100%">${segs.map(s => `<option value="${s.id}">${esc(s.name)} · ${s.sendable} ${T('sendable', '人可发送')}</option>`).join('')}</select></div>
          <div class="field"><label>${T('Template', '用哪个模板')}</label>
            <select id="cpTpl" class="inp" style="width:100%">${okTpls.map(t => `<option value="${t.id}" ${t.id === pre ? 'selected' : ''}>${esc(t.name)}</option>`).join('')}</select></div>
          <div class="field"><label>${T('Campaign name (optional)', '任务名称（可选）')}</label><input id="cpName" class="inp" style="width:100%" placeholder="${T('Auto', '自动生成')}"></div>
          <div class="hr"></div>
          <div style="display:flex;justify-content:space-between;align-items:center">
            <div style="font-size:13px;color:var(--sub)">${T('Sends only to opted-in contacts.', '只发给有授权、未退订的客户。')}</div>
            <span class="btn gold" onclick="createCampaign()">${T('Submit campaign', '提交发送')}</span>
          </div>
        </div>
        <div class="card"><h3>${T('Pre-send checks', '发送前检查')}</h3>
          <table><tbody>
            <tr><td>${T('Template status', '模板状态')}</td><td style="text-align:right">${okTpls.length ? chipTpl('approved') : `<span class="chip c-bad">${T('None approved', '没有可用模板')}</span>`}</td></tr>
            <tr><td>${T('Opt-in required', '必须已授权')}</td><td style="text-align:right"><span class="chip c-ok">${T('Enforced', '系统强制')}</span></td></tr>
            <tr><td>${T('Opt-outs excluded', '已退订排除')}</td><td style="text-align:right"><span class="chip c-gray">${T('Always', '始终')}</span></td></tr>
            <tr><td>${T('Delivery mode', '发送模式')}</td><td style="text-align:right"><span class="chip c-warn">${T('Sandbox', '沙盒')}</span></td></tr>
          </tbody></table>
          <div class="note" style="margin-top:13px">${T('Sandbox mode: campaigns are queued and counted, but nothing is delivered to WhatsApp until the Cloud API is connected.', '沙盒模式：任务会入队并计数，但接上 Cloud API 之前不会真的发到 WhatsApp。')}</div>
        </div>
      </div>
      <div class="card" style="margin-top:14px"><h3>${T('Send history', '发送记录')}</h3>
        <table><thead><tr><th>${T('Campaign', '任务')}</th><th>${T('Audience', '人群')}</th><th>${T('Template', '模板')}</th>
          <th>${T('Sent', '发送')}</th><th>${T('Delivered', '送达')}</th><th>${T('Replied', '回复')}</th><th>${T('Status', '状态')}</th></tr></thead>
        <tbody>${camps.map(c => `<tr style="cursor:pointer" onclick="openCampaign(${c.id})"><td><b>${esc(c.name)}</b></td><td>${esc(c.segment_name)}</td><td>${esc(c.template_name)}</td>
          <td class="mono">${c.sent}</td><td class="mono">${c.delivered}</td>
          <td class="mono" style="color:var(--green);font-weight:700">${c.replied}</td>
          <td>${c.status === 'done' ? `<span class="chip c-ok">${T('Done', '已完成')}</span>` : `<span class="chip c-warn">${esc(c.status)}</span>`}</td></tr>`).join('')
          || `<tr><td colspan="7" style="color:var(--sub)">${T('No campaigns yet', '还没有触达任务')}</td></tr>`}</tbody></table>
      </div>
    </div>`;
}
window.createCampaign = async () => {
  try {
    const r = await api('/api/campaigns', { method: 'POST', body: JSON.stringify({
      segment_id: +$('cpSeg').value, template_id: +$('cpTpl').value, name: $('cpName').value || undefined }) });
    toast(T(`Queued to ${r.sent} contacts (not sent yet)`, `已入队 ${r.sent} 人（尚未真实发送）`));
    CACHE.useTpl = null; viewCampaigns();
  } catch (e) { toast(e.message); }
};

/* ---------------- 团队 ---------------- */
async function viewTeam() {
  const [d, tagRes] = await Promise.all([api('/api/team'), api('/api/tags')]);
  const tagName = Object.fromEntries((tagRes.items || []).map(t => [t.id, t.name]));
  const scopes = d.scopes || {};
  const SCOPE_TPL = { owner: [T('All contacts', '全部客户'), '全部客户'],
                      manager: [T('Own team', '本组'), '本组'],
                      agent: [T('Only own contacts', '只有自己名下'), '只有自己名下'] };
  $('hTitle').textContent = T('Team', '团队接待');
  $('hSub').textContent = T('Who owns which contacts · live', '每个客户归谁 · 实时');
  $('body').innerHTML = `
    <div class="col-main">
      <div class="kpis">
        <div class="kpi"><div class="k">${T('Unassigned', '待分配')}</div><div class="v">${d.totals.unassigned}</div><div class="d">${T('Waiting for an owner', '等着分给谁')}</div></div>
        <div class="kpi"><div class="k">${T('Unread', '未读消息')}</div><div class="v">${d.totals.unread}</div><div class="d">${T('Across all numbers', '全部号码合计')}</div></div>
        <div class="kpi"><div class="k">${T('Open conversations', '进行中会话')}</div><div class="v">${d.totals.open}</div><div class="d">${T('Need a reply', '待回复')}</div></div>
        <div class="kpi"><div class="k">${T('Deals won', '已成交')} <span style="color:var(--gold)">✎</span></div><div class="v">${d.items.reduce((a, x) => a + x.won, 0)}</div><div class="d">${T('Logged manually', '人工标记')}</div></div>
      </div>
      <div class="card"><h3>${T('By agent', '按销售')}<small>${T('click a row to see their contacts', '点一行看他名下的客户')}</small></h3>
        <table><thead><tr><th>${T('Agent', '销售')}</th><th>${T('Role', '角色')}</th><th>${T('Sees', '数据范围')}</th>
          <th>${T('Can claim tags', '可领标签')}</th><th>${T('Open', '进行中')}</th>
          <th>${T('Unread', '未读')}</th><th>${T('Contacts', '负责客户')}</th><th>${T('Deals won', '成交')}</th></tr></thead>
        <tbody>${d.items.map(a => {
          const sc = scopes[String(a.id)] || [];
          const scTxt = a.role !== 'agent' ? `<span style="color:var(--sub);font-size:12px">${T('not limited', '不受限')}</span>`
            : sc.length === 0 ? `<span style="color:var(--sub);font-size:12px">${T('any tag', '不限')}</span>`
            : sc.map(id => `<span class="chip c-info" style="height:19px;font-size:10.5px">${esc(tagName[id] || '#' + id)}</span>`).join(' ');
          const [sen, szh] = SCOPE_TPL[a.role] || [a.role, a.role];
          return `<tr style="cursor:pointer" onclick="openContactsByOwner(${a.id})"><td><b>${esc(a.name)}</b><div style="font-size:11px;color:var(--sub)">${esc(a.email)}</div></td>
          <td><span class="chip c-gray">${roleName(a.role)}</span></td>
          <td style="font-size:12px;color:var(--sub)">${T(sen, szh)}</td>
          <td>${scTxt || ''}</td>
          <td class="mono">${a.open}</td><td class="mono">${a.unread}</td><td class="mono">${a.contacts}</td><td class="mono">${a.won}</td></tr>`;
        }).join('')}</tbody></table>
        <div class="note" style="margin-top:12px">${T(
          'A contact belongs to whoever is set as its owner — not to a phone. Your team all work on the company WhatsApp numbers; nobody uses a personal number.',
          '客户归谁，看的是“负责人”这个字段，跟手机号无关。整个团队用的是公司的 WhatsApp 号码，没有人用个人号。')}</div>
        <div class="note" style="margin-top:8px">${T(
          'Assign in the Contacts page: open a contact and pick an owner. In the Inbox, assigning a chat assigns the customer too.',
          '分配在客户池里做：点开客户，在“负责人”那一栏选人。会话台里把一条会话分配给谁，这个客户也一起归他。')}</div>
      </div>
    </div>`;
}

/* ---------------- 设置 ---------------- */
let SET_TAB = 'workspace';
async function viewSettings() {
  const s = await api('/api/settings');
  const users = ME.role === 'owner' ? await api('/api/users') : { items: [] };
  $('hTitle').textContent = T('Settings', '设置');
  $('hSub').textContent = T('Workspace, team, compliance, AI', '工作区、团队、合规、AI');
  const nav = [['workspace', T('Workspace', '工作区')], ['team', T('Team & roles', '团队与权限')],
               ['compliance', T('Compliance', '合规设置')], ['ai', T('AI customer insights', 'AI 客户洞察')],
               ['notify', T('Notifications', '通知')], ['channels', T('Integrations', '集成')],
               ['stages', T('Deal stages', '成交状态')],
               ['pool', T('Public pool', '公海规则')],
               ['tags', T('Tags', '标签管理')],
               ['numbers', T('Numbers', '号码管理')],
               ['audit', T('Audit log', '操作日志')]];
  $('body').innerHTML = `
    <div class="col-main"><div class="setwrap">
      <div class="setnav">${nav.map(([k, n]) => `<div class="${k === SET_TAB ? 'on' : ''}" onclick="setTab('${k}')">${n}</div>`).join('')}</div>
      <div class="setpanel" id="setpanel"><div class="loading">${T('Loading…', '加载中…')}</div></div>
    </div></div>`;
  const html = await settingsPanel(s, users);
  const holder = $('setpanel');
  if (holder) { holder.innerHTML = html; if (SET_TAB === 'ai') applyAITranslations(holder); }
}
window.setTab = (k) => { if (k !== 'pool') POOL_SCOPE_DIRTY = false; SET_TAB = k; viewSettings(); };
function settingsPanel(s, users) {
  const card = (t, h) => `<div class="card" style="margin-bottom:14px"><h3>${t}</h3>${h}</div>`;
  const w = s.workspace || {}, c = s.compliance || {}, a = s.ai || {}, n = s.notify || {}, ch = s.channels || {};
  const ro = ME.role !== 'owner' ? 'disabled' : '';
  switch (SET_TAB) {
    case 'workspace': return card(T('Workspace', '工作区'), `
      <div class="grid2">
        <div class="field"><label>${T('Workspace name', '工作区名称')}</label><input class="inp" id="wsName" style="width:100%" value="${esc(w.name || '')}" ${ro}></div>
        <div class="field"><label>${T('Timezone', '时区')}</label><input class="inp" id="wsTz" style="width:100%" value="${esc(w.timezone || '')}" ${ro}></div>
        <div class="field"><label>${T('Working hours', '工作时间')}</label><input class="inp" id="wsHours" style="width:100%" value="${esc(w.hours || '')}" ${ro}></div>
        <div class="field"><label>${T('Interface language', '界面语言')}</label><div class="inp">${T('Switch in header', '右上角切换')}</div></div>
      </div>
      ${ME.role === 'owner' ? `<span class="btn gold" onclick="saveWorkspace()">${T('Save', '保存')}</span>` : ''}`);
    case 'team': return card(T('Team & roles', '团队与权限'), `
      <table><thead><tr><th>${T('Member', '成员')}</th><th>${T('Email', '邮箱')}</th><th>${T('Role', '角色')}</th><th>${T('Team', '团队')}</th></tr></thead>
      <tbody>${users.items.map(u => `<tr><td><b>${esc(u.name)}</b></td><td>${esc(u.email)}</td>
        <td><span class="chip c-gray">${T({ owner: 'Owner', manager: 'Manager', agent: 'Agent' }[u.role], { owner: '老板', manager: '主管', agent: '销售' }[u.role])}</span></td>
        <td>${esc(u.team)}</td></tr>`).join('') || `<tr><td colspan="4">${T('Only owners can see the full list', '只有老板能看全部成员')}</td></tr>`}</tbody></table>
      <div class="note" style="margin-top:12px">${T('Agents see contacts assigned to them. Managers see their team. Owners see everything.', '销售只看自己的客户；主管看本组；老板看全部。')}</div>`);
    case 'compliance': return card(T('Compliance', '合规设置'), `
      <table><tbody>
        <tr><td>${T('Opt-in required before marketing', '营销前必须授权')}</td><td style="text-align:right"><span class="chip c-ok">${T('Always on', '始终开启')}</span></td></tr>
        <tr><td>${T('Opt-out handling', '退订处理')}</td><td style="text-align:right"><span class="chip c-ok">${T('Permanent block', '永久拉黑')}</span></td></tr>
        <tr><td>${T('Service window', '客服窗口')}</td><td style="text-align:right">${c.window_hours || 24}h</td></tr>
        <tr><td>${T('Message retention', '消息留存')}</td><td style="text-align:right">${c.retention_months || 24} ${T('months', '个月')}</td></tr>
      </tbody></table>
      <div class="note" style="margin-top:12px">${T('These are enforced in code, not by a checklist.', '这些是代码层面的硬规则，不靠人工检查。')}</div>`);
    case 'ai': return aiInsightsPanel();

    case 'notify': return card(T('Notifications', '通知'), `
      <table><tbody>${Object.entries(n).map(([k, v]) => `<tr><td>${esc(k)}</td>
        <td style="text-align:right"><span class="chip ${v ? 'c-ok' : 'c-gray'}">${v ? T('On', '开') : T('Off', '关')}</span></td></tr>`).join('')}</tbody></table>`);
    case 'channels': return card(T('Integrations', '集成'), `
      <table><tbody>${Object.entries(ch).map(([k, v]) => `<tr><td><b>${esc(k)}</b></td><td style="text-align:right">
        <span class="chip ${v === 'connected' ? 'c-ok' : v === 'pending' ? 'c-warn' : 'c-gray'}">${esc(v)}</span></td></tr>`).join('')}</tbody></table>
      <div class="note" style="margin-top:12px">${T('WhatsApp Cloud API: sandbox mode. Connect credentials to go live.', 'WhatsApp Cloud API：沙盒模式。填入凭证即可切换真实发送。')}</div>`);
  }
}
window.saveWorkspace = async () => {
  try {
    await api('/api/settings', { method: 'PATCH', body: JSON.stringify({ workspace: {
      ...(CACHE.settings?.workspace || {}), name: $('wsName').value, timezone: $('wsTz').value, hours: $('wsHours').value } }) });
    toast(T('Saved', '已保存'));
  } catch (e) { toast(e.message); }
};

/* ---------------- 启动 ---------------- */
(async function boot() {
  $('loginHint').innerHTML = T('Demo accounts: owner@demo.com / manager@demo.com / agent@demo.com · password demo1234',
                              '演示账号：owner@demo.com / manager@demo.com / agent@demo.com · 密码 demo1234');
  updateBrandLine();
  if (!TOKEN) { $('login').style.display = 'flex'; return; }
  try {
    ME = await api('/api/me');
    await startApp();
  } catch (e) { logout(); }
})();

/* ================= V2：看板 / 模板 / 设置 增强 ================= */

/* ---------- 看板（多维度筛选 + 多板块） ---------- */
let AN_RANGE = '30d', AN_AGENT = '', AN_CHANNEL = '', AN_COUNTRY = '', AN_SEGMENT = '',
    AN_DEAL = '', AN_TAG = '', AN_TEAM = '', AN_NUMBER = '', AN_OPT = '',
    AN_FROM = '', AN_TO = '', AN_SEQ = 0;

async function viewAnalytics() {
  const seq = ++AN_SEQ;
  const q = new URLSearchParams({ range: AN_RANGE, agent: AN_AGENT, channel: AN_CHANNEL,
    country: AN_COUNTRY, segment: AN_SEGMENT, deal: AN_DEAL, tag: AN_TAG, team: AN_TEAM,
    number: AN_NUMBER, opt: AN_OPT, start: AN_FROM, end: AN_TO });
  const d = await api('/api/analytics?' + q.toString());
  if (seq !== AN_SEQ) return;
  const f = d.facets || {};
  const active = [AN_AGENT, AN_CHANNEL, AN_COUNTRY, AN_SEGMENT, AN_DEAL, AN_TAG, AN_TEAM,
                  AN_NUMBER, AN_OPT].filter(Boolean).length;
  $('hTitle').textContent = T('Analytics', '数据看板');
  $('hSub').textContent = active
    ? T(`${active} filter(s) applied · ${d.contacts} contacts in scope`, `已叠加 ${active} 个筛选 · 命中 ${d.contacts} 位客户`)
    : T('Filter by owner, country, source, tag, segment, stage, team and number', '可按负责人、国家、来源、标签、分层、成交阶段、团队、号码筛选');

  const sel = (key, val, list, allLabel, labelFn) => `
    <select class="pill" style="padding:0 8px;max-width:180px" onchange="setAnFilter('${key}',this.value)">
      <option value="">${allLabel}</option>
      ${list.map(x => {
        const v = String(x.id !== undefined ? x.id : x);
        const n = labelFn ? labelFn(x) : (x.name || x);
        return `<option value="${esc(v)}" ${String(val) === v ? 'selected' : ''}>${esc(n)}</option>`;
      }).join('')}
    </select>`;

  const series = d.series || [];
  const labels = series.map(x => x.d);
  const outPts = series.map(x => x.out || 0);
  const inPts = series.map(x => x.in || 0);
  const W = 640, H = 170, P = 8;
  const mx = Math.max(...outPts, ...inPts, 1);
  const xy = (arr) => arr.map((v, i) => [P + i * ((W - P * 2) / Math.max(1, arr.length - 1)),
                                          H - P - (v / mx) * (H - P * 2)]);
  const outXY = xy(outPts), inXY = xy(inPts);
  const outLine = outXY.map(c => c.join(',')).join(' ');
  const inLine = inXY.map(c => c.join(',')).join(' ');
  const area = `${P},${H - P} ` + outLine + ` ${W - P},${H - P}`;
  const step = Math.max(1, Math.ceil(series.length / 8));

  const ch = d.channel_split || [];
  const chTotal = ch.reduce((a, x) => a + x.v, 0) || 1;
  const colors = ['#1B3A5C', '#2F5C8A', '#4C7FB4', '#7E9DBF', '#C9A227', '#8C6F1F'];
  let acc = 0;
  const conic = ch.map((x, i) => {
    const from = acc / chTotal * 360; acc += x.v;
    return `${colors[i % colors.length]} ${from}deg ${acc / chTotal * 360}deg`;
  }).join(', ');

  const [f1, f2, f3, f4] = d.funnel;
  const pct = (v) => f1 ? Math.max(1.5, Math.round(v / f1 * 100)) : 0;
  const money = (v) => '$' + Number(v || 0).toLocaleString();
  const bar = (v, max) => `<div class="grow" style="height:7px"><i style="width:${max ? Math.max(2, Math.round(v / max * 100)) : 0}%"></i></div>`;
  const delta = (cur, prev) => {
    if (!prev) return '';
    const p = Math.round((cur - prev) / prev * 100);
    return `<span style="color:${p >= 0 ? 'var(--ok)' : 'var(--bad)'}">${p >= 0 ? '▲' : '▼'} ${Math.abs(p)}%</span>`;
  };

  const maxCountry = Math.max(1, ...(d.by_country || []).map(x => x.n));
  const maxOwner = Math.max(1, ...(d.by_owner || []).map(x => x.n));
  const maxTeam = Math.max(1, ...(d.by_team || []).map(x => x.n));
  const maxTag = Math.max(1, ...(d.by_tag || []).map(x => x.n));
  const maxStage = Math.max(1, ...(d.by_stage || []).map(x => x.n));
  const stageName = (x) => LANG === 'zh' ? (x.zh || x.key) : (x.en || x.key);

  $('body').innerHTML = `
  <div class="col-main">
    <div class="card" style="padding:10px 12px;margin-bottom:14px">
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
        ${[['7d', T('7 days', '近 7 天')], ['30d', T('30 days', '近 30 天')], ['90d', T('90 days', '近 90 天')]]
          .map(([k, n]) => `<span class="pill ${AN_RANGE === k && !AN_FROM ? 'dark' : ''}" onclick="setRange('${k}')">${n}</span>`).join('')}
        <span style="display:inline-flex;align-items:center;gap:5px;font-size:12px;color:var(--sub);margin-left:4px">
          <input type="date" class="inp" style="height:32px;padding:0 6px" value="${esc(AN_FROM)}" onchange="setAnDate('from',this.value)">
          –
          <input type="date" class="inp" style="height:32px;padding:0 6px" value="${esc(AN_TO)}" onchange="setAnDate('to',this.value)">
        </span>
        <span style="margin-left:auto;display:flex;gap:6px;align-items:center">
          ${active ? `<span class="chip c-warn">${T('Filters on', '筛选中')}</span>` : ''}
          <span class="pill" style="cursor:pointer" onclick="resetAnalytics()">${T('Reset', '重置')}</span>
        </span>
      </div>
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:8px;padding-top:8px;border-top:1px solid var(--line)">
        ${sel('agent', AN_AGENT, f.owners || [], T('All owners', '全部负责人'), x => x.name)}
        ${sel('channel', AN_CHANNEL, f.sources || [], T('All sources', '全部来源'))}
        ${sel('country', AN_COUNTRY, f.countries || [], T('All countries', '全部国家'))}
        ${sel('tag', AN_TAG, f.tags || [], T('All tags', '全部标签'), x => x.name)}
        ${sel('segment', AN_SEGMENT, f.segments || [], T('All segments', '全部分层'), x => x.name)}
        ${sel('deal', AN_DEAL, f.stages || [], T('All stages', '全部成交阶段'), x => stageName(x))}
        ${sel('team', AN_TEAM, f.teams || [], T('All teams', '全部团队'), x => x.name)}
        ${sel('number', AN_NUMBER, f.numbers || [], T('All numbers', '全部号码'), x => x.label)}
        ${sel('opt', AN_OPT, [{ id: 'in', name: T('Opted in', '已授权') },
                              { id: 'out', name: T('Opted out', '已退订') }], T('Any consent', '授权不限'), x => x.name)}
      </div>
    </div>

    <div class="kpis">
      <div class="kpi" style="cursor:pointer" onclick="go('contacts')"><div class="k">${T('Contacts', '客户数')} →</div>
        <div class="v count" data-to="${d.contacts}">0</div>
        <div class="d">${T('New', '新增')} ${d.new_contacts} ${delta(d.new_contacts, (d.prev || {}).new_contacts)}</div></div>
      <div class="kpi" style="cursor:pointer" onclick="go('campaigns')"><div class="k">${T('Sent', '已发送')} →</div>
        <div class="v count" data-to="${d.sent}">0</div>
        <div class="d">${T('Campaigns in period', '本期内任务')} ${delta(d.sent, (d.prev || {}).sent)}</div></div>
      <div class="kpi" style="cursor:pointer" onclick="go('campaigns')"><div class="k">${T('Reply rate', '回复率')} →</div>
        <div class="v">${d.reply_rate}%</div>
        <div class="d">${d.replied} ${T('replies', '条回复')} · ${d.delivered} ${T('delivered', '已送达')}</div></div>
      <div class="kpi" style="cursor:pointer" onclick="openContactsByDeal('Won')"><div class="k">${T('Deals won', '已成交')} ✎ →</div>
        <div class="v count" data-to="${d.won}">0</div><div class="d">${T('Click to see who', '点开看是谁')}</div></div>
      <div class="kpi"><div class="k">${T('Revenue', '成交金额')}</div>
        <div class="v">${money(d.revenue)}</div><div class="d">${T('From won deals', '来自已成交')}</div></div>
      <div class="kpi" style="cursor:pointer" onclick="go('inbox')"><div class="k">${T('Conversations', '会话')} →</div>
        <div class="v">${d.open_conversations}</div>
        <div class="d">${d.unread} ${T('unread', '条未读')} · ${T('avg reply', '平均回复')} ${d.avg_reply_min || 0} ${T('min', '分钟')}</div></div>
      <div class="kpi" style="cursor:pointer" onclick="go('ai')"><div class="k">${T('AI handled', 'AI 接待')} →</div>
        <div class="v">${d.ai.total}</div>
        <div class="d">${T('Auto', '自动')} ${d.ai.auto} · ${T('handoff', '转人工')} ${d.ai.handoff} ${delta(d.ai.total, (d.prev || {}).ai_total)}</div></div>
      <div class="kpi"><div class="k">${T('Opt-out rate', '退订率')}</div>
        <div class="v">${d.opt_out_rate}%</div>
        <div class="d">${d.opt_out} ${T('opted out', '人已退订')} · ${T('pool', '公海')} ${d.pool_count}</div></div>
    </div>

    <div class="grid2" style="grid-template-columns:1.4fr 1fr">
      <div class="card"><h3>${T('Daily messages', '每日消息')}<small>${T('outbound vs inbound', '发出 / 收到')}</small></h3>
        <svg viewBox="0 0 ${W} ${H}" style="width:100%;height:180px">
          <defs><linearGradient id="ar2" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stop-color="#1B3A5C" stop-opacity=".22"/><stop offset="1" stop-color="#1B3A5C" stop-opacity="0"/></linearGradient></defs>
          <polygon points="${area}" fill="url(#ar2)"/>
          <polyline points="${outLine}" fill="none" stroke="#1B3A5C" stroke-width="2.6" stroke-linejoin="round"
            style="stroke-dasharray:2000;stroke-dashoffset:2000;animation:draw 1.1s ease-out forwards"/>
          <polyline points="${inLine}" fill="none" stroke="#C9A227" stroke-width="2" stroke-linejoin="round" opacity=".9"/>
        </svg>
        <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--sub);padding:0 4px">
          ${labels.filter((_, i) => i % step === 0).map(l => `<span>${l}</span>`).join('')}
        </div>
        <div style="display:flex;gap:16px;font-size:11.5px;color:var(--sub);margin-top:6px">
          <span><i style="display:inline-block;width:10px;height:3px;background:#1B3A5C;vertical-align:middle"></i> ${T('Outbound', '发出')} ${d.messages_out}</span>
          <span><i style="display:inline-block;width:10px;height:3px;background:#C9A227;vertical-align:middle"></i> ${T('Inbound', '收到')} ${d.messages_in}</span>
          <span>${T('AI sent', 'AI 发出')} ${d.ai_messages}</span>
        </div>
      </div>

      <div class="card"><h3>${T('Where contacts come from', '客户来源占比')}</h3>
        <div style="display:flex;align-items:center;gap:18px">
          <div style="width:118px;height:118px;border-radius:50%;flex:none;
            background:conic-gradient(${conic || '#EEF2F7 0deg 360deg'});animation:spinIn .7s ease-out"></div>
          <div style="font-size:12.5px;min-width:0">
            ${ch.slice(0, 7).map((x, i) => `<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
              <i style="width:10px;height:10px;border-radius:3px;background:${colors[i % colors.length]};display:inline-block;flex:none"></i>
              <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(x.k)}</span>
              <b style="margin-left:auto">${x.v}</b></div>`).join('') || `<span style="color:var(--sub)">${T('No data in scope', '当前范围没有数据')}</span>`}
          </div>
        </div>
      </div>
    </div>

    <div class="grid2" style="margin-top:14px">
      <div class="card"><h3>${T('Funnel', '转化漏斗')}</h3>
        ${[[T('Sent', '已发送'), f1, "go('campaigns')"], [T('Delivered', '已送达'), f2, "go('campaigns')"],
           [T('Replied', '已回复'), f3, "go('campaigns')"], [T('Deals won ✎', '已成交 ✎'), f4, "openContactsByDeal('Won')"]]
          .map(([k, v, act]) => `<div style="margin-bottom:12px;cursor:pointer" onclick="${act}">
            <div style="display:flex;justify-content:space-between;font-size:12.5px;margin-bottom:5px">
              <span>${k}</span><span class="mono">${v}</span></div>
            <div class="grow"><i style="width:${pct(v)}%"></i></div></div>`).join('')}
        <div class="note" style="margin-top:6px">${T('Task metrics cover the whole company unless you filter by segment.', '发送数据按公司任务统计；只有按分层筛选时才会跟着拆分。')}</div>
      </div>

      <div class="card"><h3>${T('Segment performance', '各分层表现')}<small>${T('click to open', '点击查看')}</small></h3>
        <table><thead><tr><th>${T('Segment', '分层')}</th><th>${T('Matched', '命中')}</th>
          <th>${T('Sendable', '可发送')}</th><th>${T('Won', '成交')}</th><th>${T('Revenue', '金额')}</th></tr></thead>
        <tbody>${d.segments.map(s2 => `<tr style="cursor:pointer;${String(AN_SEGMENT) === String(s2.id) ? 'background:#FFF8E1' : ''}" onclick="openSegment(${s2.id})">
          <td>${esc(s2.name)}</td><td class="mono">${s2.matched}</td><td class="mono">${s2.sendable}</td>
          <td class="mono">${s2.won}</td><td class="mono">${money(s2.revenue)}</td></tr>`).join('') || `<tr><td colspan="5">${T('No segments', '没有分层')}</td></tr>`}</tbody></table>
      </div>
    </div>

    <div class="grid2" style="margin-top:14px">
      <div class="card"><h3>${T('By country', '按国家')}</h3>
        <table><thead><tr><th>${T('Country', '国家')}</th><th>${T('Contacts', '客户')}</th><th>${T('Won', '成交')}</th><th>${T('Revenue', '金额')}</th></tr></thead>
        <tbody>${(d.by_country || []).slice(0, 8).map(x => `<tr><td>${esc(x.k)}</td>
          <td style="width:38%"><div style="display:flex;align-items:center;gap:8px"><span class="mono" style="width:28px">${x.n}</span>${bar(x.n, maxCountry)}</div></td>
          <td class="mono">${x.won}</td><td class="mono">${money(x.revenue)}</td></tr>`).join('') || `<tr><td colspan="4" style="color:var(--sub)">${T('No data', '没有数据')}</td></tr>`}</tbody></table>
      </div>
      <div class="card"><h3>${T('By tag', '按标签')}</h3>
        <table><thead><tr><th>${T('Tag', '标签')}</th><th>${T('Contacts', '客户')}</th><th>${T('Won', '成交')}</th><th>${T('Opted out', '退订')}</th></tr></thead>
        <tbody>${(d.by_tag || []).slice(0, 8).map(x => `<tr><td>${esc(x.name)}</td>
          <td style="width:38%"><div style="display:flex;align-items:center;gap:8px"><span class="mono" style="width:28px">${x.n}</span>${bar(x.n, maxTag)}</div></td>
          <td class="mono">${x.won}</td><td class="mono">${x.opt_out}</td></tr>`).join('') || `<tr><td colspan="4" style="color:var(--sub)">${T('No tags', '没有标签')}</td></tr>`}</tbody></table>
      </div>
    </div>

    <div class="grid2" style="margin-top:14px">
      <div class="card"><h3>${T('By owner', '按负责人')}<small>${T('click a name to filter', '点名字按他筛选')}</small></h3>
        <table><thead><tr><th>${T('Owner', '负责人')}</th><th>${T('Contacts', '客户')}</th><th>${T('Won', '成交')}</th><th>${T('Revenue', '金额')}</th></tr></thead>
        <tbody>${(d.by_owner || []).slice(0, 10).map(x => `<tr>
          <td>${x.id ? `<span style="cursor:pointer" onclick="setAnFilter('agent','${x.id}')">${esc(x.name)}</span>` : `<span style="color:var(--sub)">${T('Unassigned', '未分配')}</span>`}</td>
          <td style="width:32%"><div style="display:flex;align-items:center;gap:8px"><span class="mono" style="width:28px">${x.n}</span>${bar(x.n, maxOwner)}</div></td>
          <td class="mono">${x.won}</td><td class="mono">${money(x.revenue)}</td></tr>`).join('') || `<tr><td colspan="4" style="color:var(--sub)">${T('No data', '没有数据')}</td></tr>`}</tbody></table>
      </div>
      <div class="card"><h3>${T('By team', '按团队')}</h3>
        <table><thead><tr><th>${T('Team', '团队')}</th><th>${T('Contacts', '客户')}</th><th>${T('Won', '成交')}</th><th>${T('Revenue', '金额')}</th></tr></thead>
        <tbody>${(d.by_team || []).map(x => `<tr><td>${esc(x.name)}</td>
          <td style="width:32%"><div style="display:flex;align-items:center;gap:8px"><span class="mono" style="width:28px">${x.n}</span>${bar(x.n, maxTeam)}</div></td>
          <td class="mono">${x.won}</td><td class="mono">${money(x.revenue)}</td></tr>`).join('') || `<tr><td colspan="4" style="color:var(--sub)">${T('No teams', '没有团队')}</td></tr>`}</tbody></table>
      </div>
    </div>

    <div class="grid2" style="margin-top:14px">
      <div class="card"><h3>${T('By number', '按号码')}</h3>
        <table><thead><tr><th>${T('Number', '号码')}</th><th>${T('Chats', '会话')}</th><th>${T('Unread', '未读')}</th><th>${T('Msg in / out', '收 / 发')}</th><th>AI</th></tr></thead>
        <tbody>${(d.by_number || []).map(x => `<tr><td><b>${esc(x.label)}</b><div style="font-size:11px;color:var(--sub)">${esc(x.phone)} · ${esc(x.status)}</div></td>
          <td class="mono">${x.conversations}</td><td class="mono">${x.unread}</td>
          <td class="mono">${x.in} / ${x.out}</td><td class="mono">${x.ai}</td></tr>`).join('') || `<tr><td colspan="5" style="color:var(--sub)">${T('No numbers', '没有号码')}</td></tr>`}</tbody></table>
      </div>
      <div class="card"><h3>${T('Pipeline by stage', '成交阶段分布')}<small>${T('live status, not time-bound', '当前状态')}</small></h3>
        ${(d.by_stage || []).map(x => `<div style="margin-bottom:11px">
          <div style="display:flex;justify-content:space-between;font-size:12.5px;margin-bottom:4px">
            <span>${esc(stageName(x))}</span><span class="mono">${x.n} · ${money(x.revenue)}</span></div>
          <div class="grow"><i style="width:${maxStage ? Math.max(1, Math.round(x.n / maxStage * 100)) : 0}%"></i></div></div>`).join('')}
      </div>
    </div>

    <div class="grid2" style="margin-top:14px">
      <div class="card"><h3>${T('Campaign performance', '触达任务表现')}<small>${T('period total', '本期')}</small></h3>
        <table><thead><tr><th>${T('Campaign', '任务')}</th><th>${T('Sent', '发送')}</th><th>${T('Replied', '回复')}</th><th>${T('Rate', '回复率')}</th></tr></thead>
        <tbody>${(d.campaigns || []).slice(0, 8).map(x => `<tr><td>${esc(x.name)}<div style="font-size:11px;color:var(--sub)">${esc((x.created_at || '').slice(0, 10))}</div></td>
          <td class="mono">${x.sent}</td><td class="mono">${x.replied}</td><td class="mono">${x.reply_rate}%</td></tr>`).join('') || `<tr><td colspan="4" style="color:var(--sub)">${T('No campaigns in this period', '本期没有任务')}</td></tr>`}</tbody></table>
        ${d.campaign_scope === 'filtered' ? `<div class="note" style="margin-top:8px">${T('Campaign totals are company-wide; contact filters do not split them (except segment).', '任务发送量按公司口径统计，不随负责人/国家/标签等客户筛选拆分；按分层筛选时会拆分。')}</div>` : ''}
      </div>
      <div class="card"><h3>${T('AI reception', 'AI 接待效果')}<small>${T('in this period', '本期内')}</small></h3>
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;text-align:center">
          ${[[T('Handled', '处理量'), d.ai.total], [T('Auto sent', '自动回复'), d.ai.auto], [T('Draft', '生成草稿'), d.ai.draft],
             [T('Handoff', '转人工'), d.ai.handoff], [T('Blocked', '安全拦截'), d.ai.blocked], [T('Source hit', '命中知识'), d.ai.source_hit]]
            .map(([k, v]) => `<div style="background:#F7F9FC;border-radius:10px;padding:10px 6px">
              <div style="font-size:19px;font-weight:750">${v}</div><div style="font-size:11px;color:var(--sub);margin-top:2px">${k}</div></div>`).join('')}
        </div>
        <div style="margin-top:12px;font-size:12.5px;color:var(--sub);line-height:1.9">
          ${T('Auto rate', '自动处理率')}: <b style="color:var(--ink)">${d.ai.auto_rate}%</b> ·
          ${T('Handoff rate', '转人工率')}: <b style="color:var(--ink)">${d.ai.handoff_rate}%</b> ·
          ${T('Avg latency', '平均耗时')}: <b style="color:var(--ink)">${d.ai.avg_latency_ms} ms</b>
        </div>
        <div class="note" style="margin-top:8px">${T('Source hit = the answer cited a knowledge base item. Low hit rate means missing knowledge.', '命中知识 = 回答引用了知识库条目。命中率低说明知识库缺内容。')}</div>
      </div>
    </div>
  </div>`;
  animateCounts();
}
window.setRange = (v) => { AN_RANGE = v; AN_FROM = ''; AN_TO = ''; viewAnalytics(); };
window.setAnDate = (k, v) => { if (k === 'from') AN_FROM = v; else AN_TO = v; AN_RANGE = 'custom'; viewAnalytics(); };
window.setAnFilter = (key, v) => {
  if (key === 'agent') AN_AGENT = v;
  else if (key === 'channel') AN_CHANNEL = v;
  else if (key === 'country') AN_COUNTRY = v;
  else if (key === 'segment') AN_SEGMENT = v;
  else if (key === 'deal') AN_DEAL = v;
  else if (key === 'tag') AN_TAG = v;
  else if (key === 'team') AN_TEAM = v;
  else if (key === 'number') AN_NUMBER = v;
  else if (key === 'opt') AN_OPT = v;
  viewAnalytics();
};
window.resetAnalytics = () => {
  AN_RANGE = '30d'; AN_AGENT = AN_CHANNEL = AN_COUNTRY = AN_SEGMENT = AN_DEAL = AN_TAG =
    AN_TEAM = AN_NUMBER = AN_OPT = AN_FROM = AN_TO = '';
  viewAnalytics();
};
window.setAgent = (v) => { AN_AGENT = v; viewAnalytics(); };
window.setChannel = (v) => { AN_CHANNEL = v; viewAnalytics(); };

function animateCounts() {
  document.querySelectorAll('.count').forEach(el => {
    const to = +el.dataset.to || 0; let cur = 0;
    const step = Math.max(1, Math.round(to / 24));
    const id = setInterval(() => { cur = Math.min(to, cur + step); el.textContent = cur; if (cur >= to) clearInterval(id); }, 28);
  });
}

/* ---------- 模板：新建 + 来源说明 ---------- */
async function viewTemplates() {
  const { items } = await api('/api/templates');
  $('hTitle').textContent = T('Templates', '模板库');
  $('hSub').textContent = T('Created here · reviewed in Meta · only approved can send', '在这里建 · 在 Meta 审核 · 只有通过才能发');
  if (!CACHE.tpl || !items.find(t => t.id === CACHE.tpl)) CACHE.tpl = items[0] ? items[0].id : null;
  const sel = items.find(t => t.id === CACHE.tpl) || items[0];
  const canEdit = ME.role !== 'agent';
  $('body').innerHTML = `
    <div class="col-list">
      <div class="toolbar"><div class="searchbox">🔍 ${T('Search templates', '搜索模板')}</div>
        ${canEdit ? `<span class="btn gold" style="justify-content:center" onclick="newTemplate()">＋ ${T('New template', '新建模板')}</span>` : ''}
      </div>
      ${items.map(t => `<div class="row ${sel && t.id === sel.id ? 'on' : ''}" onclick="pickTpl(${t.id})">
        <div style="min-width:0;flex:1"><div class="nm">${esc(t.name)}</div>
          <div class="mt">${esc(t.category)} · ${esc(t.language)}</div></div>
        <div style="flex:none">${chipTpl(t.status)}</div></div>`).join('')}
    </div>
    <div class="col-main">
      ${sel ? `
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
        <div style="font-size:19px;font-weight:800">${esc(sel.name)}</div>${chipTpl(sel.status)}
        <div style="margin-left:auto;display:flex;gap:8px">
          ${ME.role === 'owner' ? `
            <span class="btn" onclick="setTplStatus(${sel.id},'approved')">${T('Mark approved', '标为通过')}</span>
            <span class="btn" onclick="setTplStatus(${sel.id},'rejected')">${T('Mark rejected', '标为被拒')}</span>` : ''}
          ${ME.role === 'owner' ? `<span class="btn" onclick="syncTemplates()">${T('Sync from Meta', '同步 Meta 状态')}</span>` : ''}
          <span class="btn gold" onclick="useTpl(${sel.id})">${T('Use this template', '用它发一批')}</span>
        </div>
      </div>
      <div class="grid2">
        <div class="card"><h3>${T('Preview', '模板内容')}</h3>
          <div class="phone"><div class="bubble">${esc(sel.body).replace(/\{\{(\d)\}\}/g, '<span class="var">{{$1}}</span>')}</div></div>
          <div style="margin-top:13px;font-size:12px;color:var(--sub);line-height:1.9">
            ${T('Variables are filled per contact at send time.', '变量在发送时按客户自动填充。')}</div>
        </div>
        <div class="card"><h3>${T('Details', '详情')}</h3>
          <dl class="dl"><dt>${T('Category', '分类')}</dt><dd>${esc(sel.category)}</dd>
            <dt>${T('Language', '语言')}</dt><dd>${esc(sel.language)}</dd>
            <dt>${T('Status', '状态')}</dt><dd>${chipTpl(sel.status)}</dd>
            <dt>${T('Created', '创建')}</dt><dd>${esc((sel.created_at || '').slice(0, 10))}</dd></dl>
          <div class="note" style="margin-top:12px">${T("Templates are written here, then submitted in Meta's WhatsApp Manager for review. This page records the result.", '模板在这里写，然后到 Meta 的 WhatsApp Manager 提交审核，这里只记录审核结果。')}</div>
        </div>
      </div>` : `<div class="loading">${T('No templates yet — create one', '还没有模板，先建一个')}</div>`}
    </div>`;
}

window.newTemplate = () => {
  $('modal').innerHTML = `
    <h2>${T('New template', '新建模板')}</h2>
    <p class="s">${T('Create it here, then submit the same text in WhatsApp Manager for review.', '在这里建好，再把同样内容提交到 WhatsApp Manager 审核。')}</p>
    <div class="field"><label>${T('Name', '名称')}</label><input id="ntName" class="inp" style="width:100%" placeholder="${T('e.g. Win-back · Q4', '例如：Q4 老客召回')}"></div>
    <div class="grid2">
      <div class="field"><label>${T('Category', '分类')}</label>
        <select id="ntCat" class="inp" style="width:100%"><option>Marketing</option><option>Utility</option></select></div>
      <div class="field"><label>${T('Language', '语言')}</label>
        <select id="ntLang" class="inp" style="width:100%"><option>English</option><option>Arabic</option><option>Spanish</option><option>Russian</option><option>Multi</option></select></div>
    </div>
    <div class="field"><label>${T('Body (use {{1}} {{2}} for variables)', '正文（用 {{1}} {{2}} 表示变量）')}</label>
      <textarea id="ntBody" class="inp" style="width:100%;height:120px"></textarea></div>
    <div class="acts"><span class="btn" onclick="closeDeal()">${T('Cancel', '取消')}</span>
      <span class="btn gold" onclick="saveTemplate()">${T('Create', '创建')}</span></div>`;
  $('mask').classList.add('on');
};
window.saveTemplate = async () => {
  try {
    const r = await api('/api/templates', { method: 'POST', body: JSON.stringify({
      name: $('ntName').value, category: $('ntCat').value, language: $('ntLang').value, body: $('ntBody').value }) });
    closeDeal(); CACHE.tpl = r.id; toast(T('Created · pending review', '已创建 · 待审核')); viewTemplates();
  } catch (e) { toast(e.message); }
};

/* ---------- 设置：团队操作 / AI Key / 人话标签 ---------- */
const NOTIFY_LABEL = {
  template_review: ['Template approved or rejected', '模板通过或被拒'],
  quality_drop: ['Number quality drops', '号码质量下降'],
  daily_digest: ['Daily digest at 09:00', '每日 09:00 汇总'],
  new_reply: ['New inbound reply', '有新客户回复'],
  campaign_done: ['Campaign finished', '触达任务完成'],
};
const CHANNEL_LABEL = {
  website: ['Website forms', '网站表单'],
  facebook: ['Facebook Lead Ads', 'Facebook 广告线索'],
  instagram: ['Instagram DMs', 'Instagram 私信'],
  webhook: ['Webhook to your ERP', 'Webhook 推送到 ERP'],
};
const CHANNEL_STATUS = {
  connected: ['Connected', '已连接'],
  pending: ['Waiting for authorisation', '等待授权'],
  none: ['Not set up', '未配置'],
};

function settingsPanel(s, users) {
  const card = (t, h) => `<div class="card" style="margin-bottom:14px"><h3>${t}</h3>${h}</div>`;
  const w = s.workspace || {}, c = s.compliance || {}, a = s.ai || {}, n = s.notify || {}, ch = s.channels || {};
  const ro = ME.role !== 'owner' ? 'disabled' : '';
  switch (SET_TAB) {
    case 'workspace': return card(T('Workspace', '工作区'), `
      <div class="grid2">
        <div class="field"><label>${T('Workspace name', '工作区名称')}</label><input class="inp" id="wsName" style="width:100%" value="${esc(w.name || '')}" ${ro}></div>
        <div class="field"><label>${T('Timezone', '时区')}</label><input class="inp" id="wsTz" style="width:100%" value="${esc(w.timezone || '')}" ${ro}></div>
        <div class="field"><label>${T('Working hours', '工作时间')}</label><input class="inp" id="wsHours" style="width:100%" value="${esc(w.hours || '')}" ${ro}></div>
        <div class="field"><label>${T('Interface language', '界面语言')}</label><div class="inp">${T('Switch in header', '右上角切换')}</div></div>
      </div>
      ${ME.role === 'owner' ? `<span class="btn gold" onclick="saveWorkspace()">${T('Save', '保存')}</span>` : ''}`);

    case 'team': return card(T('Team & roles', '团队与权限'), `
      <table><thead><tr><th>${T('Member', '成员')}</th><th>${T('Role', '角色')}</th><th>${T('Contacts', '负责客户')}</th>
        <th>${T('Status', '状态')}</th><th style="text-align:right">${T('Actions', '操作')}</th></tr></thead>
      <tbody>${(users.items || []).map(u => `<tr>
        <td><b>${esc(u.name)}</b><div style="color:var(--sub);font-size:11.5px">${esc(u.email)}</div></td>
        <td><span class="chip c-gray">${T({owner:'Owner',manager:'Manager',agent:'Agent'}[u.role], {owner:'老板',manager:'主管',agent:'销售'}[u.role])}</span></td>
        <td class="mono">—</td>
        <td>${u.active ? `<span class="chip c-ok">${T('Active', '在职')}</span>` : `<span class="chip c-gray">${T('Disabled', '已停用')}</span>`}</td>
        <td style="text-align:right;white-space:nowrap">
          <span class="btn sm" onclick="toggleUser(${u.id}, ${u.active ? 0 : 1})">${u.active ? T('Disable', '停用') : T('Enable', '启用')}</span>
          <span class="btn sm" onclick="transferUser(${u.id})">${T('Transfer', '转移客户')}</span>
          <span class="btn sm" onclick="removeUser(${u.id})">${T('Delete', '删除')}</span>
        </td></tr>`).join('') || `<tr><td colspan="5">${T('Only owners can see the full list', '只有老板能看全部成员')}</td></tr>`}</tbody></table>
      <div class="note" style="margin-top:12px">
        ${T('Disable = the person can no longer log in, but their history stays. Transfer = move all contacts and conversations to another agent. Delete = only when they own nothing.',
            '停用＝此人不能登录，历史保留；转移＝把他名下客户和会话整体交给别人；删除＝名下没有客户时才能删。')}
      </div>`);

    case 'compliance': return card(T('Compliance', '合规设置'), `
      <table><tbody>
        <tr><td>${T('Opt-in required before marketing', '营销前必须授权')}</td><td style="text-align:right"><span class="chip c-ok">${T('Always on', '始终开启')}</span></td></tr>
        <tr><td>${T('Opt-out handling', '退订处理')}</td><td style="text-align:right"><span class="chip c-ok">${T('Permanent block', '永久拉黑')}</span></td></tr>
        <tr><td>${T('Service window', '客服窗口')}</td><td style="text-align:right">${c.window_hours || 24} ${T('hours', '小时')}</td></tr>
        <tr><td>${T('Message retention', '消息留存')}</td><td style="text-align:right">${c.retention_months || 24} ${T('months', '个月')}</td></tr>
      </tbody></table>
      <div class="note" style="margin-top:12px">${T('These are enforced in code, not by a checklist.', '这些是代码层面的硬规则，不靠人工检查。')}</div>`);

    case 'ai': return card(T('AI assistant', 'AI 助手'), `
      <div class="grid2">
        <div class="field"><label>${T('Provider', '模型服务商')}</label>
          <select id="aiProvider" class="inp" style="width:100%" ${ro}>
            ${[['volcengine','火山方舟 / Doubao'],['openai','OpenAI'],['anthropic','Anthropic'],['custom','自定义']]
              .map(([k, n2]) => `<option value="${k}" ${a.provider === k ? 'selected' : ''}>${n2}</option>`).join('')}
          </select></div>
        <div class="field"><label>${T('Model', '模型')}</label>
          <input id="aiModel" class="inp" style="width:100%" value="${esc(a.model || '')}" ${ro}></div>
      </div>
      <div class="field"><label>${T('API key', 'API Key')}</label>
        <input id="aiKey" class="inp" style="width:100%" placeholder="${a.api_key_set ? T('Saved — type a new key to replace', '已保存 — 输入新 Key 可替换') : T('Paste your key', '粘贴你的 Key')}" ${ro}>
        <div style="font-size:11.5px;color:var(--sub);margin-top:6px">
          ${a.api_key_set ? T('Current: ', '当前：') + esc(a.api_key) + ' · ' + T('stored on your server', '存在你自己的服务器') : T('Not set', '未设置')}
        </div>
      </div>
      <div class="grid2">
        <div class="field"><label>${T('Auto-reply inside 24h window', '24 小时窗口内自动回复')}</label>
          <div class="inp">${a.auto_reply ? T('On', '开启') : T('Off', '关闭')}</div></div>
        <div class="field"><label>${T('Handoff threshold', '转人工阈值')}</label>
          <div class="inp">${T('Confidence below', '置信度低于')} ${a.handoff_threshold || 70}%</div></div>
      </div>
      ${ME.role === 'owner' ? `<span class="btn gold" onclick="saveAI()">${T('Save', '保存')}</span>
        <span class="btn" onclick="testAI()">${T('Test connection', '测试连接')}</span>` : ''}
      <div class="note" style="margin-top:12px">${T('AI never quotes prices or promises delivery dates. Those go to a human.', 'AI 不报价、不承诺交期，这两类一律转人工。')}</div>`);

    case 'notify': return card(T('Notifications', '通知'), `
      <table><tbody>${Object.entries(n).map(([k, v]) => `<tr>
        <td>${T((NOTIFY_LABEL[k] || [k, k])[0], (NOTIFY_LABEL[k] || [k, k])[1])}</td>
        <td style="text-align:right"><span class="chip ${v ? 'c-ok' : 'c-gray'}">${v ? T('On', '开') : T('Off', '关')}</span></td></tr>`).join('')}</tbody></table>
      <div class="note" style="margin-top:12px">${T('Where notifications go (email / in-app) will be set once the mail server is connected.', '通知发到哪里（邮件 / 站内）等接上邮件服务后再配。')}</div>`);

    case 'channels': return card(T('Integrations', '集成'), `
      <table><thead><tr><th>${T('Channel', '渠道')}</th><th>${T('What it does', '作用')}</th><th style="text-align:right">${T('Status', '状态')}</th></tr></thead>
      <tbody>${Object.entries(ch).map(([k, v]) => {
        const nm = CHANNEL_LABEL[k] || [k, k];
        const st = CHANNEL_STATUS[v] || [v, v];
        const cls = v === 'connected' ? 'c-ok' : v === 'pending' ? 'c-warn' : 'c-gray';
        return `<tr><td><b>${T(nm[0], nm[1])}</b></td>
          <td style="color:var(--sub);font-size:12.5px">${{
            website: T('Leads with opt-in from your site', '从网站带授权收集线索'),
            facebook: T('Sync leads from Meta ads', '同步 Meta 广告线索'),
            instagram: T('Merge Instagram DM contacts', '合并 Instagram 私信客户'),
            webhook: T('Push events to your own system', '把事件推给你自己的系统')}[k] || ''}</td>
          <td style="text-align:right"><span class="chip ${cls}">${T(st[0], st[1])}</span></td></tr>`;
      }).join('')}</tbody></table>
      <div class="note" style="margin-top:12px">${T('WhatsApp Cloud API: sandbox mode. Add credentials to switch to live sending.', 'WhatsApp Cloud API：沙盒模式。填入凭证即可切换真实发送。')}</div>`);

    case 'stages': {
      const ds = s.deal_stages || { preset: 'trade', stages: STAGES };
      return card(T('Deal stages', '成交状态'), `
        <div class="field"><label>${T('Industry preset', '行业预设')}</label>
          <select class="inp" style="width:100%" onchange="applyPreset(this.value)" ${ro}>
            ${[['trade', T('Trade / export', '外贸 · 出口')], ['partnership', T('Partnership / service', '合作 · 服务')],
               ['education', T('Education', '教育培训')], ['generic', T('Generic', '通用')]]
              .map(([k, n2]) => `<option value="${k}" ${ds.preset === k ? 'selected' : ''}>${n2}</option>`).join('')}
          </select></div>
        <table><tbody>${ds.stages.map(st => `<tr>
          <td><span class="chip ${({ok:'c-ok',bad:'c-bad',warn:'c-warn',info:'c-info',blue:'c-info',gray:'c-gray'})[st.color] || 'c-gray'}">${T(st.en, st.zh)}</span></td>
          <td class="mono" style="color:var(--sub)">${st.key}</td>
          <td style="color:var(--sub);font-size:12.5px">${st.key === ds.stages[ds.stages.length - 1].key ? T('closing (not counted as won)', '结束态（不计入成交）') : ''}</td>
        </tr>`).join('')}</tbody></table>
        <div class="note" style="margin-top:12px">${T('Different industries call it different things. Pick a preset — "won" means closed successfully in that industry.',
          '不同行业叫法不一样。"成交"在这套系统里指"这单成功落地"——外贸叫成交，合作叫签约，教育叫报名。')}</div>`);
    }
  }
}

window.createMember = async () => {
  const name = $('nuName').value.trim(), email = $('nuEmail').value.trim();
  const password = $('nuPwd').value, role = $('nuRole').value;
  if (!name || !email || password.length < 8) return toast(T('Name, email and an 8+ character password are required', '姓名、邮箱、8 位以上密码都要填'));
  try {
    await api('/api/users', { method: 'POST', body: JSON.stringify({ name, email, password, role, team: 'sales', can_reply: $('nuReply').checked }) });
    toast(T('Member created — they can log in now', '成员已创建，现在就能登录'));
    viewSettings();
  } catch (e) {
    toast(e.message === 'email already exists' ? T('This email is already used', '这个邮箱已经用过了') : e.message);
  }
};
window.toggleReply = async (id, current) => {
  try { await api(`/api/users/${id}/reply`, { method: 'POST', body: JSON.stringify({ can_reply: !current }) });
    toast(!current ? T('This member can reply again', '已允许该成员回复') : T('Switched to read-only', '已改为只读账号')); viewSettings();
  } catch (e) { toast(e.message); }
};
window.toggleUser = async (id, active) => {
  await api(`/api/users/${id}/status`, { method: 'POST', body: JSON.stringify({ active }) });
  toast(active ? T('Enabled', '已启用') : T('Disabled', '已停用')); viewSettings();
};
window.transferUser = async (id) => {
  const users = await api('/api/users');
  const others = users.items.filter(u => u.id !== id && u.active);
  const list = others.map(u => `${u.id}: ${u.name}`).join('\n');
  const to = prompt(T('Transfer all contacts to which user?\n' + list, '把客户转给谁？输入用户 ID：\n' + list));
  if (!to) return;
  try {
    const r = await api(`/api/users/${id}/transfer`, { method: 'POST', body: JSON.stringify({ to_user_id: +to }) });
    toast(T(`Moved ${r.moved} contacts`, `已转移 ${r.moved} 个客户`)); viewSettings();
  } catch (e) { toast(e.message); }
};
window.removeUser = async (id) => {
  if (!confirm(T('Delete this member? Only possible when they own no contacts.', '确认删除该成员？名下没有客户才能删。'))) return;
  try { await api(`/api/users/${id}`, { method: 'DELETE' }); toast(T('Deleted', '已删除')); viewSettings(); }
  catch (e) { toast(e.message); }
};
window.saveAI = async () => {
  try {
    await api('/api/settings', { method: 'PATCH', body: JSON.stringify({ ai: {
      provider: $('aiProvider').value, model: $('aiModel').value, api_key: $('aiKey').value } }) });
    toast(T('Saved', '已保存')); viewSettings();
  } catch (e) { toast(e.message); }
};
window.testAI = () => toast(T('Sandbox: connection test needs a key and outbound network.', '沙盒：测试连接需要 Key 和外网。'));
window.applyPreset = async (p) => {
  const PRESETS = {
    trade: [['Lead','Lead','线索','gray'],['Contacted','Contacted','已联系','blue'],['Quoted','Quoted','已报价','info'],
            ['Negotiating','Negotiating','谈判中','warn'],['Won','Closed','已成交','ok'],['Lost','Lost','已丢单','bad']],
    partnership: [['Lead','Lead','线索','gray'],['Contacted','Contacted','已接洽','blue'],['Proposal','Proposal','方案中','info'],
                  ['Signed','Signed','已签约','warn'],['Active','Active','合作中','ok'],['Renewed','Renewed','已续约','ok'],['Lost','Lost','已终止','bad']],
    education: [['Lead','Lead','咨询','gray'],['Contacted','Contacted','已联系','blue'],['Trial','Trial','已试听','info'],
                ['Enrolled','Enrolled','已报名','warn'],['Active','Active','在读','ok'],['Renewed','Renewed','已续报','ok'],['Lost','Lost','流失','bad']],
    generic: [['Lead','Lead','线索','gray'],['Contacted','Contacted','已联系','blue'],['Qualified','Qualified','已确认','info'],
              ['Won','Won','成功','ok'],['Lost','Lost','失败','bad']],
  };
  const stages = PRESETS[p].map(([key, en, zh, color]) => ({ key, en, zh, color }));
  await api('/api/settings', { method: 'PATCH', body: JSON.stringify({ deal_stages: { preset: p, stages } }) });
  await loadStages(); toast(T('Preset applied', '已切换预设')); viewSettings();
};

/* ================= V3：号码 / 集成 / 审计 / 退订 ================= */
function settingsPanel(s, users) {
  const card = (t, h) => `<div class="card" style="margin-bottom:14px"><h3>${t}</h3>${h}</div>`;
  const w = s.workspace || {}, c = s.compliance || {}, a = s.ai || {}, n = s.notify || {}, ch = s.channels || {};
  const ro = ME.role !== 'owner' ? 'disabled' : '';
  const CH_META = {
    website:   [T('Website forms', '网站表单'),   T('Leads with opt-in from your site', '从网站带授权收集线索'), 'app_id'],
    facebook:  [T('Facebook Lead Ads', 'Facebook 广告线索'), T('Sync leads from Meta ads', '同步 Meta 广告线索'), 'app_id'],
    instagram: [T('Instagram DMs', 'Instagram 私信'), T('Merge Instagram DM contacts', '合并 Instagram 私信客户'), 'app_id'],
    webhook:   [T('Webhook to your ERP', 'Webhook 推送到 ERP'), T('Push events to your own system', '把事件推给你自己的系统'), 'url'],
  };
  switch (SET_TAB) {
    case 'workspace': return card(T('Workspace', '工作区'), `
      <div class="grid2">
        <div class="field"><label>${T('Workspace name', '工作区名称')}</label><input class="inp" id="wsName" style="width:100%" value="${esc(w.name || '')}" ${ro}></div>
        <div class="field"><label>${T('Timezone', '时区')}</label><input class="inp" id="wsTz" style="width:100%" value="${esc(w.timezone || '')}" ${ro}></div>
        <div class="field"><label>${T('Working hours', '工作时间')}</label><input class="inp" id="wsHours" style="width:100%" value="${esc(w.hours || '')}" ${ro}></div>
        <div class="field"><label>${T('Interface language', '界面语言')}</label><div class="inp">${T('Switch in header', '右上角切换')}</div></div>
      </div>
      ${ME.role === 'owner' ? `<span class="btn gold" onclick="saveWorkspace()">${T('Save', '保存')}</span>` : ''}
      <div class="hr"></div>
      <div style="display:flex;gap:8px;align-items:center">
        <span class="btn" onclick="exportCsv()">${T('Export contacts (CSV)', '导出联系人 CSV')}</span>
        <span class="btn" onclick="alert('${T('Backup = copy data/app.db', '备份＝复制 data/app.db 这一个文件')}')">${T('How to back up?', '怎么备份？')}</span>
      </div>`);

    case 'pool': return poolPanel(s.pool || {});

    case 'routing': return routingPanel();

    case 'tags': return tagsPanel();

    case 'numbers': return numbersPanel();

    case 'audit': return auditPanel();

    case 'channels': return card(T('Integrations', '集成'), `
      <div class="note" style="margin-bottom:14px">${T('Fill in the credentials here. Empty means not configured. Secrets are masked after saving.',
        '在这里填凭据。留空就是未配置；密钥保存后只显示前后几位。')}</div>
      ${(() => { const wa = ch.whatsapp || {};
        return `<div class="card" style="margin-bottom:12px;background:#FBFCFE">
          <h3 style="margin-bottom:8px">${T('WhatsApp Cloud API', 'WhatsApp 云接口')}
            <span class="chip ${wa.status === 'connected' ? 'c-ok' : 'c-gray'}">${wa.status === 'connected'
              ? T('Connected', '已连接') : T('Not set', '未配置')}</span></h3>
          <div style="font-size:12.5px;color:var(--sub);margin-bottom:10px">${T(
            'This is the channel that pulls your company numbers. Credentials are filled in the Numbers page.',
            '这条通道对应你公司的 WhatsApp 号码。凭证在「号码管理」里填。')}</div>
          <div class="grid2">
            <div class="field"><label>WABA ID</label>
              <div class="inp" style="width:100%">${esc(wa.waba_id || T('Not set', '未设置'))}</div></div>
            <div class="field"><label>${T('Access token', '访问令牌')}</label>
              <div class="inp" style="width:100%">${wa.token_set ? T('Saved (masked)', '已保存（打码）') : T('Not set', '未设置')}</div></div>
            <div class="field"><label>${T('Webhook URL', 'Webhook 回调地址')}</label>
              <div class="inp" style="width:100%">${esc(location.origin)}/webhook/whatsapp</div></div>
            <div class="field"><label>${T('Verify token', '校验 token')}</label>
              <input id="waVerify" class="inp" style="width:100%" placeholder="${wa.verify_token ? T('Saved (leave blank to keep)', '已保存（留空不改）') : T('Not set', '未设置')}" ${ro}></div>
            <div class="field"><label>${T('App secret', '应用密钥')}</label>
              <input id="waSecret" class="inp" style="width:100%" placeholder="${wa.app_secret ? T('Saved (leave blank to keep)', '已保存（留空不改）') : T('Not set', '未设置')}" ${ro}></div>
          </div>
          ${ME.role === 'owner' ? `<span class="btn sm gold" onclick="saveWhatsApp()">${T('Save webhook settings', '保存 Webhook 设置')}</span>
          <span class="btn sm" onclick="setTab('numbers'); syncNumbersUI()">⟳ ${T('Sync numbers from Meta', '从 Meta 同步号码')}</span>` : ''}
        </div>`; })()}
      ${Object.entries(ch).filter(([k]) => k !== 'whatsapp').map(([k, v]) => {
        const meta = CH_META[k] || [k, '', 'app_id'];
        const sec = v.secret || '';
        return `<div class="card" style="margin-bottom:12px;background:#FBFCFE">
          <h3 style="margin-bottom:8px">${meta[0]} <span class="chip ${v.status === 'connected' ? 'c-ok' : v.status === 'pending' ? 'c-warn' : 'c-gray'}">
            ${{connected:T('Connected','已连接'),pending:T('Waiting','等待授权'),none:T('Not set','未配置')}[v.status] || v.status}</span></h3>
          <div style="font-size:12.5px;color:var(--sub);margin-bottom:10px">${meta[1]}</div>
          <div class="grid2">
            <div class="field"><label>${meta[2] === 'url' ? T('Endpoint URL', '回调地址') : T('App ID', 'App ID')}</label>
              <input class="inp" id="ch_${k}_id" style="width:100%" value="${esc(v.app_id || v.url || '')}" ${ro}></div>
            <div class="field"><label>${T('Secret / verify token', '密钥 / 校验 token')}</label>
              <input class="inp" id="ch_${k}_secret" style="width:100%" placeholder="${sec ? esc(sec) : T('Not set', '未设置')}" ${ro}></div>
          </div>
          <div class="field"><label>${T('Status', '状态')}</label>
            <select class="inp" id="ch_${k}_status" style="width:100%" ${ro}>
              ${[['connected',T('Connected','已连接')],['pending',T('Waiting','等待授权')],['none',T('Not set','未配置')]]
                .map(([val, lbl]) => `<option value="${val}" ${v.status === val ? 'selected' : ''}>${lbl}</option>`).join('')}
            </select></div>
          ${ME.role === 'owner' ? `<span class="btn sm gold" onclick="saveChannel('${k}')">${T('Save', '保存')}</span>` : ''}
        </div>`;
      }).join('')}
      <div class="note">${T('Other channels are optional. Leads from forms and ads can also be imported as CSV if you prefer.', '其他渠道都是可选的。表单和广告线索嫌麻烦，也可以先用 CSV 导入。')}</div>`);

    case 'ai': return aiInsightsPanel();

    case 'notify': return card(T('Notifications', '通知'), `
      <table><tbody>${Object.entries(n).map(([k, v]) => `<tr>
        <td>${T((NOTIFY_LABEL[k] || [k, k])[0], (NOTIFY_LABEL[k] || [k, k])[1])}
          <div style="font-size:11.5px;color:var(--sub)">${{
            template_review: T('When a template is approved or rejected by Meta', '模板被 Meta 通过或被拒时'),
            quality_drop: T('When a number quality rating drops', '号码质量评级下降时'),
            daily_digest: T('A summary of yesterday, every morning', '每天早上一封昨天的汇总'),
            new_reply: T('When a customer replies to any number', '任一号码收到客户回复时'),
            campaign_done: T('When a campaign finishes sending', '触达任务发送完成时')}[k] || ''}</div></td>
        <td style="text-align:right"><span class="chip ${v ? 'c-ok' : 'c-gray'}" style="cursor:pointer"
          onclick="toggleNotify('${k}', ${v ? 1 : 0})">${v ? T('On', '开') : T('Off', '关')}</span></td></tr>`).join('')}</tbody></table>
      <div class="note" style="margin-top:12px">${T('Click a switch to change it. Email delivery needs an SMTP server — until then these only affect in-app badges.',
        '点开关就能切换。邮件发送需要先配 SMTP 服务器；在那之前只影响站内提示。')}</div>`);

    case 'compliance': return card(T('Compliance', '合规设置'), `
      <table><tbody>
        <tr><td>${T('Opt-in required before marketing', '营销前必须授权')}</td>
          <td style="text-align:right"><span class="chip c-ok">${T('Always on · cannot be turned off', '始终开启 · 不可关闭')}</span></td></tr>
        <tr><td>${T('Opt-out handling', '退订处理')}</td>
          <td style="text-align:right"><span class="chip c-ok">${T('Auto-detect + permanent block', '自动识别 + 永久拉黑')}</span></td></tr>
        <tr><td>${T('Opt-out keywords', '退订关键词')}</td>
          <td style="text-align:right"><input class="inp" id="cfKeywords" style="width:340px;display:inline-flex"
            value="${esc((c.keywords || ['STOP','退订','取消订阅','unsubscribe']).join(' / '))}" ${ro}></td></tr>
        <tr><td>${T('Service window (hours)', '客服窗口（小时）')}</td>
          <td style="text-align:right"><input class="inp" id="cfWindow" type="number" style="width:110px;display:inline-flex"
            value="${c.window_hours || 24}" ${ro}></td></tr>
        <tr><td>${T('Message retention (months)', '消息留存（月）')}</td>
          <td style="text-align:right"><input class="inp" id="cfRetention" type="number" style="width:110px;display:inline-flex"
            value="${c.retention_months || 24}" ${ro}></td></tr>
      </tbody></table>
      ${ME.role === 'owner' ? `<div style="margin-top:12px"><span class="btn gold" onclick="saveCompliance()">${T('Save', '保存')}</span></div>` : ''}
      <div class="note" style="margin-top:12px">${T('Opt-in and opt-out are enforced in code and cannot be switched off. Window and retention are yours to set.',
        '授权与退订是代码层面的硬规则，不能关闭；窗口和留存时长你可以自己定。')}</div>`);

    case 'team': return card(T('Team & roles', '团队与权限'), `
      <div class="note" style="margin-bottom:14px">${T(
        'Members are accounts inside this system — you create them here. WhatsApp does not provide a staff list; a number only tells you which company number a message came in on, not who handles it.',
        '成员是本系统里的账号，在这里自己添加。WhatsApp 不会给我们员工名单——号码只代表消息进的是哪个公司的号，不代表是谁在处理。')}</div>
      <div style="background:#F8FAFD;border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-bottom:16px">
        <div style="font-weight:700;font-size:12.5px;margin-bottom:10px">${T('Add a member', '添加成员')}</div>
        <div class="grid2">
          <div class="field"><label>${T('Name', '姓名')}</label><input id="nuName" class="inp" style="width:100%" placeholder="${T('e.g. Wang Jie', '例如：王杰')}"></div>
          <div class="field"><label>${T('Login email', '登录邮箱')}</label><input id="nuEmail" class="inp" style="width:100%" placeholder="name@company.com"></div>
          <div class="field"><label>${T('Initial password (8+ chars)', '初始密码（至少 8 位）')}</label><input id="nuPwd" class="inp" type="text" style="width:100%" placeholder="••••••••"></div>
          <div class="field"><label>${T('Role', '角色')}</label><select id="nuRole" class="inp" style="width:100%">
            <option value="agent">${T('Sales — sees only their own contacts', '销售 — 只看自己名下')}</option>
            <option value="manager">${T('Manager — sees their team', '主管 — 看本组')}</option>
            <option value="owner">${T('Owner — sees everything', '老板 — 看全部')}</option>
          </select></div>
        </div>
        <div class="field" style="margin-top:10px">
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
            <input id="nuReply" type="checkbox" checked style="width:16px;height:16px">
            ${T('This member can reply to customers (untick for a read-only account)', '这个成员可以回复客户（不勾＝只读账号，只能看不能发）')}
          </label>
        </div>
        ${ME.role === 'owner' ? `<span class="btn gold" onclick="createMember()">＋ ${T('Create member', '创建成员')}</span>`
          : `<div class="note">${T('Only the owner can add members.', '只有老板能添加成员。')}</div>`}
      </div>
      <table><thead><tr><th>${T('Member', '成员')}</th><th>${T('Role', '角色')}</th><th>${T('Can reply', '回复权限')}</th><th>${T('Contacts', '负责客户')}</th><th>${T('Status', '状态')}</th><th style="text-align:right">${T('Actions', '操作')}</th></tr></thead>
      <tbody>${(users.items || []).map(u => `<tr>
        <td><b>${esc(u.name)}</b><div style="color:var(--sub);font-size:11.5px">${esc(u.email)}</div></td>
        <td><span class="chip c-gray">${T({owner:'Owner',manager:'Manager',agent:'Agent'}[u.role], {owner:'老板',manager:'主管',agent:'销售'}[u.role])}</span></td>
        <td>${u.can_reply === 0
          ? `<span class="chip c-warn" style="cursor:pointer" onclick="toggleReply(${u.id}, 0)">🔒 ${T('Read-only', '只读')}</span>`
          : `<span class="chip c-ok" style="cursor:pointer" onclick="toggleReply(${u.id}, 1)">✎ ${T('Can reply', '可回复')}</span>`}</td>
        <td class="mono">${u.contacts != null ? u.contacts : '—'}</td>
        <td>${u.active ? `<span class="chip c-ok">${T('Active', '在职')}</span>` : `<span class="chip c-gray">${T('Disabled', '已停用')}</span>`}</td>
        <td style="text-align:right;white-space:nowrap">
          <span class="btn sm" onclick="toggleUser(${u.id}, ${u.active ? 0 : 1})">${u.active ? T('Disable', '停用') : T('Enable', '启用')}</span>
          <span class="btn sm" onclick="transferUser(${u.id})">${T('Transfer', '转移客户')}</span>
          <span class="btn sm" onclick="removeUser(${u.id})">${T('Delete', '删除')}</span>
        </td></tr>`).join('')}</tbody></table>
      <div class="note" style="margin-top:12px">${T('Disable = cannot log in, history kept. Transfer = move contacts and conversations. Delete = only when owning nothing.',
        '停用＝不能登录，历史保留；转移＝客户和会话整体移交；删除＝名下没有客户才能删。')}</div>`);

    case 'stages': {
      const ds = s.deal_stages || { preset: 'trade', stages: STAGES };
      return card(T('Deal stages', '成交状态'), `
        <div class="field"><label>${T('Industry preset', '行业预设')}</label>
          <select class="inp" style="width:100%" onchange="applyPreset(this.value)" ${ro}>
            ${[['trade', T('Trade / export', '外贸 · 出口')], ['partnership', T('Partnership / service', '合作 · 服务')],
               ['education', T('Education', '教育培训')], ['generic', T('Generic', '通用')]]
              .map(([k, n2]) => `<option value="${k}" ${ds.preset === k ? 'selected' : ''}>${n2}</option>`).join('')}
          </select></div>
        <table><tbody>${ds.stages.map(st => `<tr>
          <td><span class="chip ${({ok:'c-ok',bad:'c-bad',warn:'c-warn',info:'c-info',blue:'c-info',gray:'c-gray'})[st.color] || 'c-gray'}">${T(st.en, st.zh)}</span></td>
          <td class="mono" style="color:var(--sub)">${st.key}</td></tr>`).join('')}</tbody></table>
        <div class="note" style="margin-top:12px">${T('"Closed" means the deal landed in that industry — a sale, a signed contract, an enrolment.',
          '"成交"指这单成功落地——外贸叫成交，合作叫签约，教育叫报名。')}</div>`);
    }
  }
  return '';
}

/* ---------- 号码管理 ---------- */
async function numbersPanel() {
  const { items } = await api('/api/numbers');
  const Q = { high: T('High', '高'), medium: T('Medium', '中'), low: T('Low', '低'), unknown: T('Unknown', '未知') };
  const S = { connected: T('Connected', '已接入'), cooling: T('Cooling down', '冷却中'), disconnected: T('Disconnected', '已断开') };
  return `
    <div class="card"><h3>${T('WhatsApp numbers', 'WhatsApp 号码')}
      ${ME.role === 'owner' ? `<span style="display:flex;gap:8px">
        <span class="btn sm" onclick="syncNumbersUI()">⟳ ${T('Sync from Meta', '从 Meta 同步')}</span>
        <span class="btn sm gold" onclick="newNumber()">＋ ${T('Add number', '添加号码')}</span></span>` : ''}</h3>
      <div class="note" style="margin-bottom:14px">${T(
        'A number here is a company WhatsApp number (a channel). A member is a person who logs in. They are different things: one number can be handled by many members, and one member can use several numbers — no conflict.',
        '这里的“号码”是公司的一个 WhatsApp 号码（一条收发通道）；“团队”是能登录后台的人。两者是两回事：一个号码可以很多人一起接待，一个人也可以用多个号码，不冲突。')}</div>
      <table><thead><tr><th>${T('Number', '号码')}</th><th>${T('Purpose', '用途')}</th>
        <th>${T('WABA', 'WABA ID')}</th><th>${T('Quality', '质量')}</th><th>${T('Today', '今日')}</th>
        <th>${T('Status', '状态')}</th><th>${T('Connection', '接入方式')}</th><th></th></tr></thead>
      <tbody>${items.map(n => `<tr>
        <td><b>${esc(n.label)}</b><div class="mono" style="font-size:11.5px;color:var(--sub)">${esc(n.phone)}</div></td>
        <td>${esc(n.purpose || '')}</td>
        <td class="mono" style="font-size:11.5px">${esc(n.waba_id || '—')}</td>
        <td><span class="chip ${n.quality === 'high' ? 'c-ok' : n.quality === 'medium' ? 'c-warn' : 'c-gray'}">${Q[n.quality] || n.quality}</span></td>
        <td class="mono">${n.sent_today} / ${n.daily_limit}</td>
        <td><span class="chip ${n.status === 'connected' ? 'c-ok' : n.status === 'cooling' ? 'c-warn' : 'c-bad'}">${S[n.status] || n.status}</span></td>
        <td>${ME.role === 'owner' ? `<select style="height:28px;border:1px solid var(--line);border-radius:7px;font-size:12px;background:#fff"
          onchange="setNumberMode(${n.id}, this.value)">
          <option value="sandbox" ${(n.access_mode || 'sandbox') === 'sandbox' ? 'selected' : ''}>${T('Sandbox (no real sending)', '沙盒（不真发）')}</option>
          <option value="cloud" ${n.access_mode === 'cloud' ? 'selected' : ''}>${T('Cloud API only', '只接 Cloud API')}</option>
          <option value="coexist" ${n.access_mode === 'coexist' ? 'selected' : ''}>${T('Coexistence (App + API)', '共存（App + API）')}</option>
        </select>` : `<span class="chip c-gray">${{ sandbox: T('Sandbox', '沙盒'), cloud: 'Cloud API', coexist: T('Coexistence', '共存') }[n.access_mode || 'sandbox']}</span>`}</td>
        <td style="text-align:right">${ME.role === 'owner' ? `<span class="btn sm" onclick="delNumber(${n.id})">${T('Remove', '删除')}</span>` : ''}</td>
      </tr>`).join('') || `<tr><td colspan="7" style="color:var(--sub)">${T('No numbers yet', '还没有号码')}</td></tr>`}</tbody></table>
      <div class="note" style="margin-top:12px">${T('WABA ID and Phone Number ID come from Meta. Fill them to switch this number from sandbox to live sending. Or click "Sync from Meta" to pull every number under a WABA in one go.',
        'WABA ID 和 Phone Number ID 由 Meta 提供。填上之后，这个号码才会从沙盒切成真实发送；也可以点「从 Meta 同步」，把一个 WABA 下的号码一次性拉过来。')}</div>
      <div class="note" style="margin-top:8px">${T('Coexistence means the phone still runs WhatsApp Business while the API is connected: staff reply in this system, the boss can watch on the phone. App-sent messages come back through the webhook and are marked "via App".',
        '共存＝手机上继续用 WhatsApp Business，同时接上 API：员工在这里回复，老板可以在手机上看。手机 App 发出的消息会通过回调同步进来，标记为「手机 App」。')}</div>
    </div>`;
}
window.newNumber = () => {
  $('modal').innerHTML = `
    <h2>${T('Add WhatsApp number', '添加 WhatsApp 号码')}</h2>
    <p class="s">${T('Sandbox until WABA ID and Phone Number ID are filled.', '填 WABA 凭证之前是沙盒状态。')}</p>
    <div class="grid2">
      <div class="field"><label>${T('Label', '名称')}</label><input id="nbLabel" class="inp" style="width:100%" placeholder="UAE sales"></div>
      <div class="field"><label>${T('Phone', '号码')}</label><input id="nbPhone" class="inp" style="width:100%" placeholder="+971 50 ..."></div>
    </div>
    <div class="grid2">
      <div class="field"><label>WABA ID</label><input id="nbWaba" class="inp" style="width:100%"></div>
      <div class="field"><label>Phone Number ID</label><input id="nbPnid" class="inp" style="width:100%"></div>
    </div>
    <div class="acts"><span class="btn" onclick="closeDeal()">${T('Cancel', '取消')}</span>
      <span class="btn gold" onclick="saveNumber()">${T('Add', '添加')}</span></div>`;
  $('mask').classList.add('on');
};
window.saveNumber = async () => {
  try {
    await api('/api/numbers', { method: 'POST', body: JSON.stringify({
      label: $('nbLabel').value, phone: $('nbPhone').value,
      waba_id: $('nbWaba').value, phone_number_id: $('nbPnid').value }) });
    closeDeal(); toast(T('Added', '已添加')); viewSettings();
  } catch (e) { toast(e.message); }
};
window.setNumberMode = async (nid, mode) => {
  try { await api(`/api/numbers/${nid}`, { method: 'PATCH', body: JSON.stringify({ access_mode: mode }) });
    toast(T('Connection mode updated', '接入方式已更新')); viewSettings();
  } catch (e) { toast(e.message); }
};
window.syncNumbersUI = () => {
  $('modal').innerHTML = `
    <h2>${T('Sync numbers from Meta', '从 Meta 同步号码')}</h2>
    <p class="s">${T('Uses the WhatsApp Cloud API. The token needs access to this WABA.',
      '走 WhatsApp Cloud API。Token 需要有这个 WABA 的权限。')}</p>
    <div class="field"><label>WABA ID</label><input id="syWaba" class="inp" style="width:100%" placeholder="102xxxxxxxxxxxx"></div>
    <div class="field"><label>${T('Access token', '访问令牌')}</label><input id="syToken" class="inp" style="width:100%" placeholder="EAAG..."></div>
    <div class="note">${T('The token is stored server-side and only shown masked.',
      '令牌存在服务端，页面上只显示打码后的样子。')}</div>
    <div class="acts"><span class="btn" onclick="closeDeal()">${T('Cancel', '取消')}</span>
      <span class="btn gold" onclick="syncNumbers()">${T('Sync now', '开始同步')}</span></div>`;
  $('mask').classList.add('on');
};
window.syncNumbers = async () => {
  try {
    const r = await api('/api/numbers/sync', { method: 'POST', body: JSON.stringify({
      waba_id: $('syWaba').value.trim(), access_token: $('syToken').value.trim() }) });
    closeDeal(); toast(T(`Synced ${r.total}: ${r.added} new, ${r.updated} updated`,
      `同步了 ${r.total} 个号码：新增 ${r.added}，更新 ${r.updated}`));
    viewSettings();
  } catch (e) {
    const m = e.message || '';
    toast(m === 'missing_credentials' ? T('Fill WABA ID and token first', '先填 WABA ID 和令牌')
      : m.startsWith('meta_error') ? T('Meta rejected it: ', 'Meta 返回错误：') + m.slice(11)
      : m);
  }
};
window.delNumber = async (id) => {
  if (!confirm(T('Remove this number?', '删除这个号码？'))) return;
  await api('/api/numbers/' + id, { method: 'DELETE' }); viewSettings();
};

/* ---------- 审计日志 ---------- */
async function auditPanel() {
  const { items } = await api('/api/audit?limit=80');
  const LABEL = {
    login: T('Signed in', '登录'), update_contact: T('Updated a contact', '更新客户'),
    send_message: T('Sent a message', '发送消息'), campaign_send: T('Sent a campaign', '发起触达'),
    create_template: T('Created a template', '新建模板'), template_status: T('Changed template status', '改模板状态'),
    update_settings: T('Changed settings', '改设置'), user_status: T('Enabled / disabled a member', '停用启用成员'),
    transfer_contacts: T('Transferred contacts', '转移客户'), delete_user: T('Deleted a member', '删除成员'),
    auto_optout: T('Auto opt-out (STOP received)', '自动退订（收到 STOP）'),
    set_optout: T('Manual opt-out change', '手动改退订'),
    create_number: T('Added a number', '添加号码'), update_number: T('Updated a number', '更新号码'),
    update_channels: T('Updated integrations', '更新集成'),
  };
  return `<div class="card"><h3>${T('Audit log', '操作日志')}<small>${T('latest 80', '最近 80 条')}</small></h3>
    <table><thead><tr><th style="width:140px">${T('Time', '时间')}</th><th>${T('Who', '谁')}</th>
      <th>${T('Action', '做了什么')}</th><th>${T('Target', '对象')}</th></tr></thead>
    <tbody>${items.map(a => `<tr><td class="mono">${esc((a.created_at || '').slice(5, 16))}</td>
      <td>${esc(a.user_name || T('System', '系统'))}</td>
      <td>${T(LABEL[a.action]?.[0] || a.action, LABEL[a.action]?.[1] || a.action)}</td>
      <td class="mono" style="color:var(--sub)">${esc(a.target || '')}</td></tr>`).join('')
      || `<tr><td colspan="4" style="color:var(--sub)">${T('No activity yet', '还没有记录')}</td></tr>`}</tbody></table></div>`;
}

/* ---------- 动作 ---------- */
window.saveWhatsApp = async () => {
  const body = {};
  const vt = ($('waVerify')?.value || '').trim();
  const as = ($('waSecret')?.value || '').trim();
  if (vt) body.verify_token = vt;
  if (as) body.app_secret = as;
  if (!Object.keys(body).length) return toast(T('Nothing to save', '没有可保存的内容'));
  try {
    await api('/api/settings/channels', { method: 'PATCH', body: JSON.stringify({ whatsapp: body }) });
    toast(T('Saved', '已保存')); viewSettings();
  } catch (e) { toast(e.message); }
};
window.saveChannel = async (key) => {
  const body = {}; body[key] = {
    app_id: $('ch_' + key + '_id').value, url: $('ch_' + key + '_id').value,
    secret: $('ch_' + key + '_secret').value, status: $('ch_' + key + '_status').value };
  try { await api('/api/settings/channels', { method: 'PATCH', body: JSON.stringify(body) });
    toast(T('Saved', '已保存')); viewSettings(); } catch (e) { toast(e.message); }
};
window.exportCsv = async () => {
  const res = await fetch('/api/export/contacts.csv', { headers: { Authorization: 'Bearer ' + TOKEN } });
  const blob = await res.blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = 'contacts.csv'; a.click();
  toast(T('Downloaded', '已下载'));
};
window.syncTemplates = async () => {
  try { await api('/api/templates/sync', { method: 'POST', body: '{}' }); }
  catch (e) { toast(e.message === 'meta_not_configured'
    ? T('Add WABA credentials in Numbers first', '请先在「号码管理」里填 WABA 凭证')
    : e.message); }
};
window.simulateInbound = async (cid) => {
  const text = prompt(T('Send a test inbound message:', '测试：客户发来一条消息：'), 'STOP');
  if (!text) return;
  const r = await api(`/api/conversations/${cid}/simulate-inbound`, { method: 'POST', body: JSON.stringify({ body: text }) });
  toast(r.opt_out_triggered ? T('Contact opted out automatically', '已自动标记退订') : T('Message received', '已收到消息'));
  await viewInbox();
};
window.toggleOptOut = async (cid, cur) => {
  await api(`/api/contacts/${cid}/optout`, { method: 'POST', body: JSON.stringify({ opt_out: !cur }) });
  toast(T('Updated', '已更新')); renderContact(cid);
};

/* ---------- 合规 / 通知 保存 ---------- */
window.saveCompliance = async () => {
  try {
    await api('/api/settings', { method: 'PATCH', body: JSON.stringify({ compliance: {
      opt_in_required: true, optout_permanent: true,
      keywords: $('cfKeywords').value.split('/').map(s => s.trim()).filter(Boolean),
      window_hours: +$('cfWindow').value || 24,
      retention_months: +$('cfRetention').value || 24 } }) });
    toast(T('Saved', '已保存')); viewSettings();
  } catch (e) { toast(e.message); }
};
window.toggleNotify = async (key, cur) => {
  try {
    const s = await api('/api/settings');
    const n = { ...(s.notify || {}), [key]: !cur };
    await api('/api/settings', { method: 'PATCH', body: JSON.stringify({ notify: n }) });
    toast(T('Updated', '已更新')); viewSettings();
  } catch (e) { toast(e.message); }
};


/* ---------- 下钻：任务详情 / 分层 ---------- */
window.openSegment = (id) => { CUR_SEG = id; go('segments'); };

window.openCampaign = async (id) => {
  const d = await api('/api/campaigns/' + id);
  const c = d.campaign, r = d.recipients, s = d.summary;
  $('modal').classList.add('wide');
  $('modal').innerHTML = `
    <h2 style="margin-bottom:2px">${esc(c.name)}</h2>
    <p class="s">${esc(c.segment_name || '')} · ${esc(c.template_name || '')} · ${esc((c.created_at || '').slice(0, 10))}</p>
    <div style="display:flex;gap:22px;margin-bottom:14px">
      <div><div style="font-size:11.5px;color:var(--sub)">${T('Sent', '发送')}</div><div style="font-size:22px;font-weight:800">${c.sent}</div></div>
      <div><div style="font-size:11.5px;color:var(--sub)">${T('Delivered', '送达')}</div><div style="font-size:22px;font-weight:800">${s.delivered}</div></div>
      <div><div style="font-size:11.5px;color:var(--sub)">${T('Replied', '回复')}</div><div style="font-size:22px;font-weight:800;color:var(--green)">${s.replied}</div></div>
      <div><div style="font-size:11.5px;color:var(--sub)">${T('Failed', '失败')}</div><div style="font-size:22px;font-weight:800;color:var(--red)">${s.failed}</div></div>
    </div>
    <div style="max-height:300px;overflow:auto;border:1px solid var(--line);border-radius:10px">
      <table><thead><tr><th>${T('Contact', '客户')}</th><th>${T('Country', '国家')}</th>
        <th>${T('Status', '状态')}</th><th>${T('Deal', '状态')}</th><th></th></tr></thead>
      <tbody>${r.map(x => `<tr>
        <td><b>${esc(x.name)}</b><div class="mono" style="font-size:11px;color:var(--sub)">${esc(x.phone)}</div></td>
        <td>${esc(x.country || '')}</td>
        <td>${x.status === 'replied' ? `<span class="chip c-ok">${T('Replied', '已回复')}</span>`
              : x.status === 'delivered' ? `<span class="chip c-info">${T('Delivered', '已送达')}</span>`
              : `<span class="chip c-bad">${T('Failed', '失败')}</span>`}</td>
        <td>${chipDeal(x.deal_status)}</td>
        <td style="text-align:right">${x.conv_id ? `<span class="btn sm" onclick="openConvFromModal(${x.conv_id})">${T('Open chat', '打开会话')}</span>` : ''}</td>
      </tr>`).join('')}</tbody></table>
    </div>
    <div class="acts"><span class="btn" onclick="closeDeal()">${T('Close', '关闭')}</span></div>`;
  $('mask').classList.add('on');
};
window.claimFromDetail = async (id) => {
  try { await api(`/api/contacts/${id}/claim`, { method: 'POST', body: '{}' });
    toast(T('Claimed', '已领取')); SEL_CONTACT = id; viewContacts(); }
  catch (e) { toast(e.message === 'already_owned' ? T('Already claimed', '已被领走') : e.message); }
};
window.openConvFromModal = (cid) => { closeDeal(); SEL_CONV = cid; go('inbox'); };


/* ---------- 标签选择器（全局标签 + 新建） ---------- */
window.tagPicker = async (cid) => {
  const { items } = await api('/api/tags');
  const c = await api('/api/contacts/' + cid);
  const mine = new Set((c.tags || []).map(t => t.id));
  $('modal').innerHTML = `
    <h2>${T('Add a tag', '添加标签')}</h2>
    <p class="s">${T('Tags are shared across the whole workspace.', '标签是全局的，所有客户共用同一份。')}</p>
    <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px;max-height:180px;overflow:auto">
      ${items.filter(t => !mine.has(t.id)).map(t => `<span class="chip c-info" style="cursor:pointer;height:26px"
        onclick="pickTag(${cid}, ${t.id})">${esc(t.name)} <span style="opacity:.5">${t.n}</span></span>`).join('')
        || `<span style="color:var(--sub);font-size:12.5px">${T('All tags already added', '标签都加过了')}</span>`}
    </div>
    <div class="field"><label>${T('Or create a new tag', '或者新建一个')}</label>
      <div style="display:flex;gap:8px">
        <input id="newTagName" class="inp" style="flex:1" placeholder="${T('e.g. Canton Fair 2026', '例如：2026 广交会')}">
        <span class="btn gold" onclick="createTagFor(${cid})">${T('Create', '创建')}</span>
      </div></div>
    <div class="acts"><span class="btn" onclick="closeDeal()">${T('Done', '完成')}</span></div>`;
  $('mask').classList.add('on');
};
window.pickTag = async (cid, tid) => {
  const c = await api('/api/contacts/' + cid);
  const ids = [...(c.tags || []).map(t => t.id), tid];
  await api('/api/contacts/' + cid, { method: 'PATCH', body: JSON.stringify({ tags: ids }) });
  SEL_CONTACT = cid; await viewContacts(); await tagPicker(cid);
};
window.createTagFor = async (cid) => {
  const name = ($('newTagName').value || '').trim();
  if (!name) return;
  try {
    const t = await api('/api/tags', { method: 'POST', body: JSON.stringify({ name }) });
    await pickTag(cid, t.id);
    toast(T('Tag created and added', '标签已创建并添加'));
  } catch (e) { toast(e.message); }
};


/* ---------- 标签管理 ---------- */
async function routingPanel() {
  if (ME.role !== 'owner') {
    return `<div class="card"><h3>${T('Numbers & teams', '号码与团队')}</h3>
      <div class="note">${T('Only the owner can change which team sees which number.', '只有老板能设置“哪条号码给哪个组看”。')}</div></div>`;
  }
  const [{ items: teams }, { items: users }, { items: numbers }, st] = await Promise.all([
    api('/api/teams'), api('/api/users'), api('/api/numbers'), api('/api/settings')]);
  CACHE.routeTeams = teams;
  const strict = ((st.inbox || {}).reply_owner_only !== false);
  const visibility = ((st.inbox || {}).visibility || 'team');
  const cell = `<td style="text-align:center">`;
  return `
    <div class="card" style="margin-bottom:14px"><h3>${T('Who is allowed to reply', '谁能回复')}</h3>
      <div class="note" style="margin-bottom:12px">${T(
        'Strict mode: a conversation can only be answered by the person it is assigned to. Anyone else sees it read-only and must ask a manager to hand it over.',
        '强制模式：一条会话只有负责人能回复，其他人只能看。要接手必须让主管在会话里转给TA。')}</div>
      <div style="display:flex;gap:18px;flex-wrap:wrap">
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
          <input type="radio" name="replyMode" ${strict ? 'checked' : ''} onclick="setReplyMode(true)">
          <b>${T('Only the owner can reply (recommended)', '只有负责人能回复（推荐）')}</b></label>
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
          <input type="radio" name="replyMode" ${!strict ? 'checked' : ''} onclick="setReplyMode(false)">
          ${T('Anyone in the team can reply', '组内谁都能回复')}</label>
      </div>
      <div class="note" style="margin-top:10px">${T(
        'Unassigned conversations show a "Claim" button: whoever wants it claims it first, then replies.',
        '未分配的会话会显示「认领」按钮：谁先认领归谁，认领后才能回复。')}</div>
    </div>

    <div class="card" style="margin-bottom:14px"><h3>${T('Conversation visibility (company-wide)', '会话可见范围（全公司统一）')}
      <small>${T('only the owner can change this', '只有老板能改')}</small></h3>
      <div class="note" style="margin-bottom:12px">${T(
        'This is not something each person can switch on their own. The owner sets it once for the whole company; managers and the owner always see everything on their numbers.',
        '这不是员工自己能开的权限，是老板在全公司层面统一设置。主管和老板始终能看到本号码上的全部会话。')}</div>
      <div style="display:flex;gap:18px;flex-wrap:wrap">
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
          <input type="radio" name="visMode" ${visibility === 'team' ? 'checked' : ''} onclick="setVisibility('team')">
          <b>${T('Team shared (default)', '组内共享（默认）')}</b>
          <span style="color:var(--sub);font-size:11.5px">${T('everyone in the team can read; only the owner replies', '组里都能看，只有负责人能回')}</span></label>
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
          <input type="radio" name="visMode" ${visibility === 'own' ? 'checked' : ''} onclick="setVisibility('own')">
          <b>${T('Only their own', '只看自己的')}</b>
          <span style="color:var(--sub);font-size:11.5px">${T('sales only see chats assigned to them or unassigned', '销售只看分给自己的和未分配的')}</span></label>
      </div>
    </div>

    <div class="card" style="margin-bottom:14px"><h3>${T('Which team sees which number', '哪条号码给哪个组看')}
      <small>${T('tick = that team can open this number\'s conversations', '打勾 = 这个组能看这条号码的会话')}</small></h3>
      <div class="note" style="margin-bottom:12px">${T(
        'A number can be opened to several teams, and a person can be in several teams. Nobody is tied to one number — that is what makes it a shared inbox.',
        '一条号码可以给多个组看，一个人也可以在多个组里。没有人被固定绑在某一条号码上——这才是“共享收件箱”。')}</div>
      <table><thead><tr><th>${T('Number', '号码')}</th>
        ${teams.map(t => `<th style="text-align:center">${esc(t.name)}</th>`).join('')}</tr></thead>
        <tbody>${numbers.map(n => `<tr>
          <td><b>${esc(n.label)}</b><div class="mono" style="font-size:11px;color:var(--sub)">${esc(n.phone)}</div></td>
          ${teams.map(t => `${cell}<input type="checkbox" style="width:16px;height:16px"
            ${(n.team_ids || []).includes(t.id) ? 'checked' : ''}
            onchange="setNumberTeam(${n.id}, ${t.id}, this.checked)"></td>`).join('')}
        </tr>`).join('')}</tbody></table>
      <div style="display:flex;gap:8px;margin-top:12px">
        <input id="newTeamName" class="inp" style="width:240px" placeholder="${T('New team name', '新组名')}">
        <span class="btn gold" onclick="createTeamUI()">＋ ${T('Add team', '新建组')}</span>
      </div>
    </div>

    <div class="card"><h3>${T('Who is in each team', '每个组里有谁')}
      <small>${T('a person can be in more than one team', '一个人可以同时在多个组')}</small></h3>
      <table><thead><tr><th>${T('Team', '组')}</th>
        ${users.map(u => `<th style="text-align:center">${esc(u.name)}</th>`).join('')}<th></th></tr></thead>
        <tbody>${teams.map(t => `<tr>
          <td><b>${esc(t.name)}</b><div style="font-size:11px;color:var(--sub)">${(t.members || []).length} ${T('members', '人')}</div></td>
          ${users.map(u => `${cell}<input type="checkbox" style="width:16px;height:16px"
            ${(t.members || []).includes(u.id) ? 'checked' : ''}
            onchange="setTeamMember(${t.id}, ${u.id}, this.checked)"></td>`).join('')}
          <td style="text-align:right"><span class="btn sm" onclick="deleteTeamUI(${t.id}, '${esc(t.name).replace(/'/g, "\\'")}')">${T('Delete', '删除')}</span></td>
        </tr>`).join('')}</tbody></table>
      <div class="note" style="margin-top:12px">${T(
        'Result: a sales rep sees every conversation that comes in on the numbers their team is assigned to. A team with no number sees nothing.',
        '效果：销售能看到本组被分配号码上的全部会话；一个组没分配号码，就什么都看不到。')}</div>
    </div>`;
}
window.setVisibility = async (mode) => {
  try {
    const cur = (await api('/api/settings')).inbox || {};
    await api('/api/settings', { method: 'PATCH', body: JSON.stringify({ inbox: { ...cur, visibility: mode } }) });
    toast(mode === 'own' ? T('Sales now only see their own chats', '已改为：销售只看自己的会话')
                         : T('Whole team can read each other\'s chats', '已改为：组内共享会话'));
    viewSettings();
  } catch (e) { toast(e.message); }
};
window.setReplyMode = async (strict) => {
  try {
    const cur = (await api('/api/settings')).inbox || {};
    await api('/api/settings', { method: 'PATCH', body: JSON.stringify({ inbox: { ...cur, reply_owner_only: !!strict } }) });
    toast(strict ? T('Only the owner can reply now', '已改为：只有负责人能回复') : T('Anyone in the team can reply now', '已改为：组内谁都能回复'));
    viewSettings();
  } catch (e) { toast(e.message); }
};
window.createTeamUI = async () => {
  const name = $('newTeamName').value.trim();
  if (!name) return toast(T('Give the team a name', '先写个组名'));
  try { await api('/api/teams', { method: 'POST', body: JSON.stringify({ name }) });
    toast(T('Team created', '组已创建')); viewSettings(); } catch (e) { toast(e.message); }
};
window.deleteTeamUI = async (id, name) => {
  if (!confirm(T(`Delete team "${name}"? Members and number links are removed, people are not.`, `删除「${name}」组？组员和号码分配会解除，人不会被删。`))) return;
  try { await api(`/api/teams/${id}`, { method: 'DELETE' }); viewSettings(); } catch (e) { toast(e.message); }
};
window.setNumberTeam = async (nid, tid, on) => {
  const n = (await api('/api/numbers')).items.find(x => x.id === nid);
  const ids = new Set(n.team_ids || []); on ? ids.add(tid) : ids.delete(tid);
  try { await api(`/api/numbers/${nid}/teams`, { method: 'POST', body: JSON.stringify({ team_ids: [...ids] }) });
    viewSettings(); } catch (e) { toast(e.message); }
};
window.setTeamMember = async (tid, uid, on) => {
  const t = (await api('/api/teams')).items.find(x => x.id === tid);
  const ids = new Set(t.members || []); on ? ids.add(uid) : ids.delete(uid);
  try { await api(`/api/teams/${tid}/members`, { method: 'POST', body: JSON.stringify({ user_ids: [...ids] }) });
    viewSettings(); } catch (e) { toast(e.message); }
};

async function aiInsightsPanel() {
  const [cfg, contacts] = await Promise.all([api('/api/ai/config'), api('/api/contacts?limit=1')]);
  const c = (contacts.items || [])[0];
  const ins = cfg.insights || {};
  const days = c && c.last_contact_at
    ? Math.max(0, Math.floor((Date.now() - new Date(String(c.last_contact_at).replace(' ', 'T')).getTime()) / 86400000))
    : null;
  const st = c ? stageOf(c.deal_status) : null;
  const success = c && ['Won', 'Signed', 'Active', 'Enrolled', 'Renewed'].includes(c.deal_status);
  const chips = [];
  if (c) {
    if (c.opt_out) chips.push([T('Risk · opted out', '已退订 · 风险'), 'c-bad']);
    else if (success) chips.push(['已成交', 'c-ok']);
    else if (days != null && days > 30) chips.push(['沉默 ' + days + ' 天', 'c-warn']);
    else if (days != null && days <= 7) chips.push(['活跃', 'c-ok']);
    else chips.push(['待跟进', 'c-warn']);
    (c.tags || []).slice(0, 2).forEach(t => chips.push([t.name, 'c-info']));
  }
  const next = !c ? '—'
    : c.opt_out ? '已退订，不再营销'
    : success ? '维护关系，争取复购'
    : days != null && days > 30 ? '建议发召回模板'
    : c.deal_status === 'Negotiating' ? '今天跟进报价'
    : '保持联系节奏';
  const ro = ME.role !== 'owner' ? 'disabled' : '';
  const sw = (id, on, label, sub) => `<div class="ai-row">
    <div><div class="lbl">${label}</div><div class="sub">${sub}</div></div>
    <div class="ctl"><div class="sw ${on ? 'on' : ''}" id="${id}" onclick="this.classList.toggle('on')"></div></div></div>`;
  return `
    <div class="card" style="margin-bottom:14px">
      <h3>${T('Knowledge connection', '知识库连接')} <small>${T('key belongs to AI assistant', 'Key 在 AI 助手里填')}</small></h3>
      <div class="note" style="margin-bottom:10px">${T('Base URL, Site ID and API Key live in the AI assistant page. This page only controls how AI reads a customer.', 'Base URL、Site ID 和 API Key 在左侧「AI 助手」里；这一页只管 AI 怎么判断客户。')}</div>
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
        <span class="chip ${cfg.api_key_set ? 'c-ok' : 'c-warn'}">${cfg.api_key_set ? (cfg.key_from_env ? T('Key configured (server environment)', 'Key 已配置（服务器环境变量）') : T('Key configured', 'Key 已配置')) : (cfg.base_url ? T('Base URL set, key missing', '已填地址，但还没填 Key') : T('Not connected', '还没接知识库'))}</span>
        <span style="font-size:11.5px;color:var(--sub)">${cfg.site_id ? T('Site ID set', '站点 ID 已填') : T('Site ID missing', '站点 ID 未填')}</span>
      </div>
      <div class="ai-field" style="margin-top:10px"><label>${T('API Key', 'API Key')}</label>
        <input class="inp" id="insKey" value="" placeholder="${cfg.api_key_set ? (cfg.key_from_env ? T('Provided by server environment; type a new key to override', '已由服务器环境变量提供，输入新 Key 可覆盖') : T('Saved (masked); type a new key to replace', '已保存（打码），输入新 Key 可替换')) : T('Paste your DeskClerk API key', '粘贴 DeskClerk 的 API Key')}">
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <span class="btn sm gold" onclick="saveAIInsightsKey()">${T('Save key', '保存 Key')}</span>
        <span class="btn sm" onclick="aiOpenConnection()">${T('Full connection setup', '完整接入配置')}</span>
      </div>
    </div>

    <div class="card" style="margin-bottom:14px">
      <h3>${T('AI customer insights', 'AI 客户洞察')} <small>${T('how AI reads a customer', 'AI 怎么“看”客户')}</small></h3>
      <div class="note" style="margin-bottom:12px">${T('This page controls how AI <b>judges and presents</b> a customer: tags, summary, follow-up status, next step. Knowledge base, persona and reply mode live under AI assistant.', '这里管 AI 对客户的<b>判断与呈现</b>：自动打标签、写摘要、判断跟进状态、推荐下一步。接知识库、人设、接待方式请去左侧「AI 助手」。')}</div>
      ${sw('insTags', ins.auto_tags !== false, T('Auto-tagging', '自动打标签'), T('Tag intent and product line from chats and behaviour', '根据对话与行为给客户打上意向/产品线标签'))}
      ${sw('insSummary', ins.summary !== false, T('Customer summary', '客户摘要'), T('One-line summary at the top of the customer card', '在客户卡片顶部生成一句话摘要'))}
      ${sw('insStatus', ins.status !== false, T('Follow-up status', '跟进状态判断'), T('Active / to follow up / dormant / risk, updated from recent activity', '活跃 / 待跟进 / 沉默 / 风险，随最近沟通自动更新'))}
      ${sw('insNext', ins.next_action !== false, T('Next step', '下一步建议'), T('Tell the rep what to do with this customer now', '告诉销售这条客户现在该做什么'))}
      ${sw('insRisk', ins.risk !== false, T('Risk & sentiment', '风险与情绪'), T('Spot complaints, refunds and negative sentiment; escalate first', '识别投诉、退款、负面情绪，优先转人工'))}
      ${ME.role === 'owner' ? `<div style="margin-top:12px"><span class="btn gold" onclick="saveAIInsights()">${T('Save', '保存')}</span></div>` : ''}
    </div>

    <div class="card" style="margin-bottom:14px">
      <h3>${T('Rules', '判断规则')} <small>${T('explainable, not guessed', '可解释，不靠猜')}</small></h3>
      <table><thead><tr><th>${T('Status', '状态')}</th><th>${T('How it is decided', '怎么判断')}</th><th>${T('Where it shows', '用在哪')}</th></tr></thead><tbody>
        <tr><td><span class="chip c-ok">${T('Active', '活跃')}</span></td><td>${T('Message in or out within 7 days', '最近 7 天有来信或去信')}</td><td>${T('Contact list, inbox', '客户列表、会话台')}</td></tr>
        <tr><td><span class="chip c-warn">${T('To follow up', '待跟进')}</span></td><td>${T('No contact for 7+ days, not won', '超过 7 天没联系，且未成交')}</td><td>${T('Customer card, team board', '客户卡片、团队看板')}</td></tr>
        <tr><td><span class="chip c-warn">${T('Dormant', '沉默')}</span></td><td>${T('No contact for 30+ days', '超过 30 天没联系')}</td><td>${T('Segments, win-back lists', '分层、召回名单')}</td></tr>
        <tr><td><span class="chip c-ok">${T('Won', '已成交')}</span></td><td>${T('Deal status is a success state', '成交状态属于成功态')}</td><td>${T('Customer card, analytics', '客户卡片、看板')}</td></tr>
        <tr><td><span class="chip c-bad">${T('Risk', '风险')}</span></td><td>${T('Opt-out, complaint/refund keywords, negative sentiment', '退订、投诉/退款关键词、负面情绪')}</td><td>${T('Inbox, escalate first', '会话台、优先转人工')}</td></tr>
      </tbody></table>
      <div class="note" style="margin-top:10px">${T('These labels appear on the customer card, inbox header, contact list and segments. They are computed live, not stored as a list.', '这些标签和状态会出现在：客户卡片、会话顶部、客户列表、分层筛选。不是另存一份名单，而是实时判断。')}</div>
    </div>

    <div class="card">
      <h3>${T('Preview', '呈现示例')} <small>${c ? esc(c.name) : T('No contact', '暂无客户')}</small></h3>
      ${c ? `<div style="background:#FBFCFE;border:1px solid var(--line);border-radius:10px;padding:14px">
        <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
          <b style="font-size:15px">${esc(c.name)}</b>
          <span style="color:var(--sub);font-size:12px">${esc(c.country || '')}</span>
          ${chipDeal(c.deal_status)}
          ${chips.map(([t, cls]) => `<span class="chip ${cls}">${esc(t)}</span>`).join('')}
        </div>
        <div style="margin-top:8px;font-size:12.5px;color:#33475C">
          <b>${T('Summary', '摘要')}：</b>${esc(c.country || '')}客户，当前${st ? T(st.en, st.zh) : ''}${days != null ? '，最后联系 ' + days + ' 天前' : ''}。
        </div>
        <div style="margin-top:6px;font-size:12.5px;color:#33475C"><b>下一步：</b>${next}</div>
        <div style="margin-top:4px;font-size:12.5px;color:#33475C"><b>${T('Owner', '负责人')}：</b>${esc(c.owner_name || '无主 · 在公海')}</div>
      </div>` : `<div class="note">${T('No contacts yet. Import contacts to see a live example.', '还没有客户数据。导入客户后这里会显示真实示例。')}</div>`}
      <div style="margin-top:12px"><span class="btn" onclick="go('ai')">${T('Open AI assistant (knowledge & reply mode)', '打开 AI 助手（知识库与接待方式）')}</span></div>
    </div>`;
}

window.saveAIInsightsKey = async () => {
  const v = ($('insKey') || {}).value || '';
  if (!v.trim()) return toast('先粘贴 Key');
  try {
    await api('/api/ai/config', { method: 'PATCH', body: JSON.stringify({ api_key: v.trim() }) });
    CACHE.aiIns = null;
    toast('Key 已保存（页面只显示打码值）');
    viewSettings();
  } catch (e) { toast(e.message); }
};

window.aiOpenConnection = async () => {
  await go('ai');
  setTimeout(() => aiTab('conn'), 250);
};

window.saveAIInsights = async () => {
  try {
    await api('/api/ai/config', { method: 'PATCH', body: JSON.stringify({ insights: {
      auto_tags: $('insTags').classList.contains('on'),
      summary: $('insSummary').classList.contains('on'),
      status: $('insStatus').classList.contains('on'),
      next_action: $('insNext').classList.contains('on'),
      risk: $('insRisk').classList.contains('on'),
    } }) });
    CACHE.aiIns = null;
    toast('已保存');
  } catch (e) { toast(e.message); }
};

async function tagsPanel() {
  const { items } = await api('/api/tags');
  const canEdit = ME.role !== 'agent';
  return `<div class="card"><h3>${T('Tags', '标签')}<small>${items.length} ${T('total', '个')}</small></h3>
    <div class="note" style="margin-bottom:12px">${T('Tags are shared across the whole workspace. You can create, rename, merge and delete them here, or create one from any contact.',
      '标签是全站共用的：这里可以新建、改名、合并、删除；在客户身上也能直接新建。')}</div>
    ${canEdit ? `<div style="display:flex;gap:8px;margin-bottom:12px">
      <input id="newTag" class="inp" style="flex:1" placeholder="${T('New tag name', '新标签名称')}">
      <span class="btn gold" onclick="createTagUI()">＋ ${T('Create tag', '新建标签')}</span>
    </div>` : ''}
    <table><thead><tr><th>${T('Tag', '标签')}</th><th>${T('Contacts', '客户数')}</th>
      <th style="text-align:right">${T('Actions', '操作')}</th></tr></thead>
    <tbody>${items.map(t => `<tr>
      <td><span class="chip c-info">${esc(t.name)}</span></td>
      <td class="mono">${t.n}</td>
      <td style="text-align:right;white-space:nowrap">${canEdit ? `
        <span class="btn sm" onclick="renameTagUI(${t.id}, '${esc(t.name).replace(/'/g, "\\'")}')">${T('Rename', '改名')}</span>
        <span class="btn sm" onclick="mergeTagUI(${t.id})">${T('Merge', '合并')}</span>
        <span class="btn sm" onclick="deleteTagUI(${t.id})">${T('Delete', '删除')}</span>` : ''}</td>
    </tr>`).join('') || `<tr><td colspan="3" style="color:var(--sub)">${T('No tags yet', '还没有标签')}</td></tr>`}</tbody></table>
  </div>`;
}
window.createTagUI = async () => {
  const name = $('newTag').value.trim();
  if (!name) return toast(T('Give the tag a name', '先写个标签名'));
  try { await api('/api/tags', { method: 'POST', body: JSON.stringify({ name }) });
    toast(T('Tag created', '标签已创建')); viewSettings();
  } catch (e) { toast(e.message); }
};
window.renameTagUI = async (id, old) => {
  const name = prompt(T('New name:', '新名称：'), old);
  if (!name || name === old) return;
  try { await api(`/api/tags/${id}`, { method: 'PATCH', body: JSON.stringify({ name }) });
    toast(T('Renamed', '已改名')); viewSettings(); } catch (e) { toast(e.message); }
};
window.mergeTagUI = async (id) => {
  const { items } = await api('/api/tags');
  const others = items.filter(t => t.id !== id);
  if (!others.length) return toast(T('No other tag to merge into', '没有可合并的目标'));
  const list = others.map(t => `${t.id}: ${t.name}（${t.n}）`).join('\n');
  const to = prompt(T('Merge into which tag?\n' + list, '合并到哪个标签？输入 ID：\n' + list));
  if (!to) return;
  try { await api('/api/tags/merge', { method: 'POST', body: JSON.stringify({ from_id: id, to_id: +to }) });
    toast(T('Merged', '已合并')); viewSettings(); } catch (e) { toast(e.message); }
};
window.deleteTagUI = async (id) => {
  if (!confirm(T('Delete this tag from all contacts?', '从所有客户身上删掉这个标签？'))) return;
  await api(`/api/tags/${id}`, { method: 'DELETE' }); toast(T('Deleted', '已删除')); viewSettings();
};


/* ================= 公海 ================= */
let POOL = { tag: 0, country: '', sort: 'oldest', kw: '' };

/* [完整说明EN, 完整说明ZH, 颜色, 短标签EN, 短标签ZH] */
const BLOCK_LABEL = {
  opted_out:    ['Opted out — this person asked not to be contacted', '客户已退订，不能再联系', 'c-bad', 'Opted out', '已退订'],
  success:      ['Already a closed / won customer', '已经是成交客户，不再放回流转', 'c-ok', 'Won', '已成交'],
  protected:    ['Just released — protection period not over yet', '刚放回公海，保护期内不能抢', 'c-warn', 'Protected', '保护期'],
  out_of_scope: ['Outside the tags you are allowed to claim', '不在你负责的标签范围内', 'c-gray', 'Out of scope', '超范围'],
  owned:        ['Someone already claimed it', '已经被人领走', 'c-gray', 'Taken', '已被领'],
};

async function viewPool() {
  const qs = new URLSearchParams({ view: 'pool', limit: 200, sort: POOL.sort });
  if (POOL.tag) qs.set('tag', POOL.tag);
  if (POOL.country) qs.set('country', POOL.country);
  if (POOL.kw) qs.set('kw', POOL.kw);
  const [st, { items, total }, facets] = await Promise.all([
    api('/api/pool/stats'), api('/api/contacts?' + qs.toString()), api('/api/pool/facets')]);

  $('hTitle').textContent = T('Public pool', '公海');
  $('hSub').textContent = T('Contacts nobody owns · only some of them can be claimed', '没人负责的客户 · 不是每个都能领');
  const cfg = st.config || {};
  const blk = st.blocks || {};

  const tagChip = (id, label, n, ok) => `<span class="tab ${POOL.tag === id ? 'on' : ''}" onclick="poolFilter('tag',${id})">${esc(label)}
    <span style="opacity:.55">${n}</span>${ok < n ? `<span title="${T('of these can be claimed', '其中可领取')}" style="color:${POOL.tag === id ? '#F5DF9C' : '#2E8B57'}">· ${T('claimable', '可领')} ${ok}</span>` : ''}</span>`;

  $('body').innerHTML = `
    <div class="col-main">
      <div class="kpis">
        <div class="kpi"><div class="k">${T('In pool', '公海中')}</div><div class="v">${st.unowned}</div>
          <div class="d">${T('All unowned contacts', '全部无主客户')}</div></div>
        <div class="kpi"><div class="k">${T('Claimable now', '现在可领')}</div><div class="v" style="color:var(--green)">${st.claimable}</div>
          <div class="d">${T('Pass all the rules', '已通过领取规则')}</div></div>
        <div class="kpi"><div class="k">${T('Cannot claim', '不可领取')}</div><div class="v">${st.unowned - st.claimable}</div>
          <div class="d">${T('Opted out / won / protected', '退订 / 已成交 / 保护期')}</div></div>
        <div class="kpi"><div class="k">${T('Claimed today', '今日已领')}</div><div class="v">${st.claimed_today} / ${st.claim_limit}</div>
          <div class="d">${T('Your daily quota', '你今天的额度')}</div></div>
      </div>

      <div class="card" style="margin-bottom:14px">
        <h3>${T('Filter the pool', '筛选公海')}
          <small>${T('Click a tag or country to narrow down', '点标签或国家缩小范围')}</small></h3>
        <div class="fbar">
          <div class="rows"><span class="fl">${T('By tag', '按标签')}</span>
            ${tagChip(0, T('All', '全部'), st.unowned, st.claimable)}
            ${(facets.tags || []).map(t => tagChip(t.id, t.name, t.n, t.claimable)).join('') || `<span class="ln">${T('No tags in the pool yet', '公海里还没有标签')}</span>`}
          </div>
          <div class="rows"><span class="fl">${T('By country', '按国家')}</span>
            <span class="tab ${POOL.country === '' ? 'on' : ''}" onclick="poolFilter('country','')">${T('All', '全部')}</span>
            ${(facets.countries || []).map(c => `<span class="tab ${POOL.country === c.country ? 'on' : ''}"
              onclick="poolFilter('country','${esc(c.country)}')">${esc(c.country)} <span style="opacity:.55">${c.n}</span></span>`).join('')
              || `<span class="ln">${T('No country data', '没有国家数据')}</span>`}
          </div>
          <div class="rows"><span class="fl">${T('Sort', '排序')}</span>
            ${[['oldest', T('Longest untouched', '最久未联系')], ['newest', T('Most recent', '最近联系')]]
              .map(([k, v]) => `<span class="tab ${POOL.sort === k ? 'on' : ''}" onclick="poolFilter('sort','${k}')">${v}</span>`).join('')}
            <input class="searchbox" style="width:220px;margin-left:auto" placeholder="🔍 ${T('Search name / number / country', '搜索姓名 / 号码 / 国家')}"
              value="${esc(POOL.kw)}" oninput="poolSearch(this.value)">
          </div>
        </div>
        <div class="note" style="margin-top:12px">${T(
          'Only contacts with an owner are recycled after ' + (cfg.recycle_days || 90) + ' days. Opted-out and won contacts never enter the pool.',
          '有负责人但超过 ' + (cfg.recycle_days || 90) + ' 天没联系的客户会自动回收。已退订、已成交的客户永远不会进公海。')}</div>
      </div>

      <div class="card">
        <h3>${T('Contacts in the pool', '公海里的客户')}<small>${total} ${T('match', '条符合')}</small></h3>
        <table><thead><tr><th>${T('Contact', '客户')}</th><th>${T('Country', '国家')}</th>
          <th>${T('Tags', '标签')}</th><th>${T('Source', '来源')}</th><th>${T('Last contact', '最后联系')}</th>
          <th>${T('Status', '状态')}</th><th>${T('Owner', '负责人')}</th><th style="text-align:right">${T('Action', '操作')}</th></tr></thead>
        <tbody>${items.map(c => {
          const tgs = (c.tags || []).map(t => `<span class="chip c-info" style="height:19px;font-size:10.5px">${esc(t.name)}</span>`).join(' ')
            || `<span style="color:#94A3B3;font-size:11.5px">—</span>`;
          let act;
          if (c.claimable) act = `<span class="btn sm gold" onclick="claimContact(${c.id})">${T('Claim', '领取')}</span>`;
          else {
            const [en, zh, cls, sen, szh] = BLOCK_LABEL[c.claim_block] || [c.claim_block, c.claim_block, 'c-gray', c.claim_block, c.claim_block];
            act = `<span class="chip ${cls}" title="${T(en, zh)}" style="cursor:help">${T(sen, szh)}</span>`;
          }
          return `<tr>
            <td><b>${esc(c.name)}</b><div class="mono" style="font-size:11px;color:var(--sub)">${esc(c.phone)}</div></td>
            <td>${esc(c.country || '')}</td><td>${tgs}</td><td>${esc(c.source || '')}</td>
            <td class="mono">${esc((c.last_contact_at || '').slice(0, 10) || '—')}</td>
            <td>${chipDeal(c.deal_status)}</td>
            <td><span class="chip c-gray" title="${T('No one owns this contact — that is why it is in the pool', '这条客户没有负责人，所以才会出现在公海')}">${T('no owner', '无主')}</span></td>
            <td style="text-align:right">${act}</td>
          </tr>`;
        }).join('') || `<tr><td colspan="8" style="color:var(--sub)">${T('No contacts match these filters', '没有符合条件的客户')}</td></tr>`}</tbody></table>
      </div>
    </div>`;
}

window.poolFilter = (k, v) => { POOL[k] = v; viewPool(); };
let POOL_T = null;
window.poolSearch = (v) => { POOL.kw = v; clearTimeout(POOL_T); POOL_T = setTimeout(viewPool, 250); };

window.claimContact = async (id) => {
  try {
    const r = await api(`/api/contacts/${id}/claim`, { method: 'POST', body: '{}' });
    toast(T(`Claimed · ${r.used}/${r.limit} today`, `已领取 · 今日 ${r.used}/${r.limit}`));
    viewPool();
  } catch (e) {
    const m = e.message || '';
    if (m.startsWith('blocked:')) {
      const b = m.slice(8), L = BLOCK_LABEL[b] || [b, b];
      toast(T('Cannot claim: ', '不能领取：') + T(L[0], L[1]));
    } else {
      toast(m.startsWith('daily_limit_reached') ? T('Daily claim limit reached', '今日领取额度已用完')
        : m === 'already_owned' ? T('Someone already claimed it', '已经被人领走了') : m);
    }
    viewPool();
  }
};
window.runRecycle = async () => {
  try { const r = await api('/api/pool/recycle', { method: 'POST', body: '{}' });
    toast(T(`Recycled ${r.recycled} contacts`, `已回收 ${r.recycled} 个客户`)); viewPool(); }
  catch (e) { toast(e.message); }
};
window.releaseContact = async (id) => {
  if (!confirm(T('Release back to the pool?', '放回公海？'))) return;
  await api(`/api/contacts/${id}/release`, { method: 'POST', body: '{}' });
  toast(T('Released', '已放回公海')); viewContacts();
};


/* ---------- 公海规则 ---------- */
async function poolPanel(cfg) {
  const c = { recycle_days: 90, daily_claim_limit: 10, enabled: true, protect_hours: 24, exclude_success: true, scopes: {}, ...(cfg || {}) };
  let tags = [], agents = [];
  if (ME.role === 'owner') {
    const [tg, us] = await Promise.all([api('/api/tags'), api('/api/users')]);
    tags = tg.items || [];
    agents = (us.items || []).filter(u => u.role === 'agent' && u.active !== 0);
  }
  if (!POOL_SCOPE_DIRTY) POOL_SCOPE = JSON.parse(JSON.stringify(c.scopes || {}));
  const ro = ME.role !== 'owner' ? 'disabled' : '';
  return `<div class="card"><h3>${T('Public pool rules', '公海规则')}</h3>
    <div class="note" style="margin-bottom:14px">${T(
      'A contact with no owner lives in the pool. A contact that nobody touches for N days goes back to the pool automatically.',
      '没有负责人的客户待在公海；有负责人但超过 N 天没人联系的，自动回到公海，让别人来捡。')}</div>
    <div class="grid2">
      <div class="field"><label>${T('Recycle after (days without contact)', '多少天没联系就回收')}</label>
        <input id="poolDays" class="inp" type="number" style="width:100%" value="${c.recycle_days}" ${ro}></div>
      <div class="field"><label>${T('Daily claim limit per agent', '每人每天最多领几个')}</label>
        <input id="poolLimit" class="inp" type="number" style="width:100%" value="${c.daily_claim_limit}" ${ro}></div>
    </div>
    <div class="grid2">
      <div class="field"><label>${T('Release protection (hours)', '退回后保护几小时')}</label>
        <input id="poolProtect" class="inp" type="number" style="width:100%" value="${c.protect_hours}" ${ro}></div>
      <div class="field"><label>${T('Won contacts never recycled', '成交客户不回收')}</label>
        <input id="poolExcl" class="inp" type="checkbox" style="width:100%;height:38px" ${c.exclude_success ? 'checked' : ''} ${ro}></div>
    </div>
    <div class="field"><label>${T('Auto recycle', '自动回收')}</label>
      <div class="inp">${c.enabled ? T('On', '开启') : T('Off', '关闭')}</div></div>
    ${ME.role === 'owner' ? `<span class="btn gold" onclick="savePool()">${T('Save', '保存')}</span>
      <span class="btn" onclick="runRecycle()">${T('Run recycle now', '立即执行回收')}</span>` : ''}
    <div class="note" style="margin-top:12px">${T(
      'Set the limit high and people hoard contacts; set it low and good leads sit unclaimed. 10 per day is a common starting point.',
      '额度设太高，销售会囤客户；设太低，好线索没人领。一天 10 个是常见的起步值。')}</div>
  </div>

  <div class="card" style="margin-top:14px"><h3>${T('Claim scope — who may claim what', '领取范围 — 谁能领哪类客户')}
    <small>${T('No tag chosen = can claim anything', '不选标签＝不限制')}</small></h3>
    <div class="note" style="margin-bottom:14px">${T(
      'Limit each rep to the tags they actually work. A rep with no scope can claim any contact; a rep with tags can only claim contacts carrying at least one of them.',
      '给每个销售划范围：只让懂这行的销售领这类客户。一个都没选＝不限制，什么都能领；选了标签＝客户身上至少有一个该标签才领得到。')}</div>
    ${ME.role !== 'owner' ? `<div class="ln" style="color:var(--sub);font-size:12.5px">${T('Only the owner can set this.', '只有老板能设置。')}</div>`
      : agents.length === 0 ? `<div class="ln" style="color:var(--sub);font-size:12.5px">${T('No active sales reps yet.', '还没有在职销售。')}</div>`
      : `<table><thead><tr><th>${T('Sales rep', '销售')}</th><th>${T('Can claim these tags', '能领这些标签的客户')}</th></tr></thead>
        <tbody>${agents.map(u => {
          const sc = POOL_SCOPE[String(u.id)] || [];
          return `<tr><td><b>${esc(u.name)}</b><div style="font-size:11px;color:var(--sub)">${esc(u.email)}</div></td>
            <td><div style="display:flex;flex-wrap:wrap;gap:6px">
              ${tags.map(t => `<span class="tab ${sc.includes(t.id) ? 'on' : ''}" onclick="toggleScope(${u.id},${t.id})">${esc(t.name)}</span>`).join('')}
              ${sc.length === 0 ? `<span style="font-size:11.5px;color:var(--sub);align-self:center">${T('no limit', '不限制')}</span>` : ''}
            </div></td></tr>`;
        }).join('')}</tbody></table>
        <div style="margin-top:12px"><span class="btn gold" onclick="saveScopes()">${T('Save claim scope', '保存领取范围')}</span></div>`}
  </div>`;
}

let POOL_SCOPE = {}, POOL_SCOPE_DIRTY = false;
window.toggleScope = (uid, tid) => {
  const k = String(uid), cur = POOL_SCOPE[k] || [];
  POOL_SCOPE[k] = cur.includes(tid) ? cur.filter(x => x !== tid) : [...cur, tid];
  POOL_SCOPE_DIRTY = true;
  viewSettings();
};
window.saveScopes = async () => {
  try {
    const cur = (await api('/api/settings')).pool || {};
    await api('/api/settings', { method: 'PATCH', body: JSON.stringify({ pool: { ...cur, scopes: POOL_SCOPE } }) });
    POOL_SCOPE_DIRTY = false;
    toast(T('Saved', '已保存')); viewSettings();
  } catch (e) { toast(e.message); }
};
window.savePool = async () => {
  try {
    const cur = (await api('/api/settings')).pool || {};
    await api('/api/settings', { method: 'PATCH', body: JSON.stringify({ pool: { ...cur,
      recycle_days: +$('poolDays').value || 90,
      daily_claim_limit: +$('poolLimit').value || 10,
      protect_hours: +$('poolProtect').value || 0,
      exclude_success: $('poolExcl').checked,
      enabled: true } }) });
    toast(T('Saved', '已保存')); viewSettings();
  } catch (e) { toast(e.message); }
};

/* ---------- 视图路由（函数声明会提升，放在文件末尾也能用） ---------- */
function resolveView(t){
  switch (t) {
    case 'inbox': return viewInbox;
    case 'pool': return viewPool;
    case 'contacts': return viewContacts;
    case 'segments': return viewSegments;
    case 'templates': return viewTemplates;
    case 'campaigns': return viewCampaigns;
    case 'ai': return viewAI;
    case 'team': return viewTeam;
    case 'analytics': return viewAnalytics;
    case 'settings': return viewSettings;
    default: return null;
  }
}


/* AI 页面静态文案的英文映射（按整段文本替换，不碰输入值和聊天内容） */
const AI_I18N = {
  'AI 助手':'AI assistant','知识库 · 人设 · 安全边界 · 实时预览':'Knowledge base · persona · safety · live preview',
  '接入配置':'Connection','回复策略':'Reply policy','人设与话术':'Persona & wording','安全边界':'Safety',
  '知识库状态':'Knowledge base','问答日志':'Q&A log','测试提问':'Test question','知识与运行':'Knowledge & runtime',
  '接待方式':'Reply mode','人工接待':'Manual','AI 草稿':'AI draft','AI 全自动托管':'AI autopilot',
  'AI 只写草稿，需要人工点“采用”才发出':'AI writes a draft; a human must accept it before sending',
  'AI 会直接回复客户；价格、合同、无依据会转人工':'AI replies directly; price, contract and no-source cases go to a human',
  'AI 不参与，全部由人工回复':'AI stays out; all replies are manual',
  '测试':'Test','保存':'Save','平台连接':'Platform connection','一套知识库＝一个站点':'one knowledge base = one site',
  'Key 只存服务端；页面只显示打码值。改完点右上角保存。':'The key stays server-side and is masked here. Save with the button at top right.',
  'AI 大脑':'AI brain','DeskClerk AI 知识库（推荐 · 原生适配）':'DeskClerk AI knowledge base (recommended, native)',
  '其他知识库 / 自建':'Other knowledge base / self-hosted','去 deskclerkai.com 创建站点和 Key →':'Create a site and key at deskclerkai.com →',
  'Base URL':'Base URL','API Key':'API Key','站点 Site ID':'Site ID','Key 类型':'Key type','租户级 · 可列站点、建站点':'Tenant-wide · can list and create sites',
  '语言':'Languages','按站点 + 语言隔离':'Isolated per site + locale',
  '知识点和提问必须使用同一语言；一种语言＝一条独立知识。':'Knowledge and questions must use the same locale; one locale = one separate item.',
  '回复模式':'Reply mode','触发条件':'Triggers','置信度阈值':'Confidence threshold','最高出处分低于此值转人工':'Below this score, hand off to a human',
  '仅 24 小时窗口内自动回复':'Auto-reply only inside the 24h window','窗口外只发已审模板':'Outside it, only approved templates',
  '无知识依据时转人工':'Hand off when there is no source','空 sources 不自动发':'Empty sources are never auto-sent',
  '自动回复标识':'Auto-reply badge','首条注明“AI 自动回复”':'Mark the first reply as AI','每人每日上限':'Daily limit per customer','防止对同一客户刷屏':'Prevents spamming the same customer',
  '人设与话术':'Persona & wording','按语言独立保存':'Saved per language','角色说明 system_role（≤2400）':'Role — system_role (≤2400)',
  '公司介绍 company_intro（≤3000）':'Company intro — company_intro (≤3000)','回答范围 product_scope（≤3000）':'Scope — product_scope (≤3000)',
  '人设软约束 policy_boundaries（≤3000）':'Soft boundaries — policy_boundaries (≤3000)','语气 tone':'Tone','单次回答字数（30–500）':'Max words (30–500)',
  '时区':'Timezone','营业时间':'Business hours','专业':'Professional','亲和':'Friendly','直接':'Direct','顾问式':'Consultative',
  '禁止主题':'Blocked topics','固定开启，不可关闭':'Always on, cannot be disabled','命中以下主题直接转人工，不调用 AI。':'These topics go straight to a human; AI is not called.',
  '投诉 / 退款关键词转人工':'Complaint / refund keywords → human','用顿号或逗号分隔':'Separate with commas','客户要求人工':'Customer asks for a human','命中即转人工':'Escalate on match',
  '人设软约束':'Soft boundaries','这里是提示词级软约束；真正的硬拦截靠上面的禁止主题，在入口完成。':'Prompt-level guidance only; hard blocking happens at the entry gate above.',
  '已索引':'Indexed','条':'items','待处理':'Pending','索引完成':'Indexed','失败':'Failed','需修正重推':'Fix and re-push','最后同步':'Last sync','自动回调':'Callback',
  '索引完成回调':'Index callback','立即同步':'Sync now','最近的测试与真实问答':'Recent tests and live Q&A',
  '时间':'Time','客户':'Customer','问题':'Question','结果':'Result','最高分':'Top score','耗时':'Latency','还没有问答记录':'No Q&A records yet',
  '不会发给客户':'Never sent to customers','发送测试':'Run test','结果会显示在右侧预览，并写入问答日志。':'The result appears in the preview and is written to the Q&A log.',
  '最近测试':'Recent tests','客户会看到什么':'What the customer sees','随左侧配置变化':'Follows the config on the left','实时':'Live',
  '正常回答':'Normal answer','无知识依据':'No source','价格拦截':'Price blocked','命中知识':'Sources hit','最高相似度':'Top score','判断':'Decision',
  '可自动回复':'Can auto-reply','转人工':'Hand off','入口拦截 · 转人工':'Blocked at entry · hand off','草稿 · 人工确认':'Draft · human confirm',
  'AI 已关闭':'AI is off','AI 自动回复':'AI reply','未调用 AI':'AI not called','输入消息…':'Type a message…',
};

function applyAITranslations(root) {
  if (LANG === 'zh' || !root) return;
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (w.nextNode()) nodes.push(w.currentNode);
  nodes.forEach(n => {
    const raw = n.nodeValue || '';
    const key = raw.trim();
    if (key && AI_I18N[key]) n.nodeValue = raw.replace(key, AI_I18N[key]);
  });
  root.querySelectorAll('[placeholder]').forEach(el => {
    const p = el.getAttribute('placeholder');
    if (p && AI_I18N[p]) el.setAttribute('placeholder', AI_I18N[p]);
  });
}

/* ================= AI 助手（B+C 合并页） ================= */
let AI_CFG = null, AI_TAB = 'conn', AI_MODE = 'draft', AI_LOCALE = 'zh-CN', AI_PERSONAS = {}, AI_LOGS = [];
const AI_MODE_LABEL = { off: '人工接待', draft: 'AI 草稿', auto: 'AI 全自动托管' };
const AI_DESKCLERK_BASE = 'https://app.deskclerkai.com/api/v1/integrations';
const AI_DEC = {
  off: ['AI 已关闭', 'var(--sub)'],
  blocked: ['入口拦截 · 转人工', 'var(--red)'],
  handoff: ['转人工', 'var(--amber)'],
  draft: ['草稿 · 人工确认', 'var(--amber)'],
  auto: ['可自动回复', 'var(--green)'],
};

const aiEsc = (v) => esc(String(v == null ? '' : v));
const aiSplit = (v) => String(v || '').split(/[、,，\s]+/).map(x => x.trim()).filter(Boolean);
const aiMs = (n) => n == null ? '—' : (n < 1000 ? n + ' ms' : (n / 1000).toFixed(1) + ' 秒');

function aiModeCards() {
  return [['off', '人工接待', 'AI 不参与，全部人工'],
          ['draft', 'AI 草稿', 'AI 写好，人工确认再发'],
          ['auto', 'AI 全自动托管', '条件满足直接回，异常转人工']]
    .map(([k, n, d]) => `<div class="m ${AI_MODE === k ? 'on' : ''}" data-mode="${k}" onclick="aiSetMode('${k}')">
      <b>${n}</b><span>${d}</span></div>`).join('');
}

function aiPersonaFields(p) {
  p = p || {};
  return `
    <div class="ai-field"><label>角色说明 system_role（≤2400）</label>
      <textarea class="inp" id="aiRole" oninput="aiCount(this,2400,'cRole')">${aiEsc(p.system_role)}</textarea>
      <div class="ai-count" id="cRole">0 / 2400</div></div>
    <div class="ai-grid2">
      <div class="ai-field"><label>公司介绍 company_intro（≤3000）</label>
        <textarea class="inp" id="aiIntro" oninput="aiCount(this,3000,'cIntro')">${aiEsc(p.company_intro)}</textarea>
        <div class="ai-count" id="cIntro">0 / 3000</div></div>
      <div class="ai-field"><label>回答范围 product_scope（≤3000）</label>
        <textarea class="inp" id="aiScope" oninput="aiCount(this,3000,'cScope')">${aiEsc(p.product_scope)}</textarea>
        <div class="ai-count" id="cScope">0 / 3000</div></div>
    </div>
    <div class="ai-field"><label>人设软约束 policy_boundaries（≤3000）</label>
      <textarea class="inp" id="aiPolicyB" oninput="aiCount(this,3000,'cPolicy')">${aiEsc(p.policy_boundaries)}</textarea>
      <div class="ai-count" id="cPolicy">0 / 3000</div></div>
    <div class="ai-grid2">
      <div class="ai-field"><label>语气 tone</label>
        <select class="inp" id="aiTone">
          ${[['professional','专业'],['friendly','亲和'],['direct','直接'],['consultative','顾问式']]
            .map(([k,n]) => `<option value="${k}" ${(p.tone||'professional')===k?'selected':''}>${n} ${k}</option>`).join('')}
        </select></div>
      <div class="ai-field"><label>单次回答字数（30–500）</label>
        <input class="inp" id="aiWords" type="number" min="30" max="500" value="${p.reply_max_words||180}"></div>
      <div class="ai-field"><label>时区</label>
        <input class="inp" id="aiTz" value="${aiEsc(p.timezone||'Asia/Riyadh')}"></div>
      <div class="ai-field"><label>营业时间</label>
        <input class="inp" id="aiHours" value="${aiEsc(p.business_hours||'')}" placeholder="周一至周六 09:00–18:00"></div>
    </div>`;
}

function aiLogsTable(items) {
  return `<table class="ai-log-table"><thead><tr><th>时间</th><th>客户</th><th>问题</th><th>结果</th><th>最高分</th><th>耗时</th></tr></thead>
    <tbody>${(items||[]).map(r => {
      const label = (AI_DEC[r.decision] || [r.decision, 'var(--sub)'])[0];
      return `<tr><td class="mono">${aiEsc((r.created_at||'').slice(5,16))}</td>
        <td>${aiEsc(r.contact_name || '—')}</td>
        <td>${aiEsc((r.question||'').slice(0,40))}</td>
        <td><span class="ai-chip ${r.decision==='auto'?'ok':r.decision==='blocked'?'lock':r.decision==='handoff'?'gray':'info'}">${label}</span></td>
        <td class="mono">${r.top_score==null?'—':Number(r.top_score).toFixed(2)}</td>
        <td class="mono">${aiMs(r.latency_ms)}</td></tr>`;
    }).join('') || `<tr><td colspan="6" style="color:var(--sub)">还没有问答记录</td></tr>`}</tbody></table>`;
}

function aiPreviewHTML() {
  return `
    <div class="pv"><b>客户会看到什么</b><span>随左侧配置变化</span><i>实时</i></div>
    <div class="ai-phone">
      <div class="ai-ph-head"><div class="av" style="overflow:hidden"><img src="/static/logo.svg" alt="" style="width:100%;height:100%;border-radius:50%"></div>
        <div><div class="nm">${T('DeskClerk AI · Support', 'DeskClerk AI · 官方支持')}</div><div class="st">${T('Online · verified', '在线 · 官方认证')}</div></div></div>
      <div class="ai-ph-body">
        <div class="ai-day">今天 10:42</div>
        <div class="ai-bub in" id="aiPhoneQ">${T('How soon can you ship spare parts for this model?', '这个型号的备件多久能到货？')}</div>
        <div class="ai-bub out" id="aiPhoneA"><span class="ai-aitag">${T('AI reply', 'AI 自动回复')}</span>${T('Standard parts arrive in 3–5 working days; non-standard parts take 7–10. Final timing follows the confirmed order schedule.', '标准件 3–5 个工作日到货，非标件 7–10 个工作日。具体以订单确认后的排产为准。')}
          <div class="ai-srcs"><span class="ai-src">${T('Spare-parts lead time', '备件交付周期说明')} · 0.82</span><span class="ai-src">${T('Logistics lead time', '物流时效表')} · 0.74</span></div></div>
        <div class="ai-meta right" id="aiPhoneMeta">10:42 · 2.3 秒</div>
      </div>
      <div class="ai-ph-foot"><div class="box">输入消息…</div><div class="send">➤</div></div>
    </div>
    <div class="ai-scn">
      <button class="on" onclick="aiScenario('normal',this)">正常回答</button>
      <button onclick="aiScenario('gap',this)">无知识依据</button>
      <button onclick="aiScenario('price',this)">价格拦截</button>
    </div>
    <div class="ai-result" id="aiResult">
      <div class="l"><span>命中知识</span><b>2 条</b></div>
      <div class="l"><span>最高相似度</span><b>0.82</b></div>
      <div class="l"><span>判断</span><b style="color:var(--green)">可自动回复</b></div>
      <div class="l"><span>耗时</span><b>2.3 秒</b></div>
    </div>
    <div class="ai-testbox">
      <input class="inp" id="aiTestQ" value="这个型号的备件多久能到货？">
      <button class="btn gold" onclick="aiRunTest()">发送测试</button>
    </div>`;
}

function aiInsightOf(c) {
  if (!c) return { status: '—', cls: 'c-gray', next: '—', days: null, summary: '' };
  const days = c.last_contact_at
    ? Math.max(0, Math.floor((Date.now() - new Date(String(c.last_contact_at).replace(' ', 'T')).getTime()) / 86400000))
    : null;
  const success = ['Won', 'Signed', 'Active', 'Enrolled', 'Renewed'].includes(c.deal_status);
  const stage = stageOf(c.deal_status);
  const stageTxt = T(stage.en, stage.zh);
  let status, cls, next;
  if (c.opt_out) {
    status = T('Risk · opted out', '风险 · 已退订'); cls = 'c-bad';
    next = T('Do not market — opted out', '已退订，不再营销');
  } else if (success) {
    status = T('Won', '已成交'); cls = 'c-ok';
    next = T('Maintain and upsell', '维护关系，争取复购');
  } else if (days != null && days > 30) {
    status = T('Dormant ' + days + 'd', '沉默 ' + days + ' 天'); cls = 'c-warn';
    next = T('Send a win-back template', '建议发召回模板');
  } else if (days != null && days <= 7) {
    status = T('Active', '活跃'); cls = 'c-ok';
    next = T('Keep the pace and reply promptly', '保持节奏，及时回复');
  } else {
    status = T('To follow up', '待跟进'); cls = 'c-warn';
    next = c.deal_status === 'Negotiating'
      ? T('Follow up on the quote today', '今天跟进报价')
      : T('Schedule a follow-up', '安排一次跟进');
  }
  const tags = (c.tags || []).slice(0, 2).map(t => t.name);
  const summary = T(
    `${c.country || ''} customer, currently ${stageTxt}${days != null ? ', last contact ' + days + ' days ago' : ''}`,
    `${c.country || ''}客户，当前${stageTxt}${days != null ? '，最后联系 ' + days + ' 天前' : ''}`);
  return { status, cls, next, days, tags, summary };
}

async function viewAI() {
  if (ME.role === 'agent') { go('inbox'); return; }
  try {
    const [cfg, logs] = await Promise.all([api('/api/ai/config'), api('/api/ai/logs?limit=50')]);
    AI_CFG = cfg;
    AI_MODE = cfg.mode || 'draft';
    AI_PERSONAS = JSON.parse(JSON.stringify(cfg.personas || {}));
    if (!AI_PERSONAS[AI_LOCALE]) AI_LOCALE = Object.keys(AI_PERSONAS)[0] || 'zh-CN';
    renderAI(cfg, logs.items || []);
  } catch (e) {
    if (e.message !== 'unauthorized') $('body').innerHTML = `<div class="loading">${esc(e.message)}</div>`;
  }
}

function renderAI(cfg, logs) {
  AI_LOGS = logs || [];
  const p = AI_PERSONAS[AI_LOCALE] || {};
  const modeLabel = AI_MODE_LABEL[AI_MODE] || AI_MODE;
  const blocks = (cfg.safety && cfg.safety.blocked_topics) || [];
  const keys = Array.from(new Set([...(cfg.locales||[]), ...Object.keys(AI_PERSONAS)]));
  $('hTitle').textContent = T('AI assistant', 'AI 助手');
  $('hSub').textContent = T('Knowledge base · persona · safety · live preview', '知识库 · 人设 · 安全边界 · 实时预览');
  $('body').innerHTML = `
  <div class="ai-page">
    <aside class="ai-nav">
      <div class="grp">AI 助手</div>
      <a class="on" data-ai="conn" onclick="aiTab('conn')"><span class="ico">⇄</span>接入配置</a>
      <a data-ai="policy" onclick="aiTab('policy')"><span class="ico">◎</span>回复策略</a>
      <a data-ai="persona" onclick="aiTab('persona')"><span class="ico">✎</span>人设与话术</a>
      <a data-ai="safety" onclick="aiTab('safety')"><span class="ico">⛨</span>安全边界</a>
      <div class="grp">知识与运行</div>
      <a data-ai="kb" onclick="aiTab('kb')"><span class="ico">▤</span>知识库状态</a>
      <a data-ai="logs" onclick="aiTab('logs')"><span class="ico">≡</span>问答日志</a>
      <a data-ai="test" onclick="aiTab('test')"><span class="ico">▶</span>测试提问</a>
    </aside>

    <div class="ai-main">
      <div class="ai-head"><div><h2>AI 助手</h2><p>${T('Third-party knowledge base · responses only inside the 24h window', '第三方知识库 · 只在 24 小时窗口内自动回复，价格与交期一律转人工')}</p></div>
        <div class="acts">
          <button class="btn" onclick="aiRunTest()">测试</button>
          <button class="btn gold" onclick="saveAIAll()">保存</button></div></div>
      <div class="ai-modebar">
        <span class="lbl">接待方式</span>
        ${[['off','人工接待'],['draft','AI 草稿'],['auto','AI 全自动托管']].map(([k,n]) =>
          `<button class="${AI_MODE===k?'on':''}" data-modebar="${k}" onclick="aiSetMode('${k}')">${n}</button>`).join('')}
        <span class="hint">${AI_MODE==='auto' ? 'AI 会直接回复客户；价格、合同、无依据会转人工' : AI_MODE==='draft' ? 'AI 只写草稿，需要人工点“采用”才发出' : 'AI 不参与，全部由人工回复'}</span>
      </div>

      <div class="ai-panel on" id="ai-p-conn">
        <div class="ai-card"><h3>平台连接 <small>一套知识库＝一个站点</small></h3>
          <div class="ai-desc">Key 只存服务端；页面只显示打码值。改完点右上角保存。</div>
          <div class="ai-field"><label>AI 大脑</label>
            <select class="inp" id="aiProvider" onchange="aiProviderChange()">
              <option value="deskclerk" ${(cfg.provider||'deskclerk')==='deskclerk'?'selected':''}>DeskClerk AI 知识库（推荐 · 原生适配）</option>
              <option value="custom" ${cfg.provider==='custom'?'selected':''}>其他知识库 / 自建</option>
            </select>
            <div class="hint"><a href="https://deskclerkai.com" target="_blank" rel="noopener">去 deskclerkai.com 创建站点和 Key →</a></div></div>
          <div class="ai-grid2">
            <div class="ai-field"><label>Base URL</label><input class="inp" id="aiBase" value="${aiEsc(cfg.base_url||'')}" placeholder="https://…/api/v1/integrations"></div>
            <div class="ai-field"><label>API Key</label><input class="inp" id="aiKey" value="" placeholder="${cfg.api_key_set ? (cfg.key_from_env ? T('Provided by server environment', '已由服务器环境变量提供') : aiEsc(cfg.api_key)) : T('Paste key (server-side only)', '粘贴 Key（只存服务端）')}"></div>
            <div class="ai-field"><label>站点 Site ID</label><input class="inp" id="aiSite" value="${aiEsc(cfg.site_id||'')}" placeholder="UUID"></div>
            <div class="ai-field"><label>Key 类型</label><div class="inp">租户级 · 可列站点、建站点</div></div>
          </div>
          <div class="ai-desc" style="margin:6px 0 0">scope：chat:write · knowledge:write · sync_status:read · conversations:read · site:write</div>
        </div>
        <div class="ai-card"><h3>语言 <small>按站点 + 语言隔离</small></h3>
          <div class="ai-chips">${(cfg.locales||[]).map(l => `<span class="ai-chip ok">${aiEsc(l)}</span>`).join('')}</div>
          <div class="ai-desc" style="margin:8px 0 0">知识点和提问必须使用同一语言；一种语言＝一条独立知识。</div>
        </div>
      </div>

      <div class="ai-panel" id="ai-p-policy">
        <div class="ai-card"><h3>回复模式</h3>
          <div class="ai-mode">${aiModeCards()}</div></div>
        <div class="ai-card"><h3>触发条件</h3>
          <div class="ai-row"><div><div class="lbl">置信度阈值</div><div class="sub">最高出处分低于此值转人工</div></div>
            <div class="ctl"><input type="range" id="aiTh" min="30" max="90" value="${Math.round((cfg.threshold||0.7)*100)}" oninput="document.getElementById('aiThV').textContent=this.value+'%'"><b id="aiThV" style="width:38px;text-align:right">${Math.round((cfg.threshold||0.7)*100)}%</b></div></div>
          <div class="ai-row"><div><div class="lbl">仅 24 小时窗口内自动回复</div><div class="sub">窗口外只发已审模板</div></div>
            <div class="ctl"><div class="sw ${cfg.window_only!==false?'on':''}" id="aiWindowSw" onclick="this.classList.toggle('on')"></div></div></div>
          <div class="ai-row"><div><div class="lbl">无知识依据时转人工</div><div class="sub">空 sources 不自动发</div></div>
            <div class="ctl"><div class="sw ${cfg.no_source_handoff!==false?'on':''}" id="aiNoSrcSw" onclick="this.classList.toggle('on')"></div></div></div>
          <div class="ai-row"><div><div class="lbl">自动回复标识</div><div class="sub">首条注明“AI 自动回复”</div></div>
            <div class="ctl"><div class="sw ${cfg.badge!==false?'on':''}" id="aiBadgeSw" onclick="this.classList.toggle('on')"></div></div></div>
          <div class="ai-row"><div><div class="lbl">每人每日上限</div><div class="sub">防止对同一客户刷屏</div></div>
            <div class="ctl"><input class="inp" id="aiDaily" type="number" min="0" max="500" value="${cfg.daily_limit||50}" style="width:82px;height:32px"></div></div>
        </div>
      </div>

      <div class="ai-panel" id="ai-p-persona">
        <div class="ai-card"><h3>人设与话术 <small>按语言独立保存</small></h3>
          <div class="ai-tabs" id="aiPersonaTabs">${keys.map(loc => `<span class="ai-tab ${loc===AI_LOCALE?'on':''}" onclick="aiSwitchLocale('${aiEsc(loc)}')">${aiEsc(loc)}</span>`).join('')}</div>
          <div id="aiPersonaFields">${aiPersonaFields(p)}</div>
        </div>
      </div>

      <div class="ai-panel" id="ai-p-safety">
        <div class="ai-card"><h3>禁止主题 <small>固定开启，不可关闭</small></h3>
          <div class="ai-desc">命中以下主题直接转人工，不调用 AI。</div>
          <div class="ai-chips">${blocks.map(b => `<span class="ai-chip lock">🔒 ${aiEsc(b)}</span>`).join('')}</div>
          <div class="ai-row" style="margin-top:10px"><div><div class="lbl">投诉 / 退款关键词转人工</div><div class="sub">用顿号或逗号分隔</div></div>
            <div class="ctl" style="flex:1"><input class="inp" id="aiComplaint" value="${aiEsc(((cfg.safety||{}).complaint_keywords||[]).join('、'))}"></div></div>
          <div class="ai-row"><div><div class="lbl">客户要求人工</div><div class="sub">命中即转人工</div></div>
            <div class="ctl" style="flex:1"><input class="inp" id="aiHandoff" value="${aiEsc(((cfg.safety||{}).handoff_keywords||[]).join('、'))}"></div></div>
        </div>
        <div class="ai-card"><h3>人设软约束</h3>
          <div class="ai-desc">这里是提示词级软约束；真正的硬拦截靠上面的禁止主题，在入口完成。</div>
        </div>
      </div>

      <div class="ai-panel" id="ai-p-kb">
        <div class="ai-card"><h3>知识库状态 <small>3 个站点</small></h3>
          <div class="ai-stats">
            <div class="ai-stat"><div class="k">已索引</div><div class="v">${cfg.kb?.indexed||0}</div><div class="d">条</div></div>
            <div class="ai-stat"><div class="k">待处理</div><div class="v" style="color:var(--green)">${cfg.kb?.pending||0}</div><div class="d">索引完成</div></div>
            <div class="ai-stat"><div class="k">失败</div><div class="v" style="color:var(--red)">${cfg.kb?.failed||0}</div><div class="d">需修正重推</div></div>
            <div class="ai-stat"><div class="k">最后同步</div><div class="v" style="font-size:14px">${aiEsc((cfg.kb?.last_sync||'—').slice(0,16))}</div><div class="d">自动回调</div></div>
          </div>
          <div class="ai-field" style="margin-top:12px"><label>索引完成回调</label><input class="inp" id="aiCallback" value="${aiEsc(cfg.kb?.callback_url||'')}" placeholder="https://…/api/ai/index-callback"></div>
          <button class="btn" onclick="aiKbSync()">立即同步</button>
        </div>
      </div>

      <div class="ai-panel" id="ai-p-logs">
        <div class="ai-card"><h3>问答日志 <small>最近的测试与真实问答</small></h3>
          <div id="aiLogsWrap">${aiLogsTable(AI_LOGS)}</div>
        </div>
      </div>

      <div class="ai-panel" id="ai-p-test">
        <div class="ai-card"><h3>测试提问 <small>不会发给客户</small></h3>
          <div class="ai-field"><label>问题</label><input class="inp" id="aiTestQ2" value="这个型号的备件多久能到货？"></div>
          <button class="btn gold" onclick="aiRunTest($('aiTestQ2').value)">发送测试</button>
          <div class="ai-desc" style="margin:10px 0 0">结果会显示在右侧预览，并写入问答日志。</div>
        </div>
      </div>
    </div>

    <aside class="ai-preview">${aiPreviewHTML()}</aside>
  </div>`;

  ['aiRole','aiIntro','aiScope','aiPolicyB'].forEach((id, i) => {
    const el = $(id); if (el) el.dispatchEvent(new Event('input'));
  });
  if ((cfg.provider||'deskclerk') === 'deskclerk' && !cfg.base_url) {
    const b = $('aiBase'); if (b) b.value = AI_DESKCLERK_BASE;
  }
  applyAITranslations($('body'));
  aiRenderPreview({
    question: T('How soon can you ship spare parts for this model?', '这个型号的备件多久能到货？'),
    answer: T('Standard parts arrive in 3–5 working days; non-standard parts take 7–10. Final timing follows the confirmed order schedule.', '标准件 3–5 个工作日到货，非标件 7–10 个工作日。\n具体以订单确认后的排产为准。'),
    sources: [{ title: T('Spare-parts lead time', '备件交付周期说明'), score: 0.82 },
              { title: T('Logistics lead time', '物流时效表'), score: 0.74 }],
    top_score: 0.82,
    decision: AI_MODE === 'auto' ? 'auto' : (AI_MODE === 'draft' ? 'draft' : 'off'),
    latency_ms: 2300,
  });
}

window.aiTab = (t) => {
  AI_TAB = t;
  document.querySelectorAll('.ai-nav a').forEach(a => a.classList.toggle('on', a.dataset.ai === t));
  document.querySelectorAll('.ai-panel').forEach(p => p.classList.toggle('on', p.id === 'ai-p-' + t));
};
window.aiSetMode = (m) => {
  AI_MODE = m;
  document.querySelectorAll('.ai-mode .m').forEach(x => x.classList.toggle('on', x.dataset.mode === m));
  document.querySelectorAll('[data-modebar]').forEach(x => x.classList.toggle('on', x.dataset.modebar === m));
  const pill = $('aiModePill'); if (pill) pill.textContent = AI_MODE_LABEL[m] || m;
  const hint = document.querySelector('.ai-modebar .hint');
  if (hint) hint.textContent = m === 'auto'
    ? T('AI replies directly; price, contract and no-source cases go to a human', 'AI 会直接回复客户；价格、合同、无依据会转人工')
    : m === 'draft'
    ? T('AI writes a draft; a human must accept it before sending', 'AI 只写草稿，需要人工点“采用”才发出')
    : T('AI stays out; all replies are manual', 'AI 不参与，全部由人工回复');
};
window.aiProviderChange = () => {
  const p = ($('aiProvider')||{}).value;
  const base = $('aiBase');
  if (p === 'deskclerk' && base && !base.value.trim()) base.value = AI_DESKCLERK_BASE;
};
window.aiCount = (el, max, id) => { const d = $(id); if (d) d.textContent = el.value.length + ' / ' + max; };

function aiCollectPersona() {
  return {
    system_role: ($('aiRole')||{}).value || '',
    company_intro: ($('aiIntro')||{}).value || '',
    product_scope: ($('aiScope')||{}).value || '',
    policy_boundaries: ($('aiPolicyB')||{}).value || '',
    tone: ($('aiTone')||{}).value || 'professional',
    reply_max_words: +($('aiWords')||{}).value || 180,
    timezone: ($('aiTz')||{}).value || 'Asia/Riyadh',
    business_hours: ($('aiHours')||{}).value || '',
  };
}
window.aiSwitchLocale = (loc) => {
  if (loc === AI_LOCALE) return;
  AI_PERSONAS[AI_LOCALE] = { ...(AI_PERSONAS[AI_LOCALE] || {}), ...aiCollectPersona() };
  AI_LOCALE = loc;
  if (!AI_PERSONAS[loc]) AI_PERSONAS[loc] = { ...(AI_PERSONAS['zh-CN'] || {}) };
  document.querySelectorAll('.ai-tab').forEach(x => x.classList.toggle('on', x.textContent.trim() === loc));
  const holder = $('aiPersonaFields');
  if (holder) {
    holder.innerHTML = aiPersonaFields(AI_PERSONAS[loc]);
    ['aiRole','aiIntro','aiScope','aiPolicyB'].forEach(id => { const el = $(id); if (el) el.dispatchEvent(new Event('input')); });
  }
};

window.saveAIAll = async () => {
  AI_PERSONAS[AI_LOCALE] = { ...(AI_PERSONAS[AI_LOCALE] || {}), ...aiCollectPersona() };
  const body = {
    provider: ($('aiProvider')||{}).value || 'deskclerk',
    mode: AI_MODE,
    threshold: (+$('aiTh').value || 70) / 100,
    window_only: $('aiWindowSw').classList.contains('on'),
    no_source_handoff: $('aiNoSrcSw').classList.contains('on'),
    badge: $('aiBadgeSw').classList.contains('on'),
    daily_limit: +$('aiDaily').value || 50,
    base_url: $('aiBase').value.trim(),
    site_id: $('aiSite').value.trim(),
    api_key: $('aiKey').value.trim(),
    personas: AI_PERSONAS,
    safety: { ...(AI_CFG.safety || {}),
      complaint_keywords: aiSplit($('aiComplaint').value),
      handoff_keywords: aiSplit($('aiHandoff').value) },
    kb: { ...(AI_CFG.kb || {}), callback_url: $('aiCallback').value.trim() },
  };
  try {
    const r = await api('/api/ai/config', { method: 'PATCH', body: JSON.stringify(body) });
    AI_CFG = r; toast(T('Saved', '已保存')); viewAI();
  } catch (e) { toast(e.message); }
};

function aiRenderPreview(r) {
  const q = $('aiPhoneQ'), a = $('aiPhoneA'), meta = $('aiPhoneMeta'), res = $('aiResult');
  if (!q || !a) return;
  q.textContent = r.question || '';
  const dec = AI_DEC[r.decision] || [r.decision, 'var(--sub)'];
  let tag = `<span class="ai-aitag">${T('AI reply', 'AI 自动回复')}</span>`;
  if (r.decision === 'draft') tag = `<span class="ai-aitag" style="background:var(--amber)">${T('AI draft', 'AI 草稿')}</span>`;
  if (r.decision === 'blocked') tag = `<span class="ai-aitag" style="background:var(--red)">${T('AI not called', '未调用 AI')}</span>`;
  if (r.decision === 'handoff') tag = `<span class="ai-aitag" style="background:var(--amber)">${T('Hand off', '转人工')}</span>`;
  if (r.decision === 'off') tag = `<span class="ai-aitag">${T('AI is off', 'AI 已关闭')}</span>`;
  const answer = r.answer || (r.decision === 'off' ? T('AI is off; a human will handle this message.', 'AI 当前关闭，消息由人工处理。')
    : r.decision === 'blocked' ? T('This has been handed to a colleague.', '这个问题已转给同事，稍后回复您。')
    : T('Let me confirm with a colleague and get back to you.', '这个问题我需要请同事确认，稍后回复您。'));
  const src = (r.sources && r.sources.length)
    ? `<div class="ai-srcs">${r.sources.map(s => `<span class="ai-src">${aiEsc(s.title)} · ${Number(s.score||0).toFixed(2)}</span>`).join('')}</div>`
    : `<div class="ai-srcs"><span class="ai-src" style="color:var(--sub)">无知识依据</span></div>`;
  a.innerHTML = tag + aiEsc(answer).replace(/\n/g, '<br>') + src;
  meta.textContent = aiMs(r.latency_ms);
  res.innerHTML = `
    <div class="l"><span>命中知识</span><b>${(r.sources||[]).length} 条</b></div>
    <div class="l"><span>最高相似度</span><b>${r.top_score==null?'—':Number(r.top_score).toFixed(2)}</b></div>
    <div class="l"><span>判断</span><b style="color:${dec[1]}">${dec[0]}</b></div>
    <div class="l"><span>耗时</span><b>${aiMs(r.latency_ms)}</b></div>`;
  applyAITranslations($('body'));
}

window.aiRunTest = async (q) => {
  q = (q != null ? q : ($('aiTestQ') ? $('aiTestQ').value : '')).trim();
  if (!q) return toast(T('Type a question first', '先输入一个问题'));
  try {
    const r = await api('/api/ai/test', { method: 'POST', body: JSON.stringify({ question: q }) });
    aiRenderPreview(r);
    AI_LOGS.unshift({ ...r, created_at: new Date().toISOString().slice(0, 19).replace('T', ' ') });
    const wrap = $('aiLogsWrap'); if (wrap) wrap.innerHTML = aiLogsTable(AI_LOGS.slice(0, 50));
    toast(T('Test done — not sent to any customer', '测试完成，没有发给任何客户'));
  } catch (e) { toast(e.message); }
};
window.aiScenario = (kind, el) => {
  document.querySelectorAll('.ai-scn button').forEach(b => b.classList.remove('on'));
  if (el) el.classList.add('on');
  const qs = {
    normal: '这个型号的备件多久能到货？',
    gap: '你们在土耳其有仓库吗？',
    price: '能不能便宜点，给我个最低价？',
  };
  const q = qs[kind] || qs.normal;
  const box = $('aiTestQ'); if (box) box.value = q;
  const box2 = $('aiTestQ2'); if (box2) box2.value = q;
  aiRunTest(q);
};
window.aiKbSync = async () => {
  try { await api('/api/ai/kb/sync', { method: 'POST', body: '{}' });
    toast(T('Knowledge sync triggered', '已触发同步')); viewAI();
  } catch (e) { toast(e.message); }
};
