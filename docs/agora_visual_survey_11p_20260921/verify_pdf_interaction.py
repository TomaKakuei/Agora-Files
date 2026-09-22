#!/usr/bin/env python3
"""Verify real PDF clicks, saved PDF bytes and reopened values in a temp copy."""
import os
from pathlib import Path
import tempfile
from playwright.sync_api import sync_playwright

HERE=Path(__file__).resolve().parent


def main():
    os.environ.update(MOZ_HEADLESS='1',MOZ_DISABLE_CONTENT_SANDBOX='1',MOZ_DISABLE_RDD_SANDBOX='1',LIBGL_ALWAYS_SOFTWARE='1',XDG_RUNTIME_DIR='/tmp')
    with tempfile.TemporaryDirectory(prefix='agora_pdf_SYNTHETIC_') as temp, sync_playwright() as p:
        browser=p.firefox.launch(headless=True,timeout=30000,firefox_user_prefs={'pdfjs.disabled':False,'browser.download.open_pdf_attachments_inline':True})
        context=browser.new_context(viewport={'width':1450,'height':1100},accept_downloads=True)
        page=context.new_page();page.set_default_timeout(15000)
        page.goto((HERE/'participants/Survey_V01.pdf').as_uri(),wait_until='load')
        page.wait_for_selector('input[name=adult]')
        for name in ['adult','english','consent']:
            assert not page.is_checked('input[name='+name+']')
            page.check('input[name='+name+']')
        page.locator('input[name=prior_exposure]').first.check()
        def navigate(tab,number):
            tab.locator('#pageNumber').fill(str(number));tab.locator('#pageNumber').press('Enter')
        navigate(page,2)
        page.wait_for_selector('input[name=R1_Q1]')
        assert page.locator('input[name^=R1]:checked').count()==0
        for field,index in [('R1_Q1',0),('R1_Q2',2),('R1_Q3',3)]:page.locator('input[name='+field+']').nth(index).check()
        navigate(page,3);page.locator('input[name=R2_Q1]').nth(1).check()
        # Firefox's privileged native Save dialog is not exposed as a
        # Playwright download event. Use the viewer's own PDF save operation
        # and reopen those exact bytes; this verifies actual form persistence.
        saved=Path(temp)/'SYNTHETIC_not_a_human_response.pdf'
        data=page.evaluate('async () => Array.from(await PDFViewerApplication.pdfDocument.saveDocument())')
        saved.write_bytes(bytes(data))
        reopened=context.new_page();reopened.set_default_timeout(15000)
        reopened.goto(saved.as_uri(),wait_until='load');reopened.wait_for_selector('input[name=adult]')
        for name in ['adult','english','consent']:assert reopened.is_checked('input[name='+name+']')
        assert reopened.locator('input[name=prior_exposure]').first.is_checked()
        navigate(reopened,2);reopened.wait_for_selector('input[name=R1_Q1]')
        for field,index in [('R1_Q1',0),('R1_Q2',2),('R1_Q3',3)]:assert reopened.locator('input[name='+field+']').nth(index).is_checked()
        navigate(reopened,3);assert reopened.locator('input[name=R2_Q1]').nth(1).is_checked()
        assert reopened.locator('input[name=R2_Q2]:checked').count()==0
        browser.close()
    print('PASS: real PDF checkboxes/radio choices, distinct groups, saved PDF bytes, and reopened answers; synthetic file deleted.')


if __name__=='__main__':main()
