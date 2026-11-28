// 配合 check_today_mumu.py 的隔离观察文件运行。浏览器渲染产品组件，按真实桌面投影刷新。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.UI_PLAYWRIGHT_CORE_PATH || 'playwright-core');

async function main() {
  const output = process.argv[2];
  assert(output && path.isAbsolute(output), '需要绝对路径的验收目录');
  const base = process.env.UI_BASE_URL || 'http://127.0.0.1:14793';
  const browser = await chromium.launch({headless:true,executablePath:process.env.UI_CHROMIUM_PATH});
  try {
    const page = await browser.newPage({viewport:{width:960,height:760}});
    await page.route('http://127.0.0.1:55419/rpc', async route => {
      const observed = JSON.parse(fs.readFileSync(path.join(output, 'view.json'), 'utf8'));
      assert.equal(route.request().postDataJSON().method, 'today_board');
      await route.fulfill({json:{ok:true,result:observed.board}});
    });
    await page.route(base+'/today-acceptance', route => route.fulfill({contentType:'text/html',body:`<!doctype html>
      <meta charset="utf-8"><div id="root"></div><script type="module">
      import Refresh from '/@react-refresh';
      Refresh.injectIntoGlobalHook(window);window.$RefreshReg$=()=>{};window.$RefreshSig$=()=>t=>t;window.__vite_plugin_react_preamble_installed__=true;
      const {createElement}=(await import('/node_modules/.vite/deps/react.js')).default;
      const {createRoot}=(await import('/node_modules/.vite/deps/react-dom_client.js')).default;
      const {TodayPane}=await import('/src/client/today-pane.tsx');
      await import('/src/client/ui-foundations.css');
      await import('/src/client/ui-controls.css');
      createRoot(document.querySelector('#root')).render(createElement(TodayPane,{info:{port:55419,token:'fixture'},onProfiles:()=>{},onOpen:async()=>{}}));
      </script>`}));
    await page.goto(base+'/today-acceptance');
    if (process.argv.includes('--review')) {
      await page.locator('.jr-head h1').waitFor();
      const submit = page.getByRole('button',{name:'回复原任务'});
      assert(await submit.isDisabled());
      assert.equal(await page.locator('.jr-choices button').count(),0,'纯文本问题沿用原会话的文字答复');
      await page.getByLabel('自行补充').fill('请留五分钟讨论');
      await page.getByRole('button',{name:'独立阅读'}).click();
      assert.equal(await page.getByLabel('自行补充').inputValue(),'请留五分钟讨论');
      assert(await submit.isEnabled(), '允许只提交自行填写的答案');
      await page.screenshot({path:path.join(output,'today-desktop.png')});
      await page.setViewportSize({width:390,height:844});
      await page.evaluate(()=>{document.documentElement.classList.add('dark');document.body.style.background='hsl(var(--background))';});
      await page.getByRole('button',{name:'偏好'}).click();
      await page.getByText('项目、内容来源与周期').click();
      await page.getByLabel('关注项目').selectOption('today-demo');
      await page.getByRole('button',{name:'晚间简报'}).click();
      await page.getByLabel('内容偏好',{exact:true}).fill('评审 设计');
      await page.getByRole('button',{name:'早间简报'}).click();
      assert.notEqual(await page.getByLabel('内容偏好',{exact:true}).inputValue(),'评审 设计');
      await page.getByRole('button',{name:'晚间简报'}).click();
      assert.equal(await page.getByLabel('内容偏好',{exact:true}).inputValue(),'评审 设计');
      assert(await page.evaluate(()=>document.documentElement.scrollWidth <= window.innerWidth));
      await page.screenshot({path:path.join(output,'today-preferences.png'),fullPage:true});
      const push=page.getByRole('switch',{name:'开启推送'});
      await push.click();
      assert(await page.getByRole('button',{name:/推送时间/}).isDisabled());
      await push.click();
      await page.getByRole('button',{name:/推送时间/}).click();
      const hour=page.getByRole('spinbutton',{name:'小时'});
      await hour.focus();await hour.press('Home');await hour.press('ArrowDown');
      await page.getByRole('button',{name:'确认时间'}).click();
      assert.match(await page.getByRole('button',{name:/推送时间/}).innerText(),/01:/);
      await page.getByRole('button',{name:/每日科技资讯/}).click();
      assert.match(await page.getByLabel('内容偏好',{exact:true}).inputValue(),/每日科技资讯/);
      await page.getByRole('button',{name:'取消'}).click();
      await page.getByRole('button',{name:'偏好'}).click();
      await page.getByRole('button',{name:'晚间简报'}).click();
      assert.notEqual(await page.getByLabel('内容偏好',{exact:true}).inputValue(),'评审 设计');
      console.log('PASS 窄屏定制、时段草稿、取消和项目选择');
      return;
    }
    const question = page.locator('article').first().getByRole('heading',{name:/今日验收：评审需要多少分钟/});
    await question.waitFor();
    await page.screenshot({path:path.join(output,'windows-before.png')});
    console.log('Windows 已显示原问题');
    await question.waitFor({state:'detached',timeout:300000});
    await page.getByRole('heading',{name:'Windows 收到了你的答复'}).waitFor();
    const observed=JSON.parse(fs.readFileSync(path.join(output,'view.json'),'utf8'));
    assert.equal(observed.history[0].rows.filter(row=>row.text==='45min').length,1);
    await page.screenshot({path:path.join(output,'windows-after.png')});
    console.log('PASS Windows 看板已撤卡，原会话中有且仅有一次 45min');
  } finally {
    await browser.close();
  }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
