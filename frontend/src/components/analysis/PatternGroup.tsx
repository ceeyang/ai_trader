import { CheckField, Group } from "./Group";

export const PATTERN_LABELS: Record<string, string> = {
  hammer: "锤子线", hanging_man: "上吊线", doji: "十字星", bullish_engulfing: "看涨吞没", bearish_engulfing: "看跌吞没",
  morning_star: "早晨之星", evening_star: "黄昏之星", three_white_soldiers: "三白兵", three_black_crows: "三黑鸦",
};

export function PatternGroup({ enabled, onChange }: { enabled: Set<string>; onChange: (s: Set<string>) => void }) {
  return (
    <Group title="K线形态 (显示过滤)" defaultOpen={false}>
      {Object.entries(PATTERN_LABELS).map(([key, label]) => (
        <CheckField key={key} label={label} checked={enabled.has(key)}
          onChange={(v) => { const next = new Set(enabled); if (v) next.add(key); else next.delete(key); onChange(next); }} />
      ))}
    </Group>
  );
}
