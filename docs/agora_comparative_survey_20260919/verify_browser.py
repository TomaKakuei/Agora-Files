#!/usr/bin/env python3
"""Local end-to-end browser verification with a synthetic pilot response only."""
import json
import os
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE=Path(__file__).resolve().parent
os.environ.update(MOZ_HEADLESS='1',MOZ_DISABLE_CONTENT_SANDBOX='1',MOZ_DISABLE_RDD_SANDBOX='1',LIBGL_ALWAYS_SOFTWARE='1',XDG_RUNTIME_DIR='/tmp')
with sync_playwright() as p:
    browser=p.firefox.launch(headless=True,timeout=30000)
    context=browser.new_context(viewport={'width':1280,'height':960},accept_downloads=True)
    page=context.new_page();errors=[];network=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('request',lambda r:network.append(r.url))
    page.goto((HERE/'public/START_SURVEY.html').as_uri(),wait_until='load')
    page.screenshot(path='/tmp/agora_survey_front.png',full_page=True)
    page.fill('#code','P001')
    for x in ['adult','english','consent']:page.check('#'+x)
    page.click('#start-form button[type=submit]')
    assert page.locator('.world').count()==2
    assert page.locator('input[type=radio]').count()==36
    page.screenshot(path='/tmp/agora_survey_duel.png',full_page=True)
    assert page.locator('input[type=radio]:checked').count()==0
    page.click('#rating-form button[type=submit]')
    assert '1 / 4' in page.locator('.kicker').inner_text()
    questions=['overall','premise','coherence','society','specificity','actions']
    for i in range(4):
        for q in questions:page.check(f'input[name="{q}"][value="tie"]')
        if i==0:
            page.select_option('#language','en')
            assert page.locator('input[type=radio]:checked').count()==6
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile overflow'
            page.screenshot(path='/tmp/agora_survey_mobile.png',full_page=True)
            page.set_viewport_size({'width':1280,'height':960})
        page.fill('textarea[name=comment]','SYNTHETIC SOFTWARE TEST — NOT A HUMAN RESPONSE')
        page.click('#rating-form button[type=submit]')
    assert page.locator('#download').count()==1
    assert not page.is_checked('#quotes')
    with page.expect_download() as event:page.click('#download')
    download=event.value
    response=json.loads(Path(download.path()).read_text())
    assert response['assignment_code']=='P001' and response['stage']=='pilot'
    assert len(response['responses'])==4 and not response['quote_consent']
    assert all(all(x=='tie' for x in r['answers'].values()) for r in response['responses'])
    assert all(not u.startswith(('http:','https:')) for u in network)
    assert not errors,errors
    page.click('#edit');page.click('#back')
    assert page.locator('input[type=radio]:checked').count()==6
    print('PASS: desktop/mobile render; required choices; language-switch persistence; four-pair completion; private JSON download; no network requests, JS errors, or default preference; edit/back persistence.')
    browser.close()
