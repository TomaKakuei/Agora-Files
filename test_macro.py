from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.firefox.launch(headless=True)
    page = browser.new_page()
    page.goto('http://127.0.0.1:8125/macro')
    print("Page title:", page.title())
    browser.close()
