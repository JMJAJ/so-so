export type AssetClass = "stock" | "etf" | "crypto" | "forex" | "commodity" | "index";
export const ASSET_CLASS_ORDER: AssetClass[] = [
  "stock",
  "etf",
  "crypto",
  "forex",
  "commodity",
  "index",
];

export interface Instrument {
  id: string;
  symbol: string;
  name: string;
  asset_class: AssetClass;
  provider_symbol: string;
  sector: string;
  quote_currency: string;
  multiplier: number;
  tradable: boolean;
  benchmark_id: string | null;
  market_open?: boolean;
  quote?: Quote | null;
}

export interface Quote {
  instrument_id: string;
  price: number | null;
  change_pct: number | null;
  as_of: string | null;
  stale: boolean;
  market_open: boolean;
}

export type SignalName = "momentum" | "trend" | "reversal" | "rsi" | "analog" | "event";
export const SIGNALS: SignalName[] = ["momentum", "trend", "reversal", "rsi", "analog", "event"];

export interface Forecast {
  instrument_id: string;
  symbol: string;
  name: string;
  asset_class: AssetClass;
  sector: string;
  as_of: string;
  stale_days: number;
  price: number;
  signals: Record<SignalName, number | null>;
  vol_20d: number | null;
  model_has_edge: boolean;
  expected_return: number | null;
  sigma: number | null;
  score: number | null;
  prob_up: number | null;
  contributions: Record<string, number | null>;
  recent_events: string[];
  news_flow: number;
  news_count: number;
}

export interface Evidence {
  type: string;
  summary: string;
  n?: number;
  stat?: number;
}

export interface Recommendation {
  id: string;
  created_at: string;
  instrument_id: string;
  symbol: string;
  name: string;
  asset_class: AssetClass;
  direction: "long" | "short";
  horizon_days: number;
  entry_price: number;
  stop: number;
  target: number;
  expected_return: number | null;
  probability: number;
  confidence: "low" | "medium" | "high";
  thesis: string;
  catalysts: string[];
  evidence: Evidence[];
  invalidation: string;
  source: string;
  run_id: string | null;
  status: "open" | "closed" | "cancelled";
  position_id: string | null;
  expires_at: string;
  closed_at: string | null;
  exit_price: number | null;
  exit_reason: string | null;
  realized_return: number | null;
  benchmark_return: number | null;
  excess_return: number | null;
  mark_price: number | null;
  mark_return: number | null;
  trade_note?: string;
}

export interface Regime {
  risk: "risk-on" | "risk-off" | "neutral";
  vix: number | null;
  vix_percentile: number | null;
  spy_trend: "up" | "down" | null;
  spy_ret_60d: number | null;
  spy_drawdown: number | null;
  curve_10y_3m: number | null;
  curve_inverted: boolean;
  us10y: number | null;
  us10y_chg_60d: number | null;
  dollar_ret_60d: number | null;
  oil_ret_60d: number | null;
  hy_spread: number | null;
  conflict_z: number | null;
}

export interface HorizonStats {
  n: number;
  mean: number;
  median: number;
  baseline: number;
  edge: number;
  hit_rate: number;
  t_stat: number;
  p_value: number;
}

export interface MarketEvent {
  id: string;
  type: string;
  label: string;
  instrument_id: string | null;
  scope?: string;
  date: string;
  title: string;
  magnitude: number | null;
  surprise: number | null;
  source?: string;
  impact_on?: string;
  impact?: HorizonStats | null;
  most_affected?: Array<{
    instrument_id: string;
    symbol: string;
    n: number;
    edge: number;
    hit_rate: number;
    t_stat: number;
  }>;
}

export interface NewsItem {
  id: string;
  published_at: string;
  title: string;
  summary: string | null;
  url: string | null;
  source: string | null;
  provider: string;
  category: string | null;
  direction: number | null;
  magnitude: number | null;
  affected: string[];
  tickers: string[];
  rationale: string | null;
  historical_analogs: string[];
}

export interface Position {
  id: string;
  instrument_id: string;
  symbol: string;
  name: string;
  asset_class: AssetClass;
  side: "long" | "short";
  quantity: number;
  status: "pending" | "open";
  entry_price: number | null;
  current_price: number | null;
  pnl: number;
  pnl_pct: number;
  notional: number;
  stop: number | null;
  target: number | null;
  expires_at: string | null;
  recommendation_id: string | null;
  created_at: string;
  opened_at: string | null;
}

export interface Trade {
  id: string;
  instrument_id: string;
  symbol: string;
  side: "long" | "short";
  quantity: number;
  entry_price: number;
  exit_price: number;
  opened_at: string;
  closed_at: string;
  net_pnl: number;
  fees: number;
  exit_reason: string;
  recommendation_id: string | null;
}

export interface Portfolio {
  starting_equity: number;
  equity: number;
  cash: number;
  realized: number;
  unrealized: number;
  exposure: number;
  exposure_pct: number;
  return_pct: number;
  open_count: number;
  pending_count: number;
  trade_count: number;
  win_rate: number | null;
  avg_win: number | null;
  avg_loss: number | null;
  positions: Position[];
  equity_curve?: Array<{
    date: string;
    equity: number;
    return_pct: number;
    spy_return_pct: number | null;
  }>;
  trades?: Trade[];
}

export interface RecordStats {
  n: number;
  hit_rate?: number | null;
  avg_return?: number | null;
  avg_excess?: number | null;
  t_stat?: number | null;
  brier?: number;
  avg_probability?: number;
  best?: number | null;
  worst?: number | null;
}

export interface TrackRecord {
  overall: RecordStats;
  open: { n: number; avg_mark_return: number | null };
  by_asset_class: Record<string, RecordStats>;
  by_confidence: Record<string, RecordStats>;
  by_direction: Record<string, RecordStats>;
  by_source: Record<string, RecordStats>;
  by_evidence: Record<string, RecordStats>;
  by_exit: Record<string, RecordStats>;
  calibration: Array<{ bucket: string; n: number; stated: number; realized: number }>;
  recent: Recommendation[];
  lessons: string;
}

export interface SignalStats {
  ic: number;
  t_stat: number;
  n: number;
  hit_rate: number | null;
  long_short: number | null;
}

export interface ModelSummary {
  asset_class: string;
  computed_at: string;
  has_edge: boolean;
  reason: string | null;
  walk_forward: {
    ic: number;
    t_stat: number;
    n: number;
    hit_rate: number;
    top_quintile: number;
    bottom_quintile: number;
    long_short: number;
    unconditional: number;
    ic_by_year: Record<string, number>;
    period: [string, string];
  } | null;
  signals: Record<string, SignalStats> | null;
  coefficients: Record<string, number> | null;
}

export interface AnalogResult {
  instrument_id: string;
  as_of: string;
  k: number;
  horizon: number;
  features: string[];
  today_state: Record<string, number>;
  mean_return: number;
  median_return: number;
  hit_rate: number;
  mean_excess: number | null;
  dispersion: number;
  analogs: Array<{ date: string; distance: number; fwd_return: number }>;
  fan?: Array<{ day: number; p10: number; p25: number; p50: number; p75: number; p90: number }>;
}

export interface EventEffect {
  event_type: string;
  label: string;
  measure: string;
  n: number;
  mean: number;
  edge: number;
  hit_rate: number;
  t_stat: number;
  p_value: number;
  baseline: number;
  median: number;
}

export interface AssetDetail {
  instrument: Instrument;
  quote: Quote | null;
  bars: Array<{
    t: string;
    o: number | null;
    h: number | null;
    l: number | null;
    c: number;
    v: number | null;
  }>;
  technicals: Record<string, number | null> | null;
  forecast: Forecast | null;
  events: MarketEvent[];
  event_effects: {
    active_events_last_10d: Array<{
      date: string;
      type: string;
      title: string;
      history: HorizonStats | null;
      pooled: boolean | null;
    }>;
    most_reliable_event_effects: EventEffect[];
  };
  analogs: AnalogResult | null;
  correlations: {
    peers: {
      positive: Array<{
        instrument_id: string;
        symbol: string;
        corr_1y: number;
        corr_60d: number | null;
      }>;
      negative: Array<{
        instrument_id: string;
        symbol: string;
        corr_1y: number;
        corr_60d: number | null;
      }>;
    };
    lead_lag: Array<{
      driver: string;
      name: string;
      horizon: number;
      corr: number;
      n: number;
      threshold: number;
      latest_z: number | null;
      implied_direction: number;
    }>;
  };
  news: NewsItem[];
  recommendations: Recommendation[];
}

export interface EventStudyDetail {
  impact: {
    event_type: string;
    label: string;
    pooled: boolean;
    basis: string;
    measure: string;
    horizons: Record<string, HorizonStats>;
  } | null;
  event_type: string;
  label: string;
  measure: string;
  rows: Array<
    { date: string; title: string; surprise: number | null } & Record<
      string,
      number | null | string
    >
  >;
}

export interface JobStatus {
  name: string;
  description?: string;
  running: boolean;
  progress: string | null;
  last_status: string | null;
  last_started?: string | null;
  last_finished: string | null;
  last_error?: string | null;
  last_summary?: string | null;
  duration_ms?: number | null;
  next_run: string | null;
}

export interface SystemStatus {
  has_data: boolean;
  universe_size: number;
  coverage: {
    instruments: number;
    last_bar: string | null;
    events: number;
    news: number;
    news_classified: number;
    gdelt_days: number;
    gdelt_from: string | null;
    event_impact_rows: number;
  };
  llm: { provider: string; model: string; fast_model: string; key_set: boolean };
  analyst_running: boolean;
  jobs: JobStatus[];
  autopilot: boolean;
}

export interface Dashboard {
  regime: {
    current: Regime;
    as_of: string;
    history: Array<{
      date: string;
      vix: number | null;
      spy_dd: number | null;
      curve: number | null;
      conflict_z: number | null;
    }>;
  } | null;
  ideas: Forecast[];
  open_recommendations: Recommendation[];
  brief: {
    id: string;
    started_at: string;
    finished_at: string | null;
    status: string;
    summary: string | null;
    error: string | null;
  } | null;
  key_events: MarketEvent[];
  headlines: NewsItem[];
  portfolio: Pick<
    Portfolio,
    | "equity"
    | "return_pct"
    | "exposure_pct"
    | "open_count"
    | "pending_count"
    | "realized"
    | "unrealized"
  >;
  track: RecordStats;
}

export interface Settings {
  values: Record<string, string>;
  secrets: Record<string, { set: boolean; source: string | null; hint: string | null }>;
  providers: Record<
    string,
    { label: string; default_model: string; key: string | null; base_url?: string }
  >;
  asset_classes: string[];
}

export interface Run {
  id: string;
  kind: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  summary: string | null;
  error: string | null;
}

export interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  tools?: Array<{
    id?: string;
    name: string;
    input: Record<string, unknown>;
    is_error?: boolean;
    preview?: string;
  }>;
  pending?: boolean;
}

export type ChatEvent =
  | { type: "conversation"; id: string }
  | { type: "text"; text: string }
  | { type: "tool_call"; id: string; name: string; input: Record<string, unknown> }
  | { type: "tool_result"; id: string; name: string; is_error: boolean; preview: string }
  | { type: "done"; stop_reason: string }
  | { type: "error"; message: string }
  | { type: "end" };
