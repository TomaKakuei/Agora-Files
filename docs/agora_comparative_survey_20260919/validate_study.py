#!/usr/bin/env python3
"""Check source fidelity, blinding, allocation, and decoding with synthetic data."""
import contextlib
import csv
import hashlib
import io
import json
import tempfile
from collections import Counter
from pathlib import Path
from analyze_responses import analyze, ITEMS
from build_study import packet

HERE=Path(__file__).resolve().parent
def main():
    key=json.loads((HERE/'researcher_only/blind_key.json').read_text())
    data=json.loads((HERE/'researcher_only/public_payload.json').read_text())
    assert len(data['artifacts'])==37 and len(data['pairs'])==51
    for aid,k in key['artifacts'].items():
        p=HERE/'researcher_only/source_records'/k['path']
        assert hashlib.sha256(p.read_bytes()).hexdigest()==k['sha256']
        assert packet(json.loads(p.read_text()))==data['artifacts'][aid]
    for k in json.loads((HERE/'researcher_only/provenance.json').read_text()):
        p=HERE/'researcher_only/source_records'/k['path']
        assert hashlib.sha256(p.read_bytes()).hexdigest()==k['sha256']
    public=(HERE/'public/START_SURVEY.html').read_text()
    for s in ['gemini-','gpt-5.6','gemini_','gpt_5_6','single_pass','agora_compositional','blind_key','source_records','fetch(','XMLHttpRequest']:
        assert s not in public,'Public file exposes a source identity, key, or network operation: '+s
    orientation=Counter();frequency=Counter();first=Counter()
    for code,tasks in data['schedule'].items():
        assert len(tasks)==4 and len({t['pair_id'] for t in tasks})==4
        assert Counter(key['pairs'][t['pair_id']]['arm'] for t in tasks)=={'model':2,'architecture':2}
        if code.startswith('P'):continue
        first[key['pairs'][tasks[0]['pair_id']]['arm']]+=1
        for t in tasks:
            candidates=key['pairs'][t['pair_id']]['candidates']
            assert {t['left'],t['right']}==set(candidates)
            frequency[t['pair_id']]+=1;orientation[(t['pair_id'],t['left'])]+=1
    for pid,meta in key['pairs'].items():
        a,b=meta['candidates'];assert orientation[(pid,a)]==orientation[(pid,b)]
        assert frequency[pid] in ([4] if meta['arm']=='model' else [16,18])
    assert first=={'model':41,'architecture':41}
    with tempfile.TemporaryDirectory(prefix='agora_synthetic_test_') as temp:
        temp=Path(temp);responses=temp/'SYNTHETIC_INPUT';responses.mkdir();out=temp/'SYNTHETIC_OUTPUT'
        for code,tasks in data['schedule'].items():
            d=dict(version=data['version'],assignment_code=code,consent=True,adult=True,english_reading=True,prior_exposure='no',instructions_language='zh',quote_consent=False,responses=[])
            for i,t in enumerate(tasks):
                c1=min(key['artifacts'][t['left']]['condition'],key['artifacts'][t['right']]['condition'])
                choice='A_slight' if key['artifacts'][t['left']]['condition']==c1 else 'B_much'
                d['responses'].append(dict(**t,position=i+1,answers={q:choice for q in ITEMS},active_seconds=1,comment='SYNTHETIC SOFTWARE TEST; NOT A HUMAN RESPONSE'))
            (responses/(code+'.json')).write_text(json.dumps(d))
        with contextlib.redirect_stdout(io.StringIO()):analyze(responses,out,bootstrap=100)
        status=json.loads((out/'analysis_status.json').read_text());assert status['included_participants']==82 and len(status['excluded'])==8
        rows=list(csv.DictReader((out/'preference_summary.csv').open()));assert rows and all(float(r['macro_preference_1'])==1 for r in rows)
        assert all(r['complete_prompt_coverage']=='True' for r in rows)
        # Ties must decode to 0.5; abstentions must be reported as missing, never as ties.
        for p in responses.glob('S*.json'):
            d=json.loads(p.read_text())
            for r in d['responses']:
                r['answers']['overall']='tie';r['answers']['premise']='unable'
            p.write_text(json.dumps(d))
        with contextlib.redirect_stdout(io.StringIO()):analyze(responses,out,bootstrap=100)
        rows=list(csv.DictReader((out/'preference_summary.csv').open()))
        assert all(float(r['macro_preference_1'])==.5 for r in rows if r['item']=='overall')
        assert all(not r['macro_preference_1'] and int(r['unable'])==int(r['ratings']) for r in rows if r['item']=='premise')
        (responses/'duplicate.json').write_bytes((responses/'S001.json').read_bytes())
        try:
            with contextlib.redirect_stdout(io.StringIO()):analyze(responses,out,bootstrap=10)
            raise AssertionError('Duplicate accepted')
        except ValueError as e:assert 'Duplicate assignment' in str(e)
    print('PASS: 37 source-faithful artifacts, 51 pairs, private identities absent from participant HTML, balanced orientations and arm order; decoding, ties, abstentions, pilot exclusions, and duplicate rejection verified with temporary synthetic responses.')

if __name__=='__main__':main()
