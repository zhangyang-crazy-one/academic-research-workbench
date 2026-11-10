# 全量 issue / PR 覆盖审计（2026-10-23）

**结论：存在未完整覆盖的需求；不能把关闭状态、关联 PR 或 CI 绿灯等同于验收完成。** 初始快照覆盖78个issue（67closed/11open）和98个PR（82merged/1closed未合并/15open）。本轮新增PR另列，不混入原始分母。

主代理独立比对全部编号集合：无重复/遗漏。历史矩阵由独立审查代理逐项审读正文/owner修订与留存证据，主代理核查关键缺口、政策与矩阵集合；并未重跑82个历史PR的所有测试。完整机器可读矩阵见 [JSON](upstream-coverage-20261023.json)。

## 已验证

- #120 按用户已有的明确人工判据认定；实际重跑留存pilot：10条，8一致、1不一致、1明确unknown；NEP16/17各两轮resume，状态与abandoned提醒一致。不把自动比较改写成人工标注。
- 已关闭issue原基线：57项按明确修订后的工程范围已有合并覆盖、1项SHA政策被maintained-major替代、1项直接提交修复、7项部分覆盖、1项完整发布证据无法核实。部分覆盖中确认三个代码遗漏：#36 conflict生产接入、#37根CFF、#39结构化PDF与进程边界。
- 当前规则以已留存maintained-major/no-exact-SHA为准；不为满足旧#32文字倒退策略。#47后续漂移由#136承接，未遗失，但新版本尚未admission。

### 当前开放issue覆盖

| Issue | PR | 状态 | 覆盖与剩余 |
|---|---|---|---|
| [120](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/120) | [144](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/144) | 已验证 | 已有人工标注接受本轮用户重申；10样例=8一致/1不一致/1unknown，四次resume通过。PR未合并。 |
| [136](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/136) | 无升级PR | 未验证 | 漂移通知已登记；ARS3.22.2→3.23.1/file-base0.11.0→0.12.1尚无vendor admission PR，需来源/许可/补丁/manifest/native资格评审。 |
| [145](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/145) | [168](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/168) | 已验证 | manifest绑定修复已有PR；主代理重跑4个resume测试通过，PR未合并。 |
| [150](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/150) | [154](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/154), [171](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/171) | 未验证 | streaming已合并；reuse补修已推#171，320通过/1跳过。真实installed四入口同机A/B墙钟/RSS/PSS/逻辑读取尚缺，本地native启动仍超时。 |
| [151](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/151) | [157](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/157), [172](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/172) | 已验证 | 当前#172替代旧#157，角色路由工程覆盖；主代理图形链89项检查通过，PR未合并。 |
| [152](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/152) | [158](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/158), [173](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/173) | 已验证 | 当前#173替代旧#158，版本化组合工程覆盖；包含在图形链89项验证，PR未合并。 |
| [153](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/153) | [159](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/159), [174](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/174) | 未验证 | 当前#174替代旧#159，真实PNG/PDF与机械基准存在；非生产者人类视觉接受仍待完成，#120判据不转用。 |
| [162](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/162) | [163](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/163), [175](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/175) | 阻塞 | 当前#175替代旧#163；round3修复并主代理88测试/三PNG像素复核。三策略缺representation对照源事实，人工接受/终稿尺寸仍未验证。 |
| [164](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/164) | [165](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/165), [167](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/167), [170](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/170), [177](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/177) | 未验证 | 只完成候选准备；须final-main CI、portable installed证据与精确候选发布决策。未合并/发布任何版本。 |
| [166](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/166) | [167](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/167) | 已验证 | 完整注册表容量改为256；真实registry与overflow主代理9测试通过。尚未合并，不把旧候选门禁当新main资格。 |
| [169](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/169) | [170](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/170), [177](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/177) | 已验证 | source前置修复#170；新增#177解决浮动Python3.15缺torch轮子，保留3.x core与3.14全extras；主代理97测试通过。未合并。 |

### 本轮修复与独立复验

- #177：以#170为base，3.14全extras与独立3.x core CI；主代理97专项通过，完整依赖213包解析成功。
- #178：补root CITATION.cff；cffconvert 1.2.0 schema和CodeMeta/pyproject一致性检查通过；组件许可索引未改为笼统许可。
- #171：私有单调用cache、descriptor/ctime/mode及最终identity检查；主代理320通过/1跳过；不自动关闭#150。
- #175：round3标签/初始化/逐坐标求和/新增guard/出口绑定修复；主代理88通过，并查看全部三张实际PNG；人类接受不冒领。
- #105：最终仅保留inventory fixture改进；撤回无必要且不可解析的依赖floor提升。63测试通过，恢复后的完整extras/dev/ars-test/storm实际resolver dry-run成功（213包）。
- #179：补#36 resolver/self-report conflict生产接入和accepted evidence绑定；主代理63项通过。
- #180：补#39 Docling结构/配置与模型摘要/受限解析子进程；主代理55项通过。真实Docling资产与公开PDF验收仍未验证。

两项修复在独立组合工作树自动合并无冲突；主代理额外运行共享CLI、citation canonical/contamination、precise locator和schema drift：**56 passed**。该组合仅本地验证，未改main。

### 素材PR #176

已完整拉取并保留本地：`build/review-assets/pr176-af41101d/research-figures/`。固定head `af41101d4401a0e8f2e721c08f7285e49dfcfb45`。200SVG+200PNG+200原型+200prompt+3索引文件，共158,739,867字节。原型占约95%，去除原型的整包约7.96MB；体积不构成整包否决理由。

主代理重新核对803文件SHA256/Git blob及600manifest摘要，解析200原生SVG结构，并查看200项总览及详细对照页。独立素材审查另检查全部PNG/独立渲染、24详细样本，以及同Git树的真实CI wheel/sdist：素材未进入运行时归档。完整取证留在本地审查目录，未将素材复制进本审计PR。

**适用性：适合作为可选、可编辑的概念图元素；不能当作测量/解剖/工程事实。**正式接入前应：

1. 补集合许可、适用文件范围、署名和第三方例外；根LICENSE只是组件索引，不自动授予新素材许可。许可选择等待有权授权者决定。
2. 修正A109：`source_reference=null`却挂OpenVLA Figure2及“see verification”状态。补实际核验与限制，或明确未核验通用设计；不可填造论文核验。
3. 保留SVG优先；点云/纹理/皮层柱等缩至10–15mm时细节变弱，按终稿尺寸放大/加粗/简化。可提供约8MB轻量包并将原型作独立可选档案，保持摘要绑定。

## 未验证

- #38：真实同模型ARW/baseline、公共任务集及成本；#40：真实宿主路由/稳定性；#54：至少十篇双领域真实范文及作者采纳。工程harness和合成测试不是这些实证验收。
- #99：原完整发布链无法独立核实；后续portable规范替代旧host要求不等于0.2.1发布已获资格。#164仍待最终main真实资格。
- #150：同机同artifact四入口A/B仍缺；native启动超时，不能用单元测试替代installed性能结果。
- #153/#162：真正人类视觉接受、完整三策略与终稿尺寸；#120的人类判据仅适用于#120。
- #136：上游版本admission未完成；通知metadata不是依赖升级证明。
- 每个PR的所有历史review线程、真实印刷、素材权利链、真实宿主与全部native门禁未全部重跑。

## 阻塞

- 素材正式分发：缺明确许可声明；A109来源记录待修。
- #162完整三策略：representation缺作者指定的控制/处理条件和预期输出；已向用户请求事实，不虚构科学对照。
- 本机native入口启动超时限制完整installed复验。外部实证/人类接受未由AI代签。

## 全部已关闭issue（基线覆盖）

该表保留修复前审计事实。#36代码缺口现由#179补齐，#37缺失CFF由#178补齐，#39工程缺口由#180补齐；均尚未合并，且#39真实模型/公开PDF验收仍未完成。

| Issue | 分类 | PR | 对应范围 |
|---|---|---|---|
| [6](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/6) | 已有合并覆盖 | [7](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/7), [10](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/10), [12](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/12), [13](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/13), [14](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/14), [15](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/15), [16](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/16), [17](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/17), [18](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/18), [19](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/19), [20](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/20), [21](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/21), [22](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/22), [23](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/23), [24](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/24) | 架构按 Phase 0–7 分批交付；#19 补精确 locator，#24 明确完成剩余实现。owner 对统计 humanization 的修订由 #23 的五种 writing 操作覆盖。 |
| [8](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/8) | 已有合并覆盖 | [19](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/19) | typed IR、五级校验、候选/接受边界、确定性 SVG、parent ledger receipt；正文 36/36 delivery 与 #19 一致。 |
| [9](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/9) | 已有合并覆盖 | [21](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/21) | observation→candidate→evaluation→qualification→consented promotion；六模式、反例桶、重建和 ledger 绑定有交付记录。正文修订明确将 WorkflowEvolver/自动工作流生成后置。 |
| [11](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/11) | 已有合并覆盖 | [20](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/20) | 项目身份、不可变记忆、窄 MCP、预算召回、跨 harness 同一身份和 stale handoff 检查由 #20 交付。 |
| [25](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/25) | 直接提交/人工关闭 | — | 无关闭 PR；直接提交 14a25a152eb8e398ad5fda1feda591639dc3840c 的正文 Closes #25，修改 launcher 和安装回归。当前 resolve_codex_home 仍使用 HOME/.codex fallback。 |
| [26](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/26) | 已有合并覆盖 | [44](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/44), [61](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/61) | 四个 Python server 共用 bounded stdio；64 KiB、递归深度、坏帧后继续服务的实现与测试纳入 #44；#61 修旧协议 _meta 回归。 |
| [27](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/27) | 已有合并覆盖 | [44](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/44), [63](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/63), [64](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/64) | 默认不注册未配置 file-base，显式 enable/preflight；#63 支持 checkout 自动 agent，#64 给出缺 native 的下一步建议。 |
| [28](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/28) | 已有合并覆盖 | [44](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/44), [49](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/49) | 加法字段容忍、未知 permission redaction、required 字段严格与旧 decoder 保留。hooks/COMPATIBILITY.md 明确三版本九事件真实捕获，fixtures 完整存在；#49 刷新 fingerprint。 |
| [29](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/29) | 已有合并覆盖 | [44](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/44) | 前置条件 markers、candidate_inputs/conftest、strict prereqs 与完整 tests 发现替代按文件枚举；后续 #169 为独立当前环境缺项，由主代理处理。 |
| [30](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/30) | 已有合并覆盖 | [44](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/44) | STORM 默认改为显式 provider/model，不读取宿主 auth.json；provenance receipt 与 parent 接纳路径补齐。 |
| [31](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/31) | 已有合并覆盖 | [44](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/44), [46](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/46) | CI 对 adopted core 做 Ruff/format/Pyright；版本约束改成 open lower bounds 是后续记录的维护策略，#46 owner 明确拒绝批量抬下限。原先全仓/上限建议未全部采纳。 |
| [32](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/32) | 政策替代 | [44](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/44), [45](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/45) | least privilege、cache-free release、attestation、Dependabot 有对应交付；原exact-SHA验收由当前owner确认的maintained-major/no-exact-SHA政策替代。opus55-review-remediation/tasks.md:49（6.7，未勾选）明确 supported major tags / without exact SHA pins；release-attestation-and-dependency-updates/design.md:5,17,27,47 明确保留 maintained-major、拒绝 SHA pin，specs/lock-free-dependency-update-monitoring/spec.md:12 要求保持该政策，tasks.md:4,19,24 记录实施范围与验收冲突。 |
| [33](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/33) | 已有合并覆盖 | [44](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/44), [71](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/71), [83](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/83), [85](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/85) | 平台矩阵收窄 Windows 为不支持、macOS Tier 2；CI 有 macos-core、每 PR native confinement，nightly ASan/UBSan；#83 修 sudo 路径并留 manual run。 |
| [34](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/34) | 已有合并覆盖 | [44](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/44), [70](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/70), [71](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/71) | watcher、升级评估、ARS 3.22.2（超过要求 3.22.1）、file-base 0.11 与补丁/许可/native evidence 分别交付；#47 是后续 drift tracker。 |
| [35](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/35) | 已有合并覆盖 | [44](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/44), [61](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/61) | 统一 StdioProtocol 和 dual-era negotiate/server-discover/tools；legacy _meta 由 #61 修复。native file-base 仍明确 legacy transport。 |
| [36](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/36) | 部分覆盖 | [44](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/44), [62](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/62), [113](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/113) | Crossref/OpenAlex/DBLP/arXiv、离线 replay、typed gate/waiver 有实现；#62 修 updated-by，#113 修版本化 arXiv。但 contamination_signals 只有单测调用，未接入模型自报差异 conflict 记录。 |
| [37](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/37) | 部分覆盖 | [44](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/44), [132](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/132) | RO-Crate export/verify、execution binding、codemeta 与 PROV 接入有实现；根目录未交付 ARW CITATION.cff，仅 vendored ARS 子树含其自身 CFF。 |
| [38](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/38) | 部分覆盖 | [44](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/44), [90](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/90) | 32 个中英自建题、12 对抗题、确定性 scorer、receipt/benchmark sample adapter 已交付。evals/README.md 明确无广义真实同模型 baseline/ARW-route 或公共基准；#90 仅独立三题合成响应面的提示词比较。 |
| [39](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/39) | 部分覆盖 | [44](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/44) | pypdf/GROBID/Docling optional adapters、文本摘要和 review 状态存在；Docling 实际路径只 export_to_markdown 后 _build，未保留 section/bbox/reference，manifest 无配置/模型 digest；CLI 直接同进程调用。 |
| [40](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/40) | 部分覆盖 | [44](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/44) | 主 skill 三个、Chinese/English 60 cues、validator 与 archive-only K-Dense admission 已交付；正文要求中文稳定宿主选择的实测本轮未验证，文档转给 #38。 |
| [41](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/41) | 部分覆盖 | [44](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/44) | 本项只索引/排序#26–#40，无独立代码需求；#36/#37/#39仍有F02/F03/F05代码缺口，#38/#40的F04/F08实证验收未验证；#32原SHA标准已被当前owner政策替代，不再列作缺口。 |
| [47](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/47) | 已有合并覆盖 | [70](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/70), [71](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/71) | ARS 3.21.1→3.22.2、file-base→0.11.0 已由#70/#71合并；后续ARS/file-base漂移由OPEN #136承接，不是未登记遗漏。2026-10-23 gh issue view 136 只读复核仍为 OPEN，updatedAt=2026-10-19T13:08:59Z；正文登记 ARS manifest 3.22.2→stable v3.23.1、file-base manifest v0.11.0→stable v0.12.1，并明确 observed metadata 不是 vendor admission。 |
| [48](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/48) | 已有合并覆盖 | [49](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/49), [68](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/68) | overlay 新增 F1–F4 数值/表行/引用锁和 H1–H7 hygiene；manifest/router/README/MODIFICATIONS 有对应，#68 修其三项 F3 缺陷。 |
| [53](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/53) | 已有合并覆盖 | [52](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/52), [56](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/56), [66](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/66), [87](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/87) | #56 在 #52 上绑定 function/claim/contribution/evidence/boundary 与真实稿件 span；#66 补 proposal replay，#87 补 accepted writing receipt。 |
| [54](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/54) | 部分覆盖 | [56](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/56) | schema、legacy candidate migration、counterexample evaluation、venue_outcome、promoted-only Phase 2 advice 均有工程实现；真实双领域≥10篇范文接受/迁移本轮未验证，PR 明确 pending、任务仍未勾。 |
| [55](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/55) | 已有合并覆盖 | [56](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/56), [65](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/65), [87](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/87) | 三层 advisory fit、冻结输入与离线回放由 #56；#65 修坏 PDF/源格式标题，#87 修 writing-derived capture/replay。 |
| [57](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/57) | 已有合并覆盖 | [69](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/69), [84](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/84), [88](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/88) | 按 owner 收窄为 ExperimentProvenance 纯函数 evaluator；数值/同口径比较、六状态、unsupported、版本回放；#84 精确有理数、#88 parent 时序补齐。 |
| [58](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/58) | 已有合并覆盖 | [68](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/68) | LaTeX tabular 结束前无显式终止符的末行纳入 F3；PR 保留源案例正负回归。 |
| [59](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/59) | 已有合并覆盖 | [68](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/68) | 按大括号外逻辑换行切分，同一物理行多逻辑行不再截断；spacing/makecell 边界有对应回归。 |
| [60](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/60) | 已有合并覆盖 | [68](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/68) | 贪心匹配改为增广路径二分图一一匹配；重排/描述列扩展及不存在匹配的负例对应。 |
| [72](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/72) | 已有合并覆盖 | [85](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/85) | session canonical allowed-root 与进程 root/ID capability 绑定；owner 修订保留 root_denied，只对真正 session mismatch 返回新原因并补 schema/pins/native 证据。 |
| [73](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/73) | 已有合并覆盖 | [87](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/87) | capture/replay 共用 versioned writing_candidate_receipt 校验，receipt/candidate/realization/manifest/event/source/human-review 绑定，保留两种旧模式。 |
| [74](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/74) | 已有合并覆盖 | [88](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/88), [129](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/129) | parent freeze、same-claim successor、journal-derived timing；owner 明确将3实验拆 #119，现由 #129 合并。 |
| [75](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/75) | 已有合并覆盖 | [84](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/84) | evaluator 1.1.0 精确 Fraction 比较、输入指数/长度域、科学计数展示、typed block、旧 1.0 回放；owner 列最坏 CPU 成本为非阻塞后续。 |
| [76](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/76) | 已有合并覆盖 | [86](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/86) | UTF-8 sentence spans/索引去重、完整 canonical receipt 8 MiB 生成前检查、legacy replay；owner 核实95项并明确极端短句仍可因预算拒绝。 |
| [77](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/77) | 已有合并覆盖 | [90](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/90) | owner 接受先离线三题、四指标、same observations ridge、all-attempt/cost unknown；另留6条真实 native 比较与 parent observation。 |
| [78](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/78) | 已有合并覆盖 | [83](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/83) | schedule/manual 共用 sudo offline-exec、显式 runtime env、invoking-user 执行、保留 artifact/manifest unchanged；owner 核对真实 run 37719851582。 |
| [79](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/79) | 已有合并覆盖 | [91](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/91) | 已有 ARS 字段先映射，accepted reading trace/stop reason、同预算成对排序、缺概率 descriptive-only、SRS 合成例；owner 明确公开实证 pilot 不在最终清单。 |
| [80](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/80) | 已有合并覆盖 | [93](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/93) | Gale–Shapley 1962 Example 2、可选独立实现、窄 schema、测试前不发布、真实隔离与安装证据；基础 wheel 排除。 |
| [81](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/81) | 已有合并覆盖 | [92](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/92) | 只读 failure diagnosis、竞争机制/probe、frozen acceptance、source IDs、memory successor/handoff；owner 明确自建合成三例足以关闭工程验收。 |
| [82](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/82) | 已有合并覆盖 | [89](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/89), [127](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/127) | trail/withdrawal/handoff summary 的代码由 #89；owner 明确10次人工试点转 #120。#127 只合并owner回答材料，不能认定 #120 核心验收完成。 |
| [94](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/94) | 已有合并覆盖 | [96](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/96), [107](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/107), [128](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/128), [131](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/131), [132](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/132), [148](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/148) | 按 owner v3 和 Q5(a)实现 AcceptedRef、多日志快照、exact numeric、declared/authenticated 与硬检查；Phase3 明确转 #121/#122，现已合并；#107/#128 为验证/性能修复。 |
| [95](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/95) | 已有合并覆盖 | [96](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/96), [101](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/101), [130](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/130), [138](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/138), [142](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/142), [131](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/131) | SVG 单面板/图层/raw/interval/series/order/pairing、启发式与图注结构化绑定；#101/#96 补单位/索引；按 owner 拆 #123 PGF 和 #121 AI，均已合并。 |
| [97](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/97) | 已有合并覆盖 | [101](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/101), [96](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/96) | #101 修直接输出量纲；owner 指出嵌套 DerivationRef 残余，#96 明确 arw.rational.v2 按子结果单位修正且保留显式 v1。 |
| [98](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/98) | 已有合并覆盖 | [101](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/101), [96](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/96) | #101 操作级 replay/ref/CSV 缓存；owner 指出缓存后仍逐点遍历，#96 补 header/row-ID 索引、实际 row-access 回归和10/100/1000基准。 |
| [99](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/99) | 完整验收未验证 | [100](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/100), [96](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/96), [114](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/114) | #100 路径规范化与3 job materialize 已合并；owner 明确早期测试用 sentinel/复制 LICENSE，只验证参数与准备，并非完整两路径CLI/clean-runner authority链。后 #114 改 portable release 契约。 |
| [103](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/103) | 已有合并覆盖 | [107](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/107) | typed experiment acceptance、接受前依赖前缀及原 evaluator raw replay 均成立才进入可信 checks；普通JSON/改写passed/缺CSV保持not_checked。 |
| [104](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/104) | 已有合并覆盖 | [107](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/107) | 可见 launcher 经隐藏 alias 时重建首隐藏入口到 observed runtime；保留完整HOME隔离、只读安装和循环/缺失拒绝。 |
| [108](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/108) | 已有合并覆盖 | [110](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/110) | runtime digest 纳入目录/链接路径、原目标、解析目标；运行后变化/不可用触发 StaleAttempt，悬空循环越界拒绝。 |
| [112](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/112) | 已有合并覆盖 | [117](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/117) | 删lock测试限定确实 qualified stage且先 assert lock存在；合法 never-locked candidate仍 0/BLOCKED。同时 artifact qualification有界等待防并发假失败。 |
| [115](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/115) | 已有合并覆盖 | [118](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/118), [126](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/126), [149](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/149) | core稳定project identity、start/status/resume、scoping、逐步请求恢复与分层状态；#126拒历史丢失回退，#149修receipt半写。 |
| [116](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/116) | 已有合并覆盖 | [118](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/118) | 两种外置包、ARS委托、AcceptedRef/experiment replay、版本化文献intake与跨阶段离线walkthrough；真实安装18 CLI/4请求/revision14为既有证据。 |
| [119](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/119) | 已有合并覆盖 | [129](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/129) | 三CPU算例完整freeze→外部worker→provenance→offline accept→cold replay，v1失败v2通过不继承事前；本轮逐字节重核85清单，无错。 |
| [121](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/121) | 已有合并覆盖 | [131](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/131), [137](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/137), [139](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/139) | 独立provenance汇总observed/human-declared/unknown，未引用文本/代码/图均在inventory；policy snapshot/venue分开；#137总预算、#139限定proof scope兼容。 |
| [122](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/122) | 已有合并覆盖 | [132](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/132), [143](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/143), [148](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/148) | ReviewConcern advisory/optional修辞角色、PROV→原RO-Crate；#143补CLI envelope预算，#148补claim-only关联纯文本sources重验。 |
| [123](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/123) | 已有合并覆盖 | [130](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/130), [138](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/138), [142](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/142) | 同一compiled plot exact values/IDs生成deterministic安全转义TeX，source-only/not_verified；#138图例队列，#142显式marker颜色。 |
| [124](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/124) | 已有合并覆盖 | [128](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/128) | 单查询exact-prefix与anchor proof复用、相同字节、fresh query重验；owner核实60→120约2.2倍，public prime API修订已进入PR。 |
| [125](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/125) | 已有合并覆盖 | [126](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/126), [149](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/149) | prepared/completed初始化边界，completed/ambiguous历史丢失拒绝，不重写首segment；owner最终review明确原P1已修。#149为不同半写可用性后继。 |
| [133](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/133) | 已有合并覆盖 | [138](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/138), [130](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/130) | 无名plot/额外interval forget plot，每named series只一legend，跨层对应/顺序正负案例；后续原特性 #130合入main。 |
| [134](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/134) | 已有合并覆盖 | [139](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/139), [131](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/131) | whole-artifact bytes允许bytes/structural_capsule/metadata_only但保留limited proof scope，mixed材料不抹掉已知participation。 |
| [135](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/135) | 已有合并覆盖 | [137](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/137), [131](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/131) | 完整draft summary/text/policy/digest共享2MiB producer/reader预算；exact boundary允许、越1字节拒绝，不截断隐藏问题。 |
| [140](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/140) | 已有合并覆盖 | [142](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/142) | addplot不用+；exporter显式线/边框/fill颜色，保留legend修复；PR记录可选真实pdflatex marker-color对照。 |
| [141](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/141) | 已有合并覆盖 | [143](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/143) | diagnosis截断及CLI读取共用完整envelope序列化与预算，保留摘要和omission；旧zero-omission bytes不变。 |
| [146](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/146) | 已有合并覆盖 | [148](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/148) | claim分支沿canonical registration核验全部occurrences，plain text变更/删除后verify/replay/prov拒绝，真实parent fixture/CLI正负回归。 |
| [147](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/147) | 已有合并覆盖 | [149](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/149) | 完整write+fsync到专用staging，再exclusive hardlink发布+dir fsync；4条真实SIGKILL边界、单event恢复和残片保留有回归。 |
| [155](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/155) | 已有合并覆盖 | [156](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/156) | 仅排除pluggy==1.7.0且提前scancode --version，range-resolved toy MIT scan与复现/对照；未放松license门或runtime范围。 |
| [160](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/160) | 已有合并覆盖 | [161](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/161) | 独立追踪原10项qualification discovery测试文件，字节SHA 66ab9e5e…匹配PR要求，未混图形或生产代码。 |

## 全部原有PR

| PR | 状态 | 覆盖/处理 |
|---|---|---|
| [1](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/1) | MERGED | 修 qualified-stage smoke 不可变输入、ARS self-tests/SBOM；留存 host evidence 的skip未被包装为资格。 |
| [2](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/2) | MERGED | SVG rail/bracket/feedback 几何文档；实际渲染与文件结构验证是声明证据，无独立issue。 |
| [3](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/3) | MERGED | ARS同步、venue官方规则/范文证据分层；旧review后继汇总在PR16历史closure文档。 |
| [4](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/4) | MERGED | integration诊断、ARS integrity/CJK、hook supply-chain；parent唯一canonical，experiment默认disabled。 |
| [5](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/5) | MERGED | ARS 0.1.27/v3.21.1与审查清理；后来70升级pin，既有legal边界保留。 |
| [7](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/7) | MERGED | 冻结实际CLI/MCP/ledger黄金；七工具目标与实际五工具已在历史review closure明确收窄。 |
| [10](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/10) | MERGED | thin kernel move+依赖方向基线；不把重构称行为变更。 |
| [12](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/12) | MERGED | 四port+adapter/routing；native FileBaseMCPAdapter在本PR显式后置，生产五工具合同保留。 |
| [13](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/13) | MERGED | SQLite投影/FTS/校验/重建；#15/#16/#18为后续完整性修复。 |
| [14](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/14) | MERGED | plugin-first技能拆分/默认provider；#15修inert wiring；十stub后由#44改为reference。 |
| [15](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/15) | MERGED | PR12/13/14五个实际review残余修复；PR16历史closure继续补已知缺口。 |
| [16](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/16) | MERGED | Semantica Lite、native store transport、历史review闭环；snapshot TOCTOU再由#18修。 |
| [17](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/17) | MERGED | Unicode inspect/privacy sanitize，完整原/派生bundle；binary与writing明确后置到#23/#24。 |
| [18](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/18) | MERGED | loader后重开DB的TOCTOU→descriptor/private SQLite snapshot；保留独立预算。 |
| [19](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/19) | MERGED | typed artifact IR+精确locator，关闭#8并推进#6。 |
| [20](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/20) | MERGED | harness-neutral memory/handoff，后续#145当前未闭由主代理审。 |
| [21](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/21) | MERGED | evidence learning+人工consent，WorkflowEvolver明确后置，不声称自动workflow生成。 |
| [22](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/22) | MERGED | optional sqlite-vec/固定local embedding模型；只限定检索fixture，不声称广泛收益。 |
| [23](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/23) | MERGED | 五writing操作、统计diagnostics与保守preservation；检测器unsupported后来#50扩展。 |
| [24](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/24) | MERGED | ARS/STORM/file-base extension与binary metadata privacy；完成#6，C2PA只识别存在。 |
| [42](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/42) | MERGED | 显式agent/local-dev runtime；后#63让source checkout默认自动选择。 |
| [43](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/43) | MERGED | Grok consumer只读/advisory适配，无plugin资格放宽或执行器新增。 |
| [44](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/44) | MERGED | 大包关闭#26–#41；F02/F03/F05为已验证代码缺口，F04/F08实证未验证；#32旧SHA标准已被owner maintained-major政策替代，见撤回F01及矩阵。 |
| [45](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/45) | MERGED | Dependabot更新五个Actions major，符合当前maintained-major/no-exact-SHA政策；外链release notes的#编号属于上游，不映射ARW issue。 |
| [46](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/46) | CLOSED | 唯一关闭未合并：owner明确拒绝没有安全/兼容理由的批量floor raises；#105重提同类不等于此项已实现或被正式替代。 |
| [49](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/49) | MERGED | #48 F1–F4/H1–H7 overlay与hook fingerprint refresh；F3再由#68修。 |
| [50](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/50) | MERGED | 可选本地detector/known-key watermark与writing audit；真实模型inference≠准确率/规避效果；未知配置fail unavailable。 |
| [51](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/51) | MERGED | 五类结构化review plan/findings，只读建议，不把模型confidence当门禁；缺review仍not_run。 |
| [52](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/52) | MERGED | project narrative持久化/author-confirmed/stale；输出realization由#56补。 |
| [56](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/56) | MERGED | 叙事实现/venue学习/fit及core route；#54真实语料pending仍是遗漏验收。 |
| [61](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/61) | MERGED | legacy _meta判定修复，共享stdio受益。 |
| [62](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/62) | MERGED | Crossref updated-by，parser1.1及旧1.0回放；不能视为全部#36冲突链完成。 |
| [63](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/63) | MERGED | source checkout自动agent，同时staged保持plugin fail-closed。 |
| [64](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/64) | MERGED | 可选file-base缺native时给advisory recommendation，非自动build。 |
| [65](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/65) | MERGED | fit坏PDF结构化错误与源格式标题规则，旧snapshot逐字节回放。 |
| [66](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/66) | MERGED | proposal.accepted补同artifact.accepted的机械/语义unknown/narrative绑定重验。 |
| [67](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/67) | MERGED | 整稿1MiB+preservation-v2去重；citation重复放大后由#86补。 |
| [68](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/68) | MERGED | F3三bug统一修复，不能把早期本地9f7a38c误当已发布。 |
| [69](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/69) | MERGED | 离线experiment合同验收；数字精度#84、parent时序#88为后继，模型/执行权限未偷渡。 |
| [70](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/70) | MERGED | ARS3.22.2升级，历史正文明确3.23.0未纳入；后续漂移现由OPEN #136登记承接，不作无人跟踪缺口。 |
| [71](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/71) | MERGED | file-base0.11/native三安全面；与#70完成当轮升级并关闭#47，后续漂移由仍OPEN #136承接。 |
| [83](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/83) | MERGED | nightly真实sudo隔离分支修复；owner核对manual run，未假用常规PR CI。 |
| [84](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/84) | MERGED | 精确有理数+有界输出/版本回放；非阻塞旧evaluator新评估可选和worst-case CPU建议尚未要求实现。 |
| [85](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/85) | MERGED | daemon session根绑定；owner指出root_denied/schema回归后修复重算native证据，日志重建件有相同digest而非原artifact下载。 |
| [86](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/86) | MERGED | indexed citation scopes+全receipt预算；短句最坏放大可typed拒绝，非保证任意1MiB均通过。 |
| [87](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/87) | MERGED | accepted writing receipt capture/frozen replay；继承86并保留legacy模式。 |
| [88](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/88) | MERGED | parent契约freeze/version chain；owner回放二次增长修复；3实验拆#119现129。 |
| [89](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/89) | MERGED | 只读decision trail+withdrawal；summary预算/缺lock/symlink owner阻塞已修；10条真实人工比对转#120。 |
| [90](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/90) | MERGED | 独立三题实验理解，6native尝试与ridge；本轮选优无区分力是非阻塞实证局限，不等价#38公共suite验收。 |
| [91](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/91) | MERGED | selection trace/paired ordering；合成已知概率不升级普通搜索为可校正；实证public corpus不在最终验收。 |
| [92](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/92) | MERGED | 只读failure diagnosis合成三例，causal unknown；mechanism非穷尽的建议保留为风险。 |
| [93](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/93) | MERGED | Gale–Shapley optional MCP/测试前不发布；仅限定Linux与equal-size ranking domain，安装不带第三方依赖。 |
| [96](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/96) | MERGED | ClaimGraph/numeric/result_plot与release准备；owner嵌套单位/row-index纠正已写入最终正文；exact-host mandatory release政策后来#114替代。 |
| [100](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/100) | MERGED | #99两个代码修复；完整原发布CLI/clean-runner authority仍需读原件，owner已明示早期test替身局限。 |
| [101](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/101) | MERGED | 直接量纲与操作级缓存；owner残余nested-unit/index由#96最终修，不能仅凭101早期总结关完整验收。 |
| [102](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/102) | MERGED | qualifier挂载观测Codex package，不挂整个HOME；隐藏中间alias再由107修；不是模型资格证据。 |
| [105](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/105) | OPEN | 已修复测试夹具并撤回不兼容的floor raises，63测试和213包解析通过；不是依赖升级资格。 |
| [106](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/106) | MERGED | 具名native/command/API harness；loopback wire与isolated execution，未调用真实API；symlink topology由110补。 |
| [107](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/107) | MERGED | typed experiment replay与隐藏alias两项修复，明确最新main candidate才能作发布证明。 |
| [109](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/109) | MERGED | removed-qualified-lock测试期望更新；candidate fallback误拒再由117修。 |
| [110](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/110) | MERGED | runtime topology digest与post-dispatch StaleAttempt；不是持续文件系统attestation。 |
| [111](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/111) | MERGED | 资格fixture scratch/runtime cache归verifier所有；保留原失败，不冒称完整qualification通过。 |
| [113](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/113) | MERGED | arXiv unversioned匹配任意返回版本、version pin严格；parser1.2，旧1.0/1.1原样回放。 |
| [114](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/114) | MERGED | portable actual-installed-core资格取代强制harness/model/exact-host；执行权限/显式Python丢失经ownerreview后修，原authority保留。 |
| [117](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/117) | MERGED | qualification有界锁等待与qualified-only删lock测试，修#112且保留合法无lock candidate。 |
| [118](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/118) | MERGED | resumable startup、外置方向/版本化intake；后126/149恢复完整性修复。 |
| [126](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/126) | MERGED | 拒绝journal-loss静默回退；receipt半写另147→149；legacy ambiguous显式恢复符合owner收窄。 |
| [127](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/127) | MERGED | 仅#120十条owner偏好材料与B，不是历史状态标注验收；主代理负责#120/#144。 |
| [128](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/128) | MERGED | 查询内exact-prefix/proof缓存，owner公共primeAPI修订纳入，不跨查询信任。 |
| [129](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/129) | MERGED | 三公开数值CPU算例+85文件证据/4结果，mean@1限定/成本unknown如实；本轮重核清单0错。 |
| [130](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/130) | MERGED | source-only PGFPlots，legend由138补、marker color由142补；TeX视觉资格仍not_verified。 |
| [131](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/131) | MERGED | provenance AI disclosure与policy，launcher/import措辞修订及137/139前置均纳入。 |
| [132](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/132) | MERGED | advisory concerns/PROV；launcher/concern数量修订纳入，141→143 envelope、146→148纯文本来源后继已合并；点击HTML明确可选后置。 |
| [137](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/137) | MERGED | 完整disclosure draft producer/reader共享2MiB，stacked131。 |
| [138](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/138) | MERGED | PGFPlots legend队列/跨层series，stacked130，marker fill不是本次引入。 |
| [139](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/139) | MERGED | disclosure limited proof scopes不污染正常材料，stacked131。 |
| [142](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/142) | MERGED | 显式palette marker颜色，不继承addplot+cycle；保留legend修复。 |
| [143](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/143) | MERGED | review完整CLI envelope预算；zero omission历史兼容。 |
| [144](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/144) | OPEN | #120人工标注与pilot覆盖，用户重申有效；未合并。 |
| [148](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/148) | MERGED | claim-only concern关联全部plain-text occurrences重验。 |
| [149](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/149) | MERGED | 初始化receipt staging fsync→exclusive atomic publish；四真实SIGKILL边界。 |
| [154](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/154) | MERGED | 仅#150 streaming hash部分，明确其余mutation-safe reuse/完整startup测量未完，后继171由主代理审。 |
| [156](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/156) | MERGED | 仅ScanCode Pluggy兼容与toy scan，未放松许可门。 |
| [157](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/157) | OPEN | 旧角色路由分支，当前#172承接；未自动关闭。 |
| [158](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/158) | OPEN | 旧组合分支，当前#173承接；未自动关闭。 |
| [159](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/159) | OPEN | 旧视觉benchmark分支，当前#174承接；未自动关闭。 |
| [161](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/161) | MERGED | 仅10项retained discovery回归，owner换base到156修CI，字节保持。 |
| [163](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/163) | OPEN | 旧机制图分支，当前#175承接；未自动关闭。 |
| [165](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/165) | MERGED | 只准备0.2.1候选，不发布；#164仍需final-main CI/portable evidence/owner authority，主代理负责。 |
| [167](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/167) | OPEN | #166容量修复，9专项通过；未合并。 |
| [168](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/168) | OPEN | #145 resume manifest修复，4专项通过；未合并。 |
| [170](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/170) | OPEN | #169 source prerequisites；#177以此为base补CI兼容。 |
| [171](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/171) | OPEN | #150本轮补强mutation-safe私有cache，320通过/1跳过；完整installed A/B未验证。 |
| [172](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/172) | OPEN | #151当前角色路由stack根。 |
| [173](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/173) | OPEN | #152当前组合stack，base#172。 |
| [174](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/174) | OPEN | #153当前visual benchmark，base#173；human_pending。 |
| [175](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/175) | OPEN | #162 draft，base#174；本轮round3已补修，88通过及三PNG复核；三策略/人工/出版未完成。 |
| [176](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/176) | OPEN | 200套概念元素，803文件158739867字节；已完整拉取，许可与A109待修。 |

## 修复分支与托管检查快照

此处为托管状态观察，不以绿灯代替具体行为证据。#177的release-native任务跳过，不能称完整发布门禁通过。

| PR | 精确head | 已成功检查数 | 失败数 | 运行/等待数 | 跳过数 |
|---|---|---:|---:|---:|---:|
| #180 | `5ca6a69109a7b4cddbdfbbc3a13ba32878be0464` | 3 | 0 | 2 | 1 |
| #179 | `6faab94b5d1eb450b96d46e4bc3c99d676b9e2a8` | 3 | 0 | 2 | 1 |
| #178 | `a40347b86ca9c4e22aae7374eda4926543d469b8` | 5 | 1 | 0 | 2 |
| #177 | `cff4b7642f3d7672f4fd6ba45932a8546529d5ec` | 6 | 0 | 1 | 1 |
| #175 | `cb6f27db8d2ba9fa61d4050096a7423d6a28d102` | 5 | 0 | 1 | 1 |
| #171 | `aa7b254c11d9b9f3d0a2db62810fc449d2e83e3e` | 5 | 0 | 1 | 1 |
| #105 | `f6af84050f22683670951235898db7374d6372ec` | 4 | 1 | 1 | 2 |

托管失败进一步核对：#178 的 Python job [120317040164](https://github.com/zhangyang-crazy-one/academic-research-workbench/actions/runs/39923823317/job/120317040164) 在 `test_network_denied_verification_retains_namespace_and_syscall_evidence` 返回97，而非CFF检查失败；#105最终head的[Python job120318715576](https://github.com/zhangyang-crazy-one/academic-research-workbench/actions/runs/39924244106/job/120318715576)也在同一测试返回97，主代理已下载核实失败日志。两者以尚未纳入#170前置修复的main为base。相对地，#177 [Python job120311259387](https://github.com/zhangyang-crazy-one/academic-research-workbench/actions/runs/39922068397/job/120311259387) 已通过source manifest验证、v2 compatibility和complete non-host test tree，最后观察时正在运行bundled ARS self-tests。这里只按实际step结果陈述，不宣称整job或release通过。

建议集成顺序：先审核#170和其后续#177，再审核基于main的各独立修复；图形链仍按#172→#173→#174→#175。此建议不是合并授权；本轮没有合并main、关闭issue或发布版本。
