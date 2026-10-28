# 合约量化：需要关注的信息、机会探测与数据源

*日期：2026-10-29 | 性质：信息性整理，不构成投资建议 | 来源：币安/Deribit 官方接口与文档、CoinGlass/CryptoQuant/Glassnode 等数据平台、2026 年公开分析（链接见各节）*

本文把三个问题合在一起：做合约要关注什么、如何敏锐地抓住机会、哪些是利多/利空以及去哪里看。核心前提来自前面的调研：**短周期方向预测在公开数据下准确率上限约 50–52%，扣费后接近零；个人能稳定抓到的机会来自结构性错位和事件，不是方向判断。**

---

## 1. 合约本身的规则（和现货最大的不同）

- **标记价格 vs 最新价**：强平、未实现盈亏、资金费都按标记价格算。回测和风控必须用 `markPrice`，否则插针行情下模型以为没爆仓、交易所已经平了。
- **资金费率**：永续每 8 小时结算一次（部分币种 4 小时或 1 小时），多空互付。持仓过夜的策略必须计入，极端行情年化可到三位数。
- **杠杆与保证金模式**：全仓/逐仓、单向/双向，决定强平价和下单参数。维持保证金率分档，仓位越大档位越高。
- **强平与 ADL**：除强平外还有自动减仓，极端行情下盈利方会被强制平掉一部分；保险基金余额是观察指标。
- **交易规则过滤器**：最小下单量、数量精度、价格 tick、最大挂单数、名义上限，下单前按 `exchangeInfo` 取整。
- **手续费**：maker 与 taker 差数倍，VIP 等级和 BNB 抵扣影响大；高频策略的盈亏往往就是这个差。
- **限频**：按 IP 和账户的请求权重、下单频率、撤单频率；触发后封 IP 数分钟到数小时。

## 2. 要接的数据

- 实时行情 WebSocket：`aggTrade`、`depth` 或 `bookTicker`、`markPrice`（含资金费预估）、`kline`。
- 清算流 `forceOrder`：极端行情和流动性真空的即时信号。
- 持仓量、多空持仓人数比、大户持仓比、主动买卖量比：交易所历史接口，5 分钟粒度。
- 期现价差（基差）与跨所价差。
- 宏观事件日历：CPI、非农、FOMC。
- 用户数据流（`listenKey`）：自己的订单、成交、仓位、余额，是执行层的真相来源。

## 3. 执行层细节

- 订单类型：限价、市价、止损市价、止盈市价、跟踪止损；`reduceOnly`、`timeInForce=GTX`（只挂单）、`closePosition`。
- 幂等：每笔订单带 `newClientOrderId`，重试先查不重发。
- 对账：定时 REST 拉仓位和余额与本地比对，不一致即停。
- 部分成交、撤单失败、维护公告、`listenKey` 每 30 分钟续期，每项都要有处理路径。
- 滑点与冲击：市价单在薄簿上的实际成交价要按盘口深度预估。

## 4. 风控：独立于策略代码的硬限制

单笔最大名义、最大杠杆、总敞口、单币种上限；日亏损、连续亏损、小时回撤触发停机；WebSocket 陈旧熔断；独立进程的杀开关（撤全单 + 平仓）；全量决策审计日志；API key 只开合约交易、关提现、绑 IP 白名单；专用小额账户；依赖审计（2026 年有多起针对交易 bot 开发者的恶意包）。

## 5. 回测与验证顺序

回测必须计入资金费、maker/taker 费、滑点、按标记价格模拟强平、保证金占用。陷阱：前视、幸存者偏差、regime 变化。顺序：历史回测 → 测试网（`testnet.binancefuture.com`）→ 真钱小额 1 倍杠杆跑几百笔 → 放大，全程同一套风控代码。

---

## 6. 六类信息如何变成"机会探测器"

| 类别 | 看什么 | 机会在哪 | 探测器设计 |
|---|---|---|---|
| 资金费率与基差 | 各所永续费率（年化）、永续对现货溢价、季度对永续价差 | 费率极端时现货+反向永续吃费率，容量最大、方向中性；极端费率本身是拥挤信号 | 结算前 30 分钟拉全部 USDT 永续费率，标出历史 95 分位以上；比较三家交易所费率差 |
| 持仓量、价格、清算 | 持仓变化率、多空人数比、大户持仓比、`forceOrder` | 持仓急升价格不动 = 一方堆仓；清算集中爆发的几分钟是流动性真空，过冲后回归 | 持仓 1 小时变化超 30 日 95 分位；清算 5 分钟滚动和超阈值；事后统计"清算后 15 分钟反向收益" |
| 订单簿与成交流 | 最优档失衡、前十档深度比、主动买卖比、大单/冰山、簿变薄 | 唯一有学术证据的短期因子，但只在几秒到一两分钟有效；BTC 扣费后不显著，小币种才有 | 小市值永续 1 秒级簿失衡监控，统计 10 秒、60 秒后变动 |
| 跨所与跨品种价差 | 币安/OKX/Bybit 同一永续；永续对季度；现货对永续；U 本位对币本位 | 上币、下架、宕机、单边清算时价差拉开 | 记录价差序列，超历史 99 分位报警，记录收敛时长 |
| 事件日历与链上流 | CPI/非农/FOMC；ETF 申赎；代币解锁；交易所公告；稳定币增发；交易所钱包大额转账 | 事件前波动率压缩、事件后扩张，可交易波动率而非方向 | 结构化日历，事件前 1 小时自动切到"只平不开"或波动率模式；上币公告关键字监控 |
| 波动率状态 | 已实现波动率（1 分钟 bar）、Deribit DVOL、两者差、压缩指标 | 压缩后突破有统计延续性；隐含远高于已实现时卖波动率有正期望但尾部大 | 已实现波动率处于 30 日 10 分位以下且持续 N 小时 → "待突破" |

**"敏锐"的养成**：每类信息做成带分位数阈值的探测器而不是人盯屏；每个探测器记录触发后 10 分钟、1 小时、4 小时的前瞻收益，每周看一张信号有效性表；先做事件研究（事件前后平均价格路径）再写策略；每种机会一页 playbook（触发、动作、仓位、退出、失效条件）；每笔自动交易存触发时的状态快照用于复盘。

**个人开发者的可行性排序**：资金费率/基差套利 > 事件驱动的波动率策略 > 清算过冲回归与跨所价差（需低延迟与预挂单）> 短周期方向（证据最弱）。

---

## 7. 利多 / 利空对照表与数据源

| 维度 | 偏利多的读法 | 偏利空的读法 | 去哪看 |
|---|---|---|---|
| 宏观流动性 | 美联储净流动性回升、RRP/TGA 释放、10 年期与 DXY 回落 | 净流动性收缩、TGA 重建抽水、QT 继续、10 年期与 DXY 走高 | 美联储 H.4.1 周报、财政部 TGA 日报；日评如 [Au79 Macro Research](https://martyau79.substack.com/p/27oct2026-crypto-and-macro-liquidity) |
| 现货 ETF 资金流 | 连续净流入，单周 >10 亿美元 | 连续净流出，单周 >10 亿美元 | [Farside](https://farside.co.uk/?p=997)、SoSoValue、[Glassnode ETF 流](https://studio.glassnode.com/charts/institutions.UsSpotEtfFlowsAll)、[TFTC 月度归档](https://www.tftc.io/bitcoin-etf-flows/july-2026)。2026 年 5–6 月累计净流出 69 亿美元 |
| 资金费率 | 温和为正且价格同步上涨 | 年化持续 >8% 而价格不涨（多头拥挤）；持续为负（空头拥挤） | [CoinGlass](https://www.chainpick.io/market-data/coinglass)；币安 `fapi/v1/premiumIndex`、`fapi/v1/fundingRate` |
| 持仓量 | 上涨中同步回升 | 下跌时持仓上升（硬扛）；持仓创高后价格停滞 | CoinGlass；币安 `futures/data/openInterestHist`、[币安 Vision 日度 metrics](https://github.com/binance/binance-public-data/issues/211) |
| 多空比与大户持仓 | 大户净多、散户净空 | 散户极端净多、大户减仓 | 币安 `futures/data/globalLongShortAccountRatio`、`topLongShortPositionRatio`、`takerlongshortRatio`（[端点说明](https://apify.com/gochujang/long-short-oi-aggregator)） |
| 清算 | 空头集中清算后的回补 | 多头清算级联、热力图上方密集 | CoinGlass 清算热力图；币安 WS `forceOrder` |
| 期权 | 隐含波动率低位、看涨偏斜 | 大额到期临近、最大痛点远低于现价、看跌偏斜加重 | Deribit 官方数据、DVOL、Amberdata/Laevitas |
| 链上与交易所余额 | 交易所 BTC 余额下降、稳定币供应增加、长期持有者不动 | 交易所余额上升、稳定币供应收缩、矿工/巨鲸向交易所转入 | [CryptoQuant](https://coinbureau.com/review/crypto-research-tools)、Glassnode、Arkham、Whale Alert |
| 供给事件 | 无大额解锁 | 大额解锁、项目方抛售、矿工抛压 | [Tokenomist](https://tokenomist.ai/research)、CryptoRank 解锁日历 |
| 事件日历 | 数据符合预期后波动率回落 | CPI/非农/PCE/FOMC 前后波动率跳升 | [CoinMarketCal](https://oakresearch.io/en/feed/calendar)、美联储会议日程、BLS 发布日历 |
| 监管与交易所 | 上币、合约上线、ETF 获批 | 下架、交易所事故、监管诉讼、杠杆调整 | 交易所公告页、SEC/CFTC 新闻稿 |
| 情绪 | 恐惧贪婪指数极端恐惧（反向） | 极端贪婪 | Alternative.me |

综述来源：[Bitcoin Foundation 指标指南](https://bitcoinfoundation.org/news/bitcoin/best-bitcoin-indicators-for-timing-the-market-in-2026/)、[Mudrex 熊市信号](https://mudrex.com/learn/2026-crypto-bear-market/)、[Amberdata 2026 展望](https://blog.amberdata.io/crypto-markets-in-early-2026-rally-builds-as-etf-flows-return)、[Coin Bureau 工具对比](https://coinbureau.com/review/crypto-research-tools)、[CoinGlass API 评测](https://dev.to/great-time-flies/coinglass-api-review-2026-is-it-worth-it-for-crypto-quant-traders-2bcf)、[DEXTools 解锁追踪器](https://www.dextools.io/tutorials/top-5-token-unlock-trackers-2026-pt)。

### 2026-10 下旬读数示例（单一来源，仅作状态示例）

美联储净流动性约 5.87 万亿美元，被 8,830 亿 TGA 重建压缩，RRP 接近 1 亿；10 年期 5.1%，DXY 101.8；BTC 约 8.0–8.1 万，守 50 日线 8.15 万附近，BTC 占比 59.9%；10 月 30 日 Deribit 有 35% 的 BTC 期权持仓到期，最大痛点 7.9 万、看涨墙 9.5 万（[Au79 Macro Research](https://martyau79.substack.com/p/20oct2026-crypto-and-macro-liquidity)）。组合读法：宏观偏紧、仓位防守、波动率事件临近。

### 使用提醒

- 利多/利空都是条件性的。资金费率高是"拥挤"，上涨趋势中可持续数周，只有与价格停滞、持仓创高同时出现才是反转信号。看组合，不看单一指标。
- 这些公开数据所有人都在看，价值不在预测方向，而在事件前降杠杆、拥挤时不追、清算过冲时有预案。

---

## 8. 接入本项目的方案

- **数据层分三层**：币安合约公开接口（资金费、持仓量、多空比、主动买卖比、清算流，免费）；CoinGlass API V4（付费，多所聚合）；ETF 流与解锁日历靠抓取 Farside/Tokenomist 或第三方 API。
- **信号雷达模块**：币安合约 WebSocket（标记价、资金费、持仓量、清算流）+ 定时拉多空比和大户持仓；六类探测器各一个；告警推 Telegram；每次信号的前瞻收益落库；Web 面板显示信号有效性表（复用现有 `analyze_signal_effectiveness` 的思路）。先跑一个月再决定围绕哪个探测器写执行。
- **环境限制**：本机 `fapi.binance.com`、`dapi.binance.com` 被 DNS 劫持不可达，`testnet.binancefuture.com` 可达；采集需跑海外服务器或 VPN，开发可先用测试网。现货行情镜像 `data-api.binance.vision` 不提供合约数据。
- **与现有代码衔接**：需新增合约 WebSocket 客户端、`BinanceFuturesBroker`（实现现有 `BaseBroker` 空壳，含过滤器取整、幂等、对账）、独立风控模块、事件驱动策略循环、面板的 WebSocket 推送。
