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


DOCUMENTS = {
    "main": "agora_one_sentence_one_living_world_20260923",
    "supp": "agora_one_sentence_one_living_world_20260923_supplement",
}


def read_document(path, seen):
    """Follow actual inputs so excluded or orphaned sections cannot pass checks."""
    path = path.resolve()
    assert path not in seen, f"Repeated input: {path}"
    seen.add(path)
    text = path.read_text()
    def include(match):
        child = PAPER / match[1]
        if not child.suffix:
            child = child.with_suffix(".tex")
        assert child.is_file(), child
        return read_document(child, seen)
    return re.sub(r"\\input\{([^}]+)\}", include, text)


def main():
    included = set()
    documents = {}
    local_labels = {}
    keys = set(re.findall(r"@\w+\{([^,]+),", (PAPER / "references.bib").read_text()))
    cited = set()
    for kind, name in DOCUMENTS.items():
        seen = set()
        tex = read_document(PAPER / (name + ".tex"), seen)
        documents[kind] = tex
        included.update(seen)
        labels = re.findall(r"\\label\{([^}]+)\}", tex)
        assert len(labels) == len(set(labels)), (kind, "duplicate labels")
        local_labels[kind] = set(labels)
        doc_cited = {k.strip() for c in re.findall(r"\\cite\w*\{([^}]+)\}", tex) for k in c.split(",")}
        assert doc_cited <= keys, (kind, doc_cited - keys)
        cited.update(doc_cited)
        for fig in re.findall(r"\\includegraphics(?:\[[^]]*\])?\{([^}]+)\}", tex):
            assert (PAPER / fig).is_file(), fig
        # Each document owns its labels and bibliography; imports stay external.
        aux = (PAPER / (name + ".aux")).read_text()
        aux_labels = set(re.findall(r"\\newlabel\{([^}]+)\}", aux))
        assert local_labels[kind] <= aux_labels, (kind, local_labels[kind] - aux_labels)
        bib_keys = set(re.findall(r"\\bibcite\{([^}]+)\}", aux))
        assert bib_keys == doc_cited, (kind, "bibliography mismatch", bib_keys ^ doc_cited)
        assert (PAPER / (name + ".pdf")).is_file(), name
        print(f"{kind}: {len(labels)} local labels, {len(doc_cited)} cited references")
    assert not local_labels["main"] & local_labels["supp"], "overlapping document labels"
    for kind, tex in documents.items():
        other = "supp" if kind == "main" else "main"
        refs = set(re.findall(r"\\(?:ref|eqref|pageref|autoref)\{([^}]+)\}", tex))
        valid = local_labels[kind] | {other + "-" + label for label in local_labels[other]}
        assert refs <= valid, (kind, "undefined or wrongly scoped references", refs - valid)
        expected = r"\externaldocument[" + other + "-][nocite]{" + DOCUMENTS[other] + "}"
        assert expected in tex, (kind, "missing external-document import")
    source_sections = {p.resolve() for folder in ("sections", "supplement") for p in (PAPER / folder).rglob("*.tex")}
    assert source_sections <= included, ("orphaned sections", source_sections - included)
    assert cited == keys, {"missing_entries": cited-keys, "uncited_entries": keys-cited}
    assert len(cited) == 29, len(cited)
    label_count = sum(map(len, local_labels.values()))

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

    forbidden=['undefined references','undefined citations','Citation(s) may have changed',
               'Label(s) may have changed','Overfull \\hbox','Overfull \\vbox','LaTeX Error',
               'Extra alignment tab','Font shape','Missing character','LABELS NOT IMPORTED',
               'multiply defined']
    for name in DOCUMENTS.values():
        log = (PAPER / (name + '.log')).read_text()
        for phrase in forbidden:
            assert phrase not in log, (name, phrase)
    print(f"Verified {len(keys)} cited references, {label_count} labels across two documents, {len(list((PAPER / 'figures').glob('*.pdf')))} figure assets, "
          "49/56 action results, 53 fresh events, 1,052 pilot events, "
          "paired-test arithmetic, and Clockwork subset totals.")
    print("Both PDFs: no unresolved citations/references, overfull boxes, alignment or font errors.")


if __name__=='__main__':main()
