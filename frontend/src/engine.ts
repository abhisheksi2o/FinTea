/**
 * Browser-side spreadsheet engine for the static (GitHub Pages) build.
 *
 * Parses the Excel formulas embedded in the model JSON and evaluates them with
 * Excel semantics (blank -> 0, error propagation, SUM ignores text, ...). It
 * supports exactly the grammar FinTea's Python renderer emits: cell and range
 * references (optionally sheet-qualified), + - * / ^, comparisons, unary minus,
 * numbers, strings, TRUE/FALSE and the functions SUM AVERAGE MIN MAX COUNT ABS
 * SQRT ROUND IF AND OR NOT IFERROR SLOPE INTERCEPT RSQ CORREL STDEV VARP COVAR.
 */
import type { Cell, Sheet } from "./types";

export class XErr { constructor(public code: string) {} }
export type Val = number | string | boolean | null | XErr;
const DIV0 = new XErr("#DIV/0!"), VALUE = new XErr("#VALUE!"), NUM = new XErr("#NUM!"), NA = new XErr("#N/A"), REF = new XErr("#REF!");

type Node =
  | { t: "num"; v: number } | { t: "str"; v: string } | { t: "bool"; v: boolean }
  | { t: "ref"; sheet: string | null; r: number; c: number }
  | { t: "range"; sheet: string | null; r0: number; c0: number; r1: number; c1: number }
  | { t: "bin"; op: string; a: Node; b: Node } | { t: "neg"; a: Node } | { t: "fn"; name: string; args: Node[] };

// ---------------------------------------------------------------- tokenizer
type Tok = { k: "num" | "str" | "id" | "op" | "ref" | "end"; v: string; sheet?: string | null };

function colNum(letters: string): number { let n = 0; for (const ch of letters) n = n * 26 + (ch.charCodeAt(0) - 64); return n; }

function tokenize(src: string): Tok[] {
  const out: Tok[] = [];
  let i = 0;
  while (i < src.length) {
    const ch = src[i];
    if (ch === " ") { i++; continue; }
    if (ch === "'") { // quoted sheet name
      let j = i + 1, name = "";
      while (j < src.length) { if (src[j] === "'") { if (src[j + 1] === "'") { name += "'"; j += 2; continue; } break; } name += src[j]; j++; }
      if (src[j + 1] !== "!") throw new Error("bad sheet ref");
      i = j + 2;
      const m = /^\$?[A-Z]{1,3}\$?\d+/.exec(src.slice(i));
      if (!m) throw new Error("bad ref after sheet");
      out.push({ k: "ref", v: m[0].replace(/\$/g, ""), sheet: name }); i += m[0].length; continue;
    }
    if (ch === '"') { let j = i + 1, s = ""; while (j < src.length) { if (src[j] === '"') { if (src[j + 1] === '"') { s += '"'; j += 2; continue; } break; } s += src[j]; j++; } out.push({ k: "str", v: s }); i = j + 1; continue; }
    const num = /^(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?/.exec(src.slice(i));
    if (num) { out.push({ k: "num", v: num[0] }); i += num[0].length; continue; }
    const ref = /^\$?[A-Z]{1,3}\$?\d+(?![A-Za-z0-9_(])/.exec(src.slice(i));
    if (ref) { out.push({ k: "ref", v: ref[0].replace(/\$/g, ""), sheet: null }); i += ref[0].length; continue; }
    const id = /^[A-Za-z_][A-Za-z0-9_.]*/.exec(src.slice(i));
    if (id) { out.push({ k: "id", v: id[0].toUpperCase() }); i += id[0].length; continue; }
    const op = /^(<>|<=|>=|[-+*/^=<>(),:])/.exec(src.slice(i));
    if (op) { out.push({ k: "op", v: op[0] }); i += op[0].length; continue; }
    throw new Error(`unexpected '${ch}' in formula`);
  }
  out.push({ k: "end", v: "" });
  return out;
}

// ------------------------------------------------------------------- parser
function parse(formula: string): Node {
  const toks = tokenize(formula.startsWith("=") ? formula.slice(1) : formula);
  let p = 0;
  const peek = () => toks[p], next = () => toks[p++];
  const expect = (v: string) => { const t = next(); if (t.v !== v) throw new Error(`expected ${v}`); };
  function refNode(t: Tok): Node {
    const m = /^([A-Z]+)(\d+)$/.exec(t.v)!;
    const node = { t: "ref" as const, sheet: t.sheet ?? null, r: +m[2], c: colNum(m[1]) };
    if (peek().k === "op" && peek().v === ":") { next(); const t2 = next(); const m2 = /^([A-Z]+)(\d+)$/.exec(t2.v)!;
      return { t: "range", sheet: node.sheet, r0: node.r, c0: node.c, r1: +m2[2], c1: colNum(m2[1]) }; }
    return node;
  }
  function primary(): Node {
    const t = next();
    if (t.k === "num") return { t: "num", v: parseFloat(t.v) };
    if (t.k === "str") return { t: "str", v: t.v };
    if (t.k === "ref") return refNode(t);
    if (t.k === "id") {
      if (t.v === "TRUE") return { t: "bool", v: true };
      if (t.v === "FALSE") return { t: "bool", v: false };
      expect("(");
      const args: Node[] = [];
      if (!(peek().k === "op" && peek().v === ")")) { for (;;) { args.push(comparison()); if (peek().v === ",") { next(); continue; } break; } }
      expect(")");
      return { t: "fn", name: t.v, args };
    }
    if (t.k === "op" && t.v === "(") { const e = comparison(); expect(")"); return e; }
    if (t.k === "op" && t.v === "-") return { t: "neg", a: unary() };
    if (t.k === "op" && t.v === "+") return unary();
    throw new Error(`unexpected token ${t.v}`);
  }
  function unary(): Node { return primary(); }
  function power(): Node { let a = unary(); while (peek().v === "^" && peek().k === "op") { next(); a = { t: "bin", op: "^", a, b: unary() }; } return a; }
  function term(): Node { let a = power(); while (peek().k === "op" && (peek().v === "*" || peek().v === "/")) { const op = next().v; a = { t: "bin", op, a, b: power() }; } return a; }
  function additive(): Node { let a = term(); while (peek().k === "op" && (peek().v === "+" || peek().v === "-")) { const op = next().v; a = { t: "bin", op, a, b: term() }; } return a; }
  function comparison(): Node { let a = additive(); while (peek().k === "op" && ["=", "<>", "<", "<=", ">", ">="].includes(peek().v)) { const op = next().v; a = { t: "bin", op, a, b: additive() }; } return a; }
  const node = comparison();
  if (peek().k !== "end") throw new Error("trailing tokens");
  return node;
}

// ---------------------------------------------------------------- evaluator
const isNum = (v: unknown): v is number => typeof v === "number";
function num(v: Val): number | XErr {
  if (v === null || v === undefined) return 0;
  if (typeof v === "boolean") return v ? 1 : 0;
  if (isNum(v)) return v;
  if (v instanceof XErr) return v;
  return VALUE;
}
function numbers(vals: Val[]): number[] | XErr { const out: number[] = []; for (const v of vals) { if (v instanceof XErr) return v; if (isNum(v)) out.push(v); } return out; }
function pairs(ys: Val[], xs: Val[]): [number, number][] | XErr {
  if (ys.length !== xs.length) return NA;
  const pts: [number, number][] = [];
  for (let i = 0; i < ys.length; i++) { const y = ys[i], x = xs[i]; if (isNum(y) && isNum(x)) pts.push([y, x]); }
  return pts.length < 2 ? DIV0 : pts;
}
function stats(ys: Val[], xs: Val[]) {
  const pts = pairs(ys, xs); if (pts instanceof XErr) return pts;
  const n = pts.length, my = pts.reduce((s, p) => s + p[0], 0) / n, mx = pts.reduce((s, p) => s + p[1], 0) / n;
  let sxx = 0, syy = 0, sxy = 0;
  for (const [y, x] of pts) { sxx += (x - mx) ** 2; syy += (y - my) ** 2; sxy += (x - mx) * (y - my); }
  return { n, my, mx, sxx, syy, sxy };
}
function roundHalfAway(x: number, n: number) { const m = 10 ** n; return (Math.floor(Math.abs(x) * m + 0.5) / m) * (x >= 0 ? 1 : -1); }

export class Engine {
  private cells = new Map<string, Map<string, Cell>>();
  private ast = new Map<Cell, Node>();
  private memo = new Map<Cell, Val>();
  private stack = new Set<Cell>();
  constructor(public sheets: Sheet[]) {
    for (const s of sheets) { const m = new Map<string, Cell>(); for (const row of s.rows) for (const c of row.cells) m.set(`${row.r}:${c.c}`, c); this.cells.set(s.name, m); }
  }
  cell(sheet: string, r: number, c: number): Cell | undefined { return this.cells.get(sheet)?.get(`${r}:${c}`); }
  keyed(sheet: string, key: string): Cell[] { const out: Cell[] = []; for (const c of this.cells.get(sheet)?.values() ?? []) if (c.k === key) out.push(c); return out; }
  private valueAt(sheet: string, r: number, c: number): Val {
    const cell = this.cell(sheet, r, c);
    return cell ? this.value(cell, sheet) : null;
  }
  value(cell: Cell, sheet: string): Val {
    if (!cell.f) return cell.err ? new XErr(cell.err) : (cell.v as Val);
    if (this.memo.has(cell)) return this.memo.get(cell)!;
    if (this.stack.has(cell)) throw new Error("circular reference");
    this.stack.add(cell);
    try {
      let node = this.ast.get(cell);
      if (!node) { node = parse(cell.f); this.ast.set(cell, node); }
      const v = this.eval(node, sheet);
      this.memo.set(cell, v);
      return v;
    } finally { this.stack.delete(cell); }
  }
  private rangeVals(n: Extract<Node, { t: "range" }>, sheet: string): Val[] {
    const sh = n.sheet ?? sheet; const out: Val[] = [];
    for (let r = n.r0; r <= n.r1; r++) for (let c = n.c0; c <= n.c1; c++) out.push(this.valueAt(sh, r, c));
    return out;
  }
  private argVals(a: Node, sheet: string): Val[] { return a.t === "range" ? this.rangeVals(a, sheet) : [this.eval(a, sheet)]; }
  private eval(n: Node, sheet: string): Val {
    switch (n.t) {
      case "num": return n.v; case "str": return n.v; case "bool": return n.v;
      case "ref": return this.valueAt(n.sheet ?? sheet, n.r, n.c);
      case "range": return REF;
      case "neg": { const v = num(this.eval(n.a, sheet)); return v instanceof XErr ? v : -v; }
      case "bin": {
        const a = this.eval(n.a, sheet), b = this.eval(n.b, sheet), op = n.op;
        if (["=", "<>", "<", "<=", ">", ">="].includes(op)) {
          if (a instanceof XErr) return a; if (b instanceof XErr) return b;
          if (typeof a === "string" || typeof b === "string") {
            const sa = String(a ?? "").toLowerCase(), sb = String(b ?? "").toLowerCase();
            if (op === "=") return sa === sb; if (op === "<>") return sa !== sb; return VALUE;
          }
          const x = num(a) as number, y = num(b) as number;
          return op === "=" ? x === y : op === "<>" ? x !== y : op === "<" ? x < y : op === "<=" ? x <= y : op === ">" ? x > y : x >= y;
        }
        const x = num(a), y = num(b);
        if (x instanceof XErr) return x; if (y instanceof XErr) return y;
        if (op === "+") return x + y; if (op === "-") return x - y; if (op === "*") return x * y;
        if (op === "/") return y === 0 ? DIV0 : x / y;
        if (op === "^") { const r = Math.pow(x, y); return Number.isNaN(r) || !Number.isFinite(r) ? NUM : r; }
        return VALUE;
      }
      case "fn": return this.fn(n, sheet);
    }
  }
  private fn(n: Extract<Node, { t: "fn" }>, sheet: string): Val {
    const A = n.args;
    if (n.name === "IF") { const c = this.eval(A[0], sheet); if (c instanceof XErr) return c; return num(c) ? this.eval(A[1], sheet) : (A[2] ? this.eval(A[2], sheet) : false); }
    if (n.name === "IFERROR") { const v = this.eval(A[0], sheet); return v instanceof XErr ? this.eval(A[1], sheet) : v; }
    const flat: Val[] = []; for (const a of A) flat.push(...this.argVals(a, sheet));
    const scalar = (i: number) => this.eval(A[i], sheet);
    switch (n.name) {
      case "SUM": { const v = numbers(flat); return v instanceof XErr ? v : v.reduce((s, x) => s + x, 0); }
      case "AVERAGE": { const v = numbers(flat); if (v instanceof XErr) return v; return v.length ? v.reduce((s, x) => s + x, 0) / v.length : DIV0; }
      case "MIN": { const v = numbers(flat); return v instanceof XErr ? v : (v.length ? Math.min(...v) : 0); }
      case "MAX": { const v = numbers(flat); return v instanceof XErr ? v : (v.length ? Math.max(...v) : 0); }
      case "COUNT": { const v = numbers(flat); return v instanceof XErr ? v : v.length; }
      case "ABS": { const v = num(scalar(0)); return v instanceof XErr ? v : Math.abs(v); }
      case "SQRT": { const v = num(scalar(0)); return v instanceof XErr ? v : v < 0 ? NUM : Math.sqrt(v); }
      case "ROUND": { const v = num(scalar(0)); const d = A[1] ? num(scalar(1)) : 0; if (v instanceof XErr) return v; if (d instanceof XErr) return d; return roundHalfAway(v, d); }
      case "AND": { for (const v of flat) { const x = num(v); if (x instanceof XErr) return x; if (!x) return false; } return true; }
      case "OR": { for (const v of flat) { const x = num(v); if (x instanceof XErr) return x; if (x) return true; } return false; }
      case "NOT": { const v = num(scalar(0)); return v instanceof XErr ? v : !v; }
      case "STDEV": { const v = numbers(flat); if (v instanceof XErr) return v; if (v.length < 2) return DIV0; const m = v.reduce((s, x) => s + x, 0) / v.length; return Math.sqrt(v.reduce((s, x) => s + (x - m) ** 2, 0) / (v.length - 1)); }
      case "VARP": { const v = numbers(flat); if (v instanceof XErr) return v; if (!v.length) return DIV0; const m = v.reduce((s, x) => s + x, 0) / v.length; return v.reduce((s, x) => s + (x - m) ** 2, 0) / v.length; }
      case "SLOPE": case "INTERCEPT": case "RSQ": case "CORREL": case "COVAR": {
        const ys = this.argVals(A[0], sheet), xs = this.argVals(A[1], sheet);
        const st = stats(ys, xs); if (st instanceof XErr) return st;
        if (n.name === "COVAR") return st.sxy / st.n;
        if (st.sxx === 0) return DIV0;
        const slope = st.sxy / st.sxx;
        if (n.name === "SLOPE") return slope;
        if (n.name === "INTERCEPT") return st.my - slope * st.mx;
        if (st.syy === 0) return DIV0;
        const r = st.sxy / Math.sqrt(st.sxx * st.syy);
        return n.name === "CORREL" ? r : r * r;
      }
    }
    throw new Error(`unsupported function ${n.name}`);
  }
  /** Re-evaluate every formula cell and write values back into the sheet JSON. */
  recalculate(): number {
    this.memo.clear();
    let n = 0;
    for (const s of this.sheets) for (const row of s.rows) for (const c of row.cells) {
      if (!c.f) continue;
      const v = this.value(c, s.name);
      if (v instanceof XErr) { c.v = null; c.err = v.code; } else { c.v = v; delete c.err; }
      n++;
    }
    return n;
  }
}
