#!/usr/bin/env python3
"""Package only blank instruments; never include returned participant responses."""
import hashlib
import json
from pathlib import Path
import zipfile

HERE=Path(__file__).resolve().parent


def main():
    public=sorted((HERE/'participants').glob('*'))
    assert len(public)==23 and all(p.is_file() for p in public)
    assert sum(p.suffix=='.pdf' for p in public)==11
    assert sum(p.suffix=='.docx' for p in public)==11
    target=HERE/'Agora_11人_分发问卷.zip'
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in public:z.write(p,p.name)
    with zipfile.ZipFile(target) as z:assert z.testzip() is None
    # Explicit allowlist: no collected_responses or arbitrary local workbooks.
    core=[HERE/n for n in ['.gitignore','README_ZH.md','邀请说明_研究者填写.txt','Agora_11人_结果录入.xlsx','build_packets.py','validate_packets.py','package_release.py','VALIDATION.md']]
    private=sorted((HERE/'researcher_only').glob('*'))
    assert {p.name for p in private}=={'allocation.csv','blind_key.json','frozen_display.json','source_hashes.json'}
    paths=core+private+public+[target]
    for p in paths:assert p.is_file(),p
    manifest={'files':[{'path':str(p.relative_to(HERE)),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(paths)],'human_responses_included':0}
    manifest_path=HERE/'MANIFEST.json';manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    full=HERE/'Agora_11人_研究者完整包.zip'
    with zipfile.ZipFile(full,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in paths+[manifest_path]:z.write(p,HERE.name+'/'+str(p.relative_to(HERE)))
    with zipfile.ZipFile(full) as z:assert z.testzip() is None
    for p in [target,HERE/'Agora_11人_结果录入.xlsx',full]:print(p.name,f'{p.stat().st_size:,} bytes')


if __name__=='__main__':main()
