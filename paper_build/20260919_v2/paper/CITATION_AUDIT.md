# Citation audit — 2026-09-19

The revision expands the bibliography from 10 to 27 cited works. Sources were
checked against author-hosted papers, arXiv records, publisher proceedings,
ACL Anthology, or the original journal. Citations support specific design
connections and evaluation choices; none substitutes for an Agora experiment.

| BibTeX key | Primary source | Role in the paper |
|---|---|---|
| `togelius2011` | [Original paper](https://julian.togelius.com/Togelius2011Searchbased.pdf) | Representation, generation, and fitness in procedural content generation. |
| `pcgml` | [PCGML, version 3](https://arxiv.org/abs/1702.00539v3) | Functional content, repair, and critique; precedent for repair-oriented generation. |
| `word2world` | [Word2World](https://arxiv.org/abs/2405.06686) | Direct predecessor for story-to-playable-world generation. |
| `dreamgarden` | [DreamGarden](https://arxiv.org/abs/2410.01791) | Hierarchical planning, specialized development modules, and user feedback. Updated from the 2024 preprint to CHI 2025. |
| `park2023` | [Generative Agents](https://arxiv.org/abs/2304.03442) | Memory, reflection, and planning in a persistent community; mechanism motivation. |
| `vezhnevets2023` | [Concordia](https://arxiv.org/abs/2312.03664) | Direct precedent for a Game Master grounding natural-language intentions. |
| `procthor` | [ProcTHOR](https://arxiv.org/abs/2206.06994) | Procedurally generated interactive environments for embodied agents. |
| `holodeck` | [CVPR 2024 paper](https://openaccess.thecvf.com/content/CVPR2024/html/Yang_Holodeck_Language_Guided_Generation_of_3D_Embodied_AI_Environments_CVPR_2024_paper.html) | Language-conditioned 3D layout and spatial constraints. |
| `genie` | [ICML 2024 proceedings](https://proceedings.mlr.press/v235/bruce24a.html) | Learned controllable visual dynamics as a complementary representation. |
| `textworld` | [TextWorld](https://arxiv.org/abs/1806.11532) | Generated text games, explicit state, and controlled evaluation. |
| `scienceworld` | [EMNLP 2022 paper](https://aclanthology.org/2022.emnlp-main.775/) | Grounded scientific procedures and executed outcomes. |
| `light` | [EMNLP-IJCNLP 2019 paper](https://aclanthology.org/D19-1062/) | Essential predecessor for human/model shared play with grounded dialogue and actions. The formal paper title differs from the LIGHT project expansion. |
| `zhou2024` | [SOTOPIA](https://arxiv.org/abs/2310.11667) | Social goals and multidimensional interaction evaluation. |
| `agentsociety` | [AgentSociety, version 2](https://arxiv.org/abs/2502.08691v2) | Population-scale simulation and interventions; April 2026 revision identified. |
| `lmagent` | [LMAgent](https://arxiv.org/abs/2412.09237) | Multimodal e-commerce society and scale. |
| `avalon` | [EMNLP 2024 paper](https://aclanthology.org/2024.emnlp-main.7/) | Collaboration and confrontation under explicit game rules. |
| `react` | [ReAct](https://arxiv.org/abs/2210.03629) | Interleaving reasoning and environment actions. |
| `reflexion` | [Reflexion](https://arxiv.org/abs/2303.11366) | Feedback and episodic verbal memory. |
| `voyager` | [Voyager](https://arxiv.org/abs/2305.16291) | Executable skills, feedback, and verification. The verified arXiv version is cited rather than carrying forward an unverified journal attribution. |
| `saycan` | [SayCan](https://arxiv.org/abs/2204.01691) | Distinction between a meaningful linguistic plan and feasible action. This is a conceptual connection, not an algorithmic equivalence. |
| `misleading` | [EMNLP 2024 paper / author preprint](https://arxiv.org/abs/2403.05020) | Omniscient versus information-asymmetric simulation; observation and leakage controls. |
| `sotopiapi` | [SOTOPIA-π](https://arxiv.org/abs/2403.08715) | Evaluator overestimation after training agents for social interaction. |
| `judge` | [MT-Bench / Chatbot Arena](https://arxiv.org/abs/2306.05685) | LLM-judge biases; why model-mediated values need independent evaluation. |
| `odd` | [ODD protocol, second update](https://www.jasss.org/23/2/7.html) | Reporting entities, initialization, scheduling, and rationale for replication. |
| `park1000` | [Self-report-grounded agents, version 3](https://arxiv.org/abs/2411.10109v3) | Human-grounded behavioral validation. Uses the June 2026 title and author list, replacing the former *Generative Agent Simulations of 1,000 People* title. |
| `centola` | [Original journal article](https://www.journals.uchicago.edu/doi/10.1086/521848) | Distinguishing information diffusion from socially reinforced adoption; conceptual motivation only. |
| `howcroft` | [INLG 2020 paper](https://aclanthology.org/2020.inlg-1.23/) | Defined evaluation constructs and explicit human-evaluation materials. |

The related-work table describes each paper's focus. It does not use checkmarks
to imply that unreported features are absent. The text explicitly acknowledges
precedents for world generation, shared human–agent play, and coordinator
adjudication. No direct experimental comparison with those full systems is claimed.

The `.bib` file distinguishes verified proceedings from arXiv citations. Long
author lists are abbreviated with standard BibTeX `and others` where indicated.
The 27 entries are all used in the paper; no `\nocite{*}` padding is included.


## Added in evidence revision 2

| Key | Verified primary source | Use |
|---|---|---|
| `agentsmatter` | [Kapoor et al., AI Agents That Matter, arXiv 2407.01502 (2024)](https://arxiv.org/abs/2407.01502) | Joint evaluation of performance and cost; holdout and reproducibility limitations. |
| `agentboard` | [Ma et al., AgentBoard, arXiv 2401.13178 (2024)](https://arxiv.org/abs/2401.13178) | Motivation for trajectory-level, intermediate evidence beyond final success. No performance comparison with AgentBoard is claimed. |
