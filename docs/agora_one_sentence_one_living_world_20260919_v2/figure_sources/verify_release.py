#!/usr/bin/env python3
"""Check source references, frozen evidence arithmetic, and LaTeX diagnostics."""
import json
import math
import re
from pathlib import Path

PAPER = Path(__file__).resolve().parent.parent
DATA = PAPER / "figure_sources/input_snapshot/docs"


def read_json(path):
    return json.loads((DATA / path).read_text())


def main():
    texts = [PAPER / "agora_one_sentence_one_living_world_20260919.tex", *sorted((PAPER / "sections").glob("*.tex"))]
    tex = "\n".join(p.read_text() for p in texts)
    keys = set(re.findall(r"@\w+\{([^,]+),", (PAPER / "references.bib").read_text()))
    cited = {k.strip() for c in re.findall(r"\\cite\w*\{([^}]+)\}", tex) for k in c.split(",")}
    assert cited == keys, {"missing_entries": cited-keys, "uncited_entries": keys-cited}
    assert len(cited) == 29, len(cited)
    labels = re.findall(r"\\label\{([^}]+)\}", tex)
    refs = set(re.findall(r"\\ref\{([^}]+)\}", tex))
    assert len(labels) == len(set(labels)), "duplicate labels"
    assert refs <= set(labels), refs-set(labels)
    for fig in re.findall(r"\\includegraphics(?:\[[^]]*\])?\{([^}]+)\}",tex):
        assert (PAPER/fig).is_file(), fig

    gen=read_json("benchmark_20260724/paper_evidence_summary_20260729.json")
    for field, comp, single, probability in [("eventual",10,7,.125),("first_pass",9,5,.109375)]:
        r=gen['reliability'][field]
        assert (r['specialist_successes'],r['monolithic_successes'])==(comp,single)
        n=r['specialist_only']+r['monolithic_only']
        p=sum(math.comb(n,k) for k in range(r['specialist_only'],n+1))/2**n
        assert abs(p-probability)<1e-10
    metrics=read_json("world_interaction_experiment_20260803/multiworld_metrics.json")
    audit=read_json("world_interaction_experiment_20260803/action_result_audit.json")
    total_s=total_r=total_e=0
    by_id={r['run_id']:r for r in metrics['runs']}
    for run in audit['runs']:
        rows=run['round_summaries']
        s=sum(r['action_success_count'] for r in rows)
        n=sum(r['action_result_count'] for r in rows)
        e=sum(r['story_event_count'] for r in rows)
        assert abs(s/n-by_id[run['run_id']]['action_success_rate'])<0.00006
        assert e==by_id[run['run_id']]['events']
        total_s+=s;total_r+=n;total_e+=e
    assert (total_s,total_r,total_e)==(49,56,53)
    assert total_s/total_r==metrics['aggregate']['action_success_rate']==.875
    for k in ['events','unique_dyads','open_proposal_events','world_action_events','human_interaction_events']:
        assert sum(r[k] for r in metrics['runs'])==metrics['aggregate'][k]
    pilot=read_json("world_interaction_experiment_20260803/pilot_metrics.json")
    assert sum(r['events'] for r in pilot['runs'])==1052
    events=read_json("world_interaction_experiment_20260803/clockwork_open_audit.json")['events']
    assert len(events)==7
    deltas=tuple(sum(r[k] for e in events for r in e['relationship_adjustments'])
                 for k in ['trust_delta','affection_delta','influence_fear_delta'])
    assert deltas==(-29,-5,17),deltas

    log=(PAPER/'agora_one_sentence_one_living_world_20260919.log').read_text()
    forbidden=['undefined references','undefined citations','Citation(s) may have changed',
               'Label(s) may have changed','Overfull \\hbox','Overfull \\vbox','LaTeX Error',
               'Extra alignment tab','Font shape','Missing character']
    for phrase in forbidden:
        assert phrase not in log, phrase
    print(f"Verified {len(keys)} cited references, {len(labels)} labels, 12 figure assets, "
          "49/56 action results, 53 fresh events, 1,052 pilot events, "
          "paired-test arithmetic, and Clockwork subset totals.")
    print("LaTeX: no unresolved citations/references, overfull boxes, alignment or font errors.")


if __name__=='__main__':main()
