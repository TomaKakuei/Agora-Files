const puppeteer = require('puppeteer');

(async () => {
  try {
    const browser = await puppeteer.launch({ args: ['--no-sandbox', '--disable-setuid-sandbox'] });
    const page = await browser.newPage();
    
    page.on('console', msg => console.log('PAGE LOG:', msg.text()));
    
    await page.goto('http://127.0.0.1:8134/pixel/?mode=live&seed=42617&pixel_world=6f5ab59b759c415e&headless_kick=1');
    await new Promise(resolve => setTimeout(resolve, 4000));
    
    const endpoints = await page.evaluate(() => {
      const scene = window.__AGORA_PHASER_GAME__?.scene?.scenes?.[0];
      return scene?.liveState?.endpoints;
    });
    console.log("ENDPOINTS:", endpoints);
    
    const hasLiveState = await page.evaluate(() => {
      const scene = window.__AGORA_PHASER_GAME__?.scene?.scenes?.[0];
      return !!scene?.liveState;
    });
    console.log("HAS LIVESTATE:", hasLiveState);

    await browser.close();
  } catch (err) {
    console.error("SCRIPT ERROR", err);
  }
})();
