/** Documentation acceptance using disposable projects and blocked external networking. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { readFileSync, existsSync, statSync } from 'node:fs';
import path from 'node:path';
const root = path.resolve(import.meta.dirname, '../..');
const require = createRequire(path.join(root, 'frontend/package.json'));
const { chromium, expect, request } = require('@playwright/test');
const base = process.env.WORKBENCH_DOCS_TEST_URL || 'http://127.0.0.1:3117';
const server = process.env.WORKBENCH_DOCS_TEST_URL ? null : spawn(process.env.WORKBENCH_PYTHON || 'python', ['scripts/preview_docs.py'], {cwd:path.join(root,'docs-site'),stdio:['ignore','pipe','pipe']});
let logs=''; server?.stdout.on('data',data=>logs+=data);server?.stderr.on('data',data=>logs+=data);
let browser, hosted;
const api = await request.newContext();
async function fetchLocal(url) {
  const response = await api.get(url);
  return {ok: response.ok(), status: response.status(), json: () => response.json()};
}
async function ready() {
  for(let i=0;i<100;i++) {
    if(server && server.exitCode!==null) throw Error(logs);
    try {const response=await fetchLocal(base+'/api/library');if(response.ok)return await response.json();}catch{}
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  throw Error('Fixture server failed: '+logs);
}
async function search(page) {
  await page.getByRole('button',{name:'Search',exact:true}).click();
  await page.locator('#localsearch-input').fill('Next iteration');
  await expect(page.locator('.VPLocalSearchBox .results li').first()).toBeVisible();
  await page.locator('#localsearch-input').fill('zzzznothingshouldmatchworkbench');
  await expect(page.getByText('No results for')).toBeVisible();
  await page.keyboard.press('Escape');
}
try {
  const library=await ready();
  browser=await chromium.launch();
  const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce',permissions:['clipboard-read','clipboard-write']});
  await context.route('**/*', route => route.request().url().startsWith(base) || route.request().url().startsWith('http://127.0.0.1:') ? route.continue() : route.abort());
  const page=await context.newPage();
  const failed=[];page.on('pageerror',error=>failed.push(error.message));
  const response=await page.goto(base+'/docs/user/cards/python.html'); assert.equal(response.status(),200);
  await expect(page.locator('.vp-doc h1')).toBeVisible();
  await search(page);
  await page.locator('button.copy').first().click();
  await expect(page.locator('button.copy').first()).toHaveClass(/copied/);
  const image=page.locator('.vp-doc img').first();await image.scrollIntoViewIfNeeded();await image.focus();await page.keyboard.press('Enter');
  await expect(page.getByRole('dialog')).toBeVisible();await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.goto(base+'/docs/user/cards/loop.html');
  await page.screenshot({path:path.join(root,'docs-site/.vitepress/docs-desktop.png'),animations:'disabled'});
  await page.setViewportSize({width:390,height:844});
  await page.goto(base+'/docs/user/first-workflow.html');
  await expect(page.getByRole('button',{name:'Menu',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Menu',exact:true}).click();
  await expect(page.locator('.VPSidebar')).toBeVisible();
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Mobile page overflows');
  await page.locator('.VPBackdrop').click({position:{x:380,y:100}});
  await expect(page.locator('.VPBackdrop')).not.toBeVisible();
  await page.screenshot({path:path.join(root,'docs-site/.vitepress/docs-mobile.png'),animations:'disabled'});
  for (const [route,status] of [['/docs/',200],['/docs/user/cards/loop',200],['/docs/examples/python.yaml',200],['/docs/examples/demo_script.py',200],['/docs/no-such-page.html',404],['/docs/%2e%2e%2fschema.json',404]]) {
    assert.equal((await fetchLocal(base+route)).status,status,route);
  }
  await page.goto(base+'/docs/user/inputs.html');
  await expect(page.locator('.vp-doc h1')).toHaveText('Run inputs and automatic discovery');
  await expect(page.locator('#detector-output-contract')).toBeVisible();
  for (const route of ['/docs/examples/input-discovery.yaml','/docs/examples/detect_inputs.py','/docs/developer/project-integrations.html']) {
    assert.equal((await fetchLocal(base+route)).status,200,route);
  }
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Input guide overflows on mobile');
  console.log('Passed local docs: deep links, discovery guide/downloads, search/empty results, copy, image keyboard access, mobile navigation and real 404/path boundaries.');
  if(server) {
    await page.setViewportSize({width:1440,height:1000});
    const entry=library.entries.find(e=>e.name==='Card: Calculate');
    await page.goto(base+'/?workflow='+entry.id);
    await page.getByRole('button',{name:'Edit',exact:true}).click();
    await page.getByRole('button',{name:'List',exact:true}).click();
    await page.locator('[data-card-id="operation"]').click();
    await page.getByLabel('Card name',{exact:true}).fill('Unsaved documentation check');
    const popupPromise=context.waitForEvent('page');
    await page.getByRole('link',{name:'Read this card’s guide'}).click();
    const popup=await popupPromise;await popup.waitForLoadState();
    await expect(popup.locator('.vp-doc h1')).toBeVisible();await popup.close();
    await expect(page.getByLabel('Card name',{exact:true})).toHaveValue('Unsaved documentation check');
    // Discard only this synthetic fixture draft by navigating, never a user tab.
    const poll=library.entries.find(e=>e.name==='Card: Poll until');
    await page.goto(base+'/?workflow='+poll.id);await page.getByRole('button',{name:'Run all',exact:true}).click();
    await expect(page.locator('.toolbar .status.running')).toBeVisible();
    const duringPromise=context.waitForEvent('page');await page.getByRole('link',{name:'Documentation',exact:true}).click();
    const during=await duringPromise;await during.waitForLoadState();await during.close();
    await expect(page.locator('.toolbar .status.running')).toBeVisible();
    await page.getByRole('button',{name:'Stop all',exact:true}).click();await expect(page.locator('.toolbar .status.cancelled')).toBeVisible();
    console.log('Passed application help links: unsaved card edit preserved; active polling continues until explicit Stop.');
  }
  const dist=path.join(root,'docs-site/.vitepress/dist');
  const html=readFileSync(path.join(dist,'index.html'),'utf8');
  if(html.includes('/release-workbench/assets/')) {
    hosted=createServer((request,response)=>{
      const pathname=decodeURIComponent(new URL(request.url,'http://localhost').pathname);
      if(!pathname.startsWith('/release-workbench/')){response.writeHead(404);response.end();return;}
      let file=path.resolve(dist,pathname.slice('/release-workbench/'.length)||'index.html');
      if(!file.startsWith(dist+path.sep)){response.writeHead(404);response.end();return;}
      if(existsSync(file)&&statSync(file).isDirectory())file=path.join(file,'index.html');
      if(!existsSync(file)){response.writeHead(404);response.end();return;}
      response.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.html')?'text/html':'application/octet-stream');
      response.end(readFileSync(file));
    });
    await new Promise(resolve=>hosted.listen(0,'127.0.0.1',resolve));
    const url='http://127.0.0.1:'+hosted.address().port;
    await page.goto(url+'/release-workbench/user/cards/loop.html');await expect(page.locator('.vp-doc h1')).toBeVisible();
    await search(page);assert.equal((await fetchLocal(url+'/release-workbench/examples/script.yaml')).status,200);
    console.log('Passed GitHub Pages base path, local search and example download.');
  } else if (!process.env.WORKBENCH_DOCS_TEST_URL) throw Error('Build docs with build:pages before running the two-base-path acceptance check.');
  assert.deepEqual(failed,[],'Documentation client errors');
} finally {
  await api.dispose();await browser?.close();hosted?.close();server?.kill('SIGINT');
}
