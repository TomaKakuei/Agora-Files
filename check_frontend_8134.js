const puppeteer = require('puppeteer');

(async () => {
  try {
    const browser = await puppeteer.launch({ args: ['--no-sandbox', '--disable-setuid-sandbox'] });
    const page = await browser.newPage();
    
    page.on('console', msg => console.log('PAGE LOG:', msg.text()));
    page.on('pageerror', error => console.log('PAGE ERROR:', error.message));
    
    await page.goto('http://127.0.0.1:8134/pixel/?mode=live&seed=42617&pixel_world=6f5ab59b759c415e&headless_kick=1');
    await new Promise(resolve => setTimeout(resolve, 3000));
    
    const statusText = await page.evaluate(() => document.getElementById("event-status")?.textContent);
    console.log("EVENT STATUS:", statusText);
    
    const phaserGame = await page.evaluate(() => !!window.__AGORA_PHASER_GAME__);
    console.log("PHASER GAME EXISTS:", phaserGame);
    
    const hasError = await page.evaluate(() => !!window.__AGORA_WORLD_SCENE_MANUAL_STEP_ERROR__);
    console.log("MANUAL STEP ERROR:", hasError);
    
    await browser.close();
  } catch (err) {
    console.error("SCRIPT ERROR", err);
  }
})();
