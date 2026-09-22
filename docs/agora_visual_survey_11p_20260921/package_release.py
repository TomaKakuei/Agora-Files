#!/usr/bin/env python3
"""Explicitly package the blank visual instruments and frozen research inputs."""
from pathlib import Path
import hashlib
import json
import zipfile

HERE=Path(__file__).resolve().parent


def main():
    public=sorted((HERE/'participants').glob('*'))
    assert len(public)==23 and sum(p.suffix=='.pdf' for p in public)==11 and sum(p.suffix=='.docx' for p in public)==11
    public_zip=HERE/'Visual_Survey_11_Participants.zip'
    with zipfile.ZipFile(public_zip,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in public:z.write(p,p.name)
    with zipfile.ZipFile(public_zip) as z:assert z.testzip() is None
    core=[HERE/n for n in ['.gitignore','README.md','INVITATION_TEMPLATE.txt','Results_Entry.xlsx','prepare_materials.py','render_surveys.py','build_workbook.py','validate_release.py','verify_pdf_interaction.py','package_release.py','VALIDATION.md','preview_images.png','preview_structure.png']]
    private=[HERE/'researcher_only/dataset.json',HERE/'researcher_only/SOURCE_MANIFEST.json']
    frozen=json.loads((HERE/'researcher_only/SOURCE_MANIFEST.json').read_text())
    private += [HERE/row['file'] for row in frozen]
    files=sorted(core+private+public)
    assert len(files)==len(set(files))
    manifest={'version':json.loads((HERE/'researcher_only/dataset.json').read_text())['version'],'human_responses_included':0,'files':[]}
    for p in files:
        assert p.is_file(),p
        manifest['files'].append({'path':str(p.relative_to(HERE)),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    mp=HERE/'MANIFEST.json';mp.write_text(json.dumps(manifest,indent=2)+'\n')
    full=HERE/'Researcher_Complete_Package.zip'
    with zipfile.ZipFile(full,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in files+[mp]:z.write(p,HERE.name+'/'+str(p.relative_to(HERE)))
    with zipfile.ZipFile(full) as z:assert z.testzip() is None
    for p in [public_zip,HERE/'Results_Entry.xlsx',full]:print(p.name,f'{p.stat().st_size:,} bytes')


if __name__=='__main__':main()
