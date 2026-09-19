#!/usr/bin/env python3
"""Build blinded, self-contained study packets from existing generation records."""
import argparse
import csv
import hashlib
import itertools
import json
import random
import re
import shutil
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
VERSION='agora-pairwise-20260919-v2'

def read(p):return json.loads(p.read_text())
def write(p,d):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def words(s,limit):
    s=' '.join(str(s or '').split());w=s.split()
    return ' '.join(w[:limit])+(' […]' if len(w)>limit else '')
def values(x):return x if isinstance(x,list) else []
def selected(x,n):return values(x)[:n]
def packet(spec):
    """All arms: identical keys, source order, quotas, and word limits; no rewriting."""
    def fields(row,keys,limit=24):
        return ' · '.join(words(row.get(k,''),limit) for k in keys if row.get(k)) if isinstance(row,dict) else words(row,limit)
    sections=[]
    def add(zh,en,rows):sections.append(dict(zh=zh,en=en,rows=rows or ['[No content supplied for this field.]']))
    add('世界概述','World concept',[words(spec.get('premise',''),60)])
    add('规则与制度','Rules and institutions',[fields(x,['name','description','rule'],28) for x in selected(spec.get('social_rules'),3)])
    add('活动与压力','Activities and pressures',[fields(x,['label','summary','pressure'],28) for x in selected(spec.get('gameplay_loops'),2)])
    add('人物与目标','People and goals',[fields(x,['display_name','role_name'],12)+' — '+words(x.get('arc_goal',''),30) for x in selected(spec.get('main_characters'),3)])
    add('地点与用途','Places and purposes',[fields(x,['name'],12)+' — '+words(x.get('purpose',''),28) for x in selected(spec.get('rooms'),3)])
    add('物件','Objects',[fields(x,['name','description'],20) for x in selected(spec.get('item_catalog'),3)])
    add('可能采取的行动','Possible actions',[fields(x,['name','action','description'],24) for x in selected(spec.get('custom_actions'),3)])
    add('玩家进入方式','Player entry',[fields(x,['name','description','role','summary'],28) for x in selected(spec.get('player_entry_points'),2)])
    return dict(sections=sections)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source-root',type=Path,default=Path('/home/yz_wang/yz_main/agora_2.0'));args=ap.parse_args()
    root=args.source_root;bench=root/'docs/living_world_benchmark_20260825_hidden';legacy=root/'docs/benchmark_20260724'
    (HERE/'public').mkdir(exist_ok=True);(HERE/'researcher_only').mkdir(exist_ok=True)
    rng=random.Random(20260919)
    artifacts={};keys={};pairs={};pairkeys={};provenance=[];failures=[]
    def ident(prefix):return prefix+''.join(rng.choice('23456789abcdefghjkmnpqrstuvwxyz') for _ in range(10))
    def freeze(p):
        dst=HERE/'researcher_only/source_records'/p.relative_to(root);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dst)
        return dict(path=str(p.relative_to(root)),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    def artifact(p,condition,source_id,complete):
        aid=ident('w');artifacts[aid]=packet(read(p));keys[aid]=dict(condition=condition,source_id=source_id,complete=complete,**freeze(p));return aid
    def pair(arm,prompt_id,brief,left,right):
        pid=ident('p');pairs[pid]=dict(prompt=brief,candidates=[left,right]);pairkeys[pid]=dict(arm=arm,prompt_id=prompt_id,candidates=[left,right]);return pid
    suite=read(bench/'prompt_suite_hidden_v2.json');provenance.append(freeze(bench/'prompt_suite_hidden_v2.json'))
    model_pairs=[];arch_pairs=[]
    for prompt in suite['prompts']:
        candidates=[]
        for d in sorted((bench/'confirmatory_runs').iterdir()):
            result_paths=list((d/prompt['prompt_id']).glob('*result.json'))
            if not result_paths:continue
            result=read(result_paths[0]);provenance.append(freeze(result_paths[0]))
            complete=bool(result.get('complete_success'))
            failures.append(dict(arm='model',model=d.name,prompt_id=prompt['prompt_id'],compiled=complete,error=result.get('error','')))
            if not complete:continue
            assert result['request']['brief']==prompt['sentence']
            p=next((d/prompt['prompt_id']).glob('*builder_spec.json'))
            aid=artifact(p,d.name,prompt['prompt_id'],complete);candidates.append(aid)
        for a,b in itertools.combinations(candidates,2):model_pairs.append(pair('model',prompt['prompt_id'],prompt['sentence'],a,b))
    for suffix in ['20260729','heldout_20260729']:
        comp=legacy/('decomposed_controlled_low_'+suffix);mono=legacy/('monolithic_baseline_low_24k_quality_'+suffix)
        for result_path in sorted(comp.glob('*_r01_decomposed_result.json')):
            d=read(result_path);name=result_path.name.replace('_r01_decomposed_result.json','');request=d['request']
            mp=mono/(name+'_rep01_monolithic_prompt.txt');mptext=mp.read_text();original=mptext.split('Original request:\n',1)[1].split('\n\nRequired content:',1)[0]
            assert json.loads(original)==request,'Inputs differ: '+name
            ms=mono/(name+'_rep01_monolithic_builder_spec.json');mr=mono/(name+'_rep01_result.json');md=read(mr)
            mcomplete=bool(md.get('generation_ok') and md.get('compile_probe',{}).get('compile_ok') and md.get('merged_contract_probe',{}).get('merged_contract_ok'))
            ca=artifact(comp/(name+'_r01_decomposed_builder_spec.json'),'agora_compositional',name,bool(d['complete_success']))
            ma=artifact(ms,'single_pass',name,mcomplete)
            # Supply the complete common brief, not a shortened "one-sentence" proxy.
            brief=request['brief']+'\n\nCommon targets: '+str(request['agent_count_target'])+' agents; '+str(request['player_count_target'])+' player slots.'
            arch_pairs.append(pair('architecture',name,brief,ca,ma))
            for p in [mp,mr,result_path]:provenance.append(freeze(p))
            failures.extend([dict(arm='architecture',model='agora_compositional',prompt_id=name,compiled=bool(d['complete_success']),replicate=1),dict(arm='architecture',model='single_pass',prompt_id=name,compiled=mcomplete,replicate=1)])
    assert len(model_pairs)==41 and len(arch_pairs)==10 and len(artifacts)==37
    # 41-person base block: every model pair appears exactly twice, once on each side.
    # A second mirrored block makes every exact task appear at a different serial position.
    rng.shuffle(model_pairs);rng.shuffle(arch_pairs)
    base=[];occurrence=Counter()
    for i in range(41):
        mids=[model_pairs[(2*i)%41],model_pairs[(2*i+1)%41]]
        aids=[arch_pairs[(2*i)%10],arch_pairs[(2*i+1)%10]]
        ids=[mids[0],aids[0],mids[1],aids[1]] if i%2==0 else [aids[0],mids[0],aids[1],mids[1]]
        tasks=[]
        for pid in ids:
            flip=occurrence[pid]%2;occurrence[pid]+=1
            candidates=pairs[pid]['candidates'];tasks.append(dict(pair_id=pid,left=candidates[flip],right=candidates[1-flip]))
        base.append(tasks)
    schedule={}
    for i,tasks in enumerate(base):
        schedule[f'S{i+1:03}']=tasks
        schedule[f'S{i+42:03}']=[dict(pair_id=t['pair_id'],left=t['right'],right=t['left']) for t in reversed(tasks)]
    for i in range(8): # Pilot codes are disjoint and never enter the formal analysis by default.
        schedule[f'P{i+1:03}']=base[(i*5)%41]
    public=dict(version=VERSION,artifacts=artifacts,pairs={k:dict(prompt=v['prompt']) for k,v in pairs.items()},schedule=schedule)
    write(HERE/'researcher_only/blind_key.json',dict(version=VERSION,artifacts=keys,pairs=pairkeys,schedule=schedule))
    write(HERE/'researcher_only/provenance.json',provenance)
    write(HERE/'researcher_only/generation_status.json',failures)
    write(HERE/'researcher_only/public_payload.json',public)
    with (HERE/'researcher_only/assignment_roster.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['assignment_code','stage','assigned_to_local_code','issued','returned'])
        for code in schedule:w.writerow([code,'pilot' if code.startswith('P') else 'formal','','',''])
    template=(HERE/'survey_template.html').read_text();encoded=json.dumps(public,ensure_ascii=False,separators=(',',':')).replace('</','<\\/')
    html=template.replace('__STUDY_DATA__',encoded);(HERE/'public/START_SURVEY.html').write_text(html)
    # A compact packet for paper review / printing, with real evidence for one pilot assignment.
    example=public.copy();example['example_code']='P001';write(HERE/'researcher_only/example_packet.json',example)
    counts=Counter(t['pair_id'] for code,ts in schedule.items() if code.startswith('S') for t in ts)
    assert all(counts[p]==4 for p in model_pairs)
    assert all(16<=counts[p]<=18 for p in arch_pairs)
    assert all(len({t['pair_id'] for t in ts})==4 for ts in schedule.values())
    print(f'{len(artifacts)} real artifacts; {len(model_pairs)} model and {len(arch_pairs)} architecture pairs; 82 formal + 8 pilot codes.')

if __name__=='__main__':main()
