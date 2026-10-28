# Jev 决策模型接入 Polymarket：深度调研报告

*生成日期：2026-10-12 | 来源：约 150 个（官方文档、arXiv、GitHub、媒体）| 总体置信度：中高（技术栈部分高，模型榜单部分中，法律部分为信息性参考，非法律意见）*

---

## 执行摘要

1. **Jev 是 TypeSafe AI 于 2026-09-15 发布的闭源"System One"决策模型**，API-only，只返回结构化答案（noul 是/否概率、choice 多选、score 评分），输入 $0.042/M tokens，输出免费，延迟 70–500 ms。它**不是预测/预报模型，没有检索能力，不知道当前新闻**。
2. **在 Polymarket 上的独立实测很差**：9,138 个 Jev 训练截止后结算的市场上，Jev（盲答）Brier 0.220 / AUC 0.615，而结算前 24 小时的市场价格 Brier 0.152 / AUC 0.844。把市场价喂给 Jev 反而在 72.6% 的市场上让误差变大。逻辑回归融合后 Brier 0.150，与单独用校准后的市场价相同，即 **Jev 没有带来增量信息**。
3. **"开源模型超过 Jev"是真的，但都是在通用决策榜上，不是预测市场榜**。最可能是你记得的：StartLux-Decision-v1-27B（Decision Index 0.2.1：63.88 vs Jev 57.91，权重 CC BY-NC）、Laya（typed-decisions 0.766 vs 0.727，Apache-2.0，421M）、pplx-decider v1.1（Decision Index 0.3.1 #1 62.75 vs 60.11，Apache-2.0）。
4. **真正对预测市场有意义的榜单上，开源权重大模型已经不输市场价**：Prophet Arena（4,347 个已结算事件）上 GLM-5.3 #6、DeepSeek V4 Pro #10、Kimi K3 #15 都高于 Kalshi 市场基线（#18）。但要注意 #1 到 #22 的 Brier 差距只有约 0.005，这是"持平"而非"碾压"。
5. **Polymarket 技术栈在 2026 年彻底换代**：CLOB V2 于 2026-04-28 上线，V1 客户端全部失效；抵押品改为 pUSD；官方 SDK 变成 `polymarket-client`（Python）/ `@polymarket/client`（TS）；吃单方收费、挂单方免费并有返佣；2026-11-02 前后还有 Protocol V2 切换。网上绝大多数教程和开源 bot 都已过时。
6. **实证上没有任何公开、独立验证的"LLM 预测驱动"bot 在 Polymarket 上长期盈利**。六个前沿模型各 $10k 实盘 57 天：Polymarket 平均 −1.1%，Kalshi −16% 到 −31%。可验证的 bot 利润几乎全部来自套利、做市和延迟，而这些边际正在被平台主动压缩（收费、TWAP 结算、限流分层）。
7. **地区限制**：中国大陆、香港**不在**Polymarket 任何限制名单上（但香港证监会 2026-04 警告可能构成非法赌博，大陆有加密货币禁令）；台湾、新加坡、美国为"只能平仓"（前端和 API 都限制）；日本为前端只能平仓但 API 不限。使用 VPN 绕过限制违反 ToS，会被置为 close-only。

**一句话结论**：技术上接入是直接的，一周内可以跑通 paper trading；但 Jev 本身作为信号源不太可能带来超额收益，更合理的架构是"检索增强的预报模型（开源权重可选）+ 市场价作为先验 + 严格的费用/流动性/相关性过滤 + 挂单优先执行"，并且先用真实订单簿做离线和纸面回测，拿到有统计显著性的结果之前不要上真钱。

---

## 1. Jev 到底是什么

| 项目 | 内容 | 来源 |
|---|---|---|
| 发布方 / 日期 | TypeSafe AI（创始人 Diogo Almeida，前 OpenAI），2026-09-15 | [DataCamp](https://www.datacamp.com/blog/system-one-models-jev)、[MarkTechPost](https://www.marktechpost.com/2026/09/19/typesafe-ai-releases-jev/) |
| 形态 | 闭源、API-only：`POST https://api.typesafe.ai/v1/systemone`，有 Python/JS SDK | DataCamp |
| 三个原语 | `noul`（是/否 + 校准概率）、`choice`（≤255 个选项）、`score`（有序评分） | DataCamp、[腾讯云](https://cloud.tencent.com/developer/article/2747050)、[知乎](https://zhuanlan.zhihu.com/p/2084171502883190195) |
| 价格 / 延迟 | $0.042/M 输入 tokens，输出免费，约 $0.0004/次；70–500 ms | DataCamp |
| 官方准确率 | 4 个工作流基准平均 67.8%，约等于 GPT-5.6 Terra（67.9%），低于 GPT-5.6 Sol（74.1%）和 Claude Opus 5（73.1%） | DataCamp |
| 第三方复核 | 官方给过四套互相矛盾的速度/成本倍数；独立测得 p50 延迟 314 ms | [Chorylee7/JEV](https://github.com/Chorylee7/JEV) |

### 1.1 Jev 在 Polymarket 上的实测（关键）

[dev.to / moonthetrain](https://dev.to/moonthetrain/can-jev-beat-polymarket-i-asked-it-about-26174-resolved-markets-2llb) 用 26,174 个已结算市场测试，主分析取 Jev 训练截止后（2026-09-10 至 10-10）结算的 9,138 个：

| 方法 | Brier | AUC |
|---|---|---|
| 市场价（结算前 24h） | **0.152** | **0.844** |
| Jev 盲答（只给问题和规则） | 0.220 | 0.615 |
| Jev + 市场价 | 0.190 | 0.794 |

- Jev 90% 的答案挤在 0.2–0.45 区间，几乎不敢给极端概率。
- 喂市场价后，Jev 跟踪价格（秩相关 0.85）但把所有答案往 0.3 拉，72.6% 的市场误差变大。
- 逻辑回归融合给 Jev 权重 +0.20，总 Brier 0.150，与单独校准市场价持平。
- 全部请求花费约 $1.60，意味着你可以非常便宜地自己复现这个实验。

### 1.2 围绕 Jev 的 Polymarket 开源项目（均无公开回测）

- [eadst/polyjev](https://github.com/eadst/polyjev)（MIT）：Jev 盲判每个市场，logit 空间融合，¼-Kelly 排序；作者自述"未校准，无回测"。
- [markusbug/jevymarket](https://github.com/markusbug/jevymarket)：Jev 经 OpenRouter Decisions API，外加一个联网搜索的"研究员"LLM。
- [yorkeccak/model-vs-market](https://github.com/yorkeccak/model-vs-market)（MIT）：把 OpenAI Decisions、Jev、Cloudflare Clef 对比实时 Polymarket/Kalshi 价格，适合作为你的评估脚手架。
- [MojoAI-King/jev-paper-trader](https://github.com/MojoAI-King/jev-paper-trader)、[mehek-builds/prediction-market](https://github.com/mehek-builds/prediction-market)（AGPL）、[rikkooo/jev-trade](https://github.com/rikkooo/jev-trade)。
- 汇总列表：[awesome-jev finance](https://github.com/yibie/awesome-jev/blob/main/categories/finance-trading.md)、[madewithjev trading](https://madewithjev.com/categories/trading-and-markets)。

---

## 2. 开源替代决策模型：谁"超过了 Jev"

**重要前提**：下面所有"超过 Jev"的结果都来自**通用 typed-decision 基准**（Decision Index、typed-decisions、JevBench），不是预测市场基准。目前**没有任何一个 Jev 类模型发表过击败市场价格的预测结果**。Decision Index 没有单一公开托管方，分数由厂商自报（[explainx](https://explainx.ai/blog/top-10-decision-models-jev-perplexity-openai-open-source-ranked-2026)）。

| 开源模型 | 发布方 / 许可 | 对比 Jev 的榜单结果 | 日期 / 来源 |
|---|---|---|---|
| **StartLux-Decision-v1-27B**（另有 0.8B–9B 及 35B-A3B MoE） | StartLux Labs（中国）；代码 Apache-2.0，**权重 CC BY-NC 4.0（商用需另授权）** | Decision Index 0.2.1：**63.88 vs 57.91**，38 个子基准赢 31 个；JevBench 公开题 208/231 vs 199/231；国际象棋 256 局 58.4% vs 41.6% | 2026-09-30，[GitHub](https://github.com/StartLuxLabs/Startlux-Decision)（已直接核验）、[36kr](https://eu.36kr.com/zh/p/4009510615027849)、[新浪财经](https://finance.sina.cn/stock/jdts/2026-10-04/detail-initzrfn0478465.d.html) |
| **Laya**（421M ModernBERT-large，多语 322M） | Convai Innovations，Apache-2.0，HF 热榜第一 | typed-decisions 准确率 **0.766 vs 0.727**，ECE 0.081 vs 0.246，延迟 32.8 ms vs 236–276 ms；**Jev 数据来自第三方研究，非同机对比** | 2026-09-18，[官网](https://laya.convaiinnovations.com/)（已直接核验）、[新浪科技](https://finance.sina.com.cn/tech/roll/2026-09-23/doc-inisuhkm8573088.shtml)、[知乎](https://zhuanlan.zhihu.com/p/2085760548034167437) |
| **pplx-decider v1.1**（27B，Qwen3.8 底座） | Perplexity，Apache-2.0，HF 权重无门槛 | Decision Index 0.3/0.3.1：**#1 62.75 vs Jev 60.11（#3）**；v1 曾输（56.40 vs 57.91） | 2026-10-07，[systemonemodels.org](https://systemonemodels.org/models/pplx-decider/) |
| **OpenDecider-nano（~400M）/ -small（4B）** | manjunathshiva，Apache-2.0 | typed-decisions 0.796 vs Laya 0.766 vs Jev 0.754；可自托管模型中 ECE 最好 | 2026-09-27 / 10-03，[HF blog](https://huggingface.co/blog/manjunathshiva/opendecider-beats-laya-and-jev) |
| **openJev-verdict-2.0**（150M） | Heman10x-NGU，Apache-2.0 | 77.10% / Brier 0.0636 / ECE 0.0144 vs Jev 72.70% / 0.148 / 0.144 | [GitHub](https://github.com/Heman10x-NGU/openJev-verdict-2.0) |

**未超过但值得知道**：[jaredpalmer/kev](https://github.com/jaredpalmer/kev)（Apache-2.0，0.8B–27B，提供与 Jev 兼容的 `/v1/systemone` 端点，Kev-27B 0.851 vs Jev 0.857）；Cloudflare Clef（27B，Decision Index #19，换领域后崩）。

**反方证据**：在更宽的 [S1MB 榜](https://huggingface.co/blog/hotchpotch/system-one-mosaic-benchmark)（23 模型 × 137 基准，2026-09-30）Jev 1.13 Borda 86.51 仍是第一，开源最好的 bekko 76.21；[JevBench](https://jevbench.dev/) 也仍以 Jev 为 #1。另见 [JevOut 论文](https://arxiv.org/pdf/2609.30243)：自然语境可翻转决策模型输出，鲁棒性存疑。综述：[One Month After Jev](https://redreamality.com/blog/open-decision-models-2026-survey-benchmarks/)。

**对你的含义**：如果 Jev 在你的管线里只负责"把研究员 LLM 的材料压成一个校准概率"，那么 Laya / pplx-decider / OpenDecider 这类 Apache-2.0 模型是零成本、可本地部署、延迟更低的替代品，并且可以用你自己的 Polymarket 历史数据微调校准。但这一步并不是瓶颈，瓶颈是信息获取（见第 3、6 节）。

---

## 3. 真正的预测能力榜：开源权重模型 vs 市场价

### 3.1 Prophet Arena（UChicago，实时事件，1−Brier，2026-10-12 快照，4,347 个已结算事件）

[榜单](https://www.prophetarena.co/leaderboard)（已直接核验）、[论文](https://arxiv.org/abs/2510.17638)

| 排名 | 模型 | 1−Brier | 备注 |
|---|---|---|---|
| 1 | Agent Claude Fable 5.1 | 0.9491 | |
| 2 | Claude Fable 5.1 | 0.9483 | |
| 6 | **GLM-5.3** | 0.9479 | 开源权重（智谱，GLM-5.3 条件许可） |
| 10 | **DeepSeek V4 Pro 0813** | 0.9473 | 开源权重 |
| 14 | Claude Opus 5.5 | 0.9467 | |
| 15 | **Kimi K3** | 0.9466 | 开源权重（自定义许可） |
| 16 | **DeepSeek V4.1 Flash** | 0.9460 | 开源权重 |
| **18** | **Kalshi 市场基线** | **0.9456** | |
| 21 | Foresight V3（Lightning Rod） | 0.9446 | 专门的预测微调模型，反而低于市场 |
| 22 | **Hunyuan Hy3** | 0.9443 | Apache-2.0 |

要点：四个开源权重模型高于市场基线，但 #1 到 #22 总差距约 0.005 Brier。论文指出 LLM 的瓶颈是事件回忆不准、误读数据源，以及**临近结算时信息聚合慢于市场**。

### 3.2 ForecastBench（Forecasting Research Institute，固定提示词基线榜，Brier 越低越好）

[CSV](https://raw.githubusercontent.com/forecastingresearch/forecastbench-datasets/main/leaderboards/csv/leaderboard_baseline.csv)（已直接核验）

| 排名 | 模型 | Brier |
|---|---|---|
| 1 | 超级预报员中位数 | 0.104 |
| 2 | 公众中位数 | 0.140 |
| 3 | **kimi-k3-max-128k** | 0.145 |
| 4 | o3-scratchpad | 0.147 |
| 5 | **minimax-m3** | 0.150 |
| 6 | claude-sonnet-4-6 | 0.151 |
| 8 | gpt-5.5 | 0.153 |
| 49 | qwen3-235b-a22b | 0.169 |

要点：不带检索时，**没有任何 LLM 超过公众中位数**，更不用说超级预报员。带检索的 agent 榜上，Google DeepMind 条目 0.096–0.098 已达超级预报员水平（0.098），但开源底座的 agentic 条目尚无人提交。FRI 预计 LLM 与超级预报员持平的时间约在 2026-11（[FRI substack](https://forecastingresearch.substack.com/p/llms-are-closing-the-gap-on-human)）。

### 3.3 Metaculus FutureEval（季度 bot 锦标赛）

- Spring 2026：173 个 bot、297 题；职业预报员仍领先前十 bot 团队 1.25 分/题（p=0.247，不显著），10 位职业选手中 9 位赢过所有 bot（[结果](https://www.lesswrong.com/posts/wZBbDqzfBjYG58CxK/futureeval-spring-results-pros-beat-bots-but-the-gap-is)、[综述](https://forum.effectivealtruism.org/posts/Spyz3wESZu2eeqhDj/ai-forecasting-in-2026-what-11-analyses-say)）。
- 发现：**底层推理模型比脚手架更重要**；赢家平均用 1.7 个研究来源 vs 1.0。
- 最好的开源 bot：[nostreambot](https://github.com/No-Stream/metaculus-bot)（MIT，多前沿模型集成），Fall 2025 第 9、Spring 2026 第 10–11。
- 专门微调的预测模型（权重未公开）：Lightning Rod Foresight v3/v4（[博客](https://blog.lightningrod.ai/)）、Mantic（gpt-oss-120b RL 微调，Q2-2025 基准 38.6 → 45.8，[Thinking Machines](https://thinkingmachines.ai/news/training-llms-to-predict-world-events/)）。
- 开源权重 RL 预测模型：[OpenForecaster-8B](https://huggingface.co/nikhilchandak/OpenForecaster-8B)（MIT，Qwen3-8B + GRPO，约等于 DeepSeek-V3 水平，[论文](https://arxiv.org/pdf/2512.25070)）；Foresight Learning / Future-as-Label（Qwen3-32B Brier −27%，[arXiv](https://arxiv.org/html/2604.18576v5)）。

### 3.4 开源预测/决策 agent 框架

- [Metaculus/forecasting-tools](https://github.com/Metaculus/forecasting-tools)（MIT，活跃）：检索 → N 个独立 LLM 预测 → 聚合，是最成熟的开源预报 pipeline。
- [physicalreasoning/pm-decide "Isotherm"](https://github.com/physicalreasoning/pm-decide)（Apache-2.0）：Kalshi 温度市场的"市场价 + 气象模型 + 气候学"对数意见池，校准误差 0.003–0.005 vs 市场 0.013–0.020，密封测试 +$1,851（t=1.77）。**这是"模型 + 市场价先验"架构的最好范例**。
- [PolySwarm](https://arxiv.org/html/2604.03888v1)：50 个 LLM 人格、贝叶斯融合市场隐含概率、¼-Kelly，声称校准优于单模型，**无 P&L**。
- 量化框架（FinRL / Qlib / TradingAgents / FinGPT）：**没有找到任何面向 Polymarket 的维护中分支**。

---

## 4. Polymarket 2026 技术栈现状（接入层）

> 2026-04-28 CLOB V2 上线，**无向后兼容**：V1 签名订单被拒，`py-clob-client` / `@polymarket/clob-client` 已归档失效。2026-05-04 起新账户默认 Deposit Wallet（signature type 3）。Data API v2 于 2026-09-04 上线。Protocol V2（PositionManager、position ID 取代 CTF token ID、OracleAggregator 整合 Chainlink + UMA）2026-10-05 公布，新市场暂定 2026-11-02 切换，Data API v1 据报 2026-10-24 退役。来源：[V2 migration](https://docs.polymarket.com/v2-migration)（已直接核验）、[changelog](https://docs.polymarket.com/changelog/predictions)、[CoinGape](https://coingape.com/polymarket-unveils-protocol-v2-targets-nov-2-switch-to-a-single-pusd-market)。全部文档索引：https://docs.polymarket.com/llms.txt

### 4.1 API 一览

| API | Base URL | 用途 |
|---|---|---|
| CLOB | `https://clob.polymarket.com` | 订单簿、价格、下单/撤单、API key、余额/授权 |
| Gamma | `https://gamma-api.polymarket.com` | 市场/事件发现与元数据 |
| Data API v2 | `https://data-api.polymarket.com/v2` | 持仓、活动、PnL、公开成交、持有人、OI、结算状态 |
| WebSocket | `wss://ws-subscriptions-clob.polymarket.com/ws/market` 和 `/ws/user` | 实时订单簿/价格/成交，用户订单事件 |
| Relayer | `https://relayer-v2.polymarket.com/submit` | 免 gas 链上操作（授权、split/merge/redeem、session key） |

来源：[CLOB OpenAPI](https://docs.polymarket.com/api-spec/clob-openapi.yaml)、[Discover Markets](https://docs.polymarket.com/market-data/discover-markets)、[Wallet Activity](https://docs.polymarket.com/trading/wallet-activity)、[Real-Time Data](https://docs.polymarket.com/market-data/realtime-data)。

### 4.2 认证与钱包

- **L1**：EIP-712 签名（domain `ClobAuthDomain`，chainId 137）→ `POST /auth/api-key` 或 `GET /auth/derive-api-key` → 得到 `apiKey / secret / passphrase`。
- **L2**：HMAC-SHA256(`timestamp + METHOD + path + body`)，请求头 `POLY_ADDRESS / POLY_SIGNATURE / POLY_TIMESTAMP / POLY_API_KEY / POLY_PASSPHRASE`。所有下单/账户端点和用户 WS 都要 L2。
- **签名类型**：0 EOA（仅白名单，需自付 POL gas）；1 POLY_PROXY（旧 Magic/Google 登录）；2 GNOSIS_SAFE（旧浏览器钱包）；**3 POLY_1271 Deposit Wallet（2026-05-04 后默认）**，支持 **Session Keys**：独立签名 EOA，可下单、**不能提现**，180 天固定到期，撤销即撤单。这是 bot 的推荐隔离原语。
- `funder` = 持有资金的钱包地址（settings 页可查），对 1/2/3 与签名者不同。统一 SDK 自动识别。

来源：[CLOB Authentication](https://docs.polymarket.com/developers/CLOB/authentication)、[Wallets & Auth](https://docs.polymarket.com/trading/wallets-auth)、[Session Keys](https://docs.polymarket.com/trading/session-keys)。

### 4.3 官方 SDK（只用这些）

| 库 | 状态 | 版本 |
|---|---|---|
| `polymarket-client`（Python，[py-sdk](https://github.com/Polymarket/py-sdk)） | **当前统一 SDK**，同步+异步，Python ≥3.11 | 0.13.0（2026-10-09，[PyPI](https://pypi.org/project/polymarket-client/) 已直接核验） |
| `@polymarket/client`（TS，[ts-sdk](https://github.com/Polymarket/ts-sdk)） | **当前统一 SDK** | 0.13.0 |
| `polymarket_client_sdk_v2`（Rust） | 维护中 | 0.8.0 |
| `py-clob-client-v2` / `@polymarket/clob-client-v2` | 旧 V2 CLOB-only，仍可用但官方建议新项目用统一 SDK | 1.2.0 |
| `py-clob-client` / `@polymarket/clob-client` | **已归档，生产不可用** | — |

官方 [Quickstart](https://docs.polymarket.com/trading/quickstart) 最小下单：

```python
from polymarket import AsyncSecureClient
client = await AsyncSecureClient.create(
    private_key=os.environ["POLYMARKET_PRIVATE_KEY"],
    wallet=os.environ["POLYMARKET_WALLET_ADDRESS"],   # funder / deposit wallet
)
market = await client.get_market(slug="...")
yes = market.outcomes[0]
asset_id = yes.position_id if market.version == "v2" else yes.token_id
resp = await client.place_limit_order(asset_id=asset_id, side="BUY", price="0.52", size="10")
await client.wait_for_order_fill_settlement(resp)
```

### 4.4 订单机制

- 类型：限价 `GTC`、`GTD`（到期前 1 分钟失效，至少 3 分钟后）；市价 `FAK`（能成多少成多少）、`FOK`（全成或全撤）；`post_only` 标志。
- Tick size 0.01 / 0.001 / 0.0001 按市场；最小下单量 `orderMinSize`。
- 资产 ID：CTF（v1）市场用 ERC-1155 `tokenId`；Protocol V2 市场用 `positionId`。Gamma 字段 `version` 区分。
- 抵押品 **pUSD**（6 位小数，`0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB`），1:1 包装 USDC.e，通过 CollateralOnramp `0x93070a847efEf7F70739046A929D47a521F5B8ee` 的 `wrap()` 换入（[pUSD](https://docs.polymarket.com/concepts/pusd) 已直接核验）。
- 需要 6 个授权（pUSD 对三个 Exchange；PositionManager 和 Conditional Tokens 的 `setApprovalForAll`），SDK 有 `get_trading_approvals_state`。
- 订单状态 `live / matched / delayed / unmatched`；成交 `MATCHED → MINED → CONFIRMED`。部分加密/金融市场有 150–250 ms 吃单延迟。
- Neg-risk 多结果事件：一个市场的 NO 可转换成其他所有市场的 YES；`negRisk` 标志决定路由到哪个交易所合约，**漏掉会把订单发到错误合约**。

来源：[Place Orders](https://docs.polymarket.com/trading/place-orders)、[Order Lifecycle](https://docs.polymarket.com/concepts/order-lifecycle)、[Negative Risk](https://docs.polymarket.com/concepts/negative-risk)、[Contracts](https://docs.polymarket.com/resources/contracts)。

### 4.5 费用（已直接核验官方页面）

- 公式：`fee = C × feeRate × p × (1 − p)`，C 为股数，p 为价格。**只有吃单方付费，挂单方永远免费**。
- 吃单费率：加密 0.07；体育 0.05；经济/文化/天气/其他 0.05；金融/政治/提及/科技 0.04；**地缘政治 0（免费）**。
- 例：加密市场 100 股 @ $0.50 → 费用 $1.75（3.5% 的名义额）。费用在 p=0.5 时最大，在极端价格趋近于 0。
- 挂单返佣（每日 pUSD）：加密 20%、体育 15%、其他 25%。吃单返佣按 30 日加权成交量分 3%–50%。
- Builder 费：接入方可另加 0–100 bps 吃单 / 0–50 bps 挂单。
- Gas：订单链下签名，运营方提交撮合；Deposit/Proxy/Safe 钱包经 relayer 免 gas，EOA 需 POL。

来源：[Fees](https://docs.polymarket.com/trading/fees)、[Maker Rebates](https://docs.polymarket.com/programs/maker-rebates)、[Taker Rebates](https://docs.polymarket.com/programs/taker-rebates)。注意：网上流传的带指数的旧公式（sports 0.0175 / crypto 0.25 等）是 2025 年旧版，已被 2026-03-30 的"Fee Structure V2"取代。

### 4.6 限流（10 秒滑动窗口，按 IP + Cloudflare 位置；超限为节流/排队）

- 全局 15,000/10s；CLOB 一般 9,000/10s；`/book` `/price` `/midpoint` 各 1,500；`/prices-history` 1,000。
- 下单（每签名者令牌桶，突发/10s | 持续/10min）：`POST /order` 5,000 | 120,000；`POST /orders`（批量 1–15）2,000 | 21,000；`/cancel-all` 250 | 6,000。
- Gamma 4,000/10s（`/markets` 300，`/events` 500）；Data API v2 800/10s。
- 2026-08 起令牌桶与 30 日成交量挂钩，要处理 `Poly-RateLimit-Warning` / `Retry-After`。Cloudflare 会拦截很多数据中心 IP 的 POST。
- Relayer `/submit` 25/min；Builder 层级 100 / 10,000 / 无限 tx/天。

来源：[Rate Limits](https://docs.polymarket.com/api-reference/rate-limits)、[Builder Tiers](https://docs.polymarket.com/programs/builders/tiers)。

---

## 5. 数据层：决策模型需要什么

### 5.1 市场发现（Gamma）

- 层级：event → markets → outcomes（每个 outcome 一个 ID）。
- `GET /markets` 关键字段：`question, description（结算规则！）, resolutionSource, conditionId, endDate, liquidityNum, volumeNum, spread, bestBid, bestAsk, lastTradePrice, outcomePrices, clobTokenIds / positionIds, version, negRisk, orderPriceMinTickSize, orderMinSize, acceptingOrders, feesEnabled, feeSchedule, umaResolutionStatus, closed`。
- 常用过滤：`/events?active=true&closed=false&order=volume&ascending=false`，`tag_slug`。
- 注意 `outcomes / outcomePrices / clobTokenIds` 在实际响应里是 JSON 编码的字符串（社区报告，需在实际响应上确认）。

来源：[list-markets](https://docs.polymarket.com/api-reference/markets/list-markets.md)、[list-events](https://docs.polymarket.com/api-reference/events/list-events.md)。

### 5.2 历史数据（回测）

- Data API v2 `GET /v2/prices-history`：一次只能用一种窗口（`start/end`、`interval`、`as_of`）；`interval=max` 回溯到 2022，12 小时桶；显式窗口最多 15 天；游标分页，每页 10,000。**空响应不等于无价格变动**。
- `GET /v2/trades`：`condition`（≤20）、`taker_only`（默认 true，每笔只在吃单侧出现一次）。
- `GET /v2/resolutions`：`status ∈ {initialized, posed, proposed, challenged, reproposed, disputed, resolved}`、`was_disputed`、`payouts`。**这是回测的 ground-truth 标签来源**。
- 大规模公开数据集：
  - [SII-WANGZJ/Polymarket_data](https://github.com/SII-WANGZJ/Polymarket_data)：279 GB 链上数据，66 亿条记录，400 万市场，2022-11-21 → 2026-10-04，parquet。
  - [Polymarket-v1 Database](https://arxiv.org/abs/2606.04217)：12 亿笔成交，130 万市场，100% 链上真实主动方向（HF 可能需要申请）。
  - [CH4RL3I/honest-odds](https://github.com/CH4RL3I/honest-odds)：2,946 个已结算二元市场样本 + 校准分析代码。
  - Tick 级 WS 归档：[Tardis.dev](https://docs.tardis.dev/historical-data-details/polymarket)（2026-05-25 起，每月首日免费）。
  - Dune `polymarket_polygon.*`。
- Goldsky 旧 subgraph 在 V2 后"返回不完整或错误数据"，已不推荐（[Goldsky](https://docs.goldsky.com/chains/polymarket.md)）。

### 5.3 结算（UMA Optimistic Oracle）

- 任何人提议结果并押 ~$750 pUSD 保证金 → 2 小时挑战期 → 无争议约 2 小时结算；单次争议走 re-propose；双重争议进 UMA DVM 投票（24h commit + 24h reveal，需 65% 质押 UMA 多数）。可能结果包括"Too Early"和"50/50"（每股 $0.50）。加密 Up/Down 市场改用 Chainlink TWAP。
- 实证（18,427 市场）：结束到结算中位数 41 分钟，p90 6.4 小时，p99 4 天；争议率 1.0%（NBA 0.2% → 地缘政治 4.8%）；**43% 的争议源于规则措辞**。
- 著名争议：2025-03 乌克兰矿产协议（无协议却结算 YES，单一持有人约 25% 投票权，Polymarket 不退款）；2025-07 泽连斯基西装（$237M，结算 NO）。
- **对模型的含义**：以 `description` + `resolutionSource` 为目标定义而非 `question`；按类别和主观措辞（"consensus of credible reporting"、"officially"）附加"规则歧义先验"；为 50/50 和 Too Early 预留概率；把"UMA 投票风险"当作独立于真实事件的风险；neg-risk 事件约束 YES 价格之和 ≈ 1，忽略占位结果；用 `/v2/resolutions` 查结算状态而不是看价格是否到 0.99。

来源：[Resolution](https://docs.polymarket.com/concepts/resolution)、[UMA](https://docs.uma.xyz/protocol-overview/how-does-umas-oracle-work)、[PolySyncer](https://www.polysyncer.com/blog/polymarket-resolution-time-2026)、[Decrypt](https://decrypt.co/311634/polymarket-allegations-oracle-manipulation)。

### 5.4 实时数据（WebSocket）

- 订阅：`{"assets_ids":[...],"type":"market","custom_feature_enabled":true}`；每 10 秒发文本 `PING`。
- 消息：`book`（全量快照，订阅时和影响簿的成交后推）、`price_change`（`size` 是**绝对档位量，不是增量**）、`last_trade_price`、`tick_size_change`、`best_bid_ask`、`market_resolved`。
- 本地订单簿：用 `book` 或 REST `/book` 初始化，`price_changes[]` 逐档替换（size==0 删除），收到新 `book` 或 hash 不一致即重同步。官方没有给出算法，这是从消息形状推断的。
- 公开 feed 的 `side` 推断主动方向只有约 59% 准确，不要用于判断主动买卖（[arXiv 2604.24366](https://arxiv.org/abs/2604.24366)）。

### 5.5 微观结构与校准事实（决定你的最小 edge 阈值）

- 中间价区间 [0.4, 0.6] 的**全价差中位数约 400 bps**；最低概率分位的半价差 650–900 bps；深度不集中在最优档；有效做市商约 32 家（[Dubach](https://philippdubach.com/posts/the-anatomy-of-a-decentralized-prediction-market-notes-from-the-polymarket-order-book/)）。
- 可执行量很小：NBA 盘中组合套利机会 76.9% 受限于平均仅 14.8 股（[arXiv 2605.00864](https://arxiv.org/abs/2605.00864)）。
- 校准结论互相冲突、依赖分组：Cardozo（5.88 亿笔）发现 <10c 买入每美元亏 19.3c（加密、政治显著，体育不存在）；honest-odds 发现 7 天前价格"略偏温和"，10–20c 桶实际 YES 18.2% vs 定价 14.0%，但再校准策略扣费后置信区间都包含 0；Le 发现政治市场持续**低自信**（价格向 50% 压缩）。
- 只有 3.14% 的账户是"有技能的赢家"，67% 的账户承担全部亏损（[The Block](https://www.theblock.co/post/398902/skilled-polymarket-traders-are-a-3-minority-and-everyone-else-funds-their-gains-study)）。
- 刷量：Columbia 研究估计全时段约 25% 成交量为 wash trading，部分周 >90%；**基于成交量的流动性过滤和"巨鲸跟单"特征都被污染**（[CoinDesk](https://www.coindesk.com/markets/2025/11/07/polymarket-s-trading-volume-may-be-25-fake-columbia-study-finds)）。
- 跨平台等价市场平均 2–4% 价差（[arXiv 2601.01706](https://arxiv.org/abs/2601.01706)）。

### 5.6 补充数据源

Kalshi API（`api.elections.kalshi.com/trade-api/v2`，K 线无需认证）、Metaculus API（需 token，社区聚合预测）、Manifold（`api.manifold.markets`，500 req/min）、Adjacent News（跨 4 平台 40,000+ 市场）、Polymarket Analytics / Dune 看板。

---

## 6. 决策模型 → 订单：管线设计模式

综合 [HackMD Kelly bot](https://hackmd.io/@bosonax/S13BwdrqMl)、[poly-maker](https://github.com/warproxxx/poly-maker)、[PolySwarm](https://arxiv.org/abs/2604.03888)、[pm-decide](https://github.com/physicalreasoning/pm-decide)、官方费用文档：

1. **Edge 定义**：`edge = p_model − p_executable`，其中 `p_executable` 是**沿订单簿实际能成交的价格，不是中间价**。净 edge = edge − 吃单费 − 预期滑点 − 执行缓冲。
2. **市场价作为先验**：把市场价当贝叶斯先验，模型输出向其收缩（PolySwarm 的置信加权融合；pm-decide 的对数意见池）。Jev 实验表明如果融合后 Brier 不优于单独校准市场价，模型就没有信息增量，**这是上线前必须通过的门槛测试**。
3. **交易门槛**：仅当 `fair − executable > taker_fee + half_spread + min_edge` 且价差 ≤ 上限、下单量 ≤ 可清算深度的某个比例时交易。社区常用 3–5 美分绝对 edge，但这是经验值，必须自己校准。因为费用曲线非线性，建议**按入场价格桶分别统计 P&L**。
4. **仓位**：Kelly `f* = (p·b − q)/b` 作为**上限**；常用 ¼ 到 ½ Kelly；可按模型 Brier 把系数在 0.10–0.40 间缩放；最终 `size = min(Kelly, 流动性上限, 单市场上限, 组合上限, 回撤上限)`。
5. **相关市场**：每份指南都点名的最大失败模式。做法：不同时持有逻辑关联市场的两侧；neg-risk 事件组设置**最坏情况敞口上限**；用 [Saguillo et al.](https://arxiv.org/abs/2508.03474) 的 LLM 依赖检测找组合约束。没有找到开源的多变量 Kelly 实现。
6. **限价 vs 市价**：默认在价差内一档挂 `post_only` 限价（零费用 + 返佣）；只有 edge 超过费用+滑点且随时间衰减（新闻、预言机延迟）时才用 FOK/FAK；用 GTD 在已知事件前到期，避免陈旧报价。
7. **逆向选择**：按成交的 markout EWMA 在被"捡"的市场拉宽价差/缩量（poly-maker）；VPIN + 盘口失衡 + 成交量 z-score 熔断（≥97 分位停，≥85 分位价差 ×2）；WS 陈旧或"新闻状态"时撤单；避开已知内幕暴露的市场（军事行动、公司公告）。
8. **执行安全**：幂等下单（客户端 order id 去重）；`negRisk` 路由校验；CLOB 撮合约 100 ms 但链上 ERC-1155 转移约 2 秒，**不要在确认前卖出**（"幽灵成交"）；neg-risk 市场可能出现卖不掉的 token。

---

## 7. 可参考的开源实现（按用途）

| 用途 | 项目 | 状态 / 备注 |
|---|---|---|
| **离线评估 / 纸面交易** | [agent-next/polymarket-paper-trader](https://github.com/agent-next/polymarket-paper-trader) | 活跃，497 星；用真实订单簿模拟成交，套用官方费用曲线；**最适合作为第一步** |
| 模型 vs 市场价评估 | [yorkeccak/model-vs-market](https://github.com/yorkeccak/model-vs-market) | MIT；对比 Jev / OpenAI Decisions / Clef 与实时价格 |
| 做市（CLOB V2，带风控） | [warproxxx/poly-maker](https://github.com/warproxxx/poly-maker) | 1.5k 星，MIT，实盘验证，83 测试；微价格 + 流向 EWMA、markout 逆选、neg-risk 敞口上限、日亏损 kill switch |
| 官方做市参考 | [Polymarket/poly-market-maker](https://github.com/Polymarket/poly-market-maker) | 活跃，"实验性" |
| 多策略 Rust 工具箱 | [HarrierOnChain/Prediction-Markets-Trading-Bot-Toolkits](https://github.com/HarrierOnChain/Prediction-Markets-Trading-Bot-Toolkits) | 477 星，默认 `enable_trading=false` |
| MCP（给 Claude/Cursor 用） | [caiovicentino/polymarket-mcp-server](https://github.com/caiovicentino/polymarket-mcp-server)（689 星，45 工具，默认关自动交易，$1k 单笔 / $5k 敞口上限）；[IQAIcom/mcp-polymarket](https://github.com/IQAIcom/mcp-polymarket) | 社区维护 |
| 官方 agent 框架 | [Polymarket/agents](https://github.com/Polymarket/agents) | **2026-05-11 已归档**，用 V1 客户端，仅作架构参考 |
| 预报 pipeline | [Metaculus/forecasting-tools](https://github.com/Metaculus/forecasting-tools) | MIT，活跃 |
| 官方 agent skill | [Polymarket/agent-skills](https://github.com/Polymarket/agent-skills) | 认证/下单说明 |

共同模式：**模型 → 概率 → 对比可执行价 → 仓位 → 官方 SDK 签名下单**。LLM-agent 类框架几乎都没有认真的仓位/风控层；只有 poly-maker 和 Harrier 内置了敞口控制。

---

## 8. 失败模式与实证（必读）

### 8.1 AI bot 实盘结果

| 研究 / 案例 | 设置 | 结果 |
|---|---|---|
| [Prediction Arena](https://arxiv.org/abs/2604.07355)（Arcada Labs + Harvard，2026-03） | 6 个前沿模型各 $10k 真钱，57 天，Kalshi + Polymarket 实盘 | Kalshi **−16.0% 到 −30.8%**；Polymarket 平均 **−1.1%**；"研究量与收益无相关" |
| [PolyBench](https://arxiv.org/abs/2604.14199)（2026-04） | 38,666 个二元市场，7 个 LLM，时间戳锁定订单簿 | **仅 2/7 盈利**（MiMo-V2-Flash +17.6%，Gemini-3-Flash +6.2%），其余 5 个"在一致的高自信下亏钱" |
| [Foresight-32B](https://blog.lightningrod.ai/p/foresight-32b-beats-frontier-llms-on-live-polymarket-predictions)（2025-08） | 251 个实时 Polymarket 问题，不看市场价 | 模型 Brier 0.199 vs **市场 0.170**：最好的模型也不如它要对抗的价格 |
| [LiveTradeBench](https://arxiv.org/abs/2511.03628) | 21 个 LLM，50 天 | "LMArena 高分不意味着交易结果好" |
| "我真给了 AI 钱"（[startupfortune](https://startupfortune.com/i-actually-gave-an-ai-money-to-trade-on-polymarket-heres-what-nobody-on-twitter-wants-you-to-know/)，2026-02） | $23，46 小时，140 笔 | 剩 $1.50；损失主要来自**卖不掉的 neg-risk 仓位**，不是信号 |
| 盈利自述（dev.to、substack） | 多为加密 5/15 分钟市场的动量/套利 | 未审计；高胜率与套利特征（多小赢、偶大亏）一致，不是预测 edge |

**结论**：没有公开、独立验证的 LLM 预测 bot 在 Polymarket 上以有意义的样本量盈利。可验证的 bot 利润来自套利/做市/延迟（[Saguillo et al.](https://arxiv.org/abs/2508.03474) 估计 2024-04 至 2025-04 套利提取上限约 $40M），且平台正在主动压缩这些（15 分钟加密市场加吃单费、2026-08-07 起 TWAP 结算、按成交量分层限流）。约 70% 的地址净亏损，bot 利润 77% 来自加密 Up/Down 市场（二手来源）。

### 8.2 其他失败模式

- **结算/预言机风险**：UMA 投票权集中（WSJ：争议市场 >50% 投票来自前十钱包）；MOOV2 后错误提案降 59%，但集中度仍在。
- **内幕市场**：2026-04 美国士兵因用 Polymarket 押注机密的马杜罗行动获利 $409k 被起诉，首例预测市场内幕交易案。任何挂单在这类市场都是被逆向选择的。
- **API 变更**：V2 切换后约 57.8% 的 bot 型钱包四天内沉默；Protocol V2 在 11 月还会再改一次标识符。
- **封号**：2026-04 "ghost fill" 执法封了一批刷下单/撤单的账户集群；Deposit Wallet 系统阻止批量开户；VPN 绕过 → close-only 或永久封禁。
- **供应链攻击专门针对 bot 开发者**（2026）：被劫持的 `dev-protocol` GitHub 组织发布带后门的 copytrading bot（偷 `.env` + SSH 后门）；朝鲜归因的 npm 包 `sleek-pretty` 在 `require()` 时偷 CLOB 凭证和私钥；`polymarketdev` 发布 9 个恶意 npm 包（含 `polymarket-claude-code`）；2026-06-25 第三方供应商被攻破，polymarket.com 前端被注入脚本，11–15 个钱包被恶意授权抽走 $2.9M。来源：[StepSecurity](https://www.stepsecurity.io/blog/malicious-polymarket-bot-hides-in-hijacked-dev-protocol-github-org-and-steals-wallet-keys)、[Panther](https://panther.com/blog/polymarket-trader-funds-at-risk-dprk-npm-package-steals-wallet-keys)、[SafeDep](https://safedep.io/malicious-polymarket-npm-crypto-wallet-drainer/)。

---

## 9. 法律、合规与运营约束（信息性参考，非法律意见）

### 9.1 两个独立产品

| | polymarket.com（国际版） | Polymarket US |
|---|---|---|
| 运营实体 | Adventure One QSS, Inc.，ToS 2026-08-11 生效，巴拿马法律 + 巴拿马仲裁 | QCX LLC（CFTC 监管 DCM）+ QC Clearing（DCO）；2025-07-09 获批 |
| 抵押品 | pUSD（Polygon） | 美元（借记卡、ACH、PayPal、电汇） |
| 用户 | 非"受限人士"即可；**主平台无 KYC**（2026-05-28 官方确认），但 ToS §4.3 可随时要求身份信息 | 仅美国居民，交易前完整 KYC（SSN 等） |
| API | 公开 CLOB/Gamma/Data | REST + WS（Ed25519 签名），KYC 后在 polymarket.us/developer 开 key，25 req/s |

**美国人士（或由美国人士指挥/控制的 bot）只能用 Polymarket US。** 官方 agents README 明确写道：ToS 禁止美国及部分司法区人士通过 UI 和 API 交易，"包括由受限司法区人士开发的 agent"。

### 9.2 地区限制（[geoblock 页](https://docs.polymarket.com/api-reference/geoblock) 已直接核验，ToS §4.1 指向此页）

- **完全封锁（无法开仓也无法平仓）**：伊朗、叙利亚、古巴、朝鲜、克里米亚、顿涅茨克、卢甘斯克。
- **只能平仓，前端和 API 都限制**：**美国、台湾、新加坡**、英国、法国、德国、意大利、波兰、比利时、澳大利亚、加拿大（BC/安大略/阿尔伯塔/魁北克）、新西兰、泰国、俄罗斯、白俄罗斯、巴西等 35+。
- **只能平仓，仅前端（API 不限）**：爱尔兰、**日本**、马耳他（仅体育）、荷兰、韩国。
- **中国大陆、香港：不在任何 Polymarket 限制名单上。** 但：香港证监会下属 IFEC 于 2026-04-17 警告在 Polymarket/Kalshi 交易"可能构成非法赌博"（[The Standard](https://www.thestandard.com.hk/finance/article/329624/Trading-on-prediction-markets-may-be-illegal-in-Hong-Kong-SFC-says)）；大陆的障碍是国家层面的加密货币交易禁令和网络管制，不是 Polymarket 的封锁。
- ToS §1 另列匈牙利、斯洛文尼亚；帮助中心的 39 国列表与上述略有出入。以 ToS + geoblock 页为准，随时可能无通知变更。
- 执法：`GET https://polymarket.com/api/geoblock` 返回 `{blocked, ip, country, region}`；钱包筛查（制裁、受限司法区）；ML 多账户协同检测；2026-05 起对可疑/高额账户选择性要求 ID。**VPN 绕过"严格禁止"，钱包会被置为 close-only。**

### 9.3 ToS 中与 bot 相关的条款（polymarket.com，2026-08-11 版）

- 通过 API 连接即视为接受条款（§1）。
- **没有条款禁止自动化交易本身**；§4.2 禁止爬虫抓取数据、"过载/损害"站点；限流有文档，说明 API 交易在限额内是被预期的；官方文档有"Market Making"页面。
- **机构数据限制（§4.2）**：若你是"Capital Market Client"（经纪、做市、**自营交易**、对冲基金、金融科技等），未经书面同意不得通过 API 或链上访问数据。个人开发者不在此列，但如果以公司/基金身份运营需要注意。
- 禁止：spoofing、front-running、虚假成交、wash trading、串通影响价格、三类内幕交易、"任何公司自行裁量认为滥用/不当/破坏性的交易"。
- 处罚：终止访问、取消奖励资格、配合执法；§3.2 可随时把功能改为"仅允许平仓"。
- 责任上限 $100（§7.3）；强制个人仲裁 + 集体诉讼弃权，30 天内可邮件退出（§9.10）。

### 9.4 运营前置条件

- 钱包：新账户默认 Deposit Wallet（免 gas，支持 Session Key）；EOA 直接交易需白名单且自付 POL。
- 入金：`POST /deposit` 跨链桥（Ethereum / Solana / Base / Arbitrum 等，USDC 自动包装为 pUSD；ETH 链最低 $20，Solana $3），或在 Polygon 上持 USDC.e 直接 `wrap()`。
- 出金：pUSD → USDC 到多链，"即时免费"，>$50k 建议拆分。
- 授权：6 个 approve（见 4.4），**只授权打算冒险的金额**，授权是 2026-06 事故的抽款向量。

### 9.5 安全实践

- 用 **Session Key**（可下单、不能提现、180 天到期）或专用低余额 EOA 跑 bot；Deposit Wallet 的 owner key 离线。
- 凭证只放环境变量 / 密钥管理器，`chmod 600 .env`，`npm install --ignore-scripts` 安装不可信包，审计 lockfile 中的 typosquat 和 postinstall 脚本。
- 出站白名单只允许 Polymarket 端点 + RPC。先用假 key 跑一遍看日志里凭证流向。
- 拒绝任何索要助记词的 bot；Polymarket 员工不会索要私钥。
- 清单：[dev.to 15 分钟检查表](https://dev.to/andreyschurko/before-you-give-a-polymarket-bot-your-private-key-a-15-minute-checklist-1774)。

### 9.6 税务（一段话，信息性）

ToS 把税务责任完全放在用户身上；polymarket.com 不出具任何税表；每次结算或卖出都是应税事件；用 USDC/pUSD 结算会叠加一层加密资产的成本基础追踪。非美国运营者按居住地规则（例如香港的赌博 vs 投资定性）。无论如何保留逐笔链上记录。

---

## 10. 风险评审（按 prediction-market-risk-review 输出契约）

**评审范围**：把 Jev（或开源替代决策模型）作为信号源，通过 Polymarket CLOB V2 API 自动下单的方案；本报告本身为信息性，不含买卖建议。

| 门槛 | 结论 | 说明 |
|---|---|---|
| 建议边界 | PASS | 报告不含具体买/卖/仓位建议；交易决策点保留给人 |
| 平台与监管边界 | **WARN** | 用户所在地未知。台湾/新加坡/美国不可开仓；香港有监管警告；大陆有国家级限制。需在开工前确认运营者和资金所在司法区，并以 `/api/geoblock` 实测 |
| 数据质量 | **WARN** | 成交量被 wash trading 污染；公开 feed 主动方向只 59% 准；结算延迟 p99 4 天；2026-11 标识符再变 |
| 信号质量 | **FAIL（Jev 单独）** | 独立实测 Jev 无信息增量；需换成检索增强预报 + 市场先验架构并通过"融合后优于校准市场价"的门槛测试 |
| 安全 | **WARN** | 2026 年多起专门针对 bot 开发者的供应链攻击；必须 Session Key + 最小授权 + 依赖审计 |
| 隐私 | PASS | 本报告未使用任何用户私有数据或凭证 |

**被阻止的动作**：本次未请求也未执行任何下单、授权、入金或凭证操作。

**必需的缓解措施（上线真钱前）**：
1. 司法区确认 + geoblock 实测；不用 VPN。
2. 用 polymarket-paper-trader 或自建回放，在**真实订单簿 + 官方费用曲线**上回测；样本量参考 Foresight Arena 的功效分析：要检出 0.02 Brier 的真实 alpha 需约 350 个已结算预测（80% 功效），0.01 需 4 倍。
3. 门槛测试：融合模型的 Brier 必须显著优于"校准后的市场价"。
4. 独立于模型输出的硬性限制：单笔上限、日亏损上限、组合敞口上限、neg-risk 事件组最坏敞口上限、连续亏损熔断、WS 陈旧熔断。
5. Session Key 隔离、最小授权、依赖审计、出站白名单、全量决策审计日志（不只记成功下单）。
6. 人工审批模式起步（如 MCP 的"确认 >$500"），小额真钱（如 <$100）跑至少数百笔后再放大。

**安全的下一步**：先做离线评估，不接执行。

---

## 11. 建议架构与分阶段路线（信息性）

```
[数据层]                     [信号层]                         [执行层]
Gamma 市场发现  ──┐     检索(新闻/Kalshi/Metaculus)         风控门(费用/价差/深度/相关性)
Data API v2 历史 ──┼──►  预报模型(开源权重 agent 或 Jev 类) ──► 仓位(≤¼ Kelly, 多重上限) ──► 官方 SDK
WS 本地订单簿   ──┘     市场价先验融合 + 校准                  post_only 限价优先 / Session Key
/v2/resolutions 标签     门槛测试: Brier < 校准市场价            幂等 + negRisk 路由校验 + 审计日志
```

| 阶段 | 目标 | 交付物 | 退出标准 |
|---|---|---|---|
| 0. 数据与评估 | 拉取 SII-WANGZJ 或 Data API v2 历史 + 结算标签；复现 Jev 的 26k 市场实验，并对 Laya / pplx-decider / OpenDecider、以及带检索的 GLM-5.3 / DeepSeek V4 / Kimi K3 做同样测试 | 评估脚本（可基于 model-vs-market）、按类别和价格桶的 Brier/AUC 表 | 至少一个配置在扣费后显著优于校准市场价 |
| 1. 纸面交易 | 接 WS 实时簿，用 paper-trader 模拟成交和费用 | 实时信号 → 模拟订单的完整管线、审计日志 | ≥350 个已结算预测，P&L 置信区间不含 0 |
| 2. 接入执行（只读 → 小额） | 统一 SDK + Session Key，人工审批模式 | 风控门、硬限制、熔断、幂等下单 | 数百笔小额真钱，与纸面结果一致 |
| 3. 放大 | 按成交量进入返佣分层，挂单为主 | 按类别/价格桶的持续监控 | 回撤和逆选 markout 在阈值内 |

模型选择上，Prophet Arena 与 ForecastBench 的证据都指向：**带检索的强推理模型 > 脚手架 > 专用小型决策模型**。Jev/Laya 类模型适合做管线末端的"快速、便宜、结构化"打分器，不适合做唯一信号源。

---

## 12. 方法与未验证项

**方法**：5 个并行研究线程（API 技术栈、数据与结算、AI/agent 交易实证、法律与运营、Jev 与开源替代），每线程 70–93 次搜索/抓取；主线程对以下关键声明做了二次直接核验：CLOB V2 切换与无兼容、pUSD 为强制抵押品、`polymarket-client` 0.13.0 为官方包、官方费用公式与费率、Jev 的身份与形态（DataCamp）、StartLux 的 README 数据、Jev 26k 市场实测数据、Laya 官网数据、Prophet Arena 榜单、ForecastBench CSV、geoblock 三级名单。

**未验证 / 需注意**：
- 你记忆中"超过 Jev"的具体榜单无法确定是 StartLux / Laya / pplx-decider 中哪一个；Jev 基线分数因来源不同（0.727 / 0.754 / 72.7%）。
- Decision Index 无单一公开托管，分数厂商自报；StartLux 权重 CC BY-NC，严格说不算开源商用。
- Protocol V2 的 2026-11-02 切换和 Data API v1 2026-10-24 退役仅见于 CoinGape，官方 changelog 抓取时未见。
- polymarket.com ToS 原文经 Google Doc 导出获取；帮助中心引用的章节号与 2026-08 版本不一致。
- 日本等"仅前端限制"是政策还是实现漏洞不明。
- 多个 bot 自述盈利数字未经审计；"$7.6M 狙击利润"、"bot 利润 77% 来自加密市场"为二手来源。
- Gamma 的 `outcomes / clobTokenIds` 为 JSON 字符串是社区报告。
- WebSocket 连接数/速率限制官方未列出。
- 本地订单簿更新算法是从消息形状推断的，官方未给出。
- 大陆法律风险总结自第三方站点，非一手法规。

*本报告为信息性研究，不构成投资、法律或税务建议。*
