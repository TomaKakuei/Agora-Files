#!/usr/bin/env python3
"""Build 11 blind DOCX/PDF packets and a researcher-only Excel entry workbook.

The source corpus is frozen in the adjacent 2026-09-19 study. No model calls or
human responses are generated. DOCX uses standard OOXML; PDF conversion uses
LibreOffice. Excel generation requires XlsxWriter.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import zipfile
from xml.sax.saxutils import escape

import xlsxwriter

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'agora_comparative_survey_20260919' / 'researcher_only'
VERSION = 'agora-paper-11p-20260921-v1'
SEED = 20260921
QUESTIONS = [
    ('overall', '总体世界设计', '综合所示材料，哪一份世界设计更好？'),
    ('premise', '设定实现', '哪一份更充分地把共同生成要求发展成具体世界？'),
    ('coherence', '规则与活动', '哪一份更清楚地展示规则如何影响活动和冲突？'),
    ('society', '人物与社会联系', '哪一份更清楚地展示不同人物的目标如何相互关联？'),
    ('specificity', '地点与物件', '哪一份的地点和物件更能体现这个世界的独特设定？'),
    ('actions', '可设想的行动', '哪一份更能让你设想会影响世界的具体行动？'),
]
LABELS = {
    'gemini_2_5_flash': 'Gemini 2.5 Flash',
    'gemini_3_1_flash_lite': 'Gemini 3.1 Flash Lite',
    'gemini_3_1_pro_preview': 'Gemini 3.1 Pro Preview',
    'gemini_3_5_flash_lite': 'Gemini 3.5 Flash Lite',
    'gemini_3_7_flash': 'Gemini 3.7 Flash',
    'gpt_5_6_sol': 'GPT-5.6 Sol',
    'gpt_5_6_terra': 'GPT-5.6 Terra',
    'agora_compositional': '完整 Agora',
    'single_pass': '单次生成基线',
}
ARM = {'model': '模型', 'architecture': '架构'}


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def allocate(data, key):
    """Cover all 41 model pairs and all 10 architecture pairs with 11 x 6 tasks."""
    rng = random.Random(SEED)
    model_by_prompt = defaultdict(list)
    architecture = []
    for pid, meta in sorted(key['pairs'].items()):
        if meta['arm'] == 'model':
            model_by_prompt[meta['prompt_id']].append(pid)
        else:
            architecture.append(pid)
    assert sorted(map(len, model_by_prompt.values())) == [10, 10, 21]
    prompts = sorted(model_by_prompt)
    extra_model = {}
    groups = []
    for prompt in prompts:
        base = model_by_prompt[prompt]
        extra_model[prompt] = rng.choice(base)
        group = base + [extra_model[prompt]]
        while True:
            rng.shuffle(group)
            if len(group) == 11 or all(group[i] != group[i + 1] for i in range(0, 22, 2)):
                break
        groups.append(group[:])
    assert [len(g) for g in groups] == [22, 11, 11]
    model_packets = [groups[0][2*i:2*i+2] + [groups[1][i], groups[2][i]] for i in range(11)]

    # All three repeated exact pairs reverse A/B. Singletons balance globally.
    counts = Counter(pid for packet in model_packets for pid in packet)
    orientations = {}
    single = [pid for pid in sorted(counts) if counts[pid] == 1]
    rng.shuffle(single)
    for i, pid in enumerate(single):
        orientations[pid] = [i < len(single) // 2]
    for pid, n in counts.items():
        if n == 2:
            v = [True, False]
            rng.shuffle(v)
            orientations[pid] = v

    # Every participant receives Agora on A once and on B once. Ten requests
    # receive two judgments; one seed-selected request receives two extras.
    extra_arch = rng.choice(architecture)
    a_slots = architecture + [extra_arch]
    b_slots = architecture + [extra_arch]
    rng.shuffle(a_slots)
    while True:
        rng.shuffle(b_slots)
        if all(a != b for a, b in zip(a_slots, b_slots)):
            break

    schedule = {}
    for i in range(11):
        models = []
        for pid in model_packets[i]:
            candidates = sorted(key['pairs'][pid]['candidates'], key=lambda a: key['artifacts'][a]['condition'])
            first_left = orientations[pid].pop()
            models.append(dict(pair_id=pid, left=candidates[0 if first_left else 1], right=candidates[1 if first_left else 0]))
        rng.shuffle(models)
        arch = []
        for pid, agora_left in [(a_slots[i], True), (b_slots[i], False)]:
            candidates = key['pairs'][pid]['candidates']
            agora = next(a for a in candidates if key['artifacts'][a]['condition'] == 'agora_compositional')
            baseline = next(a for a in candidates if key['artifacts'][a]['condition'] == 'single_pass')
            arch.append(dict(pair_id=pid, left=agora if agora_left else baseline, right=baseline if agora_left else agora))
        rng.shuffle(arch)
        pattern = ['model', 'model', 'architecture', 'model', 'model', 'architecture']
        offset = i % 3
        pattern = pattern[offset:] + pattern[:offset]
        schedule[f'Q{i+1:02d}'] = [(models if arm == 'model' else arch).pop(0) for arm in pattern]
    return schedule, dict(seed=SEED, extra_model_pairs_by_prompt=extra_model, extra_architecture_pair=extra_arch)


# Minimal, standards-compliant Word document writer. All evidence strings are
# inserted verbatim; Word and PDF are generated from the same paragraph tree.
NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


def run(text, bold=False, size=21, color='20334A'):
    return (f'<w:r><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="Noto Sans CJK SC"/>'
            f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/><w:color w:val="{color}"/>'
            + ('<w:b/>' if bold else '') + '</w:rPr><w:t xml:space="preserve">' + escape(str(text)) + '</w:t></w:r>')


def para(text='', bold=False, size=21, color='20334A', before=0, after=90, keep=False, center=False, page_before=False):
    return ('<w:p><w:pPr>' + (f'<w:jc w:val="center"/>' if center else '')
            + f'<w:spacing w:before="{before}" w:after="{after}" w:line="265" w:lineRule="auto"/>'
            + ('<w:keepNext/>' if keep else '') + ('<w:pageBreakBefore/>' if page_before else '') + '</w:pPr>' + run(text, bold, size, color) + '</w:p>')


def heading(text):
    return para(text, bold=True, size=23, color='087F83', before=140, after=70, keep=True)


def pagebreak():
    return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'


def table(rows, widths, header=False):
    xml = ['<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/><w:tblLayout w:type="fixed"/>'
           '<w:tblBorders><w:top w:val="single" w:sz="4" w:color="D6E2E9"/>'
           '<w:left w:val="single" w:sz="4" w:color="D6E2E9"/>'
           '<w:bottom w:val="single" w:sz="4" w:color="D6E2E9"/>'
           '<w:right w:val="single" w:sz="4" w:color="D6E2E9"/>'
           '<w:insideH w:val="single" w:sz="4" w:color="D6E2E9"/>'
           '<w:insideV w:val="single" w:sz="4" w:color="D6E2E9"/></w:tblBorders>'
           '<w:tblCellMar><w:top w:w="100" w:type="dxa"/><w:left w:w="120" w:type="dxa"/>'
           '<w:bottom w:w="100" w:type="dxa"/><w:right w:w="120" w:type="dxa"/></w:tblCellMar>'
           '</w:tblPr><w:tblGrid>' + ''.join(f'<w:gridCol w:w="{w}"/>' for w in widths) + '</w:tblGrid>']
    for i, row in enumerate(rows):
        xml.append('<w:tr><w:trPr><w:cantSplit/>' + ('<w:tblHeader/>' if header and i == 0 else '') + '</w:trPr>')
        for j, contents in enumerate(row):
            shade = 'EAF4F4' if header and i == 0 else 'FFFFFF'
            xml.append(f'<w:tc><w:tcPr><w:tcW w:w="{widths[j]}" w:type="dxa"/><w:shd w:fill="{shade}"/><w:vAlign w:val="top"/></w:tcPr>' + contents + '</w:tc>')
        xml.append('</w:tr>')
    return ''.join(xml) + '</w:tbl>'


def make_docx(path, code, tasks, data):
    body = [para('世界设计比较问卷', bold=True, size=40),
            para(f'{code}  /  独立分发版 · 共 6 场', size=25, color='087F83'),
            para('本编号只分配给一位参与者。无需打开网页，也不需要安装插件。', size=20),
            heading('阅读前，请先了解'),
            para('每场比较同一个生成要求下的设计 A 与设计 B。来源名称隐藏，没有预设赢家。只评价所示书面设计，不评价图像、真实运行效果或游玩体验。'),
            para('材料按统一字段、原始顺序和长度上限摘录；[…] 表示原文还有内容。没有展示的内容，不代表完整世界中不存在。文字更长本身不等于更好。'),
            para('材料保留英文原文。请独立阅读，不要让他人或模型代评。预计约 30–45 分钟，实际时长有待试填确认；可休息或随时停止。'),
            heading('如何填写与交回'),
            para('Word 版：在“答案”空格直接输入数字，在背景选项旁标记 √。PDF 版：打印后填写数字和勾选，拍照或扫描交回。两种格式内容相同，任选一种填写一次即可。'),
            para('每场先读完 A、B 两页，再填写本场评分页。每题填写一个 1–6 的数字；允许相当或无法判断。可选评论可用中文或英文，不填写姓名、邮箱等个人信息。'),
            heading('参与与数据'),
            para('参与自愿。收集编号、背景、评分、可选评论和自报用时，用于学术汇总及去标识化报告。评论引用另行征求同意。文件不会自动上传，请交给邀请人。交回前可自行删除；交回后可凭编号申请撤回，汇总公开后可能无法撤回。'),
            para('邀请人是研究联系渠道；开始前可向其了解答卷接收方式、保存期限、是否有报酬及其他研究安排。不要在本文件填写身份信息。', size=19),
            heading('必填确认（任一项不符合，请停止填写）'),
            para('已年满 18 岁：□ 是  □ 否     能独立读懂英文材料：□ 是  □ 否', size=20),
            para('已阅读说明并自愿同意参与：□ 是  □ 否', size=20),
            para('是否参与过本系统开发或看过其详细结果：□ 没有  □ 有  □ 不确定', size=20),
            para('文字冒险／角色扮演游戏经验（可选）：□ 没有  □ 偶尔  □ 经常  □ 不回答', size=20)]
    for i, task in enumerate(tasks, 1):
        for side, label in [('left', 'A'), ('right', 'B')]:
            body += [para(f'{code}  ·  第 {i} / 6 场  ·  设计 {label}', bold=True, size=31, page_before=True),
                     heading('共同生成要求'), para(data['pairs'][task['pair_id']]['prompt'], size=20, after=150)]
            sections = data['artifacts'][task[side]]['sections']
            cells = []
            for half in [sections[:4], sections[4:]]:
                content = []
                for section in half:
                    content.append(para(section['zh'], bold=True, size=21, color='087F83', before=70, after=50))
                    for row in section['rows']:
                        content.append(para('• ' + row, size=19, after=45))
                cells.append(''.join(content))
            body.append(table([cells], [5100, 5100]))
            body.append(para('请读完本场 A 与 B 两份材料后再评分。', size=18, color='617486', before=60))
        body += [para(f'{code}  ·  第 {i} / 6 场  ·  评分', bold=True, size=31, page_before=True),
                 para('每题在“答案”栏填写一个数字。不确定时可以选 6；不要留必填题空白。', size=21),
                 table([[para('1  A 明显更好', bold=True), para('2  A 略好', bold=True), para('3  两者相当', bold=True)],
                        [para('4  B 略好', bold=True), para('5  B 明显更好', bold=True), para('6  无法判断', bold=True)]], [3400]*3),
                 para('“相当”表示能判断但无明确偏好；“无法判断”表示材料不足，不能作判断。', size=20, before=160, after=160)]
        rows = [[para('题目', bold=True), para('答案（1–6）', bold=True)]]
        for n, (_, title, question) in enumerate(QUESTIONS, 1):
            rows.append([para(f'{n}. {title}', bold=True, after=50) + para(question, size=21, after=80), para('________', size=24, center=True, before=80)])
        body.append(table(rows, [8200, 2000], header=True))
        body += [heading('可选反馈'),
                 para('两份材料是否都不足以让你形成可信世界的印象？'),
                 para('□ 是    □ 否    □ 无法判断    □ 不回答'),
                 para('哪个具体细节最影响你的判断？（可选）'),
                 para('__________________________________________________________________', after=220),
                 para('__________________________________________________________________', after=220),
                 para('“可设想的行动”只评价书面设计，不推断行动在真实运行中能成功。', size=18, color='617486')]
        if i == len(tasks):
            body += [heading('完成与交回'),
                     para('可选：我同意去除身份信息后引用我的评论。□ 是  □ 否（不勾选视为未同意）', size=20),
                     para('自报阅读与填写用时（不含休息，可选）：________ 分钟', size=20),
                     para(f'请保留编号 {code}，将本份文件／清晰照片交给邀请人。感谢参与。', size=20)]
    sect = ('<w:sectPr><w:footerReference w:type="default" r:id="rIdFooter"/>'
            '<w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="800" w:right="850" w:bottom="850" w:left="850" w:header="300" w:footer="400"/>'
            '</w:sectPr>')
    document = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:body>' + ''.join(body) + sect + '</w:body></w:document>'
    footer = f'<w:ftr xmlns:w="{NS}"><w:p><w:pPr><w:jc w:val="center"/></w:pPr>' + run(f'{code}  ·  世界设计比较问卷  ·  ', size=17, color='617486') + '<w:fldSimple w:instr="PAGE"/></w:p></w:ftr>'
    parts = {
        '[Content_Types].xml': '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/></Types>',
        '_rels/.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        'word/document.xml': document,
        'word/footer1.xml': footer,
        'word/_rels/document.xml.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rIdFooter" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/></Relationships>',
    }
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, content in parts.items():
            z.writestr(name, content.encode('utf-8'))


def create_workbook(path, schedule, key):
    wb = xlsxwriter.Workbook(path)
    wb.set_properties({'title': 'Agora 11 人问卷结果录入', 'author': 'Agora research team', 'comments': 'Blank researcher template. No human results included.'})
    wb.set_calc_mode('auto')
    fmt = {
        'title': wb.add_format({'font_name':'Microsoft YaHei', 'font_size':20, 'bold':True, 'font_color':'#20334A'}),
        'note': wb.add_format({'font_name':'Microsoft YaHei', 'font_size':10, 'text_wrap':True, 'valign':'vcenter', 'font_color':'#52677A'}),
        'header': wb.add_format({'font_name':'Microsoft YaHei', 'bold':True, 'bg_color':'#087F83', 'font_color':'white', 'text_wrap':True, 'valign':'vcenter', 'border':1, 'border_color':'#D6E2E9'}),
        'fixed': wb.add_format({'font_name':'Microsoft YaHei', 'font_size':10, 'bg_color':'#F0F4F7', 'valign':'vcenter', 'text_wrap':True, 'border':1, 'border_color':'#D6E2E9'}),
        'input': wb.add_format({'font_name':'Microsoft YaHei', 'font_size':11, 'bg_color':'#EAF5FF', 'font_color':'#195B97', 'locked':False, 'valign':'vcenter', 'text_wrap':True, 'border':1, 'border_color':'#D6E2E9'}),
        'formula': wb.add_format({'font_name':'Microsoft YaHei', 'font_size':10, 'bg_color':'#EDF6F3', 'text_wrap':True, 'valign':'vcenter', 'border':1, 'border_color':'#D6E2E9'}),
        'percent': wb.add_format({'font_name':'Microsoft YaHei', 'font_size':10, 'bg_color':'#EDF6F3', 'num_format':'0.0%', 'border':1, 'border_color':'#D6E2E9'}),
        'warn': wb.add_format({'bg_color':'#FFF1D6', 'font_color':'#855900'}),
        'good': wb.add_format({'bg_color':'#DDF0E6', 'font_color':'#14653E'}),
    }
    names = ['使用说明','参与者登记','评分录入','架构汇总','模型汇总','逐题汇总','分配与解盲']
    sheets = {name: wb.add_worksheet(name) for name in names}
    for ws in sheets.values():
        ws.hide_gridlines(2)
        ws.set_default_row(28)
        ws.set_tab_color('#087F83')
        ws.set_landscape()
        ws.set_paper(9)
        ws.fit_to_pages(1, 0)
    def top(ws, title, note, headers):
        end = len(headers)-1
        ws.merge_range(0, 0, 0, end, title, fmt['title']); ws.set_row(0, 36)
        ws.merge_range(1, 0, 3, end, note, fmt['note'])
        for col, header in enumerate(headers): ws.write(5, col, header, fmt['header'])
        ws.set_row(5, 42)
        ws.freeze_panes(6, 2)
        ws.repeat_rows(5)
        ws.set_column(0, end, 16)
    def list_validation(ws, first, last, col, values):
        ws.data_validation(first, col, last, col, {'validate':'list', 'source':values, 'error_type':'stop', 'error_title':'请使用列表中的选项', 'error_message':'请按原始答卷录入；不要猜测或代填。', 'input_title':'原样录入', 'input_message':'留空表示尚未录入。'})

    ws = sheets['使用说明']
    ws.set_column('A:A', 4); ws.set_column('B:B', 24); ws.set_column('C:H', 14)
    ws.merge_range('B2:H3', '11 人问卷 · 结果录入工作簿', fmt['title'])
    instructions = [
        ('先分发', 'Q01–Q11 分别给 11 位不同参与者；每人只拿对应的 Word 或 PDF。不要把本 Excel、全部问卷或解盲文件给受试者。'),
        ('再登记', '在“参与者登记”的蓝色单元格填写回收、三个同意/资格确认、既往接触、可选背景。没有真实答卷时保持空白。编号不可重复。'),
        ('录入评分', '在“评分录入”按编号与场次填写 6 个数字。1=A明显；2=A略好；3=相当；4=B略好；5=B明显；6=无法判断。每人 6 场，共 36 项。'),
        ('可选信息', '两份都不足、评论、经验、用时与评论引用同意可留空。未明确同意评论引用时，不引用。请不要在此表写姓名、邮箱或招募联系人。'),
        ('哪些回答纳入', '仅“已回收=是”、年龄/英文/同意均=是、既往接触=没有、36 项评分全部有效的参与者进入汇总。未回收、待补录或被排除的回答均不计入。'),
        ('如何计算', 'A/B 按每份问卷独立解盲。主要终点把明显/略好合并为偏好；胜=1、相当=0.5、负=0。无法判断单独计数，不当作相当、零分或败场。原始 1–6 评分完整保留。'),
        ('怎么看汇总', '架构按 10 个提示等权；模型按该两模型共同具备成品的提示等权。只有全部计划提示都有可判票时显示完整宏平均；缺失覆盖会显示“未完整覆盖”。不要按混合提示总票数排模型名次。'),
        ('样本边界', '11 人共 44 场模型、22 场架构评价。41 个精确模型/提示配对中 38 个只有 1 票、3 个有 2 票；9 个架构请求各 2 票、1 个有 4 票。模型结果为探索性描述，不是稳定排名。'),
        ('六个维度', '“总体世界设计”为主要终点；其余五维为诊断项目。“逐题汇总”保留六维各自的票数和缺失，不将六个维度加总成总分或当作六个独立受试者。'),
        ('材料边界', '英文原始证据，架构比较为实际且不等计算预算的配置。模型仅评价已有成功成品；无成品失败不能自动算成人工偏好败场。此表不含置信区间、p 值、显著性星号或 Elo。'),
        ('Excel 操作', '仅编辑蓝色格。灰色为冻结编号/分配，绿色为自动结果；工作表保护防止误改，不是保密措施。使用 Excel/LibreOffice 的自动计算；若结果未更新，请启用自动计算并重算。'),
        ('保存与回传', '请将填完的工作簿另存到本地独立文件夹。完整答卷和含评论的工作簿仅供研究者处理，不要上传公开 Git；本发布包只包含空白模板，没有真实受试者结果。'),
    ]
    for row, (title, text) in enumerate(instructions, 5):
        ws.write(row,1,title,fmt['header']); ws.merge_range(row,2,row,7,text,fmt['note']); ws.set_row(row,70)
    ws.merge_range('B19:H19', f'版本：{VERSION}  |  预定样本：11 人  |  分配种子：{SEED}',fmt['note'])
    ws.print_area('B2:H19')
    ws.protect('', {'select_locked_cells':True})

    reg = sheets['参与者登记']
    reg_headers = ['编号','已回收','年满18岁','能独立读英文','同意参与','既往开发/结果接触','游戏经验（可选）','同意评论引用（可选）','用时/分钟（可选）','有效评分项 / 36','主要分析状态','录入备注（不写身份）']
    top(reg,'参与者登记 · 11 份，11 位不同参与者','先填蓝色格，再录入评分；请照原答卷填写，不能代填同意。可选项目空白不会影响纳入。',reg_headers)
    reg.set_column('A:A',9); reg.set_column('F:I',19); reg.set_column('K:L',27)
    entry = sheets['评分录入']
    entry_headers = ['编号','场次','PDF材料 / 评分页','总体','设定','规则','人物','地点','行动','两份都不足（可选）','具体细节评论（可选）','有效项/6','主要分析状态','类型','提示ID','A来源','B来源','条件1','条件2','总体条件1得分','无法判断','相当','条件1胜','条件2胜','可判票'] + [q[1]+'条件1得分' for q in QUESTIONS[1:]]
    top(entry,'原始评分录入 · 66 场','只填蓝色格。1=A明显；2=A略好；3=相当；4=B略好；5=B明显；6=无法判断。灰色的编号/场次与对应 PDF、Word 一致；模型和方法映射在右侧隐藏列。',entry_headers[:13])
    for c in range(13,len(entry_headers)):entry.write(5,c,entry_headers[c],fmt['header'])
    entry.set_column('A:B',8);entry.set_column('C:C',22);entry.set_column('D:I',9)
    entry.set_column('J:J',18);entry.set_column('K:K',45);entry.set_column('L:L',10);entry.set_column('M:M',23)
    entry.set_column(13,29,20,None,{'hidden':True})
    all_tasks=[]
    for i,(code,tasks) in enumerate(schedule.items()):
        rr=6+i;excel_reg=rr+1
        reg.write(rr,0,code,fmt['fixed'])
        for c in list(range(1,9))+[11]:reg.write_blank(rr,c,None,fmt['input'])
        start=7+6*i;end=start+5
        reg.write_formula(rr,9,f"=SUM('评分录入'!L{start}:L{end})",fmt['formula'],0)
        state=(f'=IF(B{excel_reg}<>"是","待回收",IF(OR(C{excel_reg}="否",D{excel_reg}="否",E{excel_reg}="否"),"排除：资格/同意",'
               f'IF(OR(C{excel_reg}<>"是",D{excel_reg}<>"是",E{excel_reg}<>"是",F{excel_reg}=""),"待核对：背景",'
               f'IF(F{excel_reg}<>"没有","排除：既往接触",IF(J{excel_reg}<>36,"待补录评分","纳入")))))')
        reg.write_formula(rr,10,state,fmt['formula'],'待回收')
        for j,t in enumerate(tasks):
            r=6+i*6+j;er=r+1
            meta=key['pairs'][t['pair_id']]
            a=key['artifacts'][t['left']]['condition'];b=key['artifacts'][t['right']]['condition']
            c1,c2=sorted([a,b])
            all_tasks.append(dict(code=code,position=j+1,row=er,pair_id=t['pair_id'],arm=meta['arm'],prompt_id=meta['prompt_id'],left=a,right=b,condition_1=c1,condition_2=c2))
            for col,val in enumerate([code,j+1,f'A {2+3*j} / B {3+3*j} / 评分 {4+3*j}']):entry.write(r,col,val,fmt['fixed'])
            for col in range(3,11):entry.write_blank(r,col,None,fmt['input'])
            # Drop-down values can be serialized as text by spreadsheet apps.
            # Accept numeric/text integers 1..6, reject blanks and fractions.
            checks=[]
            for score_column in 'DEFGHI':
                value=f'VALUE({score_column}{er})'
                checks.append(f'IFERROR(IF(AND({value}>=1,{value}<=6,MOD({value},1)=0),1,0),0)')
            entry.write_formula(r,11,'=SUM('+','.join(checks)+')',fmt['formula'],0)
            entry.write_formula(r,12,f"='参与者登记'!K{excel_reg}",fmt['formula'],'待回收')
            for col,val in enumerate([ARM[meta['arm']],meta['prompt_id'],LABELS[a],LABELS[b],LABELS[c1],LABELS[c2]],13):entry.write(r,col,val,fmt['fixed'])
            for q,col in zip(range(6),[19,25,26,27,28,29]):
                source=xlsxwriter.utility.xl_col_to_name(3+q)
                f=(f'=IF(M{er}<>"纳入","",IF(VALUE({source}{er})=6,"",IF(VALUE({source}{er})=3,0.5,'
                   f'IF(OR(AND(VALUE({source}{er})<3,P{er}=R{er}),AND(VALUE({source}{er})>3,Q{er}=R{er})),1,0))))')
                entry.write_formula(r,col,f,fmt['formula'],'')
            for col,expr in [(20,f'AND(M{er}="纳入",IFERROR(VALUE(D{er}),0)=6)'),(21,f'AND(M{er}="纳入",IFERROR(VALUE(D{er}),0)=3)'),(22,f'AND(M{er}="纳入",ISNUMBER(T{er}),T{er}=1)'),(23,f'AND(M{er}="纳入",ISNUMBER(T{er}),T{er}=0)'),(24,f'AND(M{er}="纳入",ISNUMBER(T{er}))')]:
                entry.write_formula(r,col,'=IF('+expr+',1,0)',fmt['formula'],0)
    for c in [1,2,3,4,7]:list_validation(reg,6,16,c,['是','否'])
    list_validation(reg,6,16,5,['没有','有','不确定'])
    list_validation(reg,6,16,6,['没有','偶尔','经常','不回答'])
    reg.data_validation(6,8,16,8,{'validate':'decimal','criteria':'between','minimum':0,'maximum':1440,'error_type':'stop'})
    entry.data_validation(6,3,71,8,{'validate':'list','source':['1','2','3','4','5','6'],'error_type':'stop','input_title':'1–6 编码','input_message':'1=A明显，2=A略好，3=相当，4=B略好，5=B明显，6=无法判断。','error_title':'只接受 1–6','error_message':'空白表示尚未录入；无法判断请录入 6。'})
    list_validation(entry,6,71,9,['是','否','无法判断','不回答'])
    for ws,last,end in [(reg,16,11),(entry,71,12)]:
        ws.autofilter(5,0,last,end)
        ws.protect('',{'autofilter':True,'select_locked_cells':True,'select_unlocked_cells':True})
    reg.conditional_format('K7:K17',{'type':'text','criteria':'containing','value':'纳入','format':fmt['good']})
    reg.conditional_format('K7:K17',{'type':'text','criteria':'containing','value':'排除','format':fmt['warn']})

    # Fixed 51 exact pairs x 6 independent items. No respondent rows are
    # invented, and empty denominators produce blank means, not zero scores.
    per=sheets['逐题汇总']
    headers=['类型','提示ID','条件1','条件2','维度','计划评价数','已纳入评价','可判票','条件1胜','相当','条件2胜','无法判断','条件1偏好值']
    top(per,'逐提示 × 逐维度 · 所有 306 个单元','胜 / 相当 / 负 = 1 / 0.5 / 0；无法判断不进入均值分母。每个项目独立汇总，原始“明显 / 略好”仍保存在评分录入。条件1/2仅用于固定解码，不代表新旧或优劣。',headers)
    per.set_column('B:B',44);per.set_column('C:D',26);per.set_column('E:E',19)
    pair_order=sorted(key['pairs'],key=lambda p:(key['pairs'][p]['arm'],key['pairs'][p]['prompt_id'],p))
    grouped={}
    for p_index,pid in enumerate(pair_order):
        meta=key['pairs'][pid]
        c1,c2=sorted(key['artifacts'][a]['condition'] for a in meta['candidates'])
        ts=[t for t in all_tasks if t['pair_id']==pid]
        grouped[pid]=dict(row=7+p_index*6,meta=meta,conditions=(c1,c2),tasks=ts)
        for qi,(_,item,_) in enumerate(QUESTIONS):
            row=6+p_index*6+qi;er=row+1
            score_col=xlsxwriter.utility.xl_col_to_name([19,25,26,27,28,29][qi])
            raw_col=xlsxwriter.utility.xl_col_to_name(3+qi)
            for c,val in enumerate([ARM[meta['arm']],meta['prompt_id'],LABELS[c1],LABELS[c2],item,len(ts)]):per.write(row,c,val,fmt['fixed'])
            def sums(expr):return '='+ '+'.join(expr(t['row']) for t in ts)
            per.write_formula(row,6,sums(lambda r:f'IF(\'评分录入\'!M{r}="纳入",1,0)'),fmt['formula'],0)
            per.write_formula(row,7,sums(lambda r:f'IF(ISNUMBER(\'评分录入\'!{score_col}{r}),1,0)'),fmt['formula'],0)
            for col,val in [(8,1),(9,.5),(10,0)]:
                per.write_formula(row,col,sums(lambda r:f'IF(AND(ISNUMBER(\'评分录入\'!{score_col}{r}),\'评分录入\'!{score_col}{r}={val}),1,0)'),fmt['formula'],0)
            per.write_formula(row,11,f'=G{er}-H{er}',fmt['formula'],0)
            per.write_formula(row,12,f'=IF(H{er}=0,"",(I{er}+J{er}*0.5)/H{er})',fmt['percent'],'')
    per.autofilter(5,0,311,12);per.protect('',{'autofilter':True,'select_locked_cells':True})

    arch=sheets['架构汇总']
    headers=['共同请求','计划评价','纳入评价','可判票','Agora胜','相当','基线胜','无法判断','Agora偏好值']
    top(arch,'完整 Agora vs 单次生成基线','主要终点：总体世界设计。逐请求显示票数；完整平均对 10 个请求等权。实际生成预算不相等，结果不能解释成同计算预算下的架构因果收益。',headers)
    arch.set_column('A:A',46);arch.set_column('B:I',15)
    arch_rows=[]
    for idx,pid in enumerate(p for p in pair_order if key['pairs'][p]['arm']=='architecture'):
        r=6+idx;e=r+1;source=grouped[pid]['row'];arch_rows.append(e)
        assert grouped[pid]['conditions'][0]=='agora_compositional'
        arch.write(r,0,key['pairs'][pid]['prompt_id'],fmt['fixed'])
        for c,sc in enumerate(['F','G','H','I','J','K','L'],1):arch.write_formula(r,c,f"='逐题汇总'!{sc}{source}",fmt['formula'],0)
        arch.write_formula(r,8,f'=IF(D{e}=0,"",(E{e}+F{e}*0.5)/D{e})',fmt['percent'],'')
    arch.write(18,0,'完整 10 请求等权平均',fmt['header'])
    arch.write_formula(18,8,'=IF(COUNT(I7:I16)=10,AVERAGE(I7:I16),"")',fmt['percent'],'')
    arch.write(19,0,'已有可判票的请求数 / 10',fmt['fixed'])
    arch.write_formula(19,8,'=COUNT(I7:I16)',fmt['formula'],0)
    arch.merge_range('A22:I23','只有 10 个请求均有可判票，才显示完整宏平均。“相当”计半票；无法判断单列。当前模板没有任何真实评分。',fmt['note'])
    arch.protect('',{'select_locked_cells':True})

    models=sheets['模型汇总']
    headers=['模型1','模型2','计划共同提示','有可判票提示','计划评价','纳入评价','可判票','无法判断','模型1等权偏好值','覆盖状态']
    top(models,'模型对决 · 21 组模型组合','按两模型共同有成品的提示等权汇总，只在计划提示均有可判票时显示宏平均。41 个精确模型/提示配对多为单人评价；不据此生成总排名。',headers)
    models.set_column('A:B',28);models.set_column('C:I',16);models.set_column('J:J',23)
    combinations=defaultdict(list)
    for pid,details in grouped.items():
        if details['meta']['arm']=='model':combinations[details['conditions']].append(details['row'])
    for index,((c1,c2),sources) in enumerate(sorted(combinations.items())):
        r=6+index;e=r+1
        models.write(r,0,LABELS[c1],fmt['fixed']);models.write(r,1,LABELS[c2],fmt['fixed']);models.write(r,2,len(sources),fmt['fixed'])
        refs=','.join(f"'逐题汇总'!M{x}" for x in sources)
        models.write_formula(r,3,f'=COUNT({refs})',fmt['formula'],0)
        for col,sc in [(4,'F'),(5,'G'),(6,'H'),(7,'L')]:models.write_formula(r,col,'=SUM('+','.join(f"'逐题汇总'!{sc}{x}" for x in sources)+')',fmt['formula'],0)
        models.write_formula(r,8,f'=IF(D{e}=C{e},AVERAGE({refs}),"")',fmt['percent'],'')
        models.write_formula(r,9,f'=IF(D{e}=C{e},"已覆盖（探索性）","未完整覆盖")',fmt['formula'],'未完整覆盖')
    models.autofilter(5,0,26,9);models.protect('',{'autofilter':True,'select_locked_cells':True})

    decode=sheets['分配与解盲']
    top(decode,'研究者专用 · 冻结分配映射','此工作簿本身包含来源身份；不要发给参与者。隐藏列和工作表保护只防误改，不是访问控制。问卷上不显示模型或方法名。', ['编号','场次','类型','提示ID','A来源','B来源','原始配对ID'])
    decode.set_column('D:D',44);decode.set_column('E:F',28);decode.set_column('G:G',22)
    for i,t in enumerate(all_tasks,6):
        for c,v in enumerate([t['code'],t['position'],ARM[t['arm']],t['prompt_id'],LABELS[t['left']],LABELS[t['right']],t['pair_id']]):decode.write(i,c,v,fmt['fixed'])
    decode.autofilter(5,0,71,6);decode.protect('',{'autofilter':True,'select_locked_cells':True})
    wb.close()
    return all_tasks


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--skip-pdf',action='store_true');args=ap.parse_args()
    data=json.loads((SOURCE/'public_payload.json').read_text())
    key=json.loads((SOURCE/'blind_key.json').read_text())
    schedule,selection=allocate(data,key)
    public=HERE/'participants';public.mkdir(exist_ok=True)
    private=HERE/'researcher_only';private.mkdir(exist_ok=True)
    for code,tasks in schedule.items():make_docx(public/f'{code}_问卷.docx',code,tasks,data)
    newkey={**key,'version':VERSION,'source_version':data['version'],'schedule':schedule,'allocation':selection}
    dump(private/'blind_key.json',newkey)
    dump(private/'frozen_display.json',{'version':VERSION,'artifacts':data['artifacts'],'pairs':data['pairs'],'schedule':schedule})
    all_tasks=create_workbook(HERE/'Agora_11人_结果录入.xlsx',schedule,key)
    with (private/'allocation.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=list(all_tasks[0]));writer.writeheader();writer.writerows(all_tasks)
    dump(private/'source_hashes.json',{name:hashlib.sha256((SOURCE/name).read_bytes()).hexdigest() for name in ['public_payload.json','blind_key.json','provenance.json']})
    if not args.skip_pdf:
        with tempfile.TemporaryDirectory(prefix='agora_11p_office_') as temp:
            command=['libreoffice',f'-env:UserInstallation={Path(temp).as_uri()}','--headless','--convert-to','pdf','--outdir',str(public)]+[str(p) for p in sorted(public.glob('Q??_问卷.docx'))]
            subprocess.run(command,check=True)
        assert len(list(public.glob('Q??_问卷.pdf')))==11
    print(f'Built {len(schedule)} packets and a blank researcher Excel workbook. Version: {VERSION}')


if __name__=='__main__':main()
