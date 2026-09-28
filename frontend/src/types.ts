export interface SearchResult { symbol: string; name: string; exchange: string; type: string; sector?: string; industry?: string }
export interface Provider { id: string; name: string; description: string; available: boolean; requires: string; reason: string }

export interface Cell {
  c: number; v: number | string | boolean | null; fmt: string; s: string;
  f?: string; err?: string; k?: string; b?: boolean; i?: number; n?: string; hl?: string; w?: boolean;
}
export interface SheetRow { r: number; cells: Cell[] }
export interface ChartSeries { name: string; color: string | null; values: (number | string | null)[] }
export interface ChartSpec {
  id: string; type: "line" | "bar" | "radar" | "area"; title: string; fmt: string; y_title: string; x_title: string;
  stacked: boolean; y_min: number | null; y_max: number | null; note: string; anchor: string;
  categories: (string | number | null)[] | null; series: ChartSeries[];
}
export interface Sheet {
  name: string; max_row: number; max_col: number;
  col_widths: Record<string, number>; period_cols: Record<string, number>; rows: SheetRow[];
  merges?: string[]; freeze?: string | null; tab_color?: string | null; row_heights?: Record<string, number>;
  charts?: ChartSpec[];
}
export interface AssumptionItem {
  key: string; label: string; section: string; fmt: string; kind: "scalar" | "vector";
  value: number | number[]; basis: string; overridden: boolean; min: number | null; max: number | null; help: string;
}
export interface QuantCheck { check: string; value: number | null; fmt: string; threshold: string; status: string; why: string }
export interface QualitativeSection { title: string; points: string[] }
export interface Feedback {
  status: string; n_fail: number; n_flag: number; quantitative: QuantCheck[];
  qualitative: QualitativeSection[]; methodology: string[];
}
export interface Verification {
  status: string; reason?: string; engine?: string; cells_checked: number; max_abs_diff?: number;
  n_mismatches?: number; mismatches: { sheet: string; cell: string; expected: unknown; actual: unknown; formula: string }[];
}
export interface ModelResponse {
  id: string; provider: string; summary: Record<string, any>;
  assumptions: { years: number; items: AssumptionItem[] };
  feedback: Feedback; verification: Verification; meta: Record<string, any>;
  llm: { status: string; text?: string; model?: string; error?: string } | null;
  download_url: string; sheets?: Sheet[]; static?: boolean; client_generated?: boolean; parent_id?: string;
}

// ------------------------------------------------------------------ default risk analysis
export type RiskGrade = "Minimal" | "Low" | "Moderate" | "High" | "Severe";
export interface RiskInputItem {
  key: string; label: string; section: string; fmt: string; kind: "scalar";
  value: number; basis: string; overridden: boolean; min: number | null; max: number | null; help: string;
}
export interface DistressVote { model: string; distress: boolean }
export interface RiskFeedback extends Feedback { distress_votes: DistressVote[]; verification_text?: string }
export interface MertonSolve {
  asset_value: number | null; asset_vol: number | null; d1: number | null; d2: number | null;
  equity_model: number | null; equity_vol_model: number | null; residual_equity: number | null; residual_vol: number | null;
  pd_risk_neutral: number | null; iterations: number | null; converged: boolean; message: string;
}
/** Per-fiscal-year series aligned with `labels`; entries may be null when a model cannot be computed for that year. */
export interface RiskSeries { labels: string[]; [key: string]: (number | null)[] | string[] }
export interface RiskStress { pd_equity_shock: number | null; pd_vol_shock: number | null; pd_both: number | null; z2_ebit_shock: number | null; z2_ebit_zone: string | null; equity_shock: number | null; vol_shock: number | null; ebit_shock: number | null }
export interface ModelApplicability { model: string; status: string; missing: string[] }
export interface RiskSubScores { sig_z2: number | null; sig_merton: number | null; sig_ohlson: number | null; sig_rating: number | null; sig_zmij: number | null; sig_pio: number | null; sig_cons: number | null }
/** Which statements the latest column uses: the latest twelve months built from quarterly statements (when available) or the last fiscal year. */
export type RiskBasis = "ltm" | "annual";
export interface RiskSummary {
  company: string; symbol: string; currency: string; units: string; sector: string; industry: string; exchange: string;
  financial_sector: boolean; price: number | null; price_date: string; market_cap: number | null; market_cap_usd_bn: number | null;
  base_year: number; labels: string[]; nh: number; has_prior_year: boolean;
  basis?: RiskBasis; ltm?: boolean; base_label?: string; balance_date?: string; n_annual?: number; periods_note?: string; basis_note?: string;
  composite_score: number | null; composite_grade: RiskGrade | string; composite_equal: number | null;
  agreement: number | null; agreement_n: number | null;
  pd_merton_naive: number | null; dd_naive: number | null; pd_naive_rf: number | null; dd_naive_rf: number | null;
  pd_merton_rn: number | null; pd_merton_phys: number | null; dd_rn?: number | null;
  expected_loss: number | null; pd_cds: number | null; liquidity_coverage_12m: number | null;
  interest_estimated_coverage: number | null; rating_on_avg_ebit: string | null;
  stress: RiskStress | null; applicability: ModelApplicability[];
  dupont?: { roe: number | null; roe_five_step: number | null; net_margin: number | null; asset_turnover: number | null; equity_multiplier: number | null;
    tax_burden: number | null; interest_burden: number | null; ebit_margin: number | null; roa: number | null; leverage_effect: number | null; roe_change: number | null };
  asset_value: number | null; asset_vol: number | null; equity_vol: number | null; mu: number | null; default_point: number | null; merton_check?: number | null;
  altman_z: number | null; altman_zone: string | null; altman_z1: number | null; altman_z1_zone: string | null; altman_z2: number | null; altman_z2_zone: string | null;
  em_score: number | null; em_rating: string | null; piotroski: number | null; piotroski_class: string | null;
  beneish_m: number | null; beneish_m5?: number | null; beneish_prob: number | null; beneish_flag: string | null;
  ohlson_o: number | null; ohlson_pd: number | null; ohlson_flag: string | null;
  zmijewski_x: number | null; zmijewski_pd: number | null; zmijewski_flag: string | null;
  springate: number | null; springate_flag: string | null; grover: number | null; grover_flag: string | null; taffler: number | null; taffler_flag: string | null;
  synthetic_rating: string | null; rating_source: string | null; rating_em?: string | null; rating_cov?: string | null;
  default_spread: number | null; implied_cost_of_debt: number | null; interest_coverage: number | null; pd_rating_1y: number | null; pd_rating_5y: number | null;
  tl_ta: number | null; debt_to_equity: number | null; nd_ebitda: number | null; current_ratio: number | null; quick_ratio: number | null; roa: number | null;
  cfo_debt: number | null; runway_years: number | null; sub_scores: RiskSubScores;
  dq_status: string; n_fail: number; n_flag: number; error_cells: Record<string, unknown>; source: string; retrieved_at: string;
  vol_source: string; n_returns: number | null; series: RiskSeries;
  [key: string]: unknown;
}
export interface RiskResponse {
  id: string; provider: string; kind: "risk"; summary: RiskSummary;
  inputs: { items: RiskInputItem[]; stats: Record<string, unknown> };
  feedback: RiskFeedback; verification: Verification; meta: Record<string, any>;
  merton: MertonSolve | null; download_url: string; sheets?: Sheet[]; charts?: ChartSpec[];
  static?: boolean; client_generated?: boolean;
}
