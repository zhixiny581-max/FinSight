#!/usr/bin/env node
/**
 * FinSight 展示站 UI 冒烟检查（本地验证工具，不进入发布白名单）。
 *
 * 前置：先启动展示站服务，例如
 *   PORT=8765 DATA_DIR=<临时目录> python -B deploy/show-v2/app.py
 * 运行：
 *   node tools/ui-smoke.cjs [baseURL] [cdpPort]
 * 默认 baseURL=http://127.0.0.1:8765，cdpPort=9224
 *
 * 产物：docs/ui-preview/smoke/report.json + 若干截图。
 * 只做只读的界面操作；不会写入密钥或提交任何数据到外部服务。
 */
'use strict';
const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');

const BASE = (process.argv[2] || 'http://127.0.0.1:8765').replace(/\/$/, '');
const CDP_PORT = Number(process.argv[3] || 9224);
const EDGE = process.env.EDGE_PATH || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const OUT = path.resolve(__dirname, '..', 'docs', 'ui-preview', 'smoke');
fs.mkdirSync(OUT, { recursive: true });

const sleep = ms => new Promise(r => setTimeout(r, ms));
function getJson(url) {
  return new Promise((res, rej) => {
    http.get(url, r => { let b = ''; r.on('data', c => b += c); r.on('end', () => { try { res(JSON.parse(b)); } catch (e) { rej(e); } }); }).on('error', rej);
  });
}

// 注入到页面里的只读辅助函数
const HELPERS = `window.__smoke={
 q:function(s){return document.querySelector(s)},
 qa:function(s){return [].slice.call(document.querySelectorAll(s))},
 txt:function(s){var e=this.q(s);return e?e.textContent.trim():null},
 num:function(s){return this.qa(s).length},
 on:function(s){var e=this.q(s);return !!e&&e.classList.contains('on')},
 active:function(){var e=this.q('.screen.active');return e?e.id:null},
 badText:function(){var t=document.body.innerText||'';var m=t.match(/undefined|NaN|\\[object Object\\]|null(?=\\s|，|。|:|$)/g);return m?m.slice(0,12):[]},
 state:function(){return {screen:this.active(),feed:this.num('#feedList .news'),
   desc:this.txt('#feedDesc'),mode:this.txt('#dataModeTag'),weekNote:this.txt('#weekNote'),
   hot:this.num('#hotList .hotrow'),theme:document.documentElement.dataset.theme,
   bad:this.badText(),vw:document.documentElement.clientWidth,sw:document.documentElement.scrollWidth}}
};'ok'`;

class CDP {
  constructor(ws) {
    this.ws = ws; this.id = 0; this.pending = new Map(); this.events = [];
    ws.addEventListener('message', ev => {
      const m = JSON.parse(ev.data);
      if (m.id && this.pending.has(m.id)) { this.pending.get(m.id)(m); this.pending.delete(m.id); return; }
      if (m.method === 'Runtime.exceptionThrown')
        this.events.push({ type: 'exception', text: (m.params.exceptionDetails.exception || {}).description || m.params.exceptionDetails.text,
          url: m.params.exceptionDetails.url || '', line: m.params.exceptionDetails.lineNumber });
      if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error')
        this.events.push({ type: 'console', text: m.params.args.map(a => a.value || a.description || '').join(' ') });
      if (m.method === 'Log.entryAdded' && ['error', 'warning'].includes(m.params.entry.level))
        this.events.push({ type: 'log', text: m.params.entry.text, url: m.params.entry.url || '' });
      if (m.method === 'Network.responseReceived' && m.params.response.status >= 400)
        this.events.push({ type: 'http', status: m.params.response.status, url: m.params.response.url });
    });
  }
  cmd(method, params = {}) {
    return new Promise(res => { const i = ++this.id; this.pending.set(i, res); this.ws.send(JSON.stringify({ id: i, method, params })); });
  }
  async evaluate(expression) {
    const r = await this.cmd('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (r.result && r.result.exceptionDetails)
      return { __evalError: r.result.exceptionDetails.text || 'eval exception' };
    return r.result && r.result.result ? r.result.result.value : null;
  }
  async shot(name) {
    const r = await this.cmd('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
    if (r.result && r.result.data) { fs.writeFileSync(path.join(OUT, name + '.png'), Buffer.from(r.result.data, 'base64')); return true; }
    return false;
  }
}

async function main() {
  const userDir = path.join(os.tmpdir(), 'finsight-smoke-edge-' + CDP_PORT + '-' + Date.now());
  const edge = spawn(EDGE, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--hide-scrollbars', '--window-size=1440,900', '--remote-debugging-port=' + CDP_PORT,
    '--user-data-dir=' + userDir, 'about:blank'
  ], { stdio: 'ignore', windowsHide: true });

  try {
    let list = null;
    for (let i = 0; i < 40; i++) {
      try { list = await getJson('http://127.0.0.1:' + CDP_PORT + '/json/list'); if (list.some(t => t.type === 'page' && t.url === 'about:blank')) break; } catch (e) { }
      await sleep(300);
    }
    const page = (list || []).find(t => t.type === 'page' && t.url === 'about:blank');
    if (!page) throw new Error('无法连接 Edge CDP 端口 ' + CDP_PORT);

    const ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', () => rej(new Error('WebSocket 连接失败'))); });
    const cdp = new CDP(ws);
    await cdp.cmd('Page.enable'); await cdp.cmd('Runtime.enable');
    await cdp.cmd('Log.enable'); await cdp.cmd('Network.enable');
    await cdp.cmd('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
    await cdp.cmd('Page.navigate', { url: BASE + '/core' });
    await sleep(4500);
    await cdp.evaluate(HELPERS);

    const steps = [];
    async function run(name, action, probe, opts = {}) {
      const before = cdp.events.length;
      if (action) {
        const r = await cdp.evaluate(action);
        if (r && r.__evalError) steps.push({ name, evalError: r.__evalError });
      }
      await sleep(opts.wait || 900);
      const state = await cdp.evaluate(probe || 'JSON.stringify(window.__smoke.state())');
      let parsed = state;
      if (typeof state === 'string') { try { parsed = JSON.parse(state); } catch (e) { parsed = { raw: state }; } }
      const newErrors = cdp.events.slice(before).map(e => {
        if (e.type === 'http') return 'HTTP ' + e.status + ' ' + e.url.replace(BASE, '');
        return e.type + ': ' + String(e.text || '').slice(0, 220);
      });
      const shot = opts.shot ? (await cdp.shot(name)) : false;
      steps.push({ name, state: parsed, newErrors, screenshot: shot ? name + '.png' : null });
      console.log('[' + name + '] ' + JSON.stringify(parsed) + (newErrors.length ? ' ERR=' + JSON.stringify(newErrors.slice(0, 3)) : ''));
    }

    const S = 'JSON.stringify(window.__smoke.state())';
    const click = s => `window.__smoke.q(${JSON.stringify(s)}).click();'ok'`;
    const setSelect = (s, v) => `(function(){var e=window.__smoke.q(${JSON.stringify(s)});e.value=${JSON.stringify(v)};e.dispatchEvent(new Event('change',{bubbles:true}));return 'ok'})()`;
    const setInput = (s, v) => `(function(){var e=window.__smoke.q(${JSON.stringify(s)});e.value=${JSON.stringify(v)};e.dispatchEvent(new Event('input',{bubbles:true}));return 'ok'})()`;

    await run('00-initial', null, S, { wait: 1200, shot: true });
    await run('01-dark-mode', click('#themeBtn'), S, { shot: true });
    await run('02-light-mode', click('#themeBtn'), S);
    await run('03-search-policy', setInput('#feedSearch', '政策'), S);
    await run('04-search-clear', setInput('#feedSearch', ''), S);
    await run('05-star5-filter', click('[data-filter="stars"] button[data-v="5"]'), S);
    await run('06-star-all', click('[data-filter="stars"] button[data-v="0"]'), S);
    await run('07-date-pop', click('#dateBtn'), `JSON.stringify({...window.__smoke.state(),pop:window.__smoke.on('#datePanel'),popDays:window.__smoke.num('#datePanel .cal-d')})`);
    await run('08-tag-macro', setSelect('[data-filter="tag"]', '宏观级'), S);
    await run('09-fav-only', click('#favFilterBtn'), S);
    await run('10-sort-stars', setSelect('[data-filter="sort"]', 'stars'), S);
    await run('11-cloud-table', click('#cloudToggle'), `JSON.stringify({...window.__smoke.state(),cloud:window.__smoke.txt('#cloudWrap').slice(0,60)})`);
    await run('12-manual-refresh', click('#feedRefreshBtn'), S, { wait: 4000 });
    await run('13-open-analysis', click('[data-screen="analysis"]'), `JSON.stringify({...window.__smoke.state(),docTitle:window.__smoke.txt('#docTitle'),aiStatus:window.__smoke.txt('#aiStatus')})`, { shot: true });
    await run('14-run-ai', click('#anaRun'), `JSON.stringify({...window.__smoke.state(),aiStatus:window.__smoke.txt('#aiStatus'),marketNote:window.__smoke.txt('#marketViewNote')})`, { wait: 3500 });
    await run('15-market-pre-event', click('#marketPreEvent'), `JSON.stringify({...window.__smoke.state(),marketNote:window.__smoke.txt('#marketViewNote'),dataNote:window.__smoke.txt('#macroDataNote')})`, { wait: 2500 });
    await run('16-market-refresh', click('#marketRefresh'), S, { wait: 2500 });
    await run('17-chain-expand', click('#chainExpandBtn'), `JSON.stringify({...window.__smoke.state(),modal:window.__smoke.on('#chainModalScrim'),aria:window.__smoke.q('#chainExpandBtn').getAttribute('aria-expanded')})`, { shot: true });
    await run('18-chain-close', click('#chainModalClose'), `JSON.stringify({...window.__smoke.state(),modal:window.__smoke.on('#chainModalScrim')})`);
    await run('19-stock-filter', setSelect('#stockImpactTypeFilter', 'direct'), `JSON.stringify({...window.__smoke.state(),stockRows:window.__smoke.num('#tblBody tr'),count:window.__smoke.txt('#stockFilterCount')})`);
    await run('20-open-import', click('[data-screen="import"]'), `JSON.stringify({...window.__smoke.state(),impRows:window.__smoke.num('#impBody tr'),impStatus:window.__smoke.txt('#importStatus')})`, { shot: true });
    await run('21-import-submit', `(function(){var t=window.__smoke.q('#importLink');t.value='http://127.0.0.1:'+${CDP_PORT}+'/nonexistent';return 'ok'})()`, `JSON.stringify({...window.__smoke.state(),impStatus:window.__smoke.txt('#importStatus')})`, { wait: 1500 });
    await run('22-import-click', click('#importBtn'), `JSON.stringify({...window.__smoke.state(),impStatus:window.__smoke.txt('#importStatus'),impRows:window.__smoke.num('#impBody tr')})`, { wait: 4000 });
    await run('23-import-tag-modal', click('#importTagBtn'), `JSON.stringify({...window.__smoke.state(),modal:window.__smoke.on('#importModalScrim'),modalTitle:window.__smoke.txt('#importModalTitle')})`, { shot: true });
    await run('24-import-modal-close', click('#importModalClose'), `JSON.stringify({...window.__smoke.state(),modal:window.__smoke.on('#importModalScrim')})`);
    await run('25-open-calendar', click('[data-screen="calendar"]'), `JSON.stringify({...window.__smoke.state(),calTitle:window.__smoke.txt('#calTitle'),openN:window.__smoke.txt('#calOpenN'),closedN:window.__smoke.txt('#calClosedN'),calNext:window.__smoke.txt('#calNext'),days:window.__smoke.num('#calGrid .cal-d'),holidays:window.__smoke.num('#holidayBody tr')})`, { shot: true });
    await run('26-cal-prev', click('#calPrev'), `JSON.stringify({...window.__smoke.state(),calTitle:window.__smoke.txt('#calTitle')})`);
    await run('27-cal-today', click('#calToday'), `JSON.stringify({...window.__smoke.state(),calTitle:window.__smoke.txt('#calTitle')})`);
    await run('28-back-feed', click('[data-screen="feed"]'), S);

    // ---- 主链路与边界补充探测 ----
    await run('30-empty-state', setInput('#feedSearch', 'ZZZ_不存在的关键词'), `JSON.stringify({...window.__smoke.state(),emptyCard:(window.__smoke.txt('#feedList')||'').slice(0,60)})`);
    await run('31-search-reset', setInput('#feedSearch', ''), S);
    await run('32-click-news-card', click('#feedList .news'), `JSON.stringify({...window.__smoke.state(),docTitle:window.__smoke.txt('#docTitle')})`, { shot: true });
    await run('33-ai-run-feedback', click('#anaRun'), `JSON.stringify({...window.__smoke.state(),aiStatus:window.__smoke.txt('#aiStatus')})`, { wait: 2500 });
    await run('34-stock-row-click', click('#tblBody tr'), `JSON.stringify({...window.__smoke.state(),drawer:window.__smoke.on('.drawer'),kSub:window.__smoke.txt('#kSub')})`, { wait: 1800, shot: true });
    await run('35-back-feed-2', click('[data-screen="feed"]'), S);
    await run('36-fav-toggle', click('#feedList .fav'), `JSON.stringify({...window.__smoke.state(),favCount:window.__smoke.txt('#stFav')})`);
    await run('37-hotrow-click', click('#hotList .hotrow'), `JSON.stringify({...window.__smoke.state(),docTitle:window.__smoke.txt('#docTitle')})`);
    await run('38-import-tag-status', click('[data-screen="import"]'), `JSON.stringify({...window.__smoke.state()})`);
    await run('39-import-tag-click', click('#importTagBtn'), `JSON.stringify({...window.__smoke.state(),impStatus:window.__smoke.txt('#importStatus'),modal:window.__smoke.on('#importModalScrim')})`);
    await run('40-calendar-day', click('[data-screen="calendar"]'), `JSON.stringify({...window.__smoke.state()})`);
    await run('41-cal-day-select', click('#calGrid .cal-d:not(.out)'), `JSON.stringify({...window.__smoke.state(),calTitle:window.__smoke.txt('#calTitle')})`);
    await run('42-theme-persist', click('#themeBtn'), `JSON.stringify({...window.__smoke.state(),savedTheme:localStorage.getItem('finsight-theme')||localStorage.getItem('theme')||null,lsKeys:Object.keys(localStorage).slice(0,8)})`);
    await run('43-final-feed', `(function(){window.__smoke.q('[data-screen="feed"]').click();return 'ok'})()`, S);

    // 真实 390px 视口复测
    const before = cdp.events.length;
    await cdp.cmd('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
    await sleep(900);
    const m = await cdp.evaluate(S);
    await cdp.shot('29-mobile-390');
    steps.push({ name: '29-mobile-390', state: typeof m === 'string' ? JSON.parse(m) : m,
      newErrors: cdp.events.slice(before).map(e => e.type + ': ' + String(e.text || '').slice(0, 160)), screenshot: '29-mobile-390.png' });
    console.log('[29-mobile-390] ' + m);

    const report = { base: BASE, edge: 'CDP ' + CDP_PORT, generatedAt: new Date().toISOString(),
      totalErrors: cdp.events.length, errors: cdp.events.slice(0, 60), steps };
    fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 2), 'utf8');
    console.log('\nREPORT ' + path.join(OUT, 'report.json') + ' | events=' + cdp.events.length + ' | steps=' + steps.length);
    ws.close();
  } finally {
    try { edge.kill(); } catch (e) { }
  }
}
main().catch(e => { console.error('SMOKE_FAILED', e.message); process.exitCode = 1; });
