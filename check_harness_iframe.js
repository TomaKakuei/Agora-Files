const puppeteer = require('puppeteer');
(async () => {
  try {
    const browser = await puppeteer.launch({ 
      args: ['--no-sandbox', '--disable-setuid-sandbox', '--use-gl=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist', '--disable-web-security'],
      headless: true
    });
    const page = await browser.newPage();
    page.on('console', msg => console.log('PAGE LOG:', msg.text()));
    await page.goto('http://127.0.0.1:8134/__test__/headless-pixel?seed=42617&access_code=6f5ab59b759c415e&token=debug_token');
    await new Promise(resolve => setTimeout(resolve, 30000));
    await browser.close();
  } catch (err) { console.error("SCRIPT ERROR", err); }
})();
