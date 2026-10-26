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
  /** Id of the market it trades on (see /api/markets). */
  market?: string;
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
  /** Whether the call has a live paper position (false: tracked only). */
  traded?: boolean;
  /** Skills loaded when the call was made / closed early, as "name@version". */
  skills?: string[];
  close_skills?: string[];
  /** For AI early closes: what holding to stop/target/horizon would have returned. */
  hold_return?: number | null;
  lesson?: string | null;
}

export interface PaperAccount {
  id: string;
  name: string;
  starting_equity: number;
  started_at: string;
  /** strict: only positive-EV trades; any: whatever the user asks for. */
  gate: "strict" | "any";
  autopilot: boolean;
  created_at: string;
  equity: number;
  return_pct: number;
  positions: number;
  trade_count: number;
}

export interface SkillInfo {
  name: string;
  description: string;
  when: string;
  version: string;
  stats: Record<string, RecordStats>;
}

export interface EarlyCloseStats {
  n: number;
  scored: number;
  avg_realized: number | null;
  avg_if_held: number | null;
  avg_saved: number | null;
  helped: number;
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
  /** Benjamini–Hochberg q-value across every (event × asset) test at this horizon. */
  q_value?: number | null;
  stable?: boolean;
  reliable?: boolean;
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
  market?: string;
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

export interface ReplaySummary {
  calls: number;
  period?: [string, string];
  hit_rate?: number;
  avg_return?: number;
  t_stat?: number | null;
  avg_probability?: number;
  avg_base?: number | null;
  brier?: number;
  calibration?: Array<{ bucket: string; n: number; stated: number; realized: number }>;
  by_event_type?: Array<{ event_type: string; n: number; hit_rate: number; avg_return: number }>;
}

export interface TrackRecord {
  replay?: ReplaySummary;
  probability_calibration?: { k: number; basis: string };
  overall: RecordStats;
  open: { n: number; avg_mark_return: number | null };
  by_asset_class: Record<string, RecordStats>;
  by_confidence: Record<string, RecordStats>;
  by_direction: Record<string, RecordStats>;
  by_source: Record<string, RecordStats>;
  by_evidence: Record<string, RecordStats>;
  by_exit: Record<string, RecordStats>;
  by_skill: Record<string, RecordStats>;
  early_closes: EarlyCloseStats;
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
  q_value?: number | null;
  stable?: boolean;
  reliable?: boolean;
}

export interface MarketStatus {
  id: string;
  name: string;
  city: string;
  tz: string;
  kind: "exchange" | "forex" | "futures" | "crypto";
  note: string;
  holidays_known: boolean;
  open: boolean;
  phase: "open" | "closed" | "pre-market" | "after-hours" | "lunch break";
  local_time: string;
  local_weekday: string;
  tz_abbr: string;
  closes_at: string | null;
  opens_at: string | null;
  next_session: [string, string] | null;
  /** Regular sessions as UTC [open, close] ISO pairs, from ~2.5 days ago to ~8 days ahead. */
  intervals: Array<[string, string]>;
  extended_intervals: Array<[string, string]>;
}

export interface MarketsOverview {
  now: string;
  markets: MarketStatus[];
}

export type IntradaySpan = "1d" | "5d" | "1mo";

export interface IntradayBars {
  instrument_id: string;
  span: IntradaySpan;
  /** t = epoch seconds (UTC). */
  bars: Array<{
    t: number;
    o: number | null;
    h: number | null;
    l: number | null;
    c: number | null;
    v: number | null;
  }>;
  quote: Quote | null;
}

export interface AssetDetail {
  instrument: Instrument;
  market?: MarketStatus;
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
    {
      label: string;
      default_model: string;
      fast_model?: string;
      key: string | null;
      base_url?: string;
    }
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

export interface Brief extends Run {
  recommendations: Recommendation[];
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
  charts?: ChatChart[];
  pending?: boolean;
}

export type FanRow = {
  day: number;
  p10: number;
  p25: number;
  p50: number;
  p75: number;
  p90: number;
};

/** How often past outcomes landed inside the simulator's bands (replayed on past dates). */
export interface SimCheckScore {
  n: number;
  in80: number;
  in50: number;
  brier: number;
  brier_base: number;
  verdict: string;
  scope?: string;
  horizon?: number;
}

export interface AssetSimulation {
  instrument_id: string;
  symbol: string;
  price: number;
  horizon: number;
  paths: number;
  as_of: string;
  fan: FanRow[];
  p_up: number;
  mean: number;
  median: number;
  var95: number;
  cvar95: number;
  typical_drawdown: number;
  vol_now: number;
  vol_long: number;
  method: { basis: string; drift: string; history_days: number; block: number };
  bracket?: {
    direction: "long" | "short";
    stop: number | null;
    target: number | null;
    p_target: number;
    p_stop: number;
    p_neither: number;
    p_profit: number;
    expected_return: number;
    note: string;
  };
  bracket_source?: string;
  levels?: Array<{ label: string; value: number }>;
  check: SimCheckScore | null;
}

export interface PortfolioSimulation {
  account: string;
  equity: number;
  horizon: number;
  paths: number;
  fan: FanRow[] | null;
  note: string;
  pending_skipped: number;
  positions: Array<{
    instrument_id?: string;
    symbol: string;
    side: "long" | "short";
    skipped?: string;
    notional?: number;
    mean_pnl?: number;
    p5_pnl?: number;
    p_stop?: number;
    p_target?: number;
    risk_share?: number;
  }>;
  mean_pnl?: number;
  median_pnl?: number;
  p_loss?: number;
  p_loss_5pct?: number;
  p_loss_10pct?: number;
  p_gain_5pct?: number;
  var95?: number;
  cvar95?: number;
  check?: SimCheckScore | null;
}

export interface ScenarioPreset {
  id: string;
  label: string;
  driver: string;
  move?: number;
  window?: number;
}

export interface ScenarioResult {
  driver: string;
  move: number | null;
  window: number | null;
  horizon: number;
  title: string;
  occurrences: number;
  now: string;
  account: string;
  account_effect: number | null;
  reliable_count: number;
  note: string;
  assets: Array<{
    instrument_id: string;
    symbol: string;
    n: number;
    mean: number;
    median: number;
    hit_rate: number;
    normal: number;
    edge: number;
    t_stat: number;
    q_value: number | null;
    stable: boolean;
    reliable: boolean;
    position?: "long" | "short";
    position_effect?: number;
  }>;
}

export interface SimCheckSummary {
  horizon: number;
  n: number;
  overall: SimCheckScore | null;
  by_class: Record<string, SimCheckScore>;
  from?: string;
  to?: string;
  note: string;
}

/** Charts the AI puts in chat via the show_chart tool (built server-side from stored data). */
export type ChatChart =
  | {
      kind: "line";
      title: string;
      format: "price" | "pct";
      series: Array<{ name: string; points: Array<{ x: string; y: number | null }> }>;
      levels: Array<{ label: string; value: number; tone: "amber" | "bull" | "bear" }>;
      markers: Array<{ x: string; label: string }>;
    }
  | {
      kind: "fan";
      title: string;
      horizon: number;
      fan: NonNullable<AnalogResult["fan"]>;
      levels?: Array<{ label: string; value: number }>;
      note?: string;
    }
  | {
      kind: "bar";
      title: string;
      format: "pct" | "number" | "money";
      bars: Array<{ label: string; value: number; note?: string }>;
      note?: string;
    };

export type ChatEvent =
  | { type: "conversation"; id: string }
  | { type: "text"; text: string }
  | { type: "tool_call"; id: string; name: string; input: Record<string, unknown> }
  | { type: "tool_result"; id: string; name: string; is_error: boolean; preview: string }
  | { type: "chart"; id: string; chart: ChatChart }
  | { type: "done"; stop_reason: string }
  | { type: "error"; message: string }
  | { type: "end" };
