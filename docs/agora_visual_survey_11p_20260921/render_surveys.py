#!/usr/bin/env python3
"""Render seven-page, English, fillable visual PDFs and editable Word copies.

Run with an interpreter providing ReportLab and Pillow. Archived pictures are
placed on a document canvas, not generated or retouched. Atlas clipping selects
the same recorded 64 x 64 frame for each character.
"""
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile
from xml.sax.saxutils import escape

from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth

HERE=Path(__file__).resolve().parent
W,H=landscape(A4)
INK='#20334A';TEAL='#087F83';MUTED='#566C7E';LINE='#D6E2E9';PALE='#F1F6F8'
QUESTIONS={
 'images':['Which world would you rather explore?','Which map is easier to read?','Which characters fit their world better?'],
 'structure':['Which world would you rather explore?','Which world is easier to understand?','Which places fit the scene better?'],
}


def words(text,width,font='Helvetica',size=10):
    result=[];line=''
    for word in text.split():
        trial=(line+' '+word).strip()
        if line and stringWidth(trial,font,size)>width:result.append(line);line=word
        else:line=trial
    if line:result.append(line)
    return result


def text(c,s,x,y,size=10,bold=False,color=INK):
    c.setFillColor(HexColor(color));c.setFont('Helvetica-Bold' if bold else 'Helvetica',size);c.drawString(x,y,s)


def paragraph(c,s,x,y,width,size=11,leading=16,bold=False,color=INK):
    for line in words(s,width,'Helvetica-Bold' if bold else 'Helvetica',size):
        text(c,line,x,y,size,bold,color);y-=leading
    return y


def frame(c,path,x,y,width,height):
    iw,ih=Image.open(path).size;scale=min(width/iw,height/ih)
    dw,dh=iw*scale,ih*scale
    c.drawImage(str(path),x+(width-dw)/2,y+(height-dh)/2,dw,dh,mask='auto')


def sprite(c,path,x,y,side=48):
    # Exact first idle-down frame from the original atlas: clip at rendering
    # time, preserving the entire frame and all of its transparent padding.
    iw,ih=Image.open(path).size;scale=side/64
    c.saveState();p=c.beginPath();p.rect(x,y,side,side);c.clipPath(p,stroke=0)
    c.drawImage(str(path),x,y-(ih-64)*scale,iw*scale,ih*scale,mask='auto');c.restoreState()


def resident_icon(c,x,y,color=TEAL):
    c.setFillColor(HexColor(color));c.circle(x+3,y+7,2.2,fill=1,stroke=0);c.roundRect(x,y-1,6,6,1,fill=1,stroke=0)


def prop_icon(c,x,y,color=MUTED):
    c.setFillColor(HexColor(color));p=c.beginPath();p.moveTo(x+4,y+9);p.lineTo(x+8,y+5);p.lineTo(x+4,y+1);p.lineTo(x,y+5);p.close();c.drawPath(p,fill=1,stroke=0)


def structure(c,artifact,x,y,width,height):
    rooms=artifact['rooms'];gap=9;cw=(width-gap)/2;rh=62
    # A containment tree, drawn from the source world -> places relationship.
    # No links between rooms or walking routes are invented.
    rail=x+width/2;last_row=(len(rooms)-1)//2
    c.setStrokeColor(HexColor(LINE));c.setLineWidth(1)
    c.line(rail,y+height+1,rail,y+height-(last_row+1)*(rh+gap)+rh/2)
    text(c,'World',rail-13,y+height+7,8,color=MUTED)
    for i,room in enumerate(rooms):
        col=i%2;row=i//2;xx=x+col*(cw+gap);yy=y+height-(row+1)*(rh+gap)
        c.line(rail,yy+rh/2,xx+(cw if col==0 else 0),yy+rh/2)
        c.setFillColor(white);c.setStrokeColor(HexColor(LINE));c.roundRect(xx,yy,cw,rh,5,fill=1,stroke=1)
        title=words(room['name'],cw-16,'Helvetica-Bold',9.4)
        assert len(title)<=2,room['name']
        for j,line in enumerate(title):text(c,line,xx+8,yy+rh-14-j*11,9.4,True)
        label=room['example_prop']
        while label and stringWidth('e.g. '+label,'Helvetica',8)>cw-16:label=label[:-1]
        if label and label!=room['example_prop']:label=label.rstrip()+'...'
        if label:text(c,'e.g. '+label,xx+8,yy+22,8,color=MUTED)
        resident_icon(c,xx+9,yy+5);text(c,str(room['residents'])+' residents',xx+21,yy+6,8.3,color=MUTED)
        prop_icon(c,xx+cw*.57,yy+4);text(c,str(room['props'])+(' prop' if room['props']==1 else ' props'),xx+cw*.57+12,yy+6,8.3,color=MUTED)
    # Source mismatches remain visible; no invented membership or silent fixes.
    if artifact['unassigned_people']:
        text(c,str(artifact['unassigned_people'])+' people have no matching home shown.',x,y-5,8,color=MUTED)


def answer_rows(c,round_index,kind):
    for q,question in enumerate(QUESTIONS[kind],1):
        y=79-(q-1)*23
        text(c,question,32,y,10.5,bold=q==1)
        for xx,label,val in [(526,'A','A'),(580,'B','B'),(634,'Same','Same'),(713,'Not sure','Not sure')]:
            c.acroForm.radio(name=f'R{round_index}_Q{q}',tooltip=question,value=val,selected=False,x=xx,y=y-2,size=11,
                buttonStyle='circle',shape='circle',borderWidth=.8,borderColor=HexColor(MUTED),fillColor=white,textColor=HexColor(TEAL))
            text(c,label,xx+16,y,10)


def footer(c,code,page):text(c,f'{code}  |  {page} / 7',W-96,12,8,color=MUTED)


def cover(c,code):
    text(c,'WORLDS AT A GLANCE',38,H-61,27,True)
    text(c,'A short visual survey',39,H-88,15,color=TEAL)
    c.setFillColor(HexColor(PALE));c.roundRect(W-229,H-107,191,65,8,fill=1,stroke=0)
    text(c,code,W-212,H-70,22,True);text(c,'Your personal survey code',W-212,H-92,10,color=MUTED)
    text(c,'6 comparisons     /     18 quick choices     /     about 10-15 minutes',39,H-128,12,True)
    text(c,'Time is an estimate; take breaks if needed.',39,H-145,9,color=MUTED)
    y=H-184
    for n,s in enumerate([
        'Look at A and B. Some pages show world images; others show world organization.',
        'Choose A, B, Same, or Not sure on each of the three rows.',
        'Same means no preference. Not sure means you cannot judge from the pictures.',
        'Judge only what is shown. More rooms or more detail is not automatically better.'
    ],1):
        text(c,str(n).zfill(2),40,y,12,True,color=TEAL);y=paragraph(c,s,72,y,715,11,16)-11
    y-=1
    c.setFillColor(HexColor(PALE));c.roundRect(38,y-52,W-76,56,6,fill=1,stroke=0)
    text(c,'Reading the structure pages',50,y-13,10,True)
    resident_icon(c,51,y-33);text(c,'people with a home in that place',64,y-31,9)
    prop_icon(c,300,y-34);text(c,'large objects / equipment',314,y-31,9)
    text(c,'Boxes are places, not walking routes.',543,y-31,9)
    y-=76
    for name,label in [('adult','I am 18 or older.'),('english','I can understand these English questions.'),('consent','I have read this page and agree to take part voluntarily.')]:
        c.acroForm.checkbox(name=name,tooltip=label,x=42,y=y-2,size=11,buttonStyle='check',checked=False,borderWidth=.8,borderColor=HexColor(MUTED),fillColor=white,textColor=HexColor(TEAL))
        text(c,label,60,y,10);y-=20
    text(c,'If any of these is not true, please stop.',42,y+2,8.5,color=MUTED);y-=18
    text(c,'Have you worked on this system or seen its detailed results?',42,y,10)
    for xx,label in [(414,'No'),(476,'Yes'),(539,'Not sure')]:
        c.acroForm.radio(name='prior_exposure',tooltip='Prior work or detailed results',value=label,selected=False,x=xx,y=y-2,size=10,borderWidth=.8,borderColor=HexColor(MUTED),fillColor=white,textColor=HexColor(TEAL))
        text(c,label,xx+14,y,9.5)
    y-=28
    paragraph(c,'Your choices are used for research summaries. Do not enter your name. You may stop or withdraw by code through the inviter; withdrawal may not be possible after publication. Ask the inviter about storage, payment, and return arrangements.',42,y,W-84,8.5,12,color=MUTED)
    text(c,'Click circles and save a copy of this PDF, or fill the Word copy / printout. Return only one copy to the inviter.',42,37,9,True)
    footer(c,code,1);c.showPage()


def round_page(c,code,index,task,data):
    pair=data['pairs'][task['pair_id']];kind=pair['kind']
    title='WORLD IMAGES' if kind=='images' else 'WORLD STRUCTURE'
    text(c,f'{index} / 6   {title}',32,H-34,17,True)
    text(c,code,W-66,H-33,11,True,color=TEAL)
    paragraph(c,'Scene: '+pair['scene'],32,H-58,W-64,10.5,13)
    width=(W-84)/2
    for side,label,x in [('left','A',32),('right','B',52+width)]:
        art=data['artifacts'][task[side]]
        text(c,label,x,H-100,19,True,color=TEAL)
        if kind=='images':
            c.setFillColor(HexColor(PALE));c.roundRect(x,169,width,313,5,fill=1,stroke=0)
            frame(c,HERE/art['map'],x+4,174,width-8,303)
            text(c,'Characters',x,144,9,color=MUTED)
            for i,ch in enumerate(art['characters']):sprite(c,HERE/ch['atlas'],x+width/2-58+i*66,109,48)
        else:
            structure(c,art,x,126,width,357)
    if kind=='structure':text(c,'Each box is one place. Icons count its residents and props; one prop label is shown as an example.',32,107,8.5,color=MUTED)
    c.setStrokeColor(HexColor(LINE));c.line(32,96,W-32,96)
    answer_rows(c,index,kind);footer(c,code,index+1);c.showPage()


def make_docx(code,tasks,data,pdf,destination):
    ns='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    rel='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    def p(s,size=22,bold=False,before=False):
        return '<w:p><w:pPr><w:spacing w:after="85"/>'+('<w:pageBreakBefore/>' if before else '')+'</w:pPr><w:r><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial"/><w:sz w:val="'+str(size)+'"/>'+('<w:b/>' if bold else '')+'</w:rPr><w:t xml:space="preserve">'+escape(s)+'</w:t></w:r></w:p>'
    body=[p('WORLDS AT A GLANCE',46,True),p(code+' | A short visual survey',30,True),
        p('6 comparisons / 18 quick choices / about 10-15 minutes (estimate).',24,True),
        p('Look at A and B. Some pages show world images; others show world organization.'),
        p('For each row, replace [choose] with A, B, Same, or Not sure.'),
        p('Same means no preference. Not sure means you cannot judge from the pictures.'),
        p('Judge only what is shown. More rooms or more detail is not automatically better.'),
        p('Structure pages: each box is a place; icons count people and large props. Boxes do not show walking routes.'),
        p('Before you start',26,True),p('[ ] I am 18 or older.'),p('[ ] I can understand these English questions.'),
        p('[ ] I have read this page and agree to take part voluntarily.'),p('If any of these is not true, please stop.'),
        p('Have you worked on this system or seen its detailed results? [ ] No   [ ] Yes   [ ] Not sure'),
        p('Your choices are used for research summaries. Do not enter your name. You may stop or withdraw by code through the inviter; withdrawal may not be possible after publication. Ask the inviter about storage, payment, and return arrangements.',19),
        p('Save this file and return it to the inviter. Fill only one Word / PDF / print copy.',22,True)]
    media=[]
    with tempfile.TemporaryDirectory(prefix='agora_visual_docx_') as temp:
        for i,t in enumerate(tasks,1):
            prefix=Path(temp)/f'page{i}'
            # Render only the original PDF evidence area, excluding its form
            # rows. Word answers remain ordinary editable table cells.
            subprocess.run(['pdftoppm','-f',str(i+1),'-l',str(i+1),'-r','144','-x','0','-y','0','-W','1684','-H','982','-singlefile','-png',str(pdf),str(prefix)],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            media.append(prefix.with_suffix('.png').read_bytes())
            cx=9700000;cy=round(cx*982/1684)
            body.append('<w:p><w:pPr><w:pageBreakBefore/><w:spacing w:after="0"/></w:pPr><w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="'+str(cx)+'" cy="'+str(cy)+'"/><wp:docPr id="'+str(i)+'" name="Visual comparison '+str(i)+'"/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic><pic:nvPicPr><pic:cNvPr id="'+str(i)+'" name="Comparison"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="img'+str(i)+'"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="'+str(cx)+'" cy="'+str(cy)+'"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')
            body.append('<w:tbl><w:tblPr><w:tblW w:w="15000" w:type="dxa"/><w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid><w:gridCol w:w="10500"/><w:gridCol w:w="4500"/></w:tblGrid>')
            for question in QUESTIONS[data['pairs'][t['pair_id']]['kind']]:
                body.append('<w:tr><w:tc><w:tcPr><w:tcW w:w="10500" w:type="dxa"/></w:tcPr>'+p(question,20)+'</w:tc><w:tc><w:tcPr><w:tcW w:w="4500" w:type="dxa"/></w:tcPr>'+p('[choose]',20)+'</w:tc></w:tr>')
            body.append('</w:tbl>'+p('Choices: A / B / Same / Not sure',18))
    body.append('<w:sectPr><w:pgSz w:w="16838" w:h="11906" w:orient="landscape"/><w:pgMar w:top="420" w:right="700" w:bottom="400" w:left="700"/></w:sectPr>')
    document=f'<w:document xmlns:w="{ns}" xmlns:r="{rel}" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><w:body>'+''.join(body)+'</w:body></w:document>'
    types='<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml',types);z.writestr('word/document.xml',document)
        z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="root" Type="'+rel+'/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr('word/_rels/document.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+''.join(f'<Relationship Id="img{i}" Type="{rel}/image" Target="media/visual{i}.png"/>' for i in range(1,7))+'</Relationships>')
        for i,blob in enumerate(media,1):z.writestr(f'word/media/visual{i}.png',blob)


def main():
    data=json.loads((HERE/'researcher_only/dataset.json').read_text());out=HERE/'participants';out.mkdir(exist_ok=True)
    for code,tasks in data['schedule'].items():
        pdf=out/f'Survey_{code}.pdf';c=canvas.Canvas(str(pdf),pagesize=(W,H),pageCompression=1)
        c.setTitle('Worlds at a glance - '+code);c.setAuthor('Research team')
        cover(c,code)
        for i,t in enumerate(tasks,1):round_page(c,code,i,t,data)
        c.save();make_docx(code,tasks,data,pdf,out/f'Survey_{code}.docx')
        print(code,'PDF + Word ready',flush=True)


if __name__=='__main__':main()
