const puppeteer = require('puppeteer-core'); const sleep = ms => new Promise(r => setTimeout(r, ms));
const BASE = process.argv[2], OUT = process.argv[3], IMPL = process.argv[4] || 'labview', RUNID = process.argv[5];
(async () => {
  const b = await puppeteer.connect({ browserURL: 'http://127.0.0.1:9222' }); const p = await b.newPage();
  await p.setViewport({ width: 1300, height: 1800 });
  const errors = []; p.on('pageerror', e => errors.push(e.message));
  const st = () => p.$eval('#hwrun-status', e => e.textContent);
  if (RUNID) { await p.goto(BASE + '?hwrun=' + RUNID, { waitUntil: 'networkidle2' }); }
  else {
    await p.goto(BASE, { waitUntil: 'networkidle2' });
    for (let i = 0; i < 30 && !/loaded|not available/.test(await st()); i++) await sleep(1000);
    await p.select('#hwrun-pcap', 'frame_boundary_repro'); await p.select('#hwrun-impl', IMPL); await p.click('#hwrun-run');
  }
  let s; for (let i = 0; i < 150; i++) { s = await st(); if (/^(Done|Run failed|Could not|Lost)/.test(s)) break; await sleep(1000); }
  console.log('status: ' + s + '  ' + p.url());
  const ver = await p.$$eval('script[src*="fpganow-hwrun/assets/app.js"]', e => e.map(x => x.src));
  console.log('app.js: ' + ver.join(' '));
  const rows = await p.$$eval('#hwrun-stats tr', trs => trs.map(tr => [...tr.cells].map(c => c.textContent).join(' | ')));
  console.log('stats table:'); rows.forEach(r => console.log('  ' + r));
  const bb = await p.$eval('#hwrun-stats', e => { const r = e.getBoundingClientRect(); return { top: Math.round(r.top + window.scrollY), h: Math.round(r.height) }; });
  await p.screenshot({ path: OUT + '/stats_' + IMPL + '.png', clip: { x: 0, y: Math.max(0, bb.top - 420), width: 1300, height: bb.h + 900 } });
  console.log('page errors: ' + (errors.length ? errors.join('; ') : 'none'));
  await p.close(); b.disconnect();
})().catch(e => { console.error('FAILED ' + e.message); process.exit(1); });
