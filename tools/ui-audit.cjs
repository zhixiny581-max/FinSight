#!/usr/bin/env node
/**
 * FinSight 前端控件审计（只读，不碰数据接口判断）。
 *
 * 对页面上每个可交互元素做三项检测：
 *   1) CSS cursor 是否声明为可点击
 *   2) 是否绑定了 click 监听（通过 hook EventTarget.addEventListener 记录，含祖先委托）
 *   3) 点击前后页面状态指纹是否变化
 * 据此判定：responds / listener-no-change / dead-pointer / static / form-control
 *
 * 用法：node tools/ui-audit.cjs [baseURL] [cdpPort]
 * 前置：PORT=8765 python -B deploy/show-v2/app.py
 * 产物：docs/ui-preview/audit/report.json
 */
'use strict';
const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');

const BASE = (process.argv[2] || 'http://127.0.0.1:8765').replace(/\/$/, '');
const CDP_PORT = Number(process.argv[3] || 9226);
const EDGE = process.env.EDGE_PATH || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const OUT = path.resolve(__dirname, '..', 'docs', 'ui-preview', 'audit');
fs.mkdirSync(OUT, { recursive: true });
const sleep = ms => new Promise(r => setTimeout(r, ms));

function getJson(url) {
  return new Promise((res, rej) => {
    http.get(url, r => { let b = ''; r.on('data', c => b += c); r.on('end', () => { try { res(JSON.parse(b)); } catch (e) { rej(e); } }); }).on('error', rej);
  });
}

// 在页面脚本执行前注入：记录所有 addEventListener 绑定 + 状态指纹
const PATCH = `(()=>{
  const orig = EventTarget.prototype.addEventListener;
  const map = new WeakMap();
  EventTarget.prototype.addEventListener = function(t,f,o){
    try{ let m=map.get(this); if(!m){m=Object.create(null);map.set(this,m);} (m[t]=m[t]||[]).push(f); }catch(e){}
    return orig.call(this,t,f,o);
  };
  window.__own = function(el,t){ const m=map.get(el); return m&&m[t]?m[t].length:0; };
  window.__up = function(el,t){ let n=0,e=el.parentElement,d=0; while(e&&d<8){ const m=map.get(e); if(m&&m[t])n+=m[t].length; e=e.parentElement; d++; } return n; };
  window.__fp = function(){
    const s=document.querySelector('.screen.active');
    const open=document.querySelector('.chain-modal-scrim.on,.modal-scrim.on,.drawer.on');
    const act=[].slice.call(document.querySelectorAll('.nav-item.active,.seg button.on')).map(e=>e.dataset.screen||e.dataset.v||'').join(',');
    return [document.documentElement.dataset.theme, s?s.id:'', location.hash,
      document.body.innerHTML.length, open?open.className:'', act].join('|');
  };
  window.__q = function(sel){ return [].slice.call(document.querySelectorAll(sel)).filter(function(e){ var r=e.getBoundingClientRect(); return r.width>0&&r.height>0; }); };
})();`;

const SEL = ['button', 'a[href]', '[data-screen]', 'select', 'input', 'textarea',
  '.news', '.hotrow', '.fav', '.cw', '.cal-d', '.chip', '[role="button"]',
  '.node', '.direct-impact-card', '.dropzone', '#impTabs button', '#tblBody tr', '#impBody tr'].join(',');

const ENUM = `(()=>{
  const SEL=${JSON.stringify(SEL)};
  const groups={}, out=[];
  window.__q(SEL).forEach(function(e, di){
    const cls=(e.className||'').toString().split(/\\s+/)[0]||'';
    const key=e.tagName+'|'+cls;
    groups[key]=(groups[key]||0)+1;
    if(groups[key]>2) return;                       // 同类最多取 2 个样本
    const cs=getComputedStyle(e);
    out.push({di:di, tag:e.tagName.toLowerCase(), id:e.id||'', cls:(e.className||'').toString().slice(0,48),
      text:(e.textContent||'').replace(/\\s+/g,' ').trim().slice(0,44),
      cursor:cs.cursor, own:window.__own(e,'click'), up:window.__up(e,'click'),
      disabled:!!e.disabled, href:e.getAttribute('href')||'', screen:(document.querySelector('.screen.active')||{}).id||''});
  });
  return out;
})()`;

class CDP {
  constructor(ws) {
    this.ws = ws; this.id = 0; this.pending = new Map();
    ws.addEventListener('message', ev => {
      const m = JSON.parse(ev.data);
      if (m.id && this.pending.has(m.id)) { this.pending.get(m.id)(m); this.pending.delete(m.id); }
    });
  }
  cmd(method, params = {}) {
    return new Promise(res => { const i = ++this.id; this.pending.set(i, res); this.ws.send(JSON.stringify({ id: i, method, params })); });
  }
  async ev(expression) {
    const r = await this.cmd('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (r.result && r.result.exceptionDetails) return { __err: r.result.exceptionDetails.text };
    return r.result && r.result.result ? r.result.result.value : null;
  }
}

async function main() {
  const userDir = path.join(os.tmpdir(), 'finsight-audit-' + Date.now());
  const edge = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--hide-scrollbars', '--window-size=1440,900', '--remote-debugging-port=' + CDP_PORT,
    '--user-data-dir=' + userDir, 'about:blank'], { stdio: 'ignore', windowsHide: true });
  try {
    let list = null;
    for (let i = 0; i < 40; i++) {
      try { list = await getJson('http://127.0.0.1:' + CDP_PORT + '/json/list'); if (list.some(t => t.type === 'page' && t.url === 'about:blank')) break; } catch (e) { }
      await sleep(300);
    }
    const page = (list || []).find(t => t.type === 'page' && t.url === 'about:blank');
    if (!page) throw new Error('无法连接 CDP ' + CDP_PORT);
    const ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', () => rej(new Error('ws error'))); });
    const cdp = new CDP(ws);
    await cdp.cmd('Page.enable'); await cdp.cmd('Runtime.enable');
    await cdp.cmd('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
    await cdp.cmd('Page.addScriptToEvaluateOnNewDocument', { source: PATCH });

    // 每个元素都从「无本地状态」的干净基线开始：
    // 页面已支持收藏/筛选持久化，若不清空，reload 后列表长度会变，元素索引随之漂移。
    const goto = async screen => {
      const path = screen && screen !== 'feed' ? '/core#' + screen : '/core';
      await cdp.cmd('Page.navigate', { url: BASE + path });
      await sleep(400);
      await cdp.ev("try{localStorage.clear()}catch(e){};'ok'");
      await cdp.cmd('Page.reload', { ignoreCache: false });
      await sleep(2600);
    };
    await cdp.cmd('Page.navigate', { url: BASE + '/core' });
    await sleep(2600);
    await cdp.ev("try{localStorage.clear()}catch(e){};'ok'");
    await cdp.cmd('Page.reload', { ignoreCache: false });
    await sleep(2600);

    const screens = ['feed', 'analysis', 'import', 'calendar'];
    const results = [];
    for (const screen of screens) {
      await goto(screen);
      const list0 = await cdp.ev(ENUM);
      console.log('--- ' + screen + ' 屏可交互元素 ' + list0.length + ' 个 ---');
      for (let i = 0; i < list0.length; i++) {
        const meta = list0[i];
        if (meta.tag === 'a' && meta.href && !meta.href.startsWith('#')) { results.push({ ...meta, verdict: 'external-link', changed: null }); continue; }
        if (['input', 'select', 'textarea'].includes(meta.tag)) { results.push({ ...meta, verdict: 'form-control', changed: null }); continue; }

        await goto(screen);                       // 每个元素从干净状态开始
        const cur = await cdp.ev(ENUM);
        const el = cur[i];
        if (!el || el.tag !== meta.tag || el.cls.split(' ')[0] !== meta.cls.split(' ')[0]) {
          results.push({ ...meta, verdict: 'unstable', changed: null }); continue;
        }
        const before = await cdp.ev('window.__fp()');
        const clicked = await cdp.ev(`(function(){var e=window.__q(${JSON.stringify(SEL)})[${el.di}]; if(!e) return 'missing'; e.click(); return 'ok';})()`);
        await sleep(650);
        const after = await cdp.ev('window.__fp()');
        const changed = before !== after;
        let verdict;
        if (clicked !== 'ok') verdict = 'not-clickable';
        else if (changed) verdict = 'responds';
        else if (el.own + el.up > 0) verdict = 'listener-no-change';
        else if (el.cursor === 'pointer') verdict = 'dead-pointer';
        else verdict = 'static';
        results.push({ ...el, verdict, changed, before: String(before).slice(0, 80), after: String(after).slice(0, 80) });
        console.log('  [' + verdict + '] ' + el.tag + (el.id ? '#' + el.id : '') + '.' + el.cls.split(' ')[0] + ' "' + el.text + '" cursor=' + el.cursor + ' own=' + el.own + ' up=' + el.up);
      }
    }

    // ---- 结构性探测（不依赖点击） ----
    await goto('feed');
    const probe = await cdp.ev(`JSON.stringify({
      hashAfterNav: location.hash,
      hasResetButton: !!document.querySelector('#feedFilterReset,[data-action="reset"],.filterbar .btn.reset'),
      hasBackToTop: !!document.querySelector('[class*="back-to-top"],[id*="backTop"],[class*="to-top"]'),
      hasReviewMatrix: !!document.querySelector('[class*="matrix"],[class*="review-grid"]'),
      hasDropzone: !!document.querySelector('.dropzone'),
      cwCursor: (function(){var e=document.querySelector('.cw');return e?getComputedStyle(e).cursor:null})(),
      cwHasListener: (function(){var e=document.querySelector('.cw');return e?window.__own(e,'click')+window.__up(e,'click'):null})(),
      weekstripCursor: (function(){var e=document.querySelector('#weekStrip .c');return e?getComputedStyle(e).cursor:null})(),
      weekstripHasListener: (function(){var e=document.querySelector('#weekStrip .c');return e?window.__own(e,'click')+window.__up(e,'click'):null})(),
      calDayCursor: (function(){var e=document.querySelector('#calGrid .cal-d');return e?getComputedStyle(e).cursor:null})(),
      calDayHasListener: (function(){var e=document.querySelector('#calGrid .cal-d');return e?window.__own(e,'click')+window.__up(e,'click'):null})(),
      hotlistCount: document.querySelectorAll('#hotList .hotrow').length,
      hasHotAll: !!document.querySelector('#hotList a, #hotAllBtn, [data-act="hotAll"]'),
      hasPrevNext: !!document.querySelector('#anaPrev,#anaNext,[data-act="prev"],[data-act="next"]'),
      favAria: (function(){var e=document.querySelector('.fav');return e?e.getAttribute('aria-pressed'):null})(),
      localStorageKeys: Object.keys(localStorage),
      searchOnOtherScreen: null
    })`);
    console.log('\n--- 结构性探测 ---\n' + probe);

    // 跨屏搜索是否生效
    await cdp.ev(`window.__q('[data-screen="analysis"]')[0].click();'ok'`);
    await sleep(600);
    await cdp.ev(`(function(){var q=document.querySelector('#feedSearch');q.value='测试';q.dispatchEvent(new Event('input',{bubbles:true}));return 'ok'})()`);
    await sleep(600);
    const crossScreen = await cdp.ev(`JSON.stringify({screen:(document.querySelector('.screen.active')||{}).id, searchValue:(document.querySelector('#feedSearch')||{}).value, hash:location.hash})`);
    console.log('跨屏搜索:', crossScreen);

    // 快捷键：/ 是否聚焦搜索
    await goto('feed');
    const focusedBefore = await cdp.ev(`document.activeElement ? document.activeElement.id || document.activeElement.tagName : null`);
    await cdp.cmd('Input.dispatchKeyEvent', { type: 'keyDown', key: '/', code: 'Slash', windowsVirtualKeyCode: 191 });
    await cdp.cmd('Input.dispatchKeyEvent', { type: 'keyUp', key: '/', code: 'Slash', windowsVirtualKeyCode: 191 });
    await sleep(400);
    const focusedAfter = await cdp.ev(`document.activeElement ? document.activeElement.id || document.activeElement.tagName : null`);
    console.log('快捷键 / 聚焦:', focusedBefore, '->', focusedAfter);

    const report = { base: BASE, generatedAt: new Date().toISOString(),
      probe: JSON.parse(probe), crossScreenSearch: JSON.parse(crossScreen),
      slashFocus: { before: focusedBefore, after: focusedAfter }, results };
    fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 2), 'utf8');
    const tally = {};
    results.forEach(r => tally[r.verdict] = (tally[r.verdict] || 0) + 1);
    console.log('\n汇总:', JSON.stringify(tally));
    console.log('REPORT', path.join(OUT, 'report.json'));
    ws.close();
  } finally { try { edge.kill(); } catch (e) { } }
}
main().catch(e => { console.error('AUDIT_FAILED', e.message); process.exitCode = 1; });
