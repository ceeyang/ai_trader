import asyncio
import json
from datetime import timedelta
from decimal import Decimal

from conftest import T0, make_decision_model, make_fill, make_signal, seed_effectiveness

from ai_trader.settings import DetectorConfig, RiskLimits, StrategyConfig
from ai_trader.strategy.autotune import AutoTuner


def mk(st, clock=None, **kw): return AutoTuner(st, StrategyConfig(), DetectorConfig(), clock=clock or (lambda: T0.timestamp()), **kw)


async def test_activity_floor_relaxes_thresholds_one_step(st):
    t = mk(st); changes = await t.tick()
    assert t.detector_cfg.liquidation_notional_threshold_usdt == Decimal(35000) and abs(t.detector_cfg.news_min_confidence - 0.55) < 1e-9
    assert abs(t.strategy_cfg.entry_threshold - 0.55) < 1e-9 and {c.rule for c in changes} == {"activity_floor"}
    assert len(await st.tuning_log(10)) == len(changes)


async def test_activity_floor_full_step_values_and_log(st):
    t = mk(st)
    changes = await t.tick()
    assert t.detector_cfg.funding_annualized_threshold == Decimal("0.24")
    by_field = {c.field: c for c in changes}
    assert set(by_field) == {
        "detectors.liquidation_notional_threshold_usdt",
        "detectors.news_min_confidence",
        "detectors.funding_annualized_threshold",
        "strategy.entry_threshold",
    }
    c = by_field["detectors.liquidation_notional_threshold_usdt"]
    assert (c.old, c.new) == ("50000", "35000")
    assert "signals=0" in c.reason and "decisions=0" in c.reason
    logged = await st.tuning_log(10)
    assert {r.field for r in logged} == set(by_field)
    assert all(r.ts == T0 for r in logged)


async def test_activity_floor_respects_floors(st):
    t = mk(st)
    for _ in range(40): await t.tick()
    assert t.detector_cfg.liquidation_notional_threshold_usdt >= Decimal(5000) and t.detector_cfg.news_min_confidence >= 0.3 - 1e-9 and t.strategy_cfg.entry_threshold >= 0.3 - 1e-9


async def test_activity_floor_floors_are_exact_and_stop_logging(st):
    t = mk(st)
    for _ in range(40):
        await t.tick()
    assert t.detector_cfg.liquidation_notional_threshold_usdt == Decimal(5000)
    assert t.detector_cfg.funding_annualized_threshold == Decimal("0.05")
    assert abs(t.detector_cfg.news_min_confidence - 0.3) < 1e-9
    assert abs(t.strategy_cfg.entry_threshold - 0.3) < 1e-9
    assert await t.tick() == []  # at the floors: nothing left to change, nothing logged


async def test_activity_floor_not_triggered_when_active(st):
    for i in range(3): await st.insert_signal(make_signal(f"s{i}", created_at=T0 - timedelta(minutes=10)))
    await st.insert_decision(make_decision_model(created_at=T0 - timedelta(minutes=5)))
    assert [c for c in await mk(st).tick() if c.rule == "activity_floor"] == []


async def test_activity_floor_ignores_activity_outside_window(st):
    for i in range(5):
        await st.insert_signal(make_signal(f"s{i}", created_at=T0 - timedelta(hours=3)))
    changes = await mk(st).tick()
    assert {c.rule for c in changes} == {"activity_floor"}


async def test_detector_quality_disables_bad_and_boosts_good(st):
    await seed_effectiveness(st, "funding_extreme", horizon_s=3600, n=25, hit_rate=0.3, mean_ret=-0.002)
    await seed_effectiveness(st, "news_sentiment", horizon_s=3600, n=25, hit_rate=0.6, mean_ret=0.003)
    t = mk(st); await t.tick()
    assert abs(t.strategy_cfg.detector_weights["funding_extreme"] - 0.25) < 1e-9 and abs(t.strategy_cfg.detector_weights["news_sentiment"] - 1.1) < 1e-9


async def test_detector_quality_ignores_small_samples(st):
    await seed_effectiveness(st, "funding_extreme", horizon_s=3600, n=5, hit_rate=0.0, mean_ret=-0.01)
    t = mk(st); await t.tick(); assert t.strategy_cfg.detector_weights["funding_extreme"] == 0.5


async def test_detector_quality_ignores_other_horizons(st):
    await seed_effectiveness(st, "funding_extreme", horizon_s=600, n=30, hit_rate=0.1, mean_ret=-0.01)
    t = mk(st)
    await t.tick()
    assert t.strategy_cfg.detector_weights["funding_extreme"] == 0.5


async def test_detector_quality_weight_bounds(st):
    await seed_effectiveness(st, "funding_extreme", horizon_s=3600, n=25, hit_rate=0.2, mean_ret=-0.002)
    await seed_effectiveness(st, "news_sentiment", horizon_s=3600, n=25, hit_rate=0.8, mean_ret=0.003)
    t = mk(st)
    for _ in range(10):
        await t.tick()
    assert t.strategy_cfg.detector_weights["funding_extreme"] == 0.0  # 0 = disabled
    assert abs(t.strategy_cfg.detector_weights["news_sentiment"] - 1.5) < 1e-9


async def test_loss_brake_halves_notional(st):
    # The brief's version used clock=T0 (00:00 UTC) with the fill at T0 − 1 h, i.e. on the
    # previous UTC day, which "当日已实现盈亏" cannot see. Same scenario two hours into the day.
    now = T0 + timedelta(hours=2)
    await st.set_kv("day_start_equity:2026-10-29", "10000")
    await st.insert_fill(make_fill("c1", realized_pnl=Decimal(-250), event_time=now - timedelta(hours=1)))
    t = mk(st, clock=lambda: now.timestamp()); await t.tick()
    assert t.strategy_cfg.base_notional_usdt == Decimal(50) and abs(t.strategy_cfg.entry_threshold - 0.65) < 1e-9   # 0.6 − 0.05 (activity_floor) + 0.1


async def test_loss_brake_ignores_previous_day_and_missing_equity(st):
    now = T0 + timedelta(hours=2)
    await st.insert_fill(make_fill("c1", realized_pnl=Decimal(-500), event_time=now - timedelta(hours=1)))
    t = mk(st, clock=lambda: now.timestamp())
    await t.tick()  # no day_start_equity kv: skipped
    assert t.strategy_cfg.base_notional_usdt == Decimal(100)
    await st.set_kv("day_start_equity:2026-10-30", "10000")
    t2 = mk(st, clock=lambda: (T0 + timedelta(days=1, hours=1)).timestamp())
    await t2.tick()  # the loss is on 2026-10-29, not "today"
    assert t2.strategy_cfg.base_notional_usdt == Decimal(100)


async def test_loss_brake_notional_floor_and_threshold_cap(st):
    now = T0 + timedelta(hours=2)
    await st.set_kv("day_start_equity:2026-10-29", "10000")
    await st.insert_fill(make_fill("c1", realized_pnl=Decimal(-500), event_time=now - timedelta(hours=1)))
    t = mk(st, clock=lambda: now.timestamp())
    for _ in range(10):
        await t.tick()
    assert t.strategy_cfg.base_notional_usdt == Decimal(50)
    assert t.strategy_cfg.entry_threshold <= 0.9 + 1e-9


async def test_loss_brake_recovers_notional_on_gain(st):
    now = T0 + timedelta(hours=2)
    await st.set_kv("day_start_equity:2026-10-29", "10000")
    await st.insert_fill(make_fill("c1", realized_pnl=Decimal(200), event_time=now - timedelta(hours=1)))
    cfg = StrategyConfig(base_notional_usdt=Decimal(50))
    t = AutoTuner(st, cfg, DetectorConfig(), clock=lambda: now.timestamp())
    await t.tick()
    assert cfg.base_notional_usdt == Decimal("62.5")
    for _ in range(5):
        await t.tick()
    assert cfg.base_notional_usdt == Decimal(100)
    assert [c for c in await t.tick() if c.rule == "loss_brake"] == []  # at the default: no change


async def test_overtrading_brake(st):
    for i in range(10): await st.insert_decision(make_decision_model(created_at=T0 - timedelta(minutes=i)))
    t = mk(st); await t.tick(); assert t.strategy_cfg.cooldown_s == 1350


async def test_overtrading_brake_caps(st):
    for i in range(10):
        await st.insert_decision(make_decision_model(created_at=T0 - timedelta(minutes=i)))
    t = mk(st)
    changes = await t.tick()
    assert {c.rule for c in changes} == {"overtrading_brake"}
    assert abs(t.strategy_cfg.entry_threshold - 0.65) < 1e-9
    for _ in range(20):
        await t.tick()
    assert t.strategy_cfg.cooldown_s == 3600
    assert abs(t.strategy_cfg.entry_threshold - 0.9) < 1e-9


async def test_overtrading_threshold_read_from_config(st):
    for i in range(59):
        await st.insert_decision(make_decision_model(created_at=T0 - timedelta(minutes=i + 1)))
    t = mk(st)
    t.strategy_cfg.overtrading_decisions = 60
    assert [c for c in await t.tick() if c.rule == "overtrading_brake"] == []  # 59 < 60
    assert t.strategy_cfg.cooldown_s == 900
    await st.insert_decision(make_decision_model(created_at=T0 - timedelta(seconds=30)))
    changes = [c for c in await t.tick() if c.rule == "overtrading_brake"]
    assert changes and "decisions=60>=60" in changes[0].reason
    assert t.strategy_cfg.cooldown_s == 1350


async def test_activity_floor_threshold_read_from_config(st):
    for i in range(3):
        await st.insert_signal(make_signal(f"s{i}", created_at=T0 - timedelta(minutes=10)))
    t = mk(st)
    assert [c for c in await t.tick() if c.rule == "activity_floor"] == []  # 3 signals, default min 3
    t.strategy_cfg.activity_min_signals = 5
    changes = [c for c in await t.tick() if c.rule == "activity_floor"]
    assert changes and "signals=3<5" in changes[0].reason


async def test_mutates_shared_config_objects_in_place(st):
    strategy, detectors = StrategyConfig(), DetectorConfig()
    weights = strategy.detector_weights
    t = AutoTuner(st, strategy, detectors, clock=lambda: T0.timestamp())
    await t.tick()
    assert t.strategy_cfg is strategy and t.detector_cfg is detectors
    assert strategy.detector_weights is weights
    assert strategy.entry_threshold < 0.6 and detectors.news_min_confidence < 0.6


async def test_never_touches_risk_limits(st):
    await seed_effectiveness(st, "funding_extreme", horizon_s=3600, n=25, hit_rate=0.3, mean_ret=-0.002)
    await st.set_kv("day_start_equity:2026-10-29", "10000")
    for i in range(10):
        await st.insert_decision(make_decision_model(created_at=T0 - timedelta(minutes=i)))
    await st.insert_fill(make_fill("c1", realized_pnl=Decimal(-500), event_time=T0))
    t = mk(st)
    assert not any(isinstance(v, RiskLimits) for v in vars(t).values())
    for _ in range(5):
        await t.tick()
    logged = await st.tuning_log(100)
    assert logged
    assert all(c.field.startswith(("strategy.", "detectors.")) for c in logged)


async def test_tuning_log_newest_first_and_limit(st):
    t = mk(st)
    await t.tick()
    t2 = mk(st, clock=lambda: (T0 + timedelta(hours=1)).timestamp())
    await t2.tick()
    rows = await st.tuning_log(3)
    assert len(rows) == 3 and rows[0].ts == T0 + timedelta(hours=1)


async def test_effective_values_persisted_to_kv(st):
    t = mk(st)
    await t.publish_effective()
    snap = json.loads(await st.get_kv("tuning_effective"))
    assert snap["strategy"]["entry_threshold"] == 0.6
    await t.tick()
    snap = json.loads(await st.get_kv("tuning_effective"))
    assert abs(snap["strategy"]["entry_threshold"] - 0.55) < 1e-9
    assert snap["strategy"]["base_notional_usdt"] == "100"
    assert snap["detectors"]["liquidation_notional_threshold_usdt"] == "35000"
    assert snap["strategy"]["detector_weights"]["news_sentiment"] == 1.0


async def test_run_waits_a_full_interval_before_first_tick(st):
    t = mk(st, interval_s=3600)
    task = asyncio.create_task(t.run())
    for _ in range(100):
        if await st.get_kv("tuning_effective") is not None:
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.1)
    await t.stop()
    await asyncio.wait_for(task, timeout=1)
    assert await st.get_kv("tuning_effective") is not None  # published right away
    assert await st.tuning_log(100) == []  # but no tick yet


async def test_run_ticks_and_stops_promptly(st):
    t = mk(st, interval_s=0.2)
    task = asyncio.create_task(t.run())
    for _ in range(100):
        if await st.tuning_log(1):
            break
        await asyncio.sleep(0.01)
    await t.stop()
    await asyncio.wait_for(task, timeout=1)
    assert await st.get_kv("tuning_effective") is not None
    assert len(await st.tuning_log(100)) == 4  # exactly one tick ran


async def _tuned_snapshot(st):
    """Publish the values a tuned process would leave behind."""
    s = StrategyConfig(entry_threshold=0.85, base_notional_usdt=Decimal(60), cooldown_s=2025)
    s.detector_weights["funding_extreme"] = 0.0
    d = DetectorConfig(liquidation_notional_threshold_usdt=Decimal(12005),
                       funding_annualized_threshold=Decimal("0.1536"), news_min_confidence=0.45)
    await AutoTuner(st, s, d, clock=lambda: T0.timestamp()).publish_effective()


async def test_restore_effective_copies_tuned_values_onto_shared_configs(st):
    await _tuned_snapshot(st)
    strategy, detectors = StrategyConfig(), DetectorConfig()
    weights = strategy.detector_weights
    t = AutoTuner(st, strategy, detectors, clock=lambda: T0.timestamp())
    assert await t.restore_effective() is True
    assert t.strategy_cfg is strategy and t.detector_cfg is detectors and strategy.detector_weights is weights
    assert strategy.entry_threshold == 0.85 and strategy.base_notional_usdt == Decimal(60)
    assert strategy.cooldown_s == 2025 and weights["funding_extreme"] == 0.0 and weights["news_sentiment"] == 1.0
    assert detectors.liquidation_notional_threshold_usdt == Decimal(12005)
    assert detectors.funding_annualized_threshold == Decimal("0.1536")
    assert detectors.news_min_confidence == 0.45


async def test_restore_effective_clamps_and_ignores_unknown_detectors(st):
    await st.set_kv("tuning_effective", json.dumps({
        "strategy": {"entry_threshold": 5, "base_notional_usdt": "1", "cooldown_s": 99999,
                     "detector_weights": {"news_sentiment": 9, "made_up": 1.0}},
        "detectors": {"funding_annualized_threshold": "0.0001", "liquidation_notional_threshold_usdt": "1",
                      "news_min_confidence": 0.0},
    }))
    strategy, detectors = StrategyConfig(), DetectorConfig()
    assert await AutoTuner(st, strategy, detectors).restore_effective() is True
    assert strategy.entry_threshold == 0.9 and strategy.base_notional_usdt == Decimal(50)
    assert strategy.cooldown_s == 3600 and strategy.detector_weights["news_sentiment"] == 1.5
    assert "made_up" not in strategy.detector_weights
    assert detectors.funding_annualized_threshold == Decimal("0.05")
    assert detectors.liquidation_notional_threshold_usdt == Decimal(5000)
    assert detectors.news_min_confidence == 0.3


async def test_restore_effective_never_looser_than_configured_brakes(st):
    # a published cooldown below the configured one, and a notional above the default cap
    await st.set_kv("tuning_effective", json.dumps({
        "strategy": {"entry_threshold": 0.6, "base_notional_usdt": "500", "cooldown_s": 10,
                     "detector_weights": {}},
        "detectors": {"funding_annualized_threshold": "0.3", "liquidation_notional_threshold_usdt": "50000",
                      "news_min_confidence": 0.6},
    }))
    strategy = StrategyConfig()
    assert await AutoTuner(st, strategy, DetectorConfig()).restore_effective() is True
    assert strategy.cooldown_s == 900 and strategy.base_notional_usdt == Decimal(100)


async def test_restore_effective_missing_or_malformed_changes_nothing(st):
    strategy, detectors = StrategyConfig(), DetectorConfig()
    t = AutoTuner(st, strategy, detectors)
    assert await t.restore_effective() is False
    await st.set_kv("tuning_effective", '{"strategy": {"entry_threshold": 0.8}')
    assert await t.restore_effective() is False
    await st.set_kv("tuning_effective", json.dumps({"strategy": {"entry_threshold": 0.8}, "detectors": {}}))
    assert await t.restore_effective() is False
    assert strategy == StrategyConfig() and detectors == DetectorConfig()


async def test_run_restores_before_first_tick(st):
    await _tuned_snapshot(st)
    strategy = StrategyConfig()
    t = AutoTuner(st, strategy, DetectorConfig(), interval_s=0.2, clock=lambda: T0.timestamp())
    task = asyncio.create_task(t.run())
    for _ in range(100):
        if await st.tuning_log(1):
            break
        await asyncio.sleep(0.01)
    await t.stop()
    await asyncio.wait_for(task, timeout=1)
    # restored 0.85, then the quiet-market tick relaxed it one step (not the default 0.6 − 0.05)
    assert abs(strategy.entry_threshold - 0.80) < 1e-9
    assert strategy.base_notional_usdt == Decimal(60)
    snap = json.loads(await st.get_kv("tuning_effective"))
    assert abs(snap["strategy"]["entry_threshold"] - 0.80) < 1e-9
