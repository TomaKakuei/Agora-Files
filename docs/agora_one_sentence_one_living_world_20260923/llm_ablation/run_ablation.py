#!/usr/bin/env python3
"""Frozen, paired input/action-space ablations of Agora's centralized 24-round harness."""
from __future__ import annotations
import argparse
import concurrent.futures
import hashlib
import importlib
import json
import os
import random
import shlex
import shutil
import statistics
import sys
import time
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONDITIONS = ('full', 'no_event_history', 'catalog_only')
CHECKPOINTS = (1, 5, 9, 13, 17, 21)
MODELS = ('gemini-2.5-flash',)
REPEATS = (1, 2, 3)
SYSTEM = ('You control a centralized multi-character policy in a persistent typed world. '
          'Produce grounded intentions, not claims that effects already happened. '
          'The coordinator alone validates and commits state changes.')
INSTRUCTIONS = '''Plan exactly 12 actions, exactly three for each round_offset 0, 1, 2, 3.
Use a different AI actor for the three actions of each round. The scripted human is a target, never an actor.
Use exact IDs. Catalog/proposal actions require actor and target in the same room at execution time;
movement can only follow listed room neighbors. Account for your earlier planned moves and transfers.
Choose actions that advance the world's activities and currently supplied tasks. Avoid vacuous repetition.
Use the provided available_action_types. Use catalog routes when suitable. Proposals, when available,
may express bounded speech, status changes, transfer of owned objects, or creation from owned inputs.
For a transfer taking another character's property, use target_response=accept only if consent is supplied.
Do not invent consent, ownership, or successful outcomes. Keep physical effects within supplied constraints.
Continue threads where the supplied context supports it; cite only event IDs actually supplied in context.
If no relevant event is supplied, use an empty responds_to_event_ids list. Thread labels are only bookkeeping.
Use short intent/expected-consequence strings (at most 100 characters each); no chain-of-thought.
For catalog, set route_id to a catalog entry. For move, set destination_room_id. For propose, supply proposal.
Omit proposal for other action types. Use empty strings for unused scalar fields.
'''

def read(path):
    return json.loads(Path(path).read_text())

def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def runtime(root=None):
    root = Path(root) if root else HERE / 'runtime_snapshot'
    if str(root) not in sys.path: sys.path.insert(0, str(root))
    return importlib.import_module('scripts.agora_generated_world_runtime_benchmark')

def credentials(path):
    # Only named credentials are loaded; values never enter experiment artifacts.
    for line in Path(path).read_text().splitlines():
        line = line.strip().removeprefix('export ')
        if not line or line.startswith('#') or '=' not in line: continue
        key, value = line.split('=', 1)
        if key in ('AGORA_AISTUDIO_API_KEY', 'AGORA_VERTEX_API_KEY', 'GEMINI_API_KEY'):
            bits = shlex.split(value); os.environ[key] = bits[0] if bits else ''
    if not os.environ.get('AGORA_AISTUDIO_API_KEY'):
        raise RuntimeError('AGORA_AISTUDIO_API_KEY is not configured')

def safe_error(exc):
    value = f'{type(exc).__name__}: {exc}'
    for key in ('AGORA_AISTUDIO_API_KEY', 'AGORA_VERTEX_API_KEY', 'GEMINI_API_KEY'):
        if os.environ.get(key): value = value.replace(os.environ[key], '[REDACTED]')
    return value[:1800]

def client_config(model):
    return {'vertex_api': {'backend': 'ai_studio', 'api_key_env': 'AGORA_AISTUDIO_API_KEY',
        'endpoint_base': 'https://generativelanguage.googleapis.com/v1beta', 'model': model,
        'temperature': 0.45, 'max_output_tokens': 6144, 'thinking_level': 'low',
        'thinking_budget': 0, 'timeout_seconds': 90,
        'retry': {'max_attempts': 2, 'initial_sleep_seconds': 2, 'max_sleep_seconds': 5,
                  'backoff_multiplier': 2, 'status_codes': [408, 429, 500, 502, 503, 504]}}}

def prompt_payload(bench, config, state, initial, events, checkpoint, intervention, condition):
    raw = bench._runtime_prompt(config=config, state=state, events=events,
                                checkpoint=checkpoint, intervention=intervention)
    data = json.loads(raw.split('\n\nSTATE:\n', 1)[1])
    # Current requests and current intervention survive the event-history ablation.
    data['current_tasks'] = [{k: e[k] for k in ('event_id', 'round_index', 'event_type', 'content') if k in e}
                             for e in events if e.get('event_type') in ('human_request', 'world_request', 'human_followup')]
    data['available_action_types'] = ['catalog', 'move', 'propose']
    if condition == 'no_event_history': data['recent_events'] = []
    elif condition == 'catalog_only':
        data['available_action_types'] = ['catalog', 'move']
        data['open_action_examples'] = []
    elif condition != 'full': raise ValueError(condition)
    return data

def schema_for(bench, condition):
    schema = deepcopy(bench._plan_schema())
    if condition == 'catalog_only':
        props = schema['properties']['actions']['items']['properties']
        props['action_type']['enum'] = ['catalog', 'move']
        props.pop('proposal')
    return schema

def material_state(state):
    return sorted((a.agent_id, a.room_id, a.coordinates.x, a.coordinates.y, a.coordinates.z,
                   sorted((i.item_id, i.quantity) for i in a.inventory if i.quantity > 0)) for a in state.agents)

def execute(bench, actions, *, state, config, rules, checkpoint, events, acted):
    output = []
    # Retain malformed/extra slots as failures; never execute outside this block.
    for index, raw in enumerate(actions):
        raw = raw if isinstance(raw, dict) else {'invalid_raw_action': raw}
        offset = raw.get('round_offset')
        before = bench._state_hash(state); material_before = digest(material_state(state))
        eid = f'model_r{checkpoint:02d}_slot{index+1:02d}'
        valid_offset = isinstance(offset, int) and not isinstance(offset, bool) and offset in range(4)
        if not valid_offset or index >= 12:
            event = bench._failed_event(event_id=eid, round_index=checkpoint, raw=raw,
                        reason='invalid block slot', before_hash=before, violations=['invalid_block_slot'])
        else:
            event = bench.execute_action(raw, event_id=eid, round_index=checkpoint+offset,
                         state=state, config=config, world_rules=rules,
                         known_event_ids={e['event_id'] for e in events}, acted=acted)
        event['material_before_hash'] = material_before
        event['material_after_hash'] = digest(material_state(state))
        event['material_changed'] = material_before != event['material_after_hash']
        events.append(event); output.append(event)
    return output

def summarize_trace(trace):
    actions = [e for e in trace['events'] if e.get('event_type') == 'model_action']
    successes = [e for e in actions if e.get('status') == 'success']
    planned = 12 * len(trace['checkpoints'])
    calls = [c for block in trace['blocks'] for c in block['telemetry']]
    usage = Counter()
    for c in calls:
        for key,value in c.get('usage_metadata', {}).items():
            if isinstance(value, (float,int)): usage[key] += value
    return {'planned_slots': planned, 'attempted_actions':len(actions), 'successful_actions':len(successes),
            'material_actions':sum(e['material_changed'] for e in successes),
            'inventory_actions':sum('inventory' in e.get('mutation_kinds', []) for e in successes),
            'move_actions':sum(e['action_type']=='move' for e in successes),
            'catalog_actions':sum(e['action_type']=='catalog' for e in successes),
            'proposal_actions':sum(e['action_type']=='propose' for e in actions),
            'approved_proposals':sum(e['action_type']=='propose' for e in successes),
            'failed_state_changes':sum(e.get('before_state_hash')!=e.get('after_state_hash') for e in actions if e.get('status')!='success'),
            'completed_blocks':sum(b['shape_valid'] for b in trace['blocks']),
            'api_errors':sum(b['status']=='error' for b in trace['blocks']),
            'api_attempts':len(calls), 'usage':dict(usage),
            'success_per_planned_slot':len(successes)/planned,
            'material_per_planned_slot':sum(e['material_changed'] for e in successes)/planned,
            'success_per_attempt':len(successes)/len(actions) if actions else None,
            'material_per_success':sum(e['material_changed'] for e in successes)/len(successes) if successes else None}

def run_one(job, manifest, output, pilot=False):
    bench = runtime(); world=job['world']; model=job['model']; condition=job['condition']
    key=f"{world}__{model}__rep{job['repeat']}__{condition}"
    dest=output/key; final=dest/'trajectory.json'
    if final.exists():
        trace=read(final)
        assert trace['protocol_sha256']==digest(manifest), 'Protocol changed; refusing to reuse results'
        return key, trace['metrics'], 'cached'
    config=read(HERE/'inputs'/f'{world}.json')
    initial_payload=read(HERE/'inputs'/f'{world}_initial_state.json')
    initial=bench.AgentStateBundleSpec.model_validate(initial_payload)
    state=initial.model_copy(deep=True)
    rules=bench.WorldRulesSpec.model_validate(read(HERE/'inputs'/f'{world}_rules.json'))
    # Scripted external shocks use the same reference rules in all conditions.
    action_config=deepcopy(config)
    if condition=='catalog_only':
        action_config.setdefault('world_rules',{}).setdefault('custom_action_rules',{})['open_proposals_enabled']=False
    checkpoints=CHECKPOINTS[:2] if pilot else CHECKPOINTS
    trace={**job,'protocol_sha256':digest(manifest),'pilot':pilot,'checkpoints':list(checkpoints),
           'initial_state_hash':bench._state_hash(initial),'blocks':[],'events':[]}
    client=bench.VertexJsonClient(client_config(model));client.telemetry_path=''
    acted=set(); started=time.monotonic()
    for checkpoint in checkpoints:
        blockfile=dest/f'block_{checkpoint:02d}.json'
        # Resume only at complete block boundaries, with logged state and used actor slots.
        if blockfile.exists():
            block=read(blockfile)
            assert block['protocol_sha256']==digest(manifest)
            assert block['state_before_intervention_hash']==bench._state_hash(state)
            state=bench.AgentStateBundleSpec.model_validate(block['state_after'])
            trace['events'].extend(block['new_events']);acted.update(tuple(a) for a in block['acted_slots'])
            trace['blocks'].append({k:v for k,v in block.items() if k not in ('state_after','new_events','acted_slots')})
            continue
        event_start=len(trace['events']); before_intervention=bench._state_hash(state)
        intervention=bench._intervention(checkpoint,state=state,config=config,events=trace['events'])
        payload=prompt_payload(bench,config,state,initial,trace['events'],checkpoint,intervention,condition)
        prompt=INSTRUCTIONS+'\nSTATE:\n'+json.dumps(payload,ensure_ascii=False,separators=(',',':'))
        block={'checkpoint':checkpoint,'protocol_sha256':digest(manifest),
               'state_before_intervention_hash':before_intervention,'prompt_payload':payload,
               'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'schema':schema_for(bench,condition)}
        call_start=len(client.call_history);call_time=time.monotonic()
        try:
            plan=client.generate_json(system_instruction=SYSTEM,prompt=prompt,schema=block['schema'],stage='paired_planner_ablation')
            actions=plan.get('actions',[])
            if not isinstance(actions,list):raise ValueError('actions must be a list')
            counts=Counter(a.get('round_offset') for a in actions if isinstance(a,dict))
            block.update(status='ok',plan=plan,shape_valid=len(actions)==12 and all(counts[i]==3 for i in range(4)))
            actions=sorted(actions,key=lambda a:a.get('round_offset',99) if isinstance(a,dict) and isinstance(a.get('round_offset'),int) else 99)
            execute(bench,actions,state=state,config=action_config,rules=rules,checkpoint=checkpoint,events=trace['events'],acted=acted)
        except Exception as exc:
            block.update(status='error',error=safe_error(exc),shape_valid=False)
        block['latency_seconds']=round(time.monotonic()-call_time,4)
        block['telemetry']=client.call_history[call_start:]
        write(blockfile,{**block,'state_after':state.model_dump(mode='json'),
                         'new_events':trace['events'][event_start:],'acted_slots':sorted(acted)})
        trace['blocks'].append(block)
    trace['final_state_hash']=bench._state_hash(state)
    trace['final_state']=state.model_dump(mode='json')
    trace['elapsed_seconds']=round(time.monotonic()-started,3)
    trace['metrics']=summarize_trace(trace)
    write(final,trace)
    return key,trace['metrics'],'complete'

def prepare(args):
    if (HERE/'protocol.json').exists():raise RuntimeError('Protocol already frozen')
    root=args.runtime_root.resolve()
    for package in ('agora_ui','asset_pipeline'):
        for f in (root/package).rglob('*.py'):
            rel=f.relative_to(root);target=HERE/'runtime_snapshot'/rel
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(f,target)
    for f in (root/'agora_ui/data/registries').glob('*.json'):
        target=HERE/'runtime_snapshot'/f.relative_to(root)
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(f,target)
    for name in ('agora_generated_world_runtime_benchmark.py',):
        target=HERE/'runtime_snapshot/scripts'/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(root/'scripts'/name,target)
    bench=runtime()
    source=root/'docs/world_interaction_experiment_20260803/multiworld_configs'
    worlds=[]
    for name in ('clockwork_rain_conservatory','tidal_embassy_lost_languages'):
        config=read(source/f'{name}.json')
        state,rules=bench._load_runtime(config,HERE/'preparation'/name)
        # Credentials are not needed in frozen world definitions.
        config.pop('vertex_api',None);config.pop('vertex_image_sdk',None)
        for k in list(config.get('runtime',{})):
            if k.startswith('vertex_'):config['runtime'].pop(k)
        write(HERE/'inputs'/f'{name}.json',config)
        write(HERE/'inputs'/f'{name}_initial_state.json',state.model_dump(mode='json'))
        write(HERE/'inputs'/f'{name}_rules.json',rules.model_dump(mode='json'))
        worlds.append({'world':name,'name':config['scenario_meta']['world_name'],
                       'source_sha256':file_digest(source/f'{name}.json'),
                       'initial_state_hash':bench._state_hash(state),'agents':len(state.agents)})
    write(HERE/'prepared_worlds.json',worlds)
    print(json.dumps({'prepared_worlds':len(worlds),'initialization':'One shared frozen state per world; no per-condition generation.'}))

def freeze(args):
    path=HERE/'protocol.json'
    if path.exists():raise RuntimeError('Protocol already frozen; create a new study version to change it')
    worlds=read(HERE/'prepared_worlds.json')
    jobs=[dict(world=w['world'],model=m,repeat=r,condition=c) for w in worlds for m in MODELS for r in REPEATS for c in CONDITIONS]
    random.Random(20260923).shuffle(jobs)
    manifest={'study':'paired_centralized_planner_ablation_v1','frozen_at_utc':datetime.now(timezone.utc).isoformat(),
      'models':list(MODELS),'conditions':list(CONDITIONS),'worlds':worlds,'repeats':list(REPEATS),'jobs':jobs,
      'rounds':24,'actions_per_round':3,'checkpoints':list(CHECKPOINTS),'planned_trajectories':len(jobs),
      'planned_calls':len(jobs)*6,'planned_action_slots':len(jobs)*72,
      'generation':client_config(MODELS[0])['vertex_api'],
      'estimands':['successful_actions / 72 planned action slots','inventory-or-location-changing successes / 72 planned action slots'],
      'secondary':['success / attempted action','material changes / success','approved proposals','failed state changes','API errors','token use'],
      'analysis':'Paired differences within each world-model-repeat block; report every world/model and repeat, with descriptive aggregation, no significance or population-generalization claim.',
      'pilot':'Two blocks on one world per model/condition, stored separately and excluded; protocol finalized after implementation validation.',
      'scope':'Centralized four-round block planner; neither decentralized episodic-memory causality nor human gameplay. Catalog-only removes expressivity, so inventory effects can be mechanically constrained.',
      'pairing':'Identical initial states, model settings, rounds, task introductions and shock rules. No API sampling seed; repeat indices are stochastic replicates, not independent worlds. Adaptive shock recipients depend on the diverged state.',
      'input_hashes':{str(p.relative_to(HERE)):file_digest(p) for p in sorted((HERE/'inputs').glob('*.json'))},
      'implementation_hashes':{str(p.relative_to(HERE)):file_digest(p) for p in [HERE/'run_ablation.py',*sorted(p for p in (HERE/'runtime_snapshot').rglob('*') if p.suffix in ('.py','.json'))]}}
    write(path,manifest);print(json.dumps({'frozen':str(path),'sha256':digest(manifest),'trajectories':len(jobs),'calls':len(jobs)*6}))

def run(args):
    credentials(args.env_file)
    if args.pilot:
        manifest={'pilot':True,'implementation_sha256':file_digest(__file__)}
        world=read(HERE/'prepared_worlds.json')[0]['world']
        jobs=[dict(world=world,model=m,repeat=0,condition=c) for m in MODELS for c in CONDITIONS]
        output=HERE/'pilot'
    else:
        manifest=read(HERE/'protocol.json');jobs=manifest['jobs'];output=HERE/'runs'
        for rel,sha in {**manifest['input_hashes'],**manifest['implementation_hashes']}.items():
            assert file_digest(HERE/rel)==sha, f'Frozen source changed: {rel}'
    started=time.monotonic();done=0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures={pool.submit(run_one,j,manifest,output,args.pilot):j for j in jobs}
        for future in concurrent.futures.as_completed(futures):
            job=futures[future]
            try:
                key,metrics,status=future.result();done+=1
                print(json.dumps({'done':done,'total':len(jobs),'run':key,'status':status,
                                  'successes':metrics['successful_actions'],'material':metrics['material_actions'],
                                  'api_errors':metrics['api_errors'],'seconds':round(time.monotonic()-started)},ensure_ascii=False),flush=True)
            except Exception as exc:
                print(json.dumps({'job':job,'error':safe_error(exc)}),flush=True)
                raise

def main():
    ap=argparse.ArgumentParser();sub=ap.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('--runtime-root',type=Path,required=True)
    sub.add_parser('freeze')
    p=sub.add_parser('run');p.add_argument('--pilot',action='store_true');p.add_argument('--workers',type=int,default=4)
    p.add_argument('--env-file',type=Path,default=Path('/home/yz_wang/.config/agora_ui_runtime.env'))
    args=ap.parse_args();{'prepare':prepare,'freeze':freeze,'run':run}[args.command](args)

if __name__=='__main__':main()
