#!/usr/bin/env python3
"""Cross-check the recalculated workbook, source choices, CSVs and denominators."""
import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path
import openpyxl

HERE=Path(__file__).resolve().parent


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--workbook',type=Path,default=HERE/'Results_Completed.xlsx')
    args=ap.parse_args()
    d=json.loads((HERE/'dataset.json').read_text())
    fields=json.loads((HERE/'extracted_fields.json').read_text())
    summary=json.loads((HERE/'summary.json').read_text())
    with (HERE/'responses_long.csv').open() as f:rows=list(csv.DictReader(f))
    with (HERE/'pair_results.csv').open() as f:pairs=list(csv.DictReader(f))
    w=openpyxl.load_workbook(args.workbook,data_only=True)
    formula=openpyxl.load_workbook(args.workbook,data_only=False)
    errors=[]
    for s in w:
        for row in s:
            for c in row:
                if c.data_type=='e':errors.append((s.title,c.coordinate,c.value))
    assert not errors,errors
    assert len(rows)==198 and sum(r['included']=='True' for r in rows)==180
    assert len(fields)==11 and summary['included']==10 and summary['pending']==['V04']
    for er in range(7,18):
        s=w['Participants'];code=s.cell(er,1).value
        assert s.cell(er,7).value==18
        assert s.cell(er,8).value==('Check cover answers' if code=='V04' else 'Include')
        for col,key in enumerate(['adult','english','consent','prior_exposure'],3):
            expected=fields[code][key]
            assert (s.cell(er,col).value or '')==('' if expected in ['', 'Off'] else expected)
    checked=0
    for er in range(7,73):
        s=w['Responses'];code,rnd=s.cell(er,1).value,int(s.cell(er,2).value)
        task=d['schedule'][code][rnd-1]
        a=d['artifacts'][task['left']]['condition'];b=d['artifacts'][task['right']]['condition']
        canonical=min(a,b)
        assert s.cell(er,11).value==task['pair_id']
        for qi in range(1,4):
            ans=fields[code][f'R{rnd}_Q{qi}']
            assert s.cell(er,qi+4).value==ans
            r=next(r for r in rows if r['code']==code and int(r['round'])==rnd and int(r['q'])==qi)
            assert r['answer']==ans and r['a']==a and r['b']==b
            score=s.cell(er,qi+15).value
            expected=None if code=='V04' or ans=='Not sure' else .5 if ans=='Same' else float((a if ans=='A' else b)==canonical)
            if expected is None:assert score in [None,''],(code,rnd,qi,score)
            else:assert score==expected,(code,rnd,qi,score,expected)
            checked+=1
    for kind,sheet in [('images','Image results'),('structure','Structure results')]:
        pids=sorted(pid for pid,p in d['pairs'].items() if p['kind']==kind)
        for index,pid in enumerate(pids):
            for qi in range(1,4):
                r=next(r for r in pairs if r['pair_id']==pid and int(r['q'])==qi)
                er=7+index*3+qi-1;s=w[sheet]
                for col,key in [(6,'n'),(7,'judgeable'),(8,'wins'),(9,'ties'),(10,'losses'),(11,'unsure')]:
                    assert s.cell(er,col).value==int(r[key]),(sheet,er,key,s.cell(er,col).value,r[key])
                assert math.isclose(s.cell(er,12).value,float(r['preference']),abs_tol=1e-12)
    for qi,item in enumerate(summary['structure']):
        s=w['Structure results']
        assert s.cell(40+qi,11).value==10
        assert math.isclose(s.cell(40+qi,12).value,item['equal_request_preference'],abs_tol=1e-12)
    assert [r['equal_request_preference'] for r in summary['structure']]==[.4,.325,.375]
    assert [r['wins'] for r in summary['structure']]==[7,8,7]
    assert [r['losses'] for r in summary['structure']]==[13,11,12]
    assert [r['ties'] for r in summary['structure']]==[0,1,0]
    assert [r['unsure'] for r in summary['structure']]==[0,0,1]
    assert sum(c.data_type=='f' for s in formula for row in s for c in row)>500
    assert not formula._external_links
    # Freeze exact inputs and keep the unconfirmed cover genuinely empty.
    assert all(w['Participants'].cell(10,c).value in [None,''] for c in range(3,7))
    print(f'PASS: {checked} source answers, 11 eligibility rows, all 93 pair/item summaries, three equal-request means, and no Excel errors.')
    (HERE/'analysis_check.json').write_text(json.dumps(dict(
        input_choices_checked=checked,included_choices=180,eligible_returns=10,
        pending_cover='V04',pair_item_summaries_checked=93,
        equal_request_means=[.4,.325,.375],spreadsheet_formula_errors=0,
        spreadsheet_formulas_recalculated=True),indent=2)+'\n')


if __name__=='__main__':main()
