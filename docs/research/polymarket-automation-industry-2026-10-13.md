# Polymarket 自动化交易：行业空间评估与自动下单方案

*日期：2026-10-13 | 来源：约 200 个（DefiRate/The Block/Pew 数据页、arXiv/SSRN/CEPR 论文、官方文档、实时 API 探测）| 置信度：行业数字高（已对照数据页），边际结论中高（多篇独立论文一致），基础设施高（官方文档 + 本机探测）*
*前置报告：[接入层](polymarket-decision-model-integration-2026-10-12.md)、[加密涨跌量化](polymarket-crypto-updown-quant-2026-10-12.md)。本报告不重复其中内容。*

---

## 执行摘要

**行业在爆发，但 Polymarket 国际站不是增长所在。** 预测市场 2026 年前三季度名义成交约 3,340 亿美元（2025 全年约 510 亿），但增长几乎全在 Kalshi（近 30 天占 75.6%）和 Polymarket US（11.8%）。你能用 API 自动交易的 Polymarket 国际站，份额从 7 月底的约 10.6% 掉到 10 月中的 3.9%，月成交从 6 月 113 亿美元峰值跌到 9 月 47 亿。它仍是全球唯一无需 KYC、无地域限制（对柬埔寨）、可直接程序化下单的大型场所，但它的"池子"正在相对变小。

**自动化交易的空间存在，但很窄，而且在挂单侧。** 经同行评审或大样本数据量化、2026 年仍为正的边际只有三类：(1) 作为**做市方**承接"热门-冷门偏差"（政治/文化类市场，≥90¢ 的热门每美元 +0.8–1.0¢，<10¢ 的冷门吃单者每美元亏 15–20¢，做市方是对手盘）；(2) **新市场开盘首小时报价**（经济/加密事件类市场开盘价差 19–21¢，做市方留存 54–86%；但政治/地缘类开盘单是知情单，留存只有 25–35%）；(3) **结算存根**（赛事结束到 UMA 结算中位 41 分钟，99¢ 存根年化极高但容量很小、有争议风险）。**吃单方向预测、跨平台套利、NBA 盘中套利、neg-risk 组合套利在 2026 年均已低于费用成本或容量只剩几百美元。**

**竞争已经机构化。** Jump（持股换做市）、Wintermute、SIG（Kalshi）、Flutter/DraftKings（做市赚钱）2026 年集中进场；Polymarket 做市方基尼系数 0.97，前 1% 做市方占 84% 做市量。Polymarket 自己的 CLOB 服务器在 AWS 伦敦，托管席位只给 KYC/KYB 的自营做市商，**明确排除 Builder 和代客执行的第三方**。

**失败基础率：** 250 万钱包中 84.1% 不盈利；月均 >5k 美元的钱包里 53% 只活跃一个月、2.6% 活跃超过一年；最新的策略回放基准（AlphaOpsBench，128 万市场）对 24 个预注册真实策略零个通过端到端验证。平台顶级 bot 的榜单也是幸存者偏差：某累计 +1,035 万美元的体育 bot 近 30 天 −47.9 万。

**对你的结论：** 作为交易者，"有空间"的定义是：用做市/挂单方式、在 1–2 个类别、几万美元本金、按月净收益率个位数到十几个百分点、随时可能被规则变更归零。这不是"写个预测模型吃单"的空间。作为基础设施/工具提供方，Builder 层每年约 2,000–5,000 万美元的总奖励池高度集中于前 6 家，Telegram 类 bot 靠每笔 0.5–1% 抽佣且实际托管用户私钥。自动下单系统本身值得建（下文给了方案），但要把它当作做市和实验平台，而不是预测引擎的出口。

---

## 1. 行业规模与走向

### 1.1 成交量（名义，DefiRate 数据页，已核验）

| 月份 | Polymarket 国际站 | Polymarket US | Kalshi |
|---|---|---|---|
| 2026-01 | $7.7B | — | $9.5B |
| 2026-03 | $10.6B | — | $13.1B |
| 2026-06 | **$11.3B**（世界杯峰值） | $4.1B | $32.7B |
| 2026-07 | $8.6B | $5.0B | $41.1B |
| 2026-08 | $5.0B | $3.8B | $40.0B |
| 2026-09 | $4.7B | **$8.8B** | **$60.7B** |
| 2026-10（1–12 日） | $1.8B | $4.9B | $34.1B |

- 近 30 天（9/13–10/12）：国际站 $4.6B 名义、$2.3B 实付、未平仓 $3.40 亿、4,170 万笔、笔均 $54.75；月活交易者 26.2 万（The Block，9 月）。
- 份额：Kalshi 75.6%，Polymarket US 11.8%，Polymarket 国际站 **4.7%**（页面另一口径为 3.9%）。2024 年底 Polymarket 曾占 90% 以上。
- 2026 年 9 月 Polymarket US 首次超过国际站（9/21–27 当周 $2.83B vs $0.96B）；US 站 51.5% 的周成交是组合体育合约（parlay），名义被放大约 3 倍（9 月名义 $8.8B vs 实付 $2.8B）。
- 来源：[DefiRate Polymarket](https://defirate.com/prediction-markets/volume/polymarket/)、[DefiRate Polymarket US](https://defirate.com/prediction-markets/volume/polymarket-us/)、[DefiRate Kalshi](https://defirate.com/prediction-markets/volume/kalshi/)、[Pew 2026-09-23](https://www.pewresearch.org/short-reads/2026/09/23/prediction-markets-trading-volume-doubled-between-may-and-july-largely-driven-by-sports/)、[The Block 月活](https://www.theblock.co/data/decentralized-finance/prediction-markets/polymarket-active-traders-monthly)。

### 1.2 类别结构（国际站，近 30 天）

体育 45.7%、其他 19.9%、加密 16.9%、政治 6.7%、世界事件 2.9%、经济 2.7%。累计口径（2024-07 起）政治曾占 32%，现在塌缩到 6.7%；体育升到近半；加密平稳在 17–20%。费用收入官方未按类别披露；Pine Analytics 建模：混合吃单费率约为吃单成交的 0.76%，净费用（扣返佣、推荐）年化约 2.1–3.4 亿美元（[Pine](https://pineanalytics.substack.com/p/polymarket-fee-rollout)）。

### 1.3 资本与监管

- Polymarket：2026-09-01 宣布 10 亿美元融资、估值 210 亿（1789 Capital 领投）；年化营收 6 月 10 亿、8 月 12 亿以上（CNBC/Bloomberg）。POLY 代币确认有计划但截至 10 月 4 日未发。Kalshi：估值 220 亿（3 月）→ 约 400 亿（9 月敲定中），年化营收约 40 亿，IPO 瞄准 2027。
- 新进入者：Robinhood 事件合约 Q2 收入 1.56 亿美元超过股票和加密；DraftKings Predictions 年化 36 亿成交；Coinbase 10 月 6 日上线自家 15 分钟加密价格市场。
- 监管：CFTC 2026-06 的规则提案（40.11 改写）尚未定稿，44 州联合反对；第三巡回（4 月）与第九巡回（8 月 28 日）对"体育事件合约是否受州博彩法管辖"裁决相反；最高法院 Flaherty v. KalshiEX 待决，39 州 + NFL 支持受理；CFTC 6 月起对 Polymarket 展开广泛调查并有三起内幕交易调查。**Polymarket 4 月 28 日申请让美国用户直接上国际站，截至今日未批。**
- 分析师预测：Bernstein 2026 年 2,400 亿、2030 年 1 万亿；Macquarie 2030 年 1.5 万亿。注意 2026 年前三季度名义已超 Bernstein 全年数，各家口径不一致（名义 vs 实付）。
- 来源：[Bloomberg 融资](https://www.bloomberg.com/news/articles/2026-08-31/polymarket-funding-round-led-by-1789-values-firm-at-21-billion)、[CNBC 营收](https://www.cnbc.com/2026/06/26/polymarket-annualized-revenue-1-billion-us-exchange-.html)、[Federal Register NPRM](https://www.federalregister.gov/documents/2026/06/12/2026-11854/prediction-markets-public-interest-determinations)、[DLA Piper 诉讼追踪](https://www.dlapiper.com/en-us/insights/publications/2026/09/legal-status-at-odds-tracking-developments-in-prediction-markets-and-sports-betting)、[CoinDesk 上岸申请](https://www.coindesk.com/policy/2026/04/28/polymarket-seeks-cftc-approval-to-reopen-main-exchange-to-u-s-traders)。

### 1.4 对自动化交易的含义

- 扩张杠杆：CFTC 批准国际站对美开放（美国流动性合并到你能用的 CLOB）、最高法院对 Kalshi 有利、40.11 定稿。
- 收缩杠杆：第九巡回式裁决全国化（体育占国际站 46%）、CFTC 对刷量/高频加密流的执法、欧英把事件合约定性为博彩。
- 结构性事实：增长在你接不了的 Polymarket US（需美国身份 + KYC + FCM）和 Kalshi（美国身份）。

---

## 2. 谁在赚钱、怎么赚

### 2.1 机构参与者（2026）

| 机构 | 场所 | 公开信息 |
|---|---|---|
| Jump Trading | Kalshi + Polymarket | 以做市换股权（2026-02），团队约 20 人并翻倍 |
| Wintermute | 两边 | 2026-05 起双边报价，资金在两平台间动态调配 |
| Susquehanna (SIG) | Kalshi | 首家机构做市商（2024-04），为 Cantor 机构大宗提供流动性；体育盘中、组合、球员道具 |
| Flutter/FanDuel、DraftKings | Kalshi 等 | Flutter CEO："做市已经在赚钱"；FanDuel Q2 做市收入约 600 万；DraftKings 称专业玩家占其预测市场成交 80–90% |
| DRW、Akuna、Flow Traders | 建队中 | DRW 列出动态偏斜做市、盘口失衡、跨平台套利、亚秒新闻动量 |
| Citadel Securities、IMC、HRT | 未进入 | — |
| Kalshi 自营（Kalshi Trading） | Kalshi | 联创公开说"不盈利"，<6% 体育做市量 |

Polymarket 做市集中度：Polymarket-v1 数据库（12 亿笔）测得**做市方基尼 0.970，前 1% 占 84.1% 做市量**；每个市场有效做市商中位约 32 家（HHI 0.031）。
来源：[Decrypt Jump](https://decrypt.co/357519/jump-trading-earn-stakes-polymarket-kalshi)、[Wintermute](https://finance.yahoo.com/markets/crypto/articles/wintermute-providing-liquidity-kalshi-polymarket-162008202.html)、[Tradermath 量化公司](https://www.tradermath.org/articles/prediction-markets-trading-at-quant-firms)、[Prospect](https://prospect.org/2026/08/26/house-always-wins-kalshi-prediction-markets/)、[Polymarket-v1 DB](https://arxiv.org/html/2606.04217v2)。

### 2.2 利润集中与失败基础率

- Akey 等（CEPR，5.88 亿笔、670 亿美元）：**前 0.1% 赢家拿走 51.2% 的盈利，前 1% 拿 76.5%，约 69% 的用户亏损；赢家挂限价单，输家吃市价单**；月度持续性"有限，可能是选择效应"（[CEPR DP21615](https://cepr.org/publications/dp21615)）。
- Gómez-Cram 等（LBS/Yale，172 万账户）：只有 3.14% 是"有技能的赢家"；60% 的"幸运赢家"样本外转亏（[CoinDesk](https://www.coindesk.com/markets/2026/04/26/only-3-of-traders-drive-prediction-markets-accuracy-not-the-crowd-study-finds)）。
- Sergeenkov（250 万钱包至 2026-04）：84.1% 不盈利；月均 >5k 美元的 6,600 个钱包中 53% 只活跃一个月，**2.6% 活跃超过一年**；连续四个月 >5k 的只有 0.015%（[TechFlow](https://www.techflowpost.com/en-US/article/31018)）。
- 榜单幸存者偏差：体育 bot "kch123" 累计 +1,035 万美元、14,303 笔，但近 30 天 −47.9 万、近 7 天胜率 31%（[Leolabs](https://leolabs.me/blog/pm-top20-strategy-patterns/en/)）。
- Kalshi 做市 vs 吃单（Bürgi/Deng/Whelan，4.6 万合约）：做市方平均 −9.6%/合约，吃单方 −31.5%；做市方买 ≥50¢ 的合约 +2.6%（[GWU](https://www2.gwu.edu/~forcpgm/2026-001.pdf)）。
- 策略回放基准 AlphaOpsBench（128 万市场、1.836 亿成交，2026-06 至 09）：**24 个预注册真实策略零个通过端到端验证**；正文报告订单簿回放均值净 ROI −3.5%，费用到 100 bp 时中位数转负（[arXiv 2609.31390](https://arxiv.org/abs/2609.31390)，摘要已核验，ROI 数字来自正文）。

### 2.3 各类别顶级钱包在做什么

- **体育**：买入持有到赎回的自动化（"swisstony"：$4.94 亿成交赚 $496 万，约 1%）；电竞官方 API 领先直播的延迟（"TeemuTeemuTeemu" 3 个月 $900 → $20.8 万，自报）。
- **政治**：少数巨鲸（0.55% 的盈利做市钱包拿走 50% 做市盈利，Solidus）；2026 中期选举 321 个 ≥10 万美元钱包提供过半资金。
- **地缘**：知情流。Mitts & Ofir：21 万个异常钱包-市场对，69.9% 胜率（>60σ），约 1.43 亿美元异常利润；伊朗空袭前 6 个新钱包净赚 98.9 万；DOJ/CFTC 首例起诉（马杜罗市场，$33,934 → $409,881）。这一类是**执法目标**，不是可复制策略。
- **文化**：新闻速度（ImJustKen $74.9 万 / 9,600 市场）、马斯克推文计数（Annica $73.5 万）。
来源：[Leolabs](https://leolabs.me/blog/pm-top20-strategy-patterns/en/)、[Solidus/CoinDesk](https://www.coindesk.com/markets/2026/04/29/a-tiny-group-is-winning-on-polymarket-as-under-1-of-wallets-take-half-the-profits)、[Mitts & Ofir](https://corpgov.law.harvard.edu/2026/03/25/from-iran-to-taylor-swift-informed-trading-in-prediction-markets/)、[DOJ](https://www.justice.gov/usao-sdny/pr/us-soldier-charged-using-classified-information-profit-prediction-market-bets)、[Frenflow](https://www.frenflow.com/blog/top-10-polymarket-culture-traders)。

---

## 3. 有据可查的空间（按边际逐项）

| 边际 | 最佳证据 | 2026 年状态 | 容量 | 对个人开发者 |
|---|---|---|---|---|
| **做市承接热门-冷门偏差**（政治/加密/文化） | Cardozo & Rivero-Wildemauwe，5.88 亿笔：<10¢ 吃单每美元 −19.35¢，≥90¢ 每美元 +0.83¢；政治冷门 −16.3%；**体育无此偏差**；冷门按挂单成交 1 小时后 +16.9%、结算时 −36.3% | 持续到 2026-03 样本末 | 大（主流市场） | **最可行**：卖冷门、买热门的挂单策略；与 Jump/Wintermute 同台 |
| **新市场开盘首小时报价** | IMDEA 16.2 万合约：非体育开盘价差 8–21¢，1 小时内收窄 10 倍；经济类做市留存比 0.86、加密事件 0.54，政治 0.35、地缘 0.25、选举 0.29 | 持续 | 中（每市场几十到几百美元首小时） | **可行且少人做**：只在经济/加密事件类开盘报价，避开政治/地缘 |
| **结算存根**（赛后买 99¢ 等结算） | PolySyncer 18,427 市场：结束到结算中位 41 分钟、p90 6.4 小时；争议率体育 0.2–0.4%、地缘 4.8% | 持续 | 小（99¢ 处挂单量） | 可做为辅助，体育类争议率最低；99¢ 处费用≈0 |
| **体育赛前价 vs 鲨鱼盘口** | nopredictions：Polymarket 中间价与去水 Pinnacle 收盘价差 +0.03pp，但吃单实付高 +0.75pp；Kalshi +0.99pp | 吃单边际为零；0.75–1pp 溢价归做市方 | 大 | 做市可分一杯羹，但与 SIG/Jump/2,000 小做市商竞争 |
| 体育盘中延迟 | NBA 173 场：单市场套利仅 7 次，组合套利 290 次、中位 101 bp，**封顶总利润 $560**，76.9% 的机会只能成交约 14.8 股 | NBA 近零；电竞/小联赛仍有秒级窗口 | 极小 | 不值得 |
| 跨平台套利（Polymarket↔Kalshi） | 65 个匹配市场平均差 1 点，政治长期市场可到 7 点；需两边吃单费（50¢ 处合计约 3¢）+ 两边锁资金 + 结算口径不同 + Kalshi 需美国身份 | 净残余 ≤1–2%/对，体育近零 | Kalshi 深度决定 | **不可行**（你不能用 Kalshi） |
| neg-risk 组合套利 | 2024–25 年约 $4,000 万 → 2025–26 年**约 $112 万**（Executable Arbitrage，摘要已核验）；只剩 YES 侧，中位窗口 16 秒 | 已竞争到亚秒 | 全年总池 ~$1M | 不值得 |
| 长期 95¢ 合约的"时间价值" | Gebele & Matthes：年化结算折价 3.1–6.9%，主要是资金锁定的理性补偿；平台已付 3.25–4% 持仓奖励 | 扣除持仓奖励后净边际接近零 | — | 不值得 |
| 新闻延迟 | Angelini & De Angelis：同期价格只完成基准变动的 64%，剩余在随后几分钟漂移，低流动性更明显 | 存在，但是做市方的逆选成本；受益者是知情钱包 | — | 需要比 Jump 更快的新闻管道，不现实 |
| 加密 5m/15m 涨跌 | 见前置报告 | 吃单净零，做市 +2.3¢/股但占量 0.02% | 小 | 见前置报告 |

来源：[Cardozo](https://arxiv.org/html/2609.12878v1)、[IMDEA 开盘](https://dspace.networks.imdea.org/bitstream/handle/20.500.12761/2065/Polymarket_Initial_Liquidity-3.pdf?sequence=1&isAllowed=y)、[PolySyncer](https://www.polysyncer.com/blog/polymarket-resolution-time-2026)、[nopredictions](https://github.com/davidhmsilva/nopredictions/pull/5)、[NBA 套利](https://arxiv.org/html/2605.00864v1)、[Executable Arbitrage](https://arxiv.org/abs/2608.00666)、[Gebele & Matthes](https://arxiv.org/html/2605.31431)、[Angelini](https://arxiv.org/abs/2606.07811)、[PolymarketTrader 跨平台](https://polymarkettrader.com/polymarket-vs-kalshi/)。

**综合判断**：2026 年仍为正且有同行评审量化支撑的边际，本质上都是"做市方对抗行为性尾部需求"。这意味着盈利能力取决于库存管理、逆向选择控制和费用返佣，而不是预测准确率。这与第一份报告中"Jev 作为预测器没有增量信息"的结论一致，但给了 Jev 类模型一个真实位置：**做市时的文本风险门**（"这个新市场的规则是否有歧义"、"这是不是知情流密集的类别"）。

---

## 4. 自动下单基础设施现状

### 4.1 本机前提（2026-10-13 实时探测）

| 检查 | 结果 |
|---|---|
| `polymarket.com/api/geoblock`（出口柬埔寨） | `{"blocked": false, "country": "KH"}`；KH 不在三级限制名单中任何一级 |
| CLOB `/ok`、Gamma、Data API v2 | 均 200，直连无代理 |
| 未签名 `POST /order` | **401**（到达撮合服务，不是 Cloudflare 403） |
| 币安 `fapi/dapi/api.binance.com` | DNS 劫持，不通；与 Polymarket 无关 |

结论：与币安不同，这台机器可以直接对 Polymarket 自动下单。生产部署仍建议用都柏林（eu-west-1）服务器，见下。

### 4.2 官方约束（已核验 geoblock 与心跳页）

- **服务器**："Primary Servers: eu-west-2"（伦敦），"Closest Non-Georestricted Region: eu-west-1"（爱尔兰）。英国是只能平仓地区，所以**伦敦 VPS 不能开仓，都柏林可以**。
- **托管席位**："Co-location is available to market makers and individual traders operating on their own account. It is not available to Builder Program participants or third-party applications executing trades on behalf of end users." 需 KYC/KYB 表单，费用未公开。
- **心跳**：`POST /heartbeats`，"If heartbeats are not sent regularly, all open orders for the user will be automatically canceled"（第三方资料：每 5 秒一次，10 秒无心跳撤单）。这是官方提供的死人开关，必须用。
- **限流分层**：按签名者 30 日成交量，Standard 40 单/秒 → Elite（$10M+）600 单/秒，每 3 小时刷新，响应头 `Poly-RateLimit-*`。
- **做市指南**官方页面：双边报价、按库存偏斜、撤陈旧单、事件前用 GTD、批量提交、用 WS 不轮询、断线后重拉挂单与成交、校验簿中价、**实现一键撤全单**。
- 来源：[geoblock](https://docs.polymarket.com/api-reference/geoblock)、[heartbeat](https://docs.polymarket.com/api-reference/trade/send-heartbeat)、[trading rate limits](https://docs.polymarket.com/api-reference/trading-rate-limits.md)、[market makers](https://docs.polymarket.com/market-makers/getting-started)。

### 4.3 近期变更与硬期限

| 日期 | 变更 |
|---|---|
| 2026-09-04 | Data API v2 上线；CLOB 加密吃单延迟 50 → 150 ms |
| 2026-09-25 | `clob-client-v2` 1.2.0：`positionID` 自动选 Exchange V3 签名（Protocol V2 订单首次官方支持） |
| 2026-10-07 | `GET /v2/tokens` 映射 V2 position ID ↔ condition |
| **2026-10-24** | **Data API v1 退役** |
| **2026-11-02（暂定）** | 所有**新**市场在 Protocol V2 创建；CTF 市场保留，需同时跑两套签名域（CTF 版本 "2"，V2 版本 "3"，合约 `0xe3333700cA9d93003F00f0F71f8515005F6c00Aa`）；授权不继承，需对 Exchange V3 重新 approve |

### 4.4 可靠性记录（2026）

- V2 切换：首次推文到切换 22 天，日期确认到切换 10 天；切换后 4 天内 **55.8% 的 22,588 个活跃 V1 做市钱包没有下过一笔 V2 单**。
- 幽灵成交：195 万笔回滚撮合、攻击者获利 ≥149 万美元（arXiv 2606.16852）；V2 后降到约 0.17%（二手），研究者称"部分缓解"。
- 状态页：8 月 10 起事件、9 月 10 起；9 月 5 日约 4 小时不可用未在状态页承认；10 月 8 日交易端点 502 增多 45 分钟。
- 节奏：约每季度一次签名/格式级破坏性变更，适配器/合约地址变更只给几天通知（7 月 Neg Risk 适配器赎回宽限 3 天）。
- 来源：[TheDeepFeed](https://www.thedeepfeed.ai/posts/2026-04-28-polymarket-v2-the-ecosystem-cull/)、[arXiv 2606.16852](https://arxiv.org/abs/2606.16852)、[status.polymarket.com](https://status.polymarket.com/history/1)、[changelog](https://docs.polymarket.com/changelog/changelog)。

### 4.5 第三方工具生态

- **执行类**：PMXT（CCXT 风格多平台 SDK，2,167 星，托管模式**代管私钥**；9 月 27 日 issue 报告 Polymarket 下单因 V2 漂移完全失效）；Polytraders（终端 + bot 构建器，$49–199/月 + 成交抽佣，2027 Q1 公测）；Telegram 跟单/狙击 bot（每笔 0.5–1%，事实上托管密钥，PolyCop 的"非托管"声明不可验证，其推荐语自认"非真实客户"）。
- **数据类**：PMXT 订单簿归档（免费 Parquet）、Tardis（2026-05-25 起，$350–3,000/月）、polbots 目录 126 个 bot。
- **开源框架**：官方统一 SDK（py-sdk 0.13.0 / ts-sdk）、`py-clob-client-v2` 1.2.0；NautilusTrader（29.9k 星，唯一生产级 OMS，V2 CLOB 已支持，Protocol V2 position 订单未确认）；poly-maker（1.5k 星，唯一带敞口上限 + 日亏损开关 + 对账的社区做市框架，但 7 月后未更新、不支持 position ID）；polyoxide（Rust，能读 V2 市场但还不能交易）。**没有任何社区框架文档化了幂等下单。**
- Dome（统一 API）被 Polymarket 收购后 4 月 28 日停服；"Adjacent" API 未找到，可能已更名或停运。

### 4.6 成本模型（小型 bot，都柏林单机，一个钱包，月吃单名义 $50k）

| 项目 | 美元/月 |
|---|---|
| 服务器（t3.small eu-west-1 或 Hetzner CPX22）+ 流量 | 17–40 |
| 住宅代理（仅当你的 ASN 被 Cloudflare 403） | 0–30 |
| 数据（PMXT 免费归档 / Pro） | 0–100 |
| Gas（relayer 代付；偶尔自付） | 1–5 |
| 出入金（跨链桥 + 滑点，一次） | 5–30 |
| 吃单费（$50k 加密中间价：50,000 × 0.07 × 0.25） | **约 875**（体育约 625；政治约 500；纯挂单 ≈ 0 并有返佣） |
| 合计 | 基础设施 25–200；含费用 550–1,100 |

**费用是其他所有成本的 5 倍以上，做市/吃单比例是唯一重要的成本决策。** 返佣规模参考：2026 年 1–5 月做市返佣 $4,430 万发给 15.2 万做市方（polyscalping 追踪，未审计）；吃单返佣 7 月单月 $1,292 万。

---

## 5. "行业有没有空间"：分三个身份回答

### 5.1 作为交易者（用自己的钱）
- **有，但窄且在挂单侧。** 可做：政治/文化类的热门-冷门做市；经济/加密事件类新市场开盘首小时报价；体育结算存根。不可做：吃单方向预测、跨平台套利（Kalshi 不可用）、NBA 盘中、neg-risk 套利、长期 95¢ 持有。
- **规模预期**：第三方（跟单平台，未审计）估计专业做市中位年化 +14%（+5–35%），本金 ≥10 万美元；早期流动性挖矿者自报 1 万本金日赚 200–300 美元"在高峰期"，现已"竞争激烈"。学术证据只能告诉你做市方比吃单方少亏 20 个百分点，不能保证为正。
- **真实风险**：规则每季度变一次；一次逆向选择成交（53¢ → 2¢）抹掉约 13 个来回；高成交量会被要求 KYC；与 Jump/Wintermute 同台。

### 5.2 作为基础设施/Builder
- Builder 奖励池估算每年 $2,000–5,000 万，但前 6 家占 81%、Gini 0.83；近 30 天前 25 名 $3.27 亿成交约占国际站 8%；排行榜上真正的量来自 Betmoar、Sharktool、MagicMarkets 这类"1–11 个用户"的 bot/终端，而不是消费级钱包。
- Builder 被明确排除在托管席位之外；增长中的 Polymarket US 不对 Builder 开放。
- 来源：[Builder 排行榜 API](https://data-api.polymarket.com/v1/builders/leaderboard?timePeriod=MONTH&limit=25)（已实时核验）、[chainstory](https://www.chainstory.co/the-invisible-ecosystem-who-actually-builds-on-polymarket/)。

### 5.3 作为工具/服务卖家
- 现状是 Telegram bot 抽佣 0.5–1% 且托管私钥，以及 $29–199/月 的终端。市场需求存在（126 个 bot 目录），但信任和合规（代客执行 = 受 Builder 规则约束，且 2026 年多起针对 bot 用户的供应链攻击）是门槛。一个真正非托管、V2 就绪、带幂等与对账的执行服务目前**不存在**，这是产品空白，但 PMXT 的 1,404 个未关 issue 说明维护成本极高。

---

## 6. 自动下单系统方案（信息性设计，供实施前评审）

目标：一个可以安全跑做市/挂单类策略的执行服务，策略可插拔；先纸面，再小额。

```
┌ 数据层 ─────────────────────────────────────────────┐
│ Gamma 市场发现（version/positionIds/negRisk/feesEnabled）│
│ CLOB WS market（book/price_change/tick_size_change）   │
│ CLOB WS user（订单/成交事件）                           │
│ PolyBolt（加密 TWAP，仅加密类需要）                     │
│ Data API v2 /positions /trades /resolutions             │
└──────────────┬──────────────────────────────────────┘
               ▼
┌ 订单管理（OMS）──────────────────────────────────────┐
│ 本地订单表：client_id → 签名订单 → 服务端 orderID       │
│ 幂等：重试前先按 client_id 查本地表与 /data/orders      │
│ 双签名域：CTF（v2）与 Protocol V2（v3）按市场版本路由    │
│ 心跳：每 5 秒 POST /heartbeats；进程退出即撤全单         │
│ 对账：每 30 秒 REST 拉挂单/持仓与本地比对，不一致即停    │
│ 限流：读 Poly-RateLimit-* 头，按 tier 自适应            │
│ 客户端自成交防护（STP）：同市场双向挂单先撤后挂          │
└──────────────┬──────────────────────────────────────┘
               ▼
┌ 风控（独立模块，策略只能经它下单）────────────────────┐
│ 单市场/事件组（neg-risk）/总敞口上限；单笔名义上限      │
│ 日亏损、连续逆选成交次数、小时回撤 → 停机并撤单          │
│ 数据陈旧（WS > N 秒无更新）→ 不报价                     │
│ 结算前 X 分钟禁止新开仓（避免 TWAP/结算窗口）            │
│ 类别白名单（默认只允许经济/加密事件/文化做市）           │
│ 杀开关：独立进程，一条命令撤全单 + 平仓                  │
│ 全量决策审计日志（含被拒绝的决策）                       │
└──────────────┬──────────────────────────────────────┘
               ▼
┌ 策略插槽 ────────────────────────────────────────────┐
│ S1 开盘报价：新市场前 60 分钟，经济/加密事件类，post-only│
│ S2 热门-冷门做市：政治/文化，卖 <15¢ 冷门、买 ≥85¢ 热门  │
│ S3 结算存根：体育赛后 99¢ 挂单                           │
│ （可选）Jev 文本门：规则歧义/知情流类别判断 → 跳过市场   │
└──────────────────────────────────────────────────────┘
部署：都柏林 eu-west-1 VPS；Deposit Wallet + Session Key（不能提现）；
      6 个授权只授权打算冒险的金额；先测 ASN 是否被 403。
```

**分阶段**
1. 纸面（2–4 周）：真实 WS + 模拟成交（polymarket-paper-trader 或自建），记录每笔 markout（成交后 1/5/30 分钟的中间价变动），这是做市盈亏的真相指标。
2. 小额实盘：几百美元 pUSD，Session Key，S1 单策略单类别，人工审批模式。
3. 放大：按成交量进入返佣与限流分层；每个类别单独统计 P&L、markout、逆选率。
4. 11 月 2 日前完成 Protocol V2 双签名与 Exchange V3 授权；10 月 24 日前确认不依赖 Data API v1（现有代码已用 v2）。

**与现有仓库的衔接**：`ai_trader` 已有 Gamma/REST 风格的数据源抽象和 Web 面板；需要新增 `core/data/providers/polymarket.py`（Gamma + CLOB WS）、`core/execution/polymarket_broker.py`（实现现有 `BaseBroker` 空壳，用官方 `polymarket-client`）、`core/risk/`、以及 Web 端的 WebSocket 推送面板。前两份报告已列出 SDK 与认证细节。

---

## 7. 风险评审（prediction-market-risk-review 契约）

| 门槛 | 结论 | 说明 |
|---|---|---|
| 建议边界 | PASS | 本报告为信息性，不含具体买卖/仓位建议；策略插槽为设计示意 |
| 平台与监管 | WARN | 柬埔寨出口不在限制名单（已实测）；但 CFTC 调查、州诉讼与最高法院待决可能改变国际站命运；高成交量会被要求 KYC |
| 数据质量 | WARN | 名义成交含 parlay 放大与刷量；排行榜有幸存者偏差；第三方 ROI 均未审计 |
| 信号质量 | WARN | 可行边际均为做市侧，依赖库存与逆选控制；无公开的、独立验证的个人 bot 长期盈利记录 |
| 执行风险 | WARN | 每季度一次破坏性变更；幽灵成交"部分缓解"；状态页漏报事故 |
| 安全 | WARN | 第三方 bot 普遍托管私钥；必须 Session Key + 最小授权 + 依赖审计 |

**被阻止的动作**：本次未下单、未授权、未入金，探测仅用公开端点和未签名请求。
**安全的下一步**：按第 6 节先做纸面做市并记录 markout；任何接入真钱的步骤需要单独的实施计划和你的明确批准。

---

## 8. 方法与未验证项

**方法**：4 个并行线程（行业规模、竞争格局、非加密边际、下单基础设施），共约 410 次搜索/抓取；主线程直接核验：DefiRate Polymarket 数据页、Builder 排行榜 API 实时调用、AlphaOpsBench 与 Executable Arbitrage 摘要、官方 geoblock 与心跳页；本机实测 geoblock、三个 API 可达性、未签名 POST 响应。

**未验证**：
- "95% 的 Kalshi 撮合来自 2,000+ 小做市商"仅见二手转述。
- 体育做市返佣 15% vs 20%：changelog 与帮助页不一致。
- 流动性奖励年度总额（"$5M+/月"、"2025 年 $12M"）为厂商说法。
- Polymarket 做市方真实收益率：无审计数据，仅第三方估算（+14% 中位）与自报。
- Cloudflare 对数据中心 IP 的拦截政策未公开；证据为 2024 年 issue 与厂商营销。
- NautilusTrader / PMXT 对 Protocol V2 position 订单的支持未在发布说明中确认。
- Polymarket US API 是否仅限美国居民：文档只写需身份验证。
- 9 月 5 日约 4 小时故障无事后报告。
- AlphaOpsBench 的具体 ROI 数字来自正文（代理读取），摘要只确认"零个真实策略通过验证"。
- 所有榜单 P&L（Leolabs、Frenflow、KalshiSpy）为链上/自愿公开，有幸存者与切片偏差。

*本报告为信息性研究，不构成投资、法律或税务建议。*
