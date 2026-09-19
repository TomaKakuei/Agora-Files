#!/usr/bin/env python3
"""Recompute simple, interpretable counts from frozen August records; no API calls."""
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

PAPER = Path(__file__).resolve().parents[1]
ROOT = PAPER / 'figure_sources/input_snapshot/extended_evidence'

def read(p):
    return json.loads(p.read_text())

def audit(root):
    generation = []
    by_model = defaultdict(list)
    sources = []
    for p in sorted((root/'generation').glob('*/*/*result.json')):
        d = read(p)
        model = p.parent.parent.name
        complete = bool(d.get('complete_success'))
        row = dict(model=model, prompt=p.parent.name, compiled=complete,
                   first_pass=complete and not d.get('generation_node_retries'),
                   recorded_repairs=len(d.get('generation_node_retries', [])),
                   error=d.get('error', ''))
        generation.append(row)
        by_model[model].append(row)
        sources.append(p)
    trajectories = []
    delta_counts = Counter()
    failure_reasons = Counter()
    for p in sorted((root/'trajectories').glob('replicate_*/*/trajectory.json')):
        d = read(p)
        a = [e for e in d['events'] if e['event_type'] == 'model_action']
        s = [e for e in a if e['status'] == 'success']
        approved = [e for e in a if (e.get('coordinator_decision') or {}).get('status') == 'approved']
        nonspeech = [e for e in approved if any(x.get('kind') != 'speech' for x in e['coordinator_decision']['proposal'].get('effects', []))]
        material = [e for e in s if set(e.get('mutation_kinds', [])) & {'inventory', 'location'}]
        rejected = [e for e in d['events'] if e['event_type'] == 'coordinator_rejection']
        known = {e['event_id'] for e in d['events']}
        unknown_refs = [dict(event=e['event_id'], status=e['status'], reference=x)
                        for e in a for x in e.get('responds_to_event_ids', []) if x not in known]
        failed = [e for e in a if e['status'] != 'success']
        assert all(e['before_state_hash'] == e['after_state_hash'] and e['state_changed'] is False for e in failed)
        assert all(e['status'] == 'rejected' and e['before_state_hash'] == e['after_state_hash'] and e['state_changed'] is False for e in rejected)
        for e in failed:
            failure_reasons[e.get('reason', '(missing)')] += 1
        for e in s:
            for u in (e.get('mutations') or {}).get('relationship_tensor_updates', []):
                delta = tuple(u['after'].get(k, 0)-u['before'].get(k, 0) for k in ['trust', 'affection', 'influence_fear'])
                delta_counts[delta] += 1
        row = dict(model=d['model'], replicate=p.parent.parent.name, rounds=d['round_count'],
                   checkpoints=d['completed_checkpoints'], actions=len(a), successes=len(s),
                   failures=len(failed), approved_proposals=len(approved),
                   nonspeech_approved=len(nonspeech), inventory_or_location_successes=len(material),
                   success_fraction=len(s)/len(a),
                   failed_state_changes=sum(bool(e.get('state_changed')) for e in failed),
                   scripted_rejections=len(rejected),
                   scripted_rejection_state_changes=sum(bool(e.get('state_changed')) for e in rejected),
                   persistence_roundtrip=bool(d['persistence_check']['roundtrip_equal']),
                   unknown_event_references=unknown_refs)
        assert row['rounds'] == 24 and row['checkpoints'] == 6 and row['actions'] == 72
        trajectories.append(row)
        sources.append(p)
    models = []
    for slug, rows in sorted(by_model.items()):
        runtime = [r for r in trajectories if r['model'].replace('-', '_').replace('.', '_') == slug]
        totals = {k:sum(r[k] for r in runtime) for k in ['actions','successes','failures','approved_proposals','nonspeech_approved','inventory_or_location_successes']}
        models.append(dict(slug=slug, model=runtime[0]['model'] if runtime else 'gpt-5.6-luna',
                           generated=len(rows), compiled=sum(r['compiled'] for r in rows),
                           first_pass=sum(r['first_pass'] for r in rows),
                           trajectory_count=len(runtime),
                           success_range=[min(r['success_fraction'] for r in runtime),max(r['success_fraction'] for r in runtime)] if runtime else None,
                           **totals))
    for p in sorted((root/'source_code').glob('*.py')):
        sources.append(p)
    report = dict(status='Retrospective raw-record audit; no new model or human observations.',
                  generation_trials=generation, trajectories=trajectories, models=models,
                  totals={k:sum(r[k] for r in trajectories) for k in ['actions','successes','failures','approved_proposals','nonspeech_approved','inventory_or_location_successes','failed_state_changes','scripted_rejections','scripted_rejection_state_changes']},
                  relationship_delta_counts=[dict(trust=k[0],affection=k[1],fear=k[2],count=v) for k,v in sorted(delta_counts.items())],
                  failure_reasons=dict(failure_reasons),
                  sources=[dict(path=str(p.relative_to(root)),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in sources])
    assert len(generation) == 24 and len(trajectories) == 21
    assert report['totals']['actions'] == 1512 and report['totals']['successes'] == 1365
    assert report['totals']['failed_state_changes'] == 0
    assert all(r['persistence_roundtrip'] for r in trajectories)
    return report

def render(report, output_root=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    models = [m for m in report['models'] if m['trajectory_count']]
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'pdf.fonttype':42})
    fig, axes = plt.subplots(1,3,figsize=(12.0,3.6),gridspec_kw={'width_ratios':[1.5,1,1]})
    y=np.arange(len(models))
    labels=[m['model'].replace('gemini-', 'Gemini ').replace('gpt-', 'GPT ').replace('-preview','').replace('-',' ') for m in models]
    for ax in axes:
        ax.spines[['top','right']].set_visible(False)
        ax.set_xlim(0,100);ax.grid(axis='x',alpha=.15);ax.set_axisbelow(True)
        ax.set_yticks(y);ax.invert_yaxis()
    means=[100*m['successes']/m['actions'] for m in models]
    axes[0].barh(y,means,color='#187f85',height=.58)
    axes[0].errorbar(means,y,xerr=[[means[i]-100*m['success_range'][0] for i,m in enumerate(models)],[100*m['success_range'][1]-means[i] for i,m in enumerate(models)]],fmt='none',ecolor='#263342',capsize=3,lw=1)
    axes[0].set_yticklabels(labels);axes[0].set_title('A  Executed successfully',loc='left',fontweight='bold');axes[0].set_xlabel('% of 216 attempted actions per model')
    axes[1].barh(y,[100*m['inventory_or_location_successes']/m['successes'] for m in models],color='#d5993b',height=.58)
    axes[1].set_yticklabels([]);axes[1].set_title('B  Inventory / location',loc='left',fontweight='bold');axes[1].set_xlabel('% of successful actions')
    axes[2].barh(y,[100*m['nonspeech_approved']/m['approved_proposals'] for m in models],color='#586e9c',height=.58)
    axes[2].set_yticklabels([]);axes[2].set_title('C  Non-speech proposals',loc='left',fontweight='bold');axes[2].set_xlabel('% of approved proposals')
    for ax in axes:ax.tick_params(axis='y',length=0)
    fig.tight_layout()
    output_root = output_root or PAPER/'figures'
    output_root.mkdir(parents=True,exist_ok=True)
    for ext in ['pdf','png']:
        fig.savefig(output_root/('extended_runtime_audit.'+ext),dpi=200,bbox_inches='tight')
    plt.close(fig)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');parser.add_argument('--output-root',type=Path);args=parser.parse_args()
    report=audit(ROOT);dest=ROOT/'audit_results.json'
    if args.check:
        assert read(dest)==report,'Frozen audit differs from recomputed raw counts'
    else:
        dest.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');render(report,args.output_root)
    print(json.dumps({'generation_trials':len(report['generation_trials']),'trajectories':len(report['trajectories']),**report['totals']}))

if __name__=='__main__':main()
