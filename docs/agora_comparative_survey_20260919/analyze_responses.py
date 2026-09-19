#!/usr/bin/env python3
"""Validate returned JSONs and report descriptive, participant-clustered preferences.
No dependencies beyond NumPy. No human observations are supplied with this release.
"""
import argparse
import csv
import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent
ITEMS=['overall','premise','coherence','society','specificity','actions']
OPTIONS={'A_much','A_slight','tie','B_slight','B_much','unable'}

def analyze(input_dir,output_dir,bootstrap=2000):
    key=json.loads((HERE/'researcher_only/blind_key.json').read_text())
    seen=set();rows=[];excluded=[]
    for p in sorted(input_dir.glob('*.json')):
        d=json.loads(p.read_text());code=d.get('assignment_code','')
        if code in seen:raise ValueError('Duplicate assignment code: '+code+'; resolve duplicate files explicitly before analysis.')
        seen.add(code)
        if d.get('version')!=key['version'] or code not in key['schedule']:raise ValueError('Unknown version or assignment: '+p.name)
        if not all(d.get(k) is True for k in ['consent','adult','english_reading']):
            excluded.append(dict(file=p.name,code=code,reason='eligibility_or_consent'));continue
        if code.startswith('P'):
            excluded.append(dict(file=p.name,code=code,reason='pilot'));continue
        if d.get('prior_exposure')!='no':
            excluded.append(dict(file=p.name,code=code,reason='prior_exposure_primary_exclusion'));continue
        expected=key['schedule'][code]
        responses=d.get('responses',[])
        if len(responses)!=4:raise ValueError('Incomplete packet: '+p.name)
        for i,(r,e) in enumerate(zip(responses,expected)):
            if any(r.get(k)!=e[k] for k in ['pair_id','left','right']) or r.get('position')!=i+1:raise ValueError('Assignment mismatch: '+p.name)
            answers=r.get('answers',{})
            if any(answers.get(k) not in OPTIONS for k in ITEMS):raise ValueError('Invalid / missing rating: '+p.name)
            meta=key['pairs'][r['pair_id']];left=key['artifacts'][r['left']]['condition'];right=key['artifacts'][r['right']]['condition']
            c1,c2=sorted([left,right])
            for item in ITEMS:
                choice=answers[item]
                pref=None if choice=='unable' else .5 if choice=='tie' else float((choice.startswith('A') and left==c1) or (choice.startswith('B') and right==c1))
                rows.append(dict(participant=code,arm=meta['arm'],prompt=meta['prompt_id'],pair_id=r['pair_id'],position=i+1,condition_1=c1,condition_2=c2,item=item,choice=choice,preference_1=pref,instructions_language=d.get('instructions_language',''),seconds=round(float(r.get('active_seconds',0)),1),both_poor=r.get('both_poor','unanswered'),quote_consent=bool(d.get('quote_consent')),comment=r.get('comment','') if item=='overall' else ''))
    output_dir.mkdir(parents=True,exist_ok=True)
    def csvwrite(name,records,fields):
        with (output_dir/name).open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(records)
    fields=['participant','arm','prompt','pair_id','position','condition_1','condition_2','item','choice','preference_1','instructions_language','seconds','both_poor','quote_consent','comment']
    csvwrite('coded_responses_PRIVATE.csv',rows,fields)
    csvwrite('exclusions.csv',excluded,['file','code','reason'])
    groups=defaultdict(list)
    for r in rows:groups[(r['arm'],r['condition_1'],r['condition_2'],r['item'])].append(r)
    rng=np.random.default_rng(20260919)
    summary=[];by_prompt=[]
    for (arm,c1,c2,item),rs in sorted(groups.items()):
        prompts=sorted({r['prompt'] for r in rs});people=sorted({r['participant'] for r in rs})
        table=np.full((len(people),len(prompts)),np.nan)
        for i,person in enumerate(people):
            for j,prompt in enumerate(prompts):
                vs=[r['preference_1'] for r in rs if r['participant']==person and r['prompt']==prompt and r['preference_1'] is not None]
                if vs:table[i,j]=np.mean(vs)
        valid_prompts=np.isfinite(table).any(axis=0)
        if valid_prompts.any():point=float(np.nanmean(np.nanmean(table[:,valid_prompts],axis=0)))
        else:point=None
        boot=[]
        if len(people)>=2 and point is not None:
            for _ in range(bootstrap):
                sample=table[rng.integers(len(people),size=len(people)),:][:,valid_prompts]
                # A draw missing a fixed prompt cannot estimate the defined macro average.
                if not np.isfinite(sample).any(axis=0).all():continue
                boot.append(float(np.mean(np.nanmean(sample,axis=0))))
        lo,hi=(np.quantile(boot,[.025,.975]).tolist() if len(boot)>=.8*bootstrap else [None,None])
        planned={m['prompt_id'] for m in key['pairs'].values() if m['arm']==arm and sorted(key['artifacts'][a]['condition'] for a in m['candidates'])==[c1,c2]}
        summary.append(dict(arm=arm,condition_1=c1,condition_2=c2,item=item,participants=len(people),ratings=len(rs),unable=sum(r['preference_1'] is None for r in rs),tie=sum(r['choice']=='tie' for r in rs),observed_prompts=int(valid_prompts.sum()),planned_prompts=len(planned),macro_preference_1=point,participant_bootstrap_low=lo,participant_bootstrap_high=hi,valid_bootstraps=len(boot),complete_prompt_coverage=int(valid_prompts.sum())==len(planned)))
        for prompt in prompts:
            sub=[r for r in rs if r['prompt']==prompt];valid=[r['preference_1'] for r in sub if r['preference_1'] is not None]
            by_prompt.append(dict(arm=arm,condition_1=c1,condition_2=c2,item=item,prompt=prompt,ratings=len(sub),unable=len(sub)-len(valid),preference_1=float(np.mean(valid)) if valid else None,choices=json.dumps(dict(Counter(r['choice'] for r in sub)))))
    csvwrite('preference_summary.csv',summary,['arm','condition_1','condition_2','item','participants','ratings','unable','tie','observed_prompts','planned_prompts','macro_preference_1','participant_bootstrap_low','participant_bootstrap_high','valid_bootstraps','complete_prompt_coverage'])
    csvwrite('per_prompt.csv',by_prompt,['arm','condition_1','condition_2','item','prompt','ratings','unable','preference_1','choices'])
    report=dict(input_files=len(seen),included_participants=len({r['participant'] for r in rows}),excluded=excluded,bootstrap_draws=bootstrap,interpretation='Fixed artifact corpus. Intervals resample participants, not model generations or new prompts. No p-values, universal model ranking, or equal-budget causal claim. Blank intervals indicate insufficient bootstrap coverage.')
    (output_dir/'analysis_status.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('input_dir',type=Path);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--bootstrap',type=int,default=2000);a=ap.parse_args();analyze(a.input_dir,a.output,a.bootstrap)
