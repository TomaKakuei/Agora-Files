#!/usr/bin/env python3
"""Freeze genuine visual outputs and build a new, six-round visual allocation."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import shutil

HERE=Path(__file__).resolve().parent
APP=Path('/home/yz_wang/yz_main/agora_2.0')
OLD=HERE.parent/'agora_comparative_survey_20260919/researcher_only'
VERSION='agora-visual-11p-20260921-v2'
SEED=20260922
SCENES={
 'archive_of_borrowed_gravity':'A city sells and taxes the direction of gravity.',
 'cartographer_lung_exchange':'Inside a giant lung in space, people trade air while the passages shift.',
 'intertidal_embassy_for_extinct_rivers':'An embassy brings extinct rivers back to life and negotiates their rights.',
 'museum_of_future_debts':'A museum displays debts that people will owe in the future.',
 'night_market_of_unfinished_weather':'A market sells unfinished weather before it reaches the sky.',
 'aurora_court_of_migrating_cities':'Walking polar cities trade heat, travel routes, food, and spare mechanical legs.',
 'clockwork_rain_conservatory':'A greenhouse uses clockwork machines to make and manage rain.',
 'mycelium_patent_bazaar':'An underground fungal city trades living bridges, medicines, and inventions.',
 'sunken_satellite_monastery':'Under the sea, a monastery is built around a fallen communications satellite.',
 'tidal_embassy_of_lost_languages':'A floating embassy trades endangered languages as the tides change.',
}


def read(p):return json.loads(p.read_text())
def dump(p,d):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def allocate(pairs):
    rng=random.Random(SEED)
    models=sorted(p for p,m in pairs.items() if m['kind']=='images')
    structs=sorted(p for p,m in pairs.items() if m['kind']=='structure')
    assert len(models)==21 and len(structs)==10
    extra_model=rng.choice(models);extra_structure=rng.choice(structs)
    base=models+[extra_model]
    while True:
        rng.shuffle(base)
        blocks=[base[2*i:2*i+2] for i in range(11)]
        if all(len(set(blocks[i]+blocks[(i+1)%11]))==4 for i in range(11)):break
    directions=[bool(rng.randrange(2)) for _ in base]
    left=structs+[extra_structure];right=left[:];rng.shuffle(left)
    while True:
        rng.shuffle(right)
        if all(a!=b for a,b in zip(left,right)):break
    schedule={}
    for i in range(11):
        visual=[]
        for idx,reverse in [(2*i,False),(2*i+1,False),(2*((i+1)%11),True),(2*((i+1)%11)+1,True)]:
            pid=base[idx];a,b=pairs[pid]['candidates']
            if directions[idx] != reverse:a,b=b,a
            visual.append({'pair_id':pid,'left':a,'right':b})
        rng.shuffle(visual)
        structure=[]
        for pid,swap in [(left[i],False),(right[i],True)]:
            a,b=pairs[pid]['candidates']
            if swap:a,b=b,a
            structure.append({'pair_id':pid,'left':a,'right':b})
        rng.shuffle(structure)
        pattern=['images','images','structure','images','images','structure']
        offset=i%3;pattern=pattern[offset:]+pattern[:offset]
        schedule[f'V{i+1:02d}']=[(visual if kind=='images' else structure).pop(0) for kind in pattern]
    return schedule,{'seed':SEED,'extra_visual_pair':extra_model,'extra_structure_pair':extra_structure}


def main():
    key=read(OLD/'blind_key.json');payload=read(OLD/'public_payload.json')
    destination=HERE/'researcher_only';destination.mkdir(exist_ok=True)
    (destination/'assets').mkdir(exist_ok=True);(destination/'specs').mkdir(exist_ok=True)
    manifest=[]
    def freeze(source,relative):
        target=destination/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
        manifest.append({'file':str(target.relative_to(HERE)),'source':str(source),'sha256':sha(target),'bytes':target.stat().st_size})
        return str(target.relative_to(HERE))
    artifacts={};pairs={}
    case_path=APP/'docs/living_world_benchmark_20260825_hidden/visual_cases/case_manifest.json'
    visual_cases=read(case_path)
    freeze(case_path,'visual_case_manifest.json')
    # Only prompt 01 has archived matched visual realizations. Other text-only
    # prompts never enter this visual instrument.
    candidates=sorted((a,m) for a,m in key['artifacts'].items() if m['source_id']=='lwb_hidden_v2_01' and m['condition'] not in ['agora_compositional','single_pass'])
    for index,(aid,meta) in enumerate(candidates):
        model=meta['condition'];asset_root=APP/'frontend/assets/generated/world_asset_sets'/('lwbv2_'+model)
        assets=read(asset_root/'world_asset_set_manifest.json')
        spec=read(OLD/'source_records'/meta['path'])
        assert assets['world_id']==spec['world_id']
        case=next(m for m in visual_cases['models'] if m.get('asset_revision')=='lwbv2_'+model)
        assert sha(Path(case['builder_spec_path']))==sha(OLD/'source_records'/meta['path'])
        art={'kind':'images','condition':model,'map':freeze(asset_root/'world_map_source.png',f'assets/{aid}_map.png'),'characters':[],'source_id':'lwb_hidden_v2_01'}
        for number,agent in enumerate(assets['agents'][:2],1):
            assert agent['publishable'] is True
            bundle=agent['asset_bundle'];atlas=Path(bundle['atlas_png']);metadata=read(Path(bundle['atlas_json']))
            frame=metadata['frames']['idle_down_0.png']['frame'];assert frame=={'x':0,'y':0,'w':64,'h':64}
            art['characters'].append({'atlas':freeze(atlas,f'assets/{aid}_character{number}.png'),'frame':frame,'source_agent':agent['agent_id'],'source_revision':agent['generation_revision']})
        art['requested_character_count']=len(assets['agents'])
        art['published_character_count']=sum(a.get('publishable') is True for a in assets['agents'])
        art['spec']=freeze(OLD/'source_records'/meta['path'],f'specs/{aid}.json')
        art['source_world_id']=spec['world_id']
        art['asset_set_manifest_sha256']=sha(asset_root/'world_asset_set_manifest.json')
        artifacts[aid]=art
    for pid,meta in key['pairs'].items():
        if meta['arm']=='model' and meta['prompt_id']=='lwb_hidden_v2_01':
            cs=sorted(meta['candidates'],key=lambda a:artifacts[a]['condition'])
            pairs[pid]={'kind':'images','source_id':meta['prompt_id'],'candidates':cs,'scene':'In a cliffside city, promises have weight. Couriers carry unpaid promises between homes.','original_prompt':payload['pairs'][pid]['prompt']}
        if meta['arm']=='architecture':
            cs=sorted(meta['candidates'],key=lambda a:key['artifacts'][a]['condition'])
            for aid in cs:
                am=key['artifacts'][aid];source=OLD/'source_records'/am['path'];spec=read(source)
                rooms=[];assigned=0
                for room in spec['rooms']:
                    residents=[p for p in spec['main_characters'] if str(p.get('home_base','')).strip().casefold()==room['name'].strip().casefold()]
                    assigned+=len(residents)
                    props=room.get('scene_components',room.get('visual',{}).get('scene_components',[]))
                    rooms.append({'name':room['name'],'residents':len(residents),'props':len(props),'example_prop':props[0].get('label','') if props else ''})
                artifacts[aid]={'kind':'structure','condition':am['condition'],'source_id':meta['prompt_id'],'rooms':rooms,'people':len(spec['main_characters']),'unassigned_people':len(spec['main_characters'])-assigned,'spec':freeze(source,f'specs/{aid}.json'),'complete':am.get('complete')}
            pairs[pid]={'kind':'structure','source_id':meta['prompt_id'],'candidates':cs,'scene':SCENES[meta['prompt_id']],'original_prompt':payload['pairs'][pid]['prompt']}
    schedule,selection=allocate(pairs)
    dataset={'version':VERSION,'artifacts':artifacts,'pairs':pairs,'schedule':schedule,'allocation':selection,
        'display_policy':{'visuals':'Unaltered archived world map; first two requested characters, first idle-down frame each, fixed framing. No synthetic replacement, retouching or model calls.',
            'structure':'Every authored room in source order; home_base membership by exact casefolded name; count all scene_components, display first component label. Boxes are containment groups, NOT physical maps or walking routes.',
            'scene':'Short shared English summaries of the original requests, identical for both sides; the original requests are retained in this private file.'}}
    dump(destination/'dataset.json',dataset);dump(destination/'SOURCE_MANIFEST.json',manifest)
    print('Frozen:',len(artifacts),'artifacts;',len(pairs),'pairs;',len(schedule),'packets;',len(manifest),'source files.')


if __name__=='__main__':main()
