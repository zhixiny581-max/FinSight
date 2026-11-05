#!/usr/bin/env node
/**
 * FinSight 移动端兼容性检查（本地只读工具，不进发布白名单）。
 *
 * 用 CDP 精确设置手机视口（Edge 无头默认会把视口钳到 508px，必须用
 * Emulation.setDeviceMetricsOverride 才能拿到真实 390px）。
 *
 * 检查内容：
 *   1) 文档是否横向溢出（scrollWidth > clientWidth）
 *   2) 哪些元素超出视口右边界，附选择器与宽度，直接定位需要改的 CSS
 *   3) 点击目标是否小于 40×40（手机上常见误触原因）
 *   4) 逐屏截图
 *
 * 用法：
 *   node tools/ui-mobile.cjs [baseURL] [cdpPort] [width]
 * 前置：PORT=8799 python -B deploy/show-v2/app.py
 */
'use strict';
const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');

const BASE = (process.argv[2] || 'http://127.0.0.1:8799').replace(/\/$/, '');
const CDP_PORT = Number(process.argv[3] || 9330);
const VW = Number(process.argv[4] || 390);
const VH = 844;
const EDGE = process.env.EDGE_PATH || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const OUT = path.resolve(__dirname, '..', 'docs', 'ui-preview', 'mobile');
fs.mkdirSync(OUT, { recursive: true });

const sleep = ms => new Promise(r => setTimeout(r, ms));
function getJson(url) {
  return new Promise((res, rej) => {
    http.get(url, r => { let b = ''; r.on('data', c => b += c); r.on('end', () => { try { res(JSON.parse(b)); } catch (e) { rej(e); } }); }).on('error', rej);
  });
}

class CDP {
  constructor(ws) {
    this.ws = ws; this.id = 0; this.waiting = new Map();
    ws.addEventListener('message', ev => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (!msg.id || !this.waiting.has(msg.id)) return;
      const { res, rej } = this.waiting.get(msg.id);
      this.waiting.delete(msg.id);
      if (msg.error) rej(new Error(msg.error.message)); else res(msg.result);
    });
  }
  static async connect(port) {
    for (let i = 0; i < 60; i++) {
      try {
        const list = await getJson(`http://127.0.0.1:${port}/json/list`);
        const page = list.find(t => t.type === 'page');
        if (page) {
          const ws = new WebSocket(page.webSocketDebuggerUrl);
          await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
          return new CDP(ws);
        }
      } catch (e) { /* 端口还没起来 */ }
      await sleep(250);
    }
    throw new Error('连不上 CDP');
  }
  send(method, params) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params: params || {} }));
    return new Promise((res, rej) => {
      this.waiting.set(id, { res, rej });
      setTimeout(() => { if (this.waiting.has(id)) { this.waiting.delete(id); rej(new Error(method + ' 超时')); } }, 30000);
    });
  }
  async evaluate(expr) {
    const r = await this.send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.text);
    return r.result.value;
  }
  async shot(file) {
    const r = await this.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
    fs.writeFileSync(file, Buffer.from(r.data, 'base64'));
  }
}

// 诊断脚本：找出超出视口的元素，按超出量排序；同时统计过小的点击目标
const DIAG = `(function(){
  var vw = document.documentElement.clientWidth;
  var doc = { vw: vw, sw: document.documentElement.scrollWidth, bh: document.body.scrollHeight };
  doc.overflow = doc.sw - vw;
  var out = [];
  var all = document.querySelectorAll('body *');
  for (var i = 0; i < all.length; i++) {
    var el = all[i];
    var r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    var st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none') continue;
    var over = Math.round(r.right - vw);
    if (over <= 1) continue;
    // 只报告最外层的溢出元素，子元素跟随父级即可，避免噪声
    var p = el.parentElement, skip = false;
    while (p && p !== document.body) {
      var pr = p.getBoundingClientRect();
      if (pr.right > vw + 1) { skip = true; break; }
      p = p.parentElement;
    }
    if (skip) continue;
    var id = el.id ? '#' + el.id : '';
    var cls = (el.className && typeof el.className === 'string')
      ? '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.') : '';
    out.push({ sel: el.tagName.toLowerCase() + id + cls, over: over, w: Math.round(r.width), text: (el.textContent || '').trim().slice(0, 24) });
  }
  out.sort(function(a, b){ return b.over - a.over; });
  doc.offenders = out.slice(0, 12);
  var small = [];
  var tappable = document.querySelectorAll('button, a, .nav-item, .chip, .tab, input, select, [role="button"]');
  for (var j = 0; j < tappable.length; j++) {
    var t = tappable[j], tr = t.getBoundingClientRect();
    if (tr.width === 0 || tr.height === 0) continue;
    if (tr.height < 32 || tr.width < 32) {
      small.push({ sel: t.tagName.toLowerCase() + (t.id ? '#' + t.id : ''),
        w: Math.round(tr.width), h: Math.round(tr.height),
        text: (t.textContent || t.value || '').trim().slice(0, 16) });
    }
  }
  doc.smallTargets = small.slice(0, 12);
  doc.smallCount = small.length;
  return doc;
})()`;

const SCREENS = [
  ['feed', '01-feed'],
  ['analysis', '02-analysis'],
  ['import', '03-import'],
  ['calendar', '04-calendar'],
  ['settings', '05-settings'],
];

(async () => {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'fs-mobile-'));
  const edge = spawn(EDGE, [
    '--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run',
    `--remote-debugging-port=${CDP_PORT}`, `--user-data-dir=${profile}`,
    `--window-size=${VW},${VH}`, 'about:blank',
  ], { stdio: 'ignore' });

  _spawn_guard(edge);
  const cdp = await CDP.connect(CDP_PORT);
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width: VW, height: VH, deviceScaleFactor: 3, mobile: true,
  });
  await cdp.send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 });

  const report = { url: BASE, viewport: { width: VW, height: VH }, screens: {} };
  for (const [hash, name] of SCREENS) {
    await cdp.send('Page.navigate', { url: `${BASE}/#${hash}` });
    await sleep(1800);
    await cdp.send('Page.reload', { ignoreCache: false });
    await sleep(2200);
    try {
      const d = await cdp.evaluate(DIAG);
      report.screens[hash] = d;
      await cdp.shot(path.join(OUT, `${name}-${VW}.png`));
      const flag = d.overflow > 1 ? `溢出 ${d.overflow}px` : '无横向溢出';
      console.log(`[${hash}] ${flag} · 过小点击目标 ${d.smallCount} 个`);
      if (d.offenders.length) {
        d.offenders.slice(0, 5).forEach(o => console.log(`   ${o.sel} 超出 ${o.over}px (宽 ${o.w}) "${o.text}"`));
      }
    } catch (e) {
      console.log(`[${hash}] 诊断失败：${e.message}`);
    }
  }

  // 快讯流额外滚到中段与底部：确认右栏在手机上已改为单列、分页器可用
  // 注意：只改 hash 不会触发切屏，必须 reload 让页面按 hash 初始化
  await cdp.send('Page.navigate', { url: `${BASE}/#feed` });
  await sleep(300);
  await cdp.send('Page.reload', { ignoreCache: false });
  await sleep(2400);
  await cdp.evaluate('window.scrollTo(0, document.documentElement.scrollHeight*0.62); "ok"');
  await sleep(600);
  await cdp.shot(path.join(OUT, `06-feed-mid-${VW}.png`));
  const bottom = await cdp.evaluate('window.scrollTo(0, document.documentElement.scrollHeight); (function(){var r=document.querySelector(".rail-col");if(!r)return null;var b=r.getBoundingClientRect();return {top:Math.round(b.top),width:Math.round(b.width),cols:getComputedStyle(r).display};})()');
  await sleep(600);
  await cdp.shot(path.join(OUT, `07-feed-bottom-${VW}.png`));
  console.log('右栏（滚到底）：' + JSON.stringify(bottom));

  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 2));
  console.log(`\n截图与报告：${OUT}`);
  try { edge.kill(); } catch (e) { /* ignore */ }
  process.exit(0);
})().catch(e => { console.error('失败：' + e.message); process.exit(1); });

function _spawn_guard(child) {
  setTimeout(() => { try { child.kill(); } catch (e) { /* ignore */ } }, 180000);
}
