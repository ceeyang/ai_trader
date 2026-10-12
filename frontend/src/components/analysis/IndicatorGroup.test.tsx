import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DEFAULT_INDICATORS } from "../../api/types";
import { IndicatorGroup } from "./IndicatorGroup";

describe("IndicatorGroup sma periods", () => {
  it("lets the user type a trailing comma and commits the parsed list on blur", async () => {
    const onChange = vi.fn();
    render(<IndicatorGroup value={{ ...DEFAULT_INDICATORS, sma_periods: [5] }} onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: /技术指标/ }));
    const input = screen.getByLabelText(/均线周期/) as HTMLInputElement;
    await userEvent.clear(input);
    await userEvent.type(input, "5,");
    expect(input.value).toBe("5,");
    await userEvent.type(input, "20");
    await userEvent.tab();
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ sma_periods: [5, 20] }));
  });
});
