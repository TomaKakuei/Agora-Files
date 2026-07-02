const puppeteer = require('puppeteer');
console.log("Starting script");
(async () => {
  try {
    const browser = await puppeteer.launch({ args: ['--no-sandbox', '--disable-setuid-sandbox'] });
    const page = await browser.newPage();
    page.on('console', msg => console.log('PAGE LOG:', msg.text()));
    page.on('pageerror', error => console.log('PAGE ERROR:', error.message));
    page.on('requestfailed', request => console.log('REQUEST FAILED:', request.url(), request.failure()?.errorText));
    
    await page.goto('http://127.0.0.1:8132/pixel/?mode=live&seed=42617&pixel_world=6f5ab59b759c415e');
    await new Promise(resolve => setTimeout(resolve, 5000));
    await browser.close();
  } catch (err) {
    console.error("SCRIPT ERROR", err);
  }
})();
