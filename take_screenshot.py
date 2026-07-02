import time
from selenium import webdriver
from selenium.webdriver.firefox.options import Options

def main():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--window-size=1280,3000")
    
    driver = webdriver.Firefox(options=options)
    
    try:
        print("Loading test_visual.html...")
        # Point to the local file
        driver.get("file:///home/yz_wang/yz_main/Agora_UI_Run/test_visual.html")
        
        # Wait a few seconds for images to load
        time.sleep(3)
        
        # Take a screenshot
        screenshot_path = "/home/yz_wang/.gemini/antigravity-ide/brain/fbd32d72-6bfd-47a7-b3ee-a0735b74c4e9/screenshot_regression.png"
        driver.save_screenshot(screenshot_path)
        print(f"Screenshot saved to {screenshot_path}")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
