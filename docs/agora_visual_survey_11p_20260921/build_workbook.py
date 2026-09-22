#!/usr/bin/env python3
"""Blank English workbook: 11 people, 66 rounds, three choices per round."""
import json
from pathlib import Path
from collections import Counter
import xlsxwriter

HERE=Path(__file__).resolve().parent
LABELS={
 'gemini_2_5_flash':'Gemini 2.5 Flash','gemini_3_1_flash_lite':'Gemini 3.1 Flash Lite',
 'gemini_3_1_pro_preview':'Gemini 3.1 Pro Preview','gemini_3_5_flash_lite':'Gemini 3.5 Flash Lite',
 'gemini_3_7_flash':'Gemini 3.7 Flash','gpt_5_6_sol':'GPT-5.6 Sol','gpt_5_6_terra':'GPT-5.6 Terra',
 'agora_compositional':'Full Agora','single_pass':'Single-pass baseline'}
QUESTIONS={
 'images':['Explore preference','Map readability','Character-world fit'],
 'structure':['Explore preference','World clarity','Place-scene fit']}


def main():
    d=json.loads((HERE/'researcher_only/dataset.json').read_text())
    w=xlsxwriter.Workbook(HERE/'Results_Entry.xlsx');w.set_calc_mode('auto')
    w.set_properties({'title':'Visual world survey - results entry','author':'Research team','comments':'Blank template. No human responses.'})
    basic={'font_name':'Arial','font_size':10,'valign':'vcenter','text_wrap':True,'border':1,'border_color':'#D6E2E9'}
    fixed=w.add_format({**basic,'bg_color':'#F0F4F7'})
    inp=w.add_format({**basic,'bg_color':'#EAF5FF','font_color':'#195B97','locked':False})
    calc=w.add_format({**basic,'bg_color':'#EDF6F3'})
    pct=w.add_format({**basic,'bg_color':'#EDF6F3','num_format':'0.0%'})
    head=w.add_format({**basic,'bg_color':'#087F83','font_color':'white','bold':True})
    title=w.add_format({'font_name':'Arial','font_size':20,'font_color':'#20334A','bold':True})
    note=w.add_format({'font_name':'Arial','font_size':10,'text_wrap':True,'valign':'vcenter','font_color':'#52677A'})
    sheets={name:w.add_worksheet(name) for name in ['Start here','Participants','Responses','Image results','Structure results','Key']}
    for s in sheets.values():s.hide_gridlines(2);s.set_default_row(29);s.set_tab_color('#087F83')
    def top(s,t,n,headers):
        s.merge_range(0,0,0,len(headers)-1,t,title);s.set_row(0,36)
        s.merge_range(1,0,3,len(headers)-1,n,note)
        for c,h in enumerate(headers):s.write(5,c,h,head)
        s.set_row(5,40);s.set_column(0,len(headers)-1,17);s.freeze_panes(6,2)
    def valid(s,r1,r2,c,choices):s.data_validation(r1,c,r2,c,{'validate':'list','source':choices,'error_type':'stop','error_title':'Use a listed choice','error_message':'Copy the actual answer. Leave empty until it is received.'})
    def protect(s):s.protect('',{'autofilter':True,'select_locked_cells':True,'select_unlocked_cells':True,'format_rows':True,'format_columns':True})

    start=sheets['Start here'];start.set_column('A:A',3);start.set_column('B:B',25);start.set_column('C:H',15)
    start.merge_range('B2:H3','Visual survey | Results entry',title)
    instructions=[
        ('1. Send one packet','Give V01-V11 to 11 different adults. Send each person only their own fillable PDF or Word file. Do not distribute this workbook: it contains identities.'),
        ('2. Register returns','Fill the blue cells on Participants from the actual cover-page answers. No names or contact details are needed.'),
        ('3. Enter 18 choices','On Responses, enter A, B, Same, or Not sure for each of the three questions in each round. Round and PDF page are already fixed.'),
        ('What Q1-Q3 mean','Images: Q1 explore preference, Q2 map readability, Q3 character-world fit. Structure: Q1 explore preference, Q2 world clarity, Q3 place-scene fit. Results stay separate.'),
        ('Automatic inclusion','Returned + adult + English + consent must be Yes, prior exposure must be No, and all 18 choices must be valid. The status shows missing or excluded packets.'),
        ('Automatic decoding','The workbook knows what A/B means on each page. Preference for Source 1 = 1; Same = 0.5; Source 2 = 0. Not sure is missing preference, counted separately.'),
        ('What is covered','Images: 7 models on one shared scene, 21 pairs, 44 ratings; each pair has 2 or 4 raters. Structure: 10 matched requests, 22 ratings, each pair has 2 or 4 raters.'),
        ('What the pictures show','Archived maps and the first two requested character samples. Structure diagrams show authored places, assigned residents and props; they are not walking maps. No baseline artwork has been invented.'),
        ('Interpretation','Eleven people provide exploratory judgments on these fixed artifacts. Do not call this a stable model ranking. Structure comparisons use the recorded unequal generation budgets.'),
        ('Reading the summaries','Image results show each exact model pair and each question. Structure results also show an equal-request mean only when all 10 requests have judgeable votes. No p-values or Elo are produced.'),
        ('Keep versions separate','This is the English visual V01-V11 version. Do not mix it with the rejected text-only Q01-Q11 survey or the earlier HTML S/P codes.'),
        ('Saving','Only blue cells are editable; protection prevents mistakes, not disclosure. Save your completed workbook outside the public release folder. No human results are included in this template.'),
    ]
    for row,(a,b) in enumerate(instructions,5):start.write(row,1,a,head);start.merge_range(row,2,row,7,b,note);start.set_row(row,63)
    start.merge_range('B19:H19',d['version']+' | Researcher copy | No macros or external links',note);protect(start)
    reg=sheets['Participants'];top(reg,'Participants | V01-V11','Copy the cover-page choices into blue cells. A missing response is not a No. Every code is used by one person only.', ['Code','Returned','Adult','English','Consent','Prior exposure','Valid choices / 18','Analysis status'])
    reg.set_column('A:A',10);reg.set_column('H:H',30)
    entry=sheets['Responses'];headers=['Code','Round','PDF page','Page type','Q1: Explore','Q2: Clarity','Q3: Fit','Valid / 3','Analysis status','Kind','Pair','A identity','B identity','Source 1','Source 2','Q1 score','Q2 score','Q3 score']
    top(entry,'Responses | Copy choices, no numerical codes','Q1: explore preference. Images Q2/Q3: map readability / character-world fit. Structure Q2/Q3: world clarity / place-scene fit. Use A, B, Same, or Not sure. Empty cells are unentered.',headers[:9])
    for col in range(9,len(headers)):entry.write(5,col,headers[col],head)
    entry.set_column('A:C',10);entry.set_column('D:G',20);entry.set_column('I:I',30);entry.set_column(9,17,22,None,{'hidden':True})
    all_rows=[]
    for pi,(code,tasks) in enumerate(d['schedule'].items()):
        rr=6+pi;er=rr+1;reg.write(rr,0,code,fixed)
        for col in range(1,6):reg.write_blank(rr,col,None,inp)
        first=7+6*pi;last=first+5
        reg.write_formula(rr,6,f'=SUM(Responses!H{first}:H{last})',calc,0)
        formula=(f'=IF(B{er}<>"Yes","Not returned",IF(OR(C{er}="No",D{er}="No",E{er}="No"),"Exclude: eligibility/consent",'
                 f'IF(OR(C{er}<>"Yes",D{er}<>"Yes",E{er}<>"Yes",F{er}=""),"Check cover answers",'
                 f'IF(F{er}<>"No","Exclude: prior exposure",IF(G{er}<>18,"Incomplete choices","Include")))))')
        reg.write_formula(rr,7,formula,calc,'Not returned')
        for ti,t in enumerate(tasks):
            row=6+pi*6+ti;r=row+1;pair=d['pairs'][t['pair_id']];kind=pair['kind']
            a=d['artifacts'][t['left']]['condition'];b=d['artifacts'][t['right']]['condition'];c1,c2=sorted([a,b])
            for col,v in enumerate([code,ti+1,ti+2,'Images' if kind=='images' else 'Structure']):entry.write(row,col,v,fixed)
            for col in range(4,7):entry.write_blank(row,col,None,inp)
            entry.write_formula(row,7,'=SUM('+','.join(f'COUNTIF(E{r}:G{r},"{value}")' for value in ['A','B','Same','Not sure'])+')',calc,0)
            entry.write_formula(row,8,f'=Participants!H{er}',calc,'Not returned')
            for col,v in enumerate([kind,t['pair_id'],LABELS[a],LABELS[b],LABELS[c1],LABELS[c2]],9):entry.write(row,col,v,fixed)
            for col,raw in zip([15,16,17],'EFG'):
                formula=(f'=IF(I{r}<>"Include","",IF({raw}{r}="Not sure","",IF({raw}{r}="Same",0.5,'
                         f'IF(OR(AND({raw}{r}="A",L{r}=N{r}),AND({raw}{r}="B",M{r}=N{r})),1,0))))')
                entry.write_formula(row,col,formula,calc,'')
            all_rows.append({'code':code,'round':ti+1,'row':r,'pair':t['pair_id'],'kind':kind,'a':a,'b':b})
    for c in [1,2,3,4]:valid(reg,6,16,c,['Yes','No'])
    valid(reg,6,16,5,['No','Yes','Not sure'])
    for c in [4,5,6]:valid(entry,6,71,c,['A','B','Same','Not sure'])
    reg.autofilter(5,0,16,7);entry.autofilter(5,0,71,8);protect(reg);protect(entry)
    for kind,sheetname in [('images','Image results'),('structure','Structure results')]:
        s=sheets[sheetname]
        top(s,sheetname+' | Source 1 preference','Only included participants are counted. Same is a half vote; Not sure is outside the preference denominator. These are fixed-artifact exploratory judgments, not a general ranking.',
            ['Pair / scene','Source 1','Source 2','Question','Planned','Included','Judgeable','Source 1 wins','Same','Source 2 wins','Not sure','Source 1 preference'])
        s.set_column('A:A',33);s.set_column('B:C',27);s.set_column('D:D',24);s.set_column('E:L',14)
        relevant=sorted((pid,p) for pid,p in d['pairs'].items() if p['kind']==kind)
        for index,(pid,pair) in enumerate(relevant):
            c1,c2=sorted(d['artifacts'][a]['condition'] for a in pair['candidates']);records=[a for a in all_rows if a['pair']==pid]
            for qi,item in enumerate(QUESTIONS[kind]):
                row=6+index*3+qi;r=row+1;score='PQR'[qi]
                label='Promise city' if kind=='images' else pair['source_id'].replace('_',' ').title()
                for col,v in enumerate([label,LABELS[c1],LABELS[c2],item,len(records)]):s.write(row,col,v,fixed)
                def summation(expression):return '='+ '+'.join(expression(x['row']) for x in records)
                s.write_formula(row,5,summation(lambda x:f'IF(Responses!I{x}="Include",1,0)'),calc,0)
                s.write_formula(row,6,summation(lambda x:f'IF(ISNUMBER(Responses!{score}{x}),1,0)'),calc,0)
                for col,value in [(7,1),(8,.5),(9,0)]:
                    s.write_formula(row,col,summation(lambda x:f'IF(AND(ISNUMBER(Responses!{score}{x}),Responses!{score}{x}={value}),1,0)'),calc,0)
                s.write_formula(row,10,f'=F{r}-G{r}',calc,0)
                s.write_formula(row,11,f'=IF(G{r}=0,"",(H{r}+I{r}*0.5)/G{r})',pct,'')
        s.autofilter(5,0,5+len(relevant)*3,11)
        if kind=='structure':
            for qi,item in enumerate(QUESTIONS[kind]):
                row=39+qi;s.merge_range(row,0,row,3,'All 10 requests, equally weighted | '+item,fixed)
                refs=','.join(f'L{7+j*3+qi}' for j in range(10))
                s.write_formula(row,10,f'=COUNT({refs})',calc,0)
                s.write_formula(row,11,f'=IF(COUNT({refs})=10,AVERAGE({refs}),"")',pct,'')
            s.merge_range('A44:L45','The three rows above show covered requests (column K) and a complete 10-request mean (column L). A missing request suppresses that mean. This comparison does not control total generation compute.',note)
        protect(s)
    key=sheets['Key'];top(key,'Private allocation | Do not distribute','The letters A/B vary by page and code. This sheet links all 66 rounds to their recorded sources.', ['Code','Round','Type','A identity','B identity','Pair ID'])
    key.set_column('D:E',29);key.set_column('F:F',24)
    for index,row in enumerate(all_rows,6):
        for col,value in enumerate([row['code'],row['round'],row['kind'],LABELS[row['a']],LABELS[row['b']],row['pair']]):key.write(index,col,value,fixed)
    key.autofilter(5,0,71,5);protect(key);w.close()
    print('Blank English workbook ready: 11 participants, 66 rounds, 198 choice cells.')


if __name__=='__main__':main()
