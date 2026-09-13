export interface SearchResult { symbol: string; name: string; exchange: string; type: string }
export interface Provider { id: string; name: string; description: string; available: boolean; requires: string; reason: string }

export interface Cell {
  c: number; v: number | string | boolean | null; fmt: string; s: string;
  f?: string; err?: string; k?: string; b?: boolean; i?: number; n?: string;
}
export interface SheetRow { r: number; cells: Cell[] }
export interface Sheet {
  name: string; max_row: number; max_col: number;
  col_widths: Record<string, number>; period_cols: Record<string, number>; rows: SheetRow[];
}
export interface AssumptionItem {
  key: string; label: string; section: string; fmt: string; kind: "scalar" | "vector";
  value: number | number[]; basis: string; overridden: boolean; min: number | null; max: number | null; help: string;
}
export interface QuantCheck { check: string; value: number | null; fmt: string; threshold: string; status: string; why: string }
export interface Feedback {
  status: string; n_fail: number; n_flag: number; quantitative: QuantCheck[];
  qualitative: { title: string; points: string[] }[]; methodology: string[];
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
  download_url: string; sheets?: Sheet[];
}
