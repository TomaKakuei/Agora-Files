# Agora — TeX source package

本包对应 2026-09-23 机制论文修订版，于 2026-09-24 打包。正文与补充材料独立编译，随包包含当前 PDF、全部引用图表和参考文献。

- 正文入口：`agora_one_sentence_one_living_world_20260923.tex`
- 补充材料入口：`agora_one_sentence_one_living_world_20260923_supplement.tex`
- 共享样式：`paper_style.tex`；参考文献：`references.bib`
- 正文内容：`sections/`；补充内容：`supplement/`
- 图表：`figures/`、`sections/generated/`、`llm_ablation/generated/`

## 编译 / Build

使用 TeX Live 或 MiKTeX，编译器选择 **XeLaTeX**，参考文献使用 **BibTeX**。在解压后的目录运行：

```bash
bash build.sh
```

脚本依次编译两份文档、生成各自参考文献，再各编译两遍以解析双向引用。它不需要 Python、不运行实验、也不调用模型。若只编译其中一份，另一份尚未生成的辅助文件会导致跨文档引用缺失；请先运行完整脚本。

需要常用宏包 `fontspec`、`geometry`、`booktabs`、`graphicx`、`amsmath`、`amssymb`、`tabularx`、`array`、`xcolor`、`xspace`、`natbib`、`xr-hyper`、`hyperref`。字体优先使用 Times New Roman / Arial，缺失时自动使用 TeX Gyre Termes / Heros；字体差异可能改变分页。

The two documents share figures, style, and bibliography source but have independent numbering and reference lists. Build both with XeLaTeX and BibTeX using the script above. No experiment runtime or API credentials are required. Keep both generated PDFs together for cross-document links.

`SHA256SUMS.txt` lists all other packaged files. On Linux, verify the original extracted package with `sha256sum -c SHA256SUMS.txt` before rebuilding or editing it.

完整数据、轨迹、问卷和复现代码保留在材料仓库及完整证据包中：
[Agora-Files](https://github.com/TomaKakuei/Agora-Files/tree/main/docs/agora_one_sentence_one_living_world_20260923)。精简 TeX 包只包含编译所需内容和两份 PDF。
