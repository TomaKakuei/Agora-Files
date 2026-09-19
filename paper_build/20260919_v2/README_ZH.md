# Agora 论文构建与证据材料 · 2026-09-19 v2

这是单独筛选的论文构建资料夹。保留约 80 MiB 的源码、论文用图和实验记录，远低于 10 GB；完整清单、来源与 SHA-256 在 `MANIFEST.json`。

## 快速入口

```bash
python verify_bundle.py
bash reproduce.sh
```

前者校验冻结文件的完整性与体积；后者在不调用模型 API 的情况下编译论文、复算证据、重绘并核对全部 12 张图。生成的 PDF 位于 `paper/agora_one_sentence_one_living_world_20260919.pdf`。PDF 的编译时间戳可能变化，图表 PNG 在相同字体与绘图库环境下应逐字节一致。

已发布的成品在仓库的 `docs/agora_one_sentence_one_living_world_20260919_v2/`；新问卷在 `docs/agora_comparative_survey_20260919/`。此目录的 `paper/` 是构建副本；其中源自发布包的历史相对链接应按上述仓库路径定位。

## 保留内容

| 目录 | 用途 |
|---|---|
| `paper/` | LaTeX、29 篇引用、12 张图、绘图程序、冻结图像输入、原始长轨迹审计；可独立编译和重绘 |
| `implementation/agora_ui/`、`asset_pipeline/` | 世界生成、类型系统、编译、协调器、状态更新、图像生成与检查的实现快照 |
| `implementation/scripts/`、`tests/` | 原实验、审计与分析程序及现有测试 |
| `implementation/frontend/`、`macro_ui/`、`world_creator_ui/` | 与世界显示、操作和生成有关的界面代码；没有复制无关的大型生成媒体库 |
| `implementation/docs/benchmark_20260724/` | 10 个共同 brief 的两种生成方法记录、质量评价、注入故障与局部修复证据 |
| `implementation/docs/world_interaction_experiment_20260803/` | 5 个通过身份审计的 mw3 运行、配置、汇总及前瞻性记忆实验协议 |
| `implementation/docs/living_world_benchmark_20260825_hidden/` | 24 个生成试验、21 条更正后的 24 轮轨迹、提示集及完整性审计 |
| `historical_stories/` | 支撑论文历史分析的三个完整故事记录，共 1,052 个事件 |

## 环境与复现范围

论文与绘图：XeLaTeX、BibTeX、Python、Matplotlib、NumPy、Pillow。原图验证环境为 Python 3.9、Matplotlib 3.5.2、DejaVu Sans；正文优先 Times New Roman/Arial，另有 TeX Gyre 字体回退。构建脚本优先使用 PATH 中的 LaTeX 安装；作者工作站的 TinyTeX 路径只是回退。

完整应用实现和部分原实验脚本使用 Python 3.10+ 的类型语法，依赖见 `implementation/requirements.txt`。这些源文件用于检查实现与重新配置实验，不保证在新的服务环境下无修改重跑；模型提供商、API 凭据、图像服务、未复制的运行环境仍需另行配置。**`reproduce.sh` 只做离线论文复现，不启动新模型调用。**

实现代码来自当前工作树，包括尚未在原实现仓库提交的改动；`MANIFEST.json` 记录源仓库 HEAD 和此事实。它不是每个历史实验的不可变代码 checkout。原始实验结果单独保留，不能把现在的源码状态当作当时已被记录的 commit。

## 筛选与排除

保留论文直接使用的材料与主要实现依赖；排除通用 `output/` 树、视频、无关模型评审排名、早期已判无效的运行、服务日志、数据库、缓存、虚拟环境、第三方依赖缓存、重复 ZIP、LaTeX 中间产物和重绘副本。旧问卷未重复放入此目录。原始工作目录没有被删除或改动。

目录中没有受试者回收答卷。新问卷的研究者包有解盲映射，只给研究者使用；`researcher_only` 是组织目录名，不是 GitHub 的访问控制。招募时只分发问卷的 `participants_only.zip`。

## 可支持与不能支持的结论

这些材料能够重建当前论文图表、汇总算术和原始记录审计。它们不包含新跑的等计算预算架构对照、完成的记忆干预或任何真实问卷结果。论文保留这些限制，没有把材料存在等同于实验已经完成。
