import type {
  AnalysisPreset,
  AnalysisRequest,
  AnalysisResponse,
  BacktestRequest,
  BacktestResponse,
  DCARequest,
  DCAResponse,
  DataRange,
  IntervalsResponse,
  KlinesResponse,
  SymbolsResponse,
} from "./types";

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (body?.detail) detail = JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

function get<T>(url: string, params?: Record<string, string | number | boolean>): Promise<T> {
  const qs = params ? "?" + new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])) : "";
  return request<T>(url + qs);
}

function send<T>(method: "POST" | "PUT", url: string, body: unknown): Promise<T> {
  return request<T>(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export const api = {
  getSymbols: (mainstreamOnly: boolean) =>
    get<SymbolsResponse>("/api/market/symbols", { mainstream_only: mainstreamOnly }),
  getIntervals: () => get<IntervalsResponse>("/api/market/intervals"),
  getKlines: (range: DataRange) => get<KlinesResponse>("/api/market/klines", { ...range }),
  calculateDca: (req: DCARequest) => send<DCAResponse>("POST", "/api/dca/calculate", req),
  runAnalysis: (req: AnalysisRequest) => send<AnalysisResponse>("POST", "/api/analysis/run", req),
  runBacktest: (req: BacktestRequest) => send<BacktestResponse>("POST", "/api/backtest/run", req),
  getPreset: () => get<AnalysisPreset>("/api/config/analysis"),
  savePreset: (p: AnalysisPreset) => send<AnalysisPreset>("PUT", "/api/config/analysis", p),
};
