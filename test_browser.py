import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        page = await browser.new_page()
        
        # Listen for console logs
        page.on("console", lambda msg: print(f"Browser console: {msg.type}: {msg.text}"))
        
        print("Navigating to URL...")
        await page.goto("http://127.0.0.1:8125/pixel/?bundle=3bb232f739244202")
        print("Waiting for network idle...")
        await page.wait_for_load_state("networkidle")
        print("Waiting 5s for Phaser...")
        await asyncio.sleep(5)
        print("Taking screenshot...")
        await page.screenshot(path="/tmp/pixel_map_test.png")
        print("Screenshot saved to /tmp/pixel_map_test.png")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
