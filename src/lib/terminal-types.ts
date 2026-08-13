export type AssetClass = "forex" | "stock" | "crypto" | "cfd" | "futures";
export type RiskProfile = "conservative" | "balanced" | "aggressive";
export type AgentMode = "advisory" | "guarded_autopilot";

export interface Instrument {
  id: string;
  symbol: string;
  name: string;
  asset_class: AssetClass;
  provider_symbol: string;
  quote_currency: string;
  multiplier: number;
  tick_size: number;
  session: string;
  eligibility: "trade_enabled" | "research_only";
  proxy: boolean;
  market_status: "open" | "closed";
}

export interface Quote {
  instrument_id: string;
  symbol: string;
  price: number | null;
  change: number | null;
  change_pct: number | null;
  as_of: string | null;
  source: string;
  delayed: boolean;
  stale: boolean;
  market_status: "open" | "closed";
}

export interface Position {
  id: string;
  instrument_id: string | null;
  pair: string;
  asset_class: AssetClass;
  side: "long" | "short";
  size: number;
  entry_price: number;
  current_price: number;
  pnl: number;
  pnl_pct: number;
  notional: number;
  opened_at: string;
  confidence: number;
  stop_loss: number | null;
  take_profit: number | null;
  protection_status: "protected" | "unprotected";
  quote_stale: boolean;
}

export interface Trade {
  id: string;
  instrument_id: string | null;
  pair: string;
  side: "long" | "short";
  size: number;
  entry_price: number;
  exit_price: number;
  pnl: number;
  fees: number;
  exit_reason: string;
  closed_at: string;
}

export interface Order {
  id: string;
  instrument_id: string;
  symbol: string;
  side: "long" | "short";
  quantity: number;
  status: "filled" | "rejected";
  fill_price: number | null;
  notional: number;
  risk_amount: number | null;
  fee: number;
  source: string;
  proposal_id: string | null;
  position_id: string | null;
  rejection_reason: string | null;
  created_at: string;
}

export interface Proposal {
  id: string;
  instrument_id: string;
  symbol: string;
  asset_class: AssetClass;
  side: "long" | "short";
  quantity: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  confidence: number | null;
  rationale: string;
  mode: AgentMode;
  status: "pending" | "executed" | "rejected";
  rejection_reason: string | null;
  created_at: string;
  decided_at: string | null;
  order_id: string | null;
}

export interface TradeIdea {
  id: string;
  instrument_id: string | null;
  symbol: string;
  asset_class: AssetClass;
  side: "long" | "short";
  entry_price: number;
  stop_loss: number | null;
  take_profit: number | null;
  confidence: number | null;
  reasoning: string | null;
  status: "active" | "closed";
  review_state: "valid" | "invalid" | "stale" | "needs_review" | "scored" | "unscored";
  outcome_pnl: number | null;
  created_at: string;
}

export interface Portfolio {
  starting_equity: number;
  equity: number;
  cash: number;
  open_pnl: number;
  realized: number;
  day_pnl: number;
  gross_exposure: number;
  exposure_pct: number;
  leverage: number;
  open_count: number;
  win_rate: number;
  wins: number;
  losses: number;
  breakeven: number;
  max_drawdown: number;
  risk_profile: RiskProfile;
  risk_used_pct: number;
  risk_limits: {
    risk_per_trade: number;
    daily_loss: number;
    max_exposure: number;
    max_positions: number;
  };
  equity_series: Array<{ t: string; eq: number }>;
  daily_pnl: Array<{ d: string; v: number }>;
  by_asset: Array<{ k: AssetClass; exposure: number; pnl: number; count: number; pct: number }>;
}

export interface AgentStatus {
  running: boolean;
  provider: string;
  model: string;
  cycle_count: number;
  last_cycle: string | null;
  last_error: string | null;
  interval_seconds: number;
  mode: AgentMode;
  kill_switch: boolean;
  stage: string;
  cycle_active: boolean;
}

export interface TerminalConfig {
  starting_equity: number;
  display_currency: string;
  risk_profile: RiskProfile;
  allowed_asset_classes: string;
  agent_mode: AgentMode;
  kill_switch: boolean;
  last_backup_path: string | null;
}

export interface LogEntry {
  id: string;
  level: "info" | "warn" | "error";
  action: string;
  pair: string | null;
  message: string;
  created_at: string;
}

export interface AgentRun {
  id: string;
  mode: AgentMode;
  status: string;
  stage: string;
  started_at: string;
  duration_ms: number | null;
  error: string | null;
  proposal_count: number;
  executed_count: number;
}

export interface SystemStatus {
  backend: { ok: boolean; version: string };
  database: { ok: boolean; path: string; backup_path: string | null };
  market_data: { provider: string; ok: boolean; delayed: boolean; stale_count?: number };
  llm: { configured: boolean; provider: string; model: string };
  autopilot_ready: boolean;
}

export interface BootstrapData {
  as_of: string;
  portfolio: Portfolio;
  positions: Position[];
  trades: Trade[];
  orders: Order[];
  proposals: Proposal[];
  trade_ideas: TradeIdea[];
  logs: LogEntry[];
  agent_runs: AgentRun[];
  agent: AgentStatus;
  instruments: Instrument[];
  quotes: Record<string, Quote>;
  config: TerminalConfig;
  system: SystemStatus;
}

export interface ValidationIssue {
  code: string;
  message: string;
  field?: string | null;
}

export interface OrderPreview {
  allowed: boolean;
  instrument?: Instrument;
  quote?: Quote;
  side?: "long" | "short";
  quantity?: number;
  estimated_fill?: number;
  notional?: number;
  risk_amount?: number | null;
  fee?: number;
  estimated_exit_fee?: number;
  slippage_bps?: number;
  resulting_exposure_pct?: number;
  max_risk?: number;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
}
