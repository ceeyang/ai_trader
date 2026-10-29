"""Application settings loaded from environment variables and `.env`."""

from decimal import Decimal
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

TESTNET_REST = "https://testnet.binancefuture.com"
TESTNET_WS = "wss://stream.binancefuture.com"
MAINNET_REST = "https://fapi.binance.com"
MAINNET_WS = "wss://fstream.binance.com"
TESTNET_HOSTS = frozenset({"testnet.binancefuture.com", "stream.binancefuture.com"})


class RiskLimits(BaseModel):
    max_leverage: int = 3
    max_order_notional_usdt: Decimal = Decimal(200)
    max_total_exposure_usdt: Decimal = Decimal(500)
    max_open_positions: int = 2
    max_daily_loss_pct: Decimal = Decimal(5)
    max_consecutive_losses: int = 3
    max_data_staleness_s: float = 10.0
    trading_enabled: bool = True


class StrategyConfig(BaseModel):
    entry_threshold: float = 0.6
    exit_threshold: float = 0.4
    base_notional_usdt: Decimal = Decimal(100)
    cooldown_s: int = 900
    stop_loss_pct: Decimal = Decimal("0.01")
    take_profit_pct: Decimal = Decimal("0.02")
    max_hold_s: int = 14400
    signal_half_life_s: int = 1800
    # AutoTuner thresholds (read at every tick): overtrading_brake fires at >= this many
    # decisions in the activity window; activity_floor fires when signals < activity_min_signals
    # and there were no decisions.
    overtrading_decisions: int = 10
    activity_min_signals: int = 3
    detector_weights: dict[str, float] = {
        "funding_extreme": 0.5,
        "liquidation_burst": 0.7,
        "news_sentiment": 1.0,
        # news signals whose sentiment came from the keyword classifier (no LLM, or the
        # LLM failed): weaker evidence, separately weighted and auto-tuned.
        "news_keyword": 0.5,
        "breakout": 0.8,
        "mean_reversion": 0.6,
    }


class DetectorConfig(BaseModel):
    funding_annualized_threshold: Decimal = Decimal("0.30")
    liquidation_window_s: int = 300
    liquidation_notional_threshold_usdt: Decimal = Decimal(50000)
    liquidation_cooldown_s: int = 900
    news_min_confidence: float = 0.6
    # breakout (closed 1m klines)
    breakout_lookback: int = 60
    breakout_volume_mult: float = 1.5
    breakout_min_move_pct: float = 0.15
    breakout_ttl_s: int = 1800
    breakout_cooldown_s: int = 900
    # mean reversion (z-score of closed 1m kline closes)
    mr_lookback: int = 30
    mr_z_entry: float = 2.5
    mr_ttl_s: int = 1200
    mr_cooldown_s: int = 900


class NewsConfig(BaseModel):
    rss_feeds: list[str] = [
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://cointelegraph.com/rss",
    ]
    rss_poll_interval_s: int = 300
    x_bearer_token: SecretStr | None = None
    x_query: str = (
        "(from:binance OR from:cz_binance OR from:coinbase OR from:SECGov "
        "OR from:federalreserve) -is:retweet"
    )
    x_poll_interval_s: int = 120
    x_max_results: int = 10
    x_daily_read_budget: int = 2000
    # Items published longer ago than this are stored but never classified (saves the
    # LLM budget) and never produce a signal.
    max_news_age_s: int = 7200


class LLMConfig(BaseModel):
    enabled: bool = True
    provider: Literal["deepseek", "none"] = "deepseek"
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"
    daily_call_budget: int = 500
    max_text_chars: int = 4000
    timeout_s: float = 30.0


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",
    )

    binance_api_key: SecretStr | None = None
    binance_api_secret: SecretStr | None = None
    deepseek_api_key: SecretStr | None = None
    binance_testnet: bool = True
    binance_rest_url: str | None = None
    binance_ws_url: str | None = None
    symbols: list[str] = ["BTCUSDT", "ETHUSDT"]
    leverage: int = 2
    margin_type: Literal["ISOLATED", "CROSSED"] = "ISOLATED"
    mode: Literal["paper", "live"] = "paper"
    db_path: Path = Path("data/ai_trader.db")
    log_level: str = "INFO"
    log_json: bool = False

    risk: RiskLimits = RiskLimits()
    strategy: StrategyConfig = StrategyConfig()
    detectors: DetectorConfig = DetectorConfig()
    news: NewsConfig = NewsConfig()
    llm: LLMConfig = LLMConfig()

    @property
    def effective_rest_url(self) -> str:
        if self.binance_rest_url:
            return self.binance_rest_url
        return TESTNET_REST if self.binance_testnet else MAINNET_REST

    @property
    def effective_ws_url(self) -> str:
        if self.binance_ws_url:
            return self.binance_ws_url
        return TESTNET_WS if self.binance_testnet else MAINNET_WS

    @property
    def targets_testnet(self) -> bool:
        """True only when both effective endpoints are Binance futures testnet hosts —
        whatever `binance_testnet` says (an explicit URL override wins)."""
        hosts = {urlparse(self.effective_rest_url).hostname, urlparse(self.effective_ws_url).hostname}
        return hosts <= TESTNET_HOSTS
