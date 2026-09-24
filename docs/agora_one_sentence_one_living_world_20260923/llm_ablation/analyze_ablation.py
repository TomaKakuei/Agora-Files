#!/usr/bin/env python3
"""Replay every frozen action and generate descriptive ablation tables; no API calls."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import statistics
from collections import Counter,defaultdict
from copy import deepcopy
from pathlib import Path
import run_ablation as r

LABELS={'full':'Full','no_event_history':'No event history','catalog_only':'Catalog only'}
WORLDS={'clockwork_rain_conservatory':'Clockwork','tidal_embassy_lost_languages':'Tidal'}

def audit_trace(path,protocol):
    b=r.runtime();t=r.read(path);key=path.parent.name;world=t['world']
    assert t['protocol_sha256']==r.digest(protocol) and not t['pilot'],key
    initial=b.AgentStateBundleSpec.model_validate(r.read(r.HERE/'inputs'/f'{world}_initial_state.json'))
    state=initial.model_copy(deep=True);events=[];acted=set()
    config=r.read(r.HERE/'inputs'/f'{world}.json');action_config=deepcopy(config)
    if t['condition']=='catalog_only':
        action_config['world_rules'].setdefault('custom_action_rules',{})['open_proposals_enabled']=False
    rules=b.WorldRulesSpec.model_validate(r.read(r.HERE/'inputs'/f'{world}_rules.json'))
    assert t['initial_state_hash']==b._state_hash(state)
    assert t['checkpoints']==list(r.CHECKPOINTS)
    for checkpoint,stored in zip(r.CHECKPOINTS,t['blocks']):
        block=r.read(path.parent/f'block_{checkpoint:02d}.json')
        assert block['checkpoint']==checkpoint
        assert block['state_before_intervention_hash']==b._state_hash(state),(key,checkpoint,'initial hash')
        start=len(events)
        intervention=b._intervention(checkpoint,state=state,config=config,events=events)
        payload=r.prompt_payload(b,config,state,initial,events,checkpoint,intervention,t['condition'])
        assert payload==block['prompt_payload'],(key,checkpoint,'treatment input')
        prompt=r.INSTRUCTIONS+'\nSTATE:\n'+json.dumps(payload,ensure_ascii=False,separators=(',',':'))
        assert hashlib.sha256(prompt.encode()).hexdigest()==block['prompt_sha256']
        assert r.schema_for(b,t['condition'])==block['schema']
        assert stored=={k:v for k,v in block.items() if k not in ('state_after','new_events','acted_slots')}
        if block['status']=='ok':
            actions=block['plan']['actions']
            counts=Counter(a.get('round_offset') for a in actions if isinstance(a,dict))
            assert block['shape_valid']==(len(actions)==12 and all(counts[i]==3 for i in range(4)))
            actions=sorted(actions,key=lambda a:a.get('round_offset',99) if isinstance(a,dict) and isinstance(a.get('round_offset'),int) else 99)
            r.execute(b,actions,state=state,config=action_config,rules=rules,checkpoint=checkpoint,events=events,acted=acted)
        else:
            assert 'error' in block and not block['shape_valid']
            assert not block.get('plan'), 'Execution error with partial plan requires explicit audit'
        assert events[start:]==block['new_events'],(key,checkpoint,'action replay differs')
        assert state.model_dump(mode='json')==block['state_after'],(key,checkpoint,'state replay differs')
        assert sorted(acted)==[tuple(v) for v in block['acted_slots']]
        assert all(c['model']==t['model'] and c['backend']=='ai_studio' for c in block['telemetry'])
    assert len(t['blocks'])==6
    assert events==t['events'] and b._state_hash(state)==t['final_state_hash']
    assert t['final_state']==state.model_dump(mode='json')
    assert r.summarize_trace(t)==t['metrics']
    if t['condition']=='catalog_only':assert t['metrics']['proposal_actions']==0
    return t

def aggregate(traces):
    keys=['planned_slots','attempted_actions','successful_actions','material_actions','inventory_actions','move_actions',
          'catalog_actions','proposal_actions','approved_proposals','failed_state_changes','completed_blocks','api_errors','api_attempts']
    result={k:sum(t['metrics'][k] for t in traces) for k in keys}
    usage=Counter()
    for t in traces:usage.update(t['metrics']['usage'])
    result['usage']=dict(usage);result['trajectories']=len(traces)
    result['success_rate']=result['successful_actions']/result['planned_slots']
    result['material_rate']=result['material_actions']/result['planned_slots']
    result['tokens_per_trajectory']=usage['totalTokenCount']/len(traces)
    return result

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--partial',action='store_true');args=ap.parse_args()
    protocol=r.read(r.HERE/'protocol.json')
    for rel,sha in {**protocol['input_hashes'],**protocol['implementation_hashes']}.items():
        assert r.file_digest(r.HERE/rel)==sha,('changed frozen file',rel)
    paths=sorted((r.HERE/'runs').glob('*/trajectory.json'))
    if args.partial:
        print(json.dumps({'completed':len(paths),'planned':len(protocol['jobs'])}));return
    assert len(paths)==len(protocol['jobs']),(len(paths),len(protocol['jobs']))
    traces=[audit_trace(p,protocol) for p in paths]
    identity=lambda j:tuple(j[k] for k in ('world','model','repeat','condition'))
    assert {identity(t) for t in traces}=={identity(j) for j in protocol['jobs']}
    grouped={c:aggregate([t for t in traces if t['condition']==c]) for c in r.CONDITIONS}
    world_group={w:{c:aggregate([t for t in traces if t['condition']==c and t['world']==w]) for c in r.CONDITIONS} for w in WORLDS}
    paired={}
    for condition in r.CONDITIONS[1:]:
        entries=[]
        for t in traces:
            if t['condition']!=condition:continue
            ref=next(s for s in traces if s['condition']=='full' and all(s[k]==t[k] for k in ('world','model','repeat')))
            entries.append({'world':t['world'],'repeat':t['repeat'],
                'success_delta_pp':100*(t['metrics']['success_per_planned_slot']-ref['metrics']['success_per_planned_slot']),
                'material_delta_pp':100*(t['metrics']['material_per_planned_slot']-ref['metrics']['material_per_planned_slot'])})
        paired[condition]={'pairs':entries}
        for metric in ('success_delta_pp','material_delta_pp'):
            values=[e[metric] for e in entries]
            paired[condition][metric]={'mean':statistics.mean(values),'min':min(values),'max':max(values)}
    summary={'protocol_sha256':r.digest(protocol),'total':aggregate(traces),'conditions':grouped,'by_world':world_group,'paired':paired,
             'checks':{'fully_replayed_trajectories':len(traces),'verified_blocks':6*len(traces),'human_data':'unchanged'}}
    r.write(r.HERE/'summary.json',summary)
    columns=['world','model','repeat','condition','successful_actions','material_actions','inventory_actions','move_actions','approved_proposals','api_errors']
    with (r.HERE/'trajectory_results.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=columns);writer.writeheader()
        for t in traces:writer.writerow({k:t.get(k,t['metrics'].get(k)) for k in columns})
    gen=r.HERE/'generated';gen.mkdir(exist_ok=True)
    rows=[r'\begin{tabular}{@{}lrrr@{}}',r'\toprule',r'Configuration & Success & Material & Inventory \\',r'\midrule']
    for c,x in grouped.items():rows.append(f"{LABELS[c]} & {x['successful_actions']} & {x['material_actions']} & {x['inventory_actions']} \\\\")
    rows.extend([r'\bottomrule',r'\end{tabular}'])
    (gen/'main_table.tex').write_text('\n'.join(rows)+'\n')
    rows=[r'\begin{tabular*}{\textwidth}{@{\extracolsep{\fill}}llrrrrrr@{}}',r'\toprule',r'World & Configuration & Rep. & Success & Material & Inventory & Move & Proposals \\',r'\midrule']
    for w in WORLDS:
        for c in r.CONDITIONS:
            for t in sorted([t for t in traces if t['world']==w and t['condition']==c],key=lambda t:t['repeat']):
                m=t['metrics'];rows.append(f"{WORLDS[w]} & {LABELS[c]} & {t['repeat']} & {m['successful_actions']}/72 & {m['material_actions']} & {m['inventory_actions']} & {m['move_actions']} & {m['approved_proposals']} \\\\")
        rows.append(r'\midrule')
    rows[-1]=r'\bottomrule';rows.append(r'\end{tabular*}')
    (gen/'detail_table.tex').write_text('\n'.join(rows)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
