#!/usr/bin/env python3
"""Render a complete, actual pilot packet; identity keys are never typeset."""
import argparse
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
def tex(s):
    mapping={'\\':r'\textbackslash{}','&':r'\&','%':r'\%','$':r'\$','#':r'\#','_':r'\_','{':r'\{','}':r'\}','~':r'\textasciitilde{}','^':r'\textasciicircum{}'}
    return ''.join(mapping.get(c,c) for c in str(s)).replace('[…]','[截断 / omitted]')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--code',default='P001');args=parser.parse_args()
    d=json.loads((HERE/'researcher_only/public_payload.json').read_text());assert args.code in d['schedule']
    out=[r'''\documentclass[10pt,a4paper]{article}
\usepackage[margin=15mm]{geometry}
\usepackage{fontspec,amssymb,xcolor,tabularx,array}
\setmainfont{Noto Sans CJK SC}
\XeTeXlinebreaklocale "zh"
\XeTeXlinebreakskip=0pt plus 1pt
\definecolor{teal}{HTML}{087F83}
\definecolor{gold}{HTML}{B8852D}
\setlength{\parindent}{0pt}
\setlength{\parskip}{5pt}
\makeatletter\def\@listi{\leftmargin3mm\parsep0pt\topsep1pt\itemsep1pt}\makeatother
\pagestyle{plain}
\newcommand{\heading}[1]{\par\vspace{5pt}{\color{teal}\bfseries #1}\par}
\newcommand{\blankline}{\par\vspace{10pt}\hrulefill}
\begin{document}
{\LARGE\bfseries 生成世界设计比较问卷}\par
{\large 完整试填材料 / Pilot packet}\par
''',r'\textbf{分配码：'+tex(args.code)+r'}\quad 仅供该编号使用，不可多人重复填写。',r'''
\textcolor{gold}{\rule{\linewidth}{1.5pt}}
\heading{目的与材料}
你将阅读四组 A/B 世界设计。每组来自同一个生成要求，来源名称隐藏，没有预设赢家。只评价所示书面设计，不评价真实运行效果、图像质量或游玩体验。

材料按统一字段数量、原始顺序和词数上限摘录；[截断 / omitted] 表示原文继续。未展示不代表完整世界中没有该内容。文字更长、细节更多本身不等于更好。英文材料保持原文，请仅在能独立阅读时参与，不要让模型或他人代评。

\heading{参与与数据}
预计约 20--30 分钟，需通过试填校准。参与自愿，可随时停止，不能判断时选“无法判断”。记录匿名编号、经验、评分、可选评论，用于学术汇总分析及去标识化报告。请勿填写姓名、邮箱或其他个人信息。评论引用需在最后单独勾选同意。

本纸本不会自动上传。完成后按邀请人的方式交回；交回前可自行销毁，之后可凭分配码向邀请人申请撤回，汇总公开后可能无法撤回。研究联系渠道为本问卷邀请人；开始前可向其咨询数据保存、报酬和研究安排。不要在本问卷上写联系人或自己的身份。

\heading{同意与背景（不符合任一必填条件请停止）}
$\square$ 我年满 18 岁。\quad $\square$ 我能独立读懂英文材料。\par
$\square$ 我已阅读说明，自愿同意按此方式参与研究。

文字冒险／角色扮演游戏经验（可选）：\par
$\square$ 没有\quad $\square$ 偶尔\quad $\square$ 经常\quad $\square$ 不回答

是否参与过本系统开发或看过详细结果？\par
$\square$ 没有\quad $\square$ 有\quad $\square$ 不确定

\heading{如何评分}
每题只选一个：A 明显更好、A 略好、两者相当、B 略好、B 明显更好、无法判断。
“相当”表示能够判断但无明确偏好；“无法判断”表示材料不足。可选评论可写中文或英文。每场先完整阅读 A 与 B，再评分。
''']
    questions=[('总体世界设计','综合所示材料，哪一份世界设计更好？'),('设定实现','哪一份更充分地把共同生成要求发展成具体世界？'),('规则与活动','哪一份更清楚地展示规则如何影响活动和冲突？'),('人物与社会联系','哪一份更清楚地展示不同人物的目标如何相互关联？'),('地点与物件','哪一份的地点和物件更能体现这个世界的独特设定？'),('可设想的行动','哪一份更能让你设想会影响世界的具体行动？')]
    for i,task in enumerate(d['schedule'][args.code],1):
        for side,label in [('left','A'),('right','B')]:
            out.extend([r'\clearpage',r'{\Large\bfseries 第 '+str(i)+r' 场 / 4 · 设计 '+label+r'}\par',r'\heading{共同生成要求}',r'{\small '+tex(d['pairs'][task['pair_id']]['prompt'])+r'}\par\vspace{6pt}'])
            sections=d['artifacts'][task[side]]['sections']
            for half_index,half in enumerate([sections[:4],sections[4:]]):
                out.append(r'\begin{minipage}[t]{0.48\linewidth}\fontsize{9}{12}\selectfont\raggedright\setlength{\parskip}{0pt}')
                for section in half:
                    out.append(r'\heading{'+tex(section['zh'])+r'}\begin{itemize}')
                    out.extend(r'\item '+tex(row) for row in section['rows']);out.append(r'\end{itemize}')
                out.append(r'\end{minipage}'+(r'\hfill' if half_index==0 else ''))
            out.append(r'\vfill\small 阅读本场 A 与 B 两份材料之后再评分。')
        out.extend([r'\clearpage',r'{\Large\bfseries 第 '+str(i)+r' 场评分}\par',r'\textbf{分配码：'+tex(args.code)+r'}\quad 每行只选一项。\par\vspace{8pt}',r'\renewcommand{\arraystretch}{1.65}',r'\begin{tabularx}{\linewidth}{>{\raggedright\arraybackslash}X*{6}{>{\centering\arraybackslash}p{13mm}}}',r'题目 & A 明显 & A 略好 & 相当 & B 略好 & B 明显 & 无法判断\\\hline'])
        for title,q in questions:out.append(r'\textbf{'+tex(title)+r'}\newline '+tex(q)+' & '+ ' & '.join([r'$\square$']*6)+r'\\\hline')
        out.extend([r'\end{tabularx}',r'\heading{可选：两份都不足以形成可信世界的印象？}',r'$\square$ 是\quad $\square$ 否\quad $\square$ 无法判断\quad $\square$ 不回答',r'\heading{可选：哪个具体细节最影响你的判断？}',r'\blankline\blankline\blankline',r'\vfill{\small “可设想的行动”只评价书面设计，不推断行动在实际运行中能成功。}'])
    out.extend([r'\heading{评论引用同意（可选，默认不勾选）}',r'$\square$ 我另行同意去除身份信息后引用我的评论。不勾选也可交回评分。',r'\par 请将此问卷按邀请人的方式交回；保留分配码以便提出撤回请求。',r'\end{document}'])
    dest=HERE/('questionnaire_example_'+args.code+'.tex');dest.write_text('\n'.join(out)+'\n');print(dest)

if __name__=='__main__':main()
