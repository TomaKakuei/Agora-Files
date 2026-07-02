const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  
  page.on('console', msg => console.log(`[CONSOLE] ${msg.type()}: ${msg.text()}`));
  page.on('requestfailed', request =>
    console.log(`[NETWORK FAIL] ${request.url()}: ${request.failure().errorText}`)
  );
  page.on('response', response => {
    if (!response.ok()) {
      console.log(`[NETWORK HTTP ERROR] ${response.status()} ${response.url()}`);
    }
  });

  try {
    await page.goto('http://localhost:8125/pixel/?bundle=3bb232f739244202', { waitUntil: 'networkidle' });
    await page.waitForTimeout(5000); // wait for phaser to load things
    await page.screenshot({ path: '/tmp/playwright_screenshot.png' });
    console.log('Screenshot saved to /tmp/playwright_screenshot.png');
  } catch (e) {
    console.error('Error during goto:', e);
  }

  await browser.close();
})();
