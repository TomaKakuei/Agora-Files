#!/usr/bin/env python3
"""Render the September 19 paper figures from frozen data and existing assets.

No model calls or newly generated visual evidence. All plots use the recorded
values; the revision changes composition, typography, and explanatory labels.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle

from make_generation_figures import WORLD_CASES, WORLD_FIGURE_AGENTS
import make_social_figures as supplement

ROOT = Path(__file__).resolve().parent / "input_snapshot"
TEAL, AMBER, INK = "#176B70", "#C17A42", "#23363F"
MUTED, PALE, GRID = "#657780", "#F0F5F4", "#DEE6E6"
CORAL, BLUE = "#B25C52", "#627EA1"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 7.5,
    "axes.titlesize": 8.5, "axes.labelsize": 7.2,
    "xtick.labelsize": 7, "ytick.labelsize": 7,
    "text.color": INK, "axes.labelcolor": INK,
    "xtick.color": MUTED, "ytick.color": MUTED,
    "pdf.fonttype": 42, "ps.fonttype": 42,
    "savefig.facecolor": "white", "figure.facecolor": "white",
})


def data(name):
    return json.loads((ROOT / "docs" / name).read_text())


def save(fig, out, name):
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / f"{name}.pdf", bbox_inches="tight", pad_inches=0.03)
    fig.savefig(out / f"{name}.png", dpi=240, bbox_inches="tight", pad_inches=0.03)
    plt.close(fig)


def clean(ax, axis="x"):
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(GRID)
    ax.tick_params(length=2, color=GRID)
    ax.set_axisbelow(True)
    ax.grid(axis=axis, color=GRID, linewidth=0.5)


def heading(ax, text):
    ax.set_title(text, loc="left", fontweight="bold", pad=9)


def arrow(ax, start, end, color=MUTED, connectionstyle="arc3,rad=0"):
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>",
        mutation_scale=9, linewidth=1.1, color=color,
        connectionstyle=connectionstyle))


def box(ax, x, y, w, h, title, body, color=TEAL, fontsize=7.2):
    patch = FancyBboxPatch((x, y), w, h,
        boxstyle="round,pad=0.006,rounding_size=0.012",
        linewidth=0.8, edgecolor=GRID, facecolor=PALE)
    ax.add_patch(patch)
    ax.plot([x + .015, x + .06], [y+h-.035, y+h-.035], color=color, lw=2.2)
    title_text = ax.text(x+.015, y+h-.075, title, va="top", fontsize=8.2,
                        color=color, weight="bold", linespacing=1.1)
    line_step = 12.5 / (ax.figure.get_figheight() * 72 * ax.get_position().height)
    body_y = y+h-.075-line_step*(title.count("\n")+1)
    body_text = ax.text(x+.015, body_y, body, va="top", fontsize=fontsize,
                       linespacing=1.35)
    ax._box_checks = getattr(ax, "_box_checks", []) + [(patch, title_text, body_text)]


def check_boxes(fig, ax):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for patch, title, body in getattr(ax, "_box_checks", []):
        bounds = patch.get_window_extent(renderer)
        for artist in [title, body]:
            b = artist.get_window_extent(renderer)
            assert bounds.x0 <= b.x0 and bounds.x1 >= b.x1, artist.get_text()
            assert bounds.y0 <= b.y0 and bounds.y1 >= b.y1, artist.get_text()
        assert title.get_window_extent(renderer).y0 > body.get_window_extent(renderer).y1, title.get_text()


def overview(out):
    fig, ax = plt.subplots(figsize=(7.15, 1.9))
    fig.subplots_adjust(left=.006, right=.994, bottom=.025, top=.98)
    ax.set(xlim=(0,1), ylim=(0,1)); ax.axis("off")
    cards = [
        (.008, .17, "01  Premise", "A floating embassy\ntrades endangered\nlanguages as\npolitical assets.", AMBER),
        (.217, .228, "02  Generate", "Institutions, roles, items\nRooms and geometry\nKnowledge and actions\nShared visual direction", TEAL),
        (.485, .232, "03  Shared world", "Stable entity identities\nAssets linked to entities\nLocations and ownership\nMutable social state", TEAL),
        (.758, .233, "04  Act together", "Human or agent intention\nCoordinator decision\nCommitted consequences\nInspectable event history", TEAL),
    ]
    for x,w,title,body,color in cards:
        box(ax,x,.27,w,.68,title,body,color)
    for start,end in [(.182,.212),(.450,.480),(.722,.752)]:
        arrow(ax,(start,.61),(end,.61))
    ax.plot([.255,.255,.674,.674],[.26,.17,.17,.26],color=AMBER,lw=1)
    arrow(ax,(.46,.17),(.26,.17),AMBER)
    ax.text(.464,.07,"Validate dependencies; repair affected content",ha="center",fontsize=7,color=AMBER)
    ax.text(.87,.105,"State feeds the next observation",ha="center",fontsize=6.9,color=MUTED)
    check_boxes(fig,ax)
    save(fig,out,"generation_overview")


def gallery(out):
    fig = plt.figure(figsize=(7.15, 1.72))
    short = ["Clockwork", "Aurora Court", "Mycelium Bazaar", "Sunken Monastery", "Tidal Embassy"]
    tags = ["Presses · sabotage", "Route rights · authority", "Strains · patents", "Packets · bandwidth", "Language · treaties"]
    for i, ((letter, _, revision), name, tag) in enumerate(zip(WORLD_CASES,short,tags)):
        x=.005+i*.201
        ax=fig.add_axes([x,.22,.184,.65])
        p=ROOT/"frontend/assets/generated/world_asset_sets"/revision/"world_map_source.png"
        ax.imshow(plt.imread(p));ax.axis("off")
        fig.text(x,.955,f"{letter}  {name}",fontsize=6.8,weight="bold",va="top")
        fig.text(x,.10,tag,fontsize=6.4,color=MUTED)
        agent,_=WORLD_FIGURE_AGENTS[revision]
        sheet=plt.imread(ROOT/"frontend/assets/generated"/agent/revision/"raw_character_128.png")
        h,w=sheet.shape[0]//4,sheet.shape[1]//4
        spr=fig.add_axes([x+.137,.225,.045,.26])
        spr.imshow(sheet[:h,:w],interpolation="nearest")
        spr.set_facecolor("white");spr.set_xticks([]);spr.set_yticks([])
        for spine in spr.spines.values():spine.set_color("white");spine.set_linewidth(1.1)
    save(fig,out,"generated_worlds")


def action_cycle(out):
    fig,ax=plt.subplots(figsize=(7.15,1.65))
    fig.subplots_adjust(left=.006,right=.994,bottom=.02,top=.98)
    ax.set(xlim=(0,1),ylim=(0,1));ax.axis("off")
    cards=[(.01,"Observe","Nearby actors and objects\nAccessible knowledge\nSelected social history"),
           (.265,"Form an intention","Visible world action\nor an open proposal\nTarget and requested effects"),
           (.52,"Adjudicate","Ownership and resources\nCo-presence and consent\nApprove / revise / reject"),
           (.775,"Record the outcome","Approved state changes\nDecision and explanation\nHistory for the next step")]
    for x,title,body in cards:box(ax,x,.31,.212,.65,title,body,fontsize=7.0)
    for x in [.227,.482,.737]:arrow(ax,(x,.65),(x+.031,.65))
    ax.plot([.879,.879,.11,.11],[.29,.16,.16,.29],color=AMBER,lw=1)
    arrow(ax,(.11,.16),(.11,.30),AMBER)
    ax.text(.50,.055,"Persistent state and recorded attempts shape later observations",ha="center",fontsize=7.1,color=AMBER)
    check_boxes(fig,ax);save(fig,out,"situated_action_cycle")


def quality(out):
    d=data("benchmark_20260724/paper_evidence_summary_20260729.json")
    fig=plt.figure(figsize=(7.15,4.65))
    gs=fig.add_gridspec(2,2,left=.17,right=.985,bottom=.105,top=.91,wspace=.74,hspace=.68)
    ax=fig.add_subplot(gs[0,0]);rows=d['paired_worlds']
    names=["Cartographer","Gravity archive","Intertidal embassy","Night market","Future debts","Aurora","Clockwork","Mycelium","Sunken","Tidal"]
    name_map={
        'Cartographer Lung Exchange':'Cartographer','Archive of Borrowed Gravity':'Gravity archive',
        'Intertidal Embassy for Extinct Rivers':'Intertidal embassy','Night Market of Unfinished Weather':'Night market',
        'Museum of Future Debts':'Future debts','Aurora Court of Migrating Cities':'Aurora',
        'Clockwork Rain Conservatory':'Clockwork','Mycelium Patent Bazaar':'Mycelium',
        'Sunken Satellite Monastery':'Sunken','Tidal Embassy of Lost Languages':'Tidal'}
    cols=['specialist_first_pass_success','monolithic_first_pass_success','specialist_eventual_success','monolithic_eventual_success']
    for i,row in enumerate(rows):
        for j,key in enumerate(cols):
            color=TEAL if j%2==0 else AMBER
            yes=row[key]
            ax.add_patch(Rectangle((j-.36,i-.36),.72,.72,facecolor=color if yes else 'white',edgecolor=color,lw=.8))
            if not yes:ax.text(j,i,'×',ha='center',va='center',color=color,fontsize=7)
    ax.set(xlim=(-.5,3.5),ylim=(9.5,-.5))
    ax.set_yticks(range(10),[name_map[r['world_name']] for r in rows],fontsize=6.8)
    ax.set_xticks(range(4),['C','S','C','S']);ax.xaxis.tick_top();ax.tick_params(length=0,pad=4)
    ax.text(.25,1.14,'First pass',transform=ax.transAxes,ha='center',fontsize=7)
    ax.text(.75,1.14,'Eventual',transform=ax.transAxes,ha='center',fontsize=7)
    ax.axhline(4.5,color=MUTED,lw=.6,ls=':')
    for s in ax.spines.values():s.set_visible(False)
    ax.text(0,-.12,'C: compositional    S: single-pass',transform=ax.transAxes,fontsize=6.6,color=MUTED)
    ax.set_title('A  Paired completion',loc='left',weight='bold',y=1.25,pad=1)

    ax=fig.add_subplot(gs[0,1]);x=np.array([0,1]);w=.28
    for k,(method,col,label) in enumerate([('specialist',TEAL,'Compositional'),('monolithic',AMBER,'Single-pass')]):
        vals=[]
        for split in ['primary','heldout']:
            vals.append(next(r['mean_total_tokens_per_trial']/1000 for r in d['cost_by_split'][split] if r['treatment']==method))
        bars=ax.bar(x+(k-.5)*w,vals,w,color=col,label=label)
        for b,val in zip(bars,vals):ax.text(b.get_x()+w/2,val+2,f'{val:.1f}',ha='center',fontsize=7)
    ax.set_xticks(x,['Primary','Held-out']);ax.set_ylim(0,96);ax.set_ylabel('Mean tokens / trial (thousands)')
    ax.legend(frameon=False,fontsize=6.8,loc='upper left',bbox_to_anchor=(-.13,1.14),ncol=1)
    ax.set_title('B  Generation cost',loc='left',weight='bold',y=1.25,pad=1);clean(ax,'y')

    ax=fig.add_subplot(gs[1,0]);metrics=[('wardrobe_canon_term_coverage','Wardrobe terms'),('merchant_inventory_pass_rate','Inventory valid'),('premise_items_recall','Premise items'),('room_visual_canon_adherence','Room canon'),('role_unique_rate','Role uniqueness'),('premise_agents_recall','Premise agents')]
    for i,(key,label) in enumerate(metrics):
        vals=[100*(r['specialist'][key]-r['monolithic'][key]) for r in d['quality_worlds']]
        ax.scatter(vals,i+np.linspace(-.17,.17,len(vals)),s=10,c='#B8C6CA',zorder=2)
        m=100*(d['quality_combined_10_worlds'][key]['decomposed_mean']-d['quality_combined_10_worlds'][key]['monolithic_mean'])
        ax.scatter([m],[i],marker='D',s=30,color=TEAL if m>=0 else AMBER,zorder=3)
    ax.axvline(0,color=MUTED,lw=.7);ax.set_yticks(range(6),[m[1] for m in metrics],fontsize=6.8)
    ax.set_ylim(5.5,-.5);ax.set_xlim(-83,61);ax.set_xticks([-75,-50,-25,0,25,50]);ax.set_xlabel('Compositional − single-pass (pp)',fontsize=6.7)
    heading(ax,'C  Quality proxies');clean(ax)
    ax.text(.0,-.30,'Dots: worlds   Diamonds: means',transform=ax.transAxes,fontsize=6.5,color=MUTED)

    ax=fig.add_subplot(gs[1,1]);keys=['call_ratio','token_ratio','provider_time_ratio']
    for row in d['localized_repair_worlds']:
        v=[100*row[k] for k in keys];ax.plot(range(3),v,color='#C4CFD1',lw=.75,zorder=1)
        ax.scatter(range(3),v,color=TEAL,s=13,zorder=2)
    means=[100*np.mean([r[k] for r in d['localized_repair_worlds']]) for k in keys]
    ax.scatter(range(3),means,color=AMBER,marker='D',s=33,zorder=3)
    for i,v in enumerate(means):ax.annotate(f'{v:.0f}%',(i,v),xytext=(7,-2),textcoords='offset points',fontsize=7,color=AMBER)
    ax.axhline(100,color=MUTED,lw=.8,ls='--');ax.set_xticks(range(3),['Calls','Tokens','Time']);ax.set_ylim(35,135);ax.set_xlim(-.35,2.5)
    ax.set_ylabel('Local repair / reference (%)');heading(ax,'D  Local repair (5 cases)');clean(ax,'y')
    save(fig,out,'world_quality_results')


def interactions(out):
    runs=data('world_interaction_experiment_20260803/multiworld_metrics.json')['runs']
    names=['Aurora','Clockwork','Mycelium','Sunken','Tidal'];y=np.arange(5)
    fig,axes=plt.subplots(1,3,figsize=(7.15,2.15))
    fig.subplots_adjust(left=.085,right=.985,bottom=.20,top=.74,wspace=.50)
    a=axes[0];open_=np.array([r['open_proposal_events'] for r in runs]);world=np.array([r['world_action_events'] for r in runs]);other=np.array([r['events'] for r in runs])-open_-world
    for val,left,col,label in [(other,0,'#BAC6C9','Other route'),(world,other,TEAL,'World route'),(open_,other+world,AMBER,'Open proposal')]:a.barh(y,val,left=left,color=col,height=.62,label=label)
    a.set_yticks(y,names);a.invert_yaxis();a.set_xticks([0,4,8,12]);a.set_xlabel('Events');a.set_xlim(0,13)
    a.legend(frameon=False,fontsize=6,loc='lower left',bbox_to_anchor=(-.02,1.0),ncol=1,handlelength=1.2,labelspacing=.15)
    a.set_title('A  Action pathways',loc='left',weight='bold',y=1.32)
    a=axes[1];a.barh(y-.16,[r['unique_dyads'] for r in runs],height=.28,color=TEAL,label='Unique dyads');a.barh(y+.16,[r['human_interaction_events'] for r in runs],height=.28,color=AMBER,label='Human-targeted')
    a.set_yticks(y,[]);a.invert_yaxis();a.set_xticks([0,3,6,9]);a.set_xlim(0,10);a.set_xlabel('Count')
    a.legend(frameon=False,fontsize=6,loc='lower left',bbox_to_anchor=(-.02,1.0),handlelength=1.2,labelspacing=.15)
    a.set_title('B  Social reach',loc='left',weight='bold',y=1.32)
    a=axes[2];left=np.zeros(5)
    for key,col,label in [('trust',TEAL,'Trust'),('affection',AMBER,'Affection'),('influence_fear',CORAL,'Influence/fear')]:
        v=np.array([r['relationship_delta_totals'][key] for r in runs]);a.barh(y,v,left=left,color=col,height=.62,label=label);left+=v
    a.set_yticks(y,[]);a.invert_yaxis();a.set_xlabel('Sum of simulated deltas');a.set_xticks([0,60,120]);a.set_xlim(0,155)
    a.legend(frameon=False,fontsize=6,loc='lower left',bbox_to_anchor=(-.02,1.0),handlelength=1.2,labelspacing=.15)
    a.set_title('C  State change',loc='left',weight='bold',y=1.32)
    for ax in axes:clean(ax)
    save(fig,out,'multiworld_interactions')


def pilot(out):
    runs=data('world_interaction_experiment_20260803/pilot_metrics.json')['runs']
    fig,axes=plt.subplots(1,2,figsize=(7.15,2.05))
    fig.subplots_adjust(left=.09,right=.985,bottom=.23,top=.82,wspace=.34)
    for run,name,col,style in zip(runs,['Guild','Black market','Storm cruise'],[TEAL,AMBER,BLUE],['-','--',':']):
        d=run['round_dynamics'];x=[r['round'] for r in d]
        for ax,key in zip(axes,['cumulative_unique_dyads','largest_component']):
            ax.plot(x,[r[key] for r in d],label=name,color=col,lw=1.7,ls=style)
    for ax in axes:clean(ax,'both');ax.set_xlabel('Round');ax.set_xticks([1,5,10,15,20,25]);ax.set_xlim(1,25)
    heading(axes[0],'A  Partner diversity keeps growing');axes[0].set_ylabel('Cumulative unique dyads');axes[0].set_ylim(0,310)
    heading(axes[1],'B  Components remain local');axes[1].set_ylabel('IDs in largest component');axes[1].set_ylim(0,15)
    axes[1].legend(frameon=False,fontsize=6.8,loc='lower right')
    save(fig,out,'pilot_social_dynamics')


def episode(out):
    records=data('world_interaction_experiment_20260803/clockwork_open_audit.json')['events']
    totals={k:sum(v.get(k,0) for e in records for v in e['relationship_adjustments'])
            for k in ['trust_delta','affection_delta','influence_fear_delta']}
    fig,ax=plt.subplots(figsize=(7.15,1.85))
    fig.subplots_adjust(left=.006,right=.994,bottom=.02,top=.98)
    ax.set(xlim=(0,1),ylim=(0,1));ax.axis('off')
    box(ax,.008,.24,.302,.71,'Round 1 · 3 proposals',
        'Marius confronts Valerius\nSeraphina asks about etching\nValerius probes authenticity')
    box(ax,.355,.24,.302,.71,'Round 2 · 4 proposals',
        'Sabotage confrontation\nFolio inspection and inquiry\nLyra discusses market impact')
    box(ax,.702,.24,.287,.71,'Open-proposal effects',
        f"Trust {totals['trust_delta']:+d}\nAffection {totals['affection_delta']:+d}\nInfluence/fear {totals['influence_fear_delta']:+d}",AMBER)
    arrow(ax,(.315,.59),(.349,.59));arrow(ax,(.662,.59),(.696,.59))
    ax.text(.5,.085,'Subset totals above; the full 12-event run has +3 trust and +21 influence/fear.',
            ha='center',fontsize=7,color=MUTED)
    check_boxes(fig,ax);save(fig,out,'clockwork_social_episode')


def runtime(out):
    root=ROOT/'runtime_captures'
    interaction=plt.imread(root/'interaction.png')
    context=plt.imread(root/'world_context.png')
    atlas=plt.imread(ROOT/'frontend/assets/generated/tidal_embassy_of_lost_languages_main_01/creator_20260805_character_v8_final/character_atlas.png')
    fig,axes=plt.subplots(1,3,figsize=(7.15,2.35),gridspec_kw={'width_ratios':[1,3.5,1.6]})
    fig.subplots_adjust(left=.005,right=.99,bottom=.03,top=.88,wspace=.15)
    for ax,im,title in zip(axes,[interaction[120:445,450:680],context,atlas],
                          ['A  Selected agent','B  Agents in the rendered world','C  Directional atlas']):
        ax.imshow(im,interpolation='nearest');ax.axis('off')
        ax.set_title(title,loc='left',fontsize=7.5,weight='bold',pad=6)
    save(fig,out,'embodied_character_interaction')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root',type=Path,default=Path(__file__).resolve().parent.parent/'reproduced_figures')
    args=parser.parse_args();out=args.output_root;out.mkdir(parents=True,exist_ok=True)
    for f in [overview,gallery,action_cycle,quality,interactions,pilot,episode,runtime]:f(out)
    # Retain the original composition of evidence-heavy appendix figures.
    supplement.OUT=out
    for f in [supplement.tidal_artifact_gallery,supplement.tidal_repair_trace,supplement.experiment_design]:f()
    print('Rendered 11 figure pairs from frozen inputs.')


if __name__=='__main__':main()
