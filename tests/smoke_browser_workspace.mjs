// REAL disposable headed Chrome + the task-only Playwright adapter.
// No personal profile, public site, mail or publication. HTTP uploads stay loopback.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { spawn } from 'node:child_process';
import { personalServer } from '../mac_bridge/browser_personal.mjs';
const require = createRequire(new URL('../.runtime/playwright/package.json', import.meta.url));
const { chromium } = require('playwright');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const temp = await mkdtemp(path.join(tmpdir(), 'mac-bridge-workspace-smoke-'));
let received = '';
const web = http.createServer(async (req, res) => {
  if (req.method === 'POST') {
    const chunks = []; for await (const chunk of req) chunks.push(chunk);
    received = Buffer.concat(chunks).toString(); res.end('stored'); return;
  }
  res.setHeader('Content-Type', 'text/html');
  res.end(`<!doctype html><title>Disposable workspace test</title>
<label>First<input id="first"></label><label>Second<input id="second"></label>
<input type="file" aria-label="Attach" id="file"><p id="status">Waiting</p>
<script>file.onchange=async()=>{await fetch('/upload',{method:'POST',body:await file.files[0].arrayBuffer()});status.textContent='Upload complete'};</script>`);
});
await new Promise(resolve => web.listen(0, '127.0.0.1', resolve));
const url = `http://127.0.0.1:${web.address().port}`;
const chrome = spawn(CHROME, [`--user-data-dir=${temp}/profile`, '--remote-debugging-port=0',
  '--no-first-run', '--no-default-browser-check', '--no-startup-window', '--disable-background-networking'],
  {stdio:'ignore'});
let connected, adapter;
try {
  let port;
  const deadline = Date.now()+15000;
  while (Date.now()<deadline) {
    try { port = (await readFile(`${temp}/profile/DevToolsActivePort`,'utf8')).split('\n')[0]; break; } catch {}
    await new Promise(r=>setTimeout(r,100));
  }
  assert.ok(port,'Disposable Chrome failed to launch');
  const endpoint = `http://127.0.0.1:${port}`;
  connected = await chromium.connectOverCDP(endpoint);
  const raw = connected.contexts()[0]; const cdp = await connected.newBrowserCDPSession();
  const sentinelURL = url + '/sentinel';
  const { targetId: sentinelId } = await cdp.send('Target.createTarget', {url:sentinelURL,newWindow:true,background:true});
  let sentinel;
  for(let i=0;i<100;i++) { sentinel = raw.pages().find(p=>p.url()===sentinelURL); if(sentinel) break; await new Promise(r=>setTimeout(r,25)); }
  assert.ok(sentinel); await sentinel.locator('#first').fill('USER_TYPING');
  const sentinelWindow = (await cdp.send('Browser.getWindowForTarget',{targetId:sentinelId})).windowId;
  adapter = await personalServer({codegen:'none',webmcp:false,outputDir:temp,outputMaxSize:20971520,
    browser:{browserName:'chromium'},timeouts:{action:3000,navigation:10000,settle:100,idle:0}},endpoint);
  const request = adapter.server._requestHandlers.get('tools/call');
  const call = async (name,args={}) => {
    const result=await request({method:'tools/call',params:{name,arguments:args}}, {signal:new AbortController().signal});
    assert.ok(!result.isError,JSON.stringify(result)); return result;
  };
  const text = r=>r.content.filter(x=>x.type==='text').map(x=>x.text).join('\n');
  const ref = (snapshot,label)=>{
    const line=snapshot.split('\n').find(x=>x.includes('"'+label+'"')&&x.includes('[ref='));
    assert.ok(line,`No ref for ${label}: ${snapshot}`); return /\[ref=([^\]]+)\]/.exec(line)[1];
  };
  const first=await call('browser_navigate',{url:url+'/task'});
  const meta=first._meta.mac_bridge_workspace;
  assert.equal(meta.task_pages,1);
  assert.notEqual(meta.task_window_ids[0],sentinelWindow);
  assert.ok(!text(await call('browser_tabs',{action:'list'})).includes('/sentinel'));
  const snap=text(await call('browser_snapshot'));
  const batch=call('browser_fill_form',{fields:[
    {target:ref(snap,'First'),name:'First',type:'textbox',value:'AUTOMATION_A'},
    {target:ref(snap,'Second'),name:'Second',type:'textbox',value:'AUTOMATION_B'}]});
  await sentinel.locator('#first').fill('USER_KEEPS_TYPING'); await batch;
  assert.equal(await sentinel.locator('#first').inputValue(),'USER_KEEPS_TYPING');
  const task=raw.pages().find(p=>p.url()===url+'/task'); assert.ok(task);
  assert.equal(await task.locator('#first').inputValue(),'AUTOMATION_A');
  assert.equal(await task.locator('#second').inputValue(),'AUTOMATION_B');
  const upload=path.join(temp,'attachment.txt'); await writeFile(upload,'DUMMY_ATTACHMENT_NO_PRIVATE_DATA');
  const attach=text(await call('browser_snapshot'));
  await call('browser_click',{target:ref(attach,'Attach'),element:'Disposable attachment button'});
  await call('browser_file_upload',{paths:[upload]});
  for(let i=0;i<100 && !received;i++) await new Promise(r=>setTimeout(r,25));
  assert.equal(received,'DUMMY_ATTACHMENT_NO_PRIVATE_DATA');
  const shot=await call('browser_take_screenshot',{type:'jpeg'});
  assert.ok(shot.content.some(x=>x.type==='image'));
  await call('browser_tabs',{action:'new',url:url+'/task2'});
  const selected=await call('browser_tabs',{action:'select',index:0});
  assert.equal(selected._meta.mac_bridge_workspace.task_pages,2);
  await call('browser_tabs',{action:'close',index:1});
  assert.equal(await sentinel.locator('#first').inputValue(),'USER_KEEPS_TYPING');
  adapter.dispose(); await adapter.server.close();
  assert.ok(!sentinel.isClosed()&&!task.isClosed());
  console.log(JSON.stringify({passed:true,checks:[
    'Separate CDP window, same disposable browser context',
    'Existing sentinel excluded from upstream tabs and snapshots',
    'Concurrent sentinel input remains distinct from batch-filled task fields',
    'Actual dummy attachment bytes received by loopback HTTP endpoint',
    'Actual JPEG, task-only create/select/close, existing page preserved on disconnect'
  ],not_tested:['Python outer-tool integration (blocked)','Actual personal Chrome profile','macOS foreground focus under real user typing','Production app build and replacement']},null,2));
} finally {
  adapter?.dispose(); await adapter?.server.close().catch(()=>{});
  await connected?.close().catch(()=>{});
  chrome.kill('SIGTERM');
  await Promise.race([new Promise(r=>chrome.once('exit',r)),new Promise(r=>setTimeout(r,3000))]);
  await new Promise(r=>web.close(r));
  await rm(temp,{recursive:true,force:true});
}
