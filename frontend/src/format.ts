export function fmtValue(v: unknown, fmt: string): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "boolean") return v ? "TRUE" : "FALSE";
  if (typeof v === "string") return v;
  const x = v as number;
  if (!isFinite(x)) return "#NUM!";
  const neg = x < 0;
  const wrap = (s: string) => (neg ? `(${s})` : s);
  const isZero = Math.abs(x) < 1e-9;
  switch (fmt) {
    case "num": return isZero ? "-" : wrap(Math.abs(x).toLocaleString("en-US", { maximumFractionDigits: 0 }));
    case "num1": return isZero ? "-" : wrap(Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 }));
    case "num2": return isZero ? "-" : wrap(Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
    case "pct": return isZero ? "-" : wrap((Math.abs(x) * 100).toFixed(1) + "%");
    case "pct2": return isZero ? "-" : wrap((Math.abs(x) * 100).toFixed(2) + "%");
    case "mult": return isZero ? "-" : wrap(Math.abs(x).toFixed(1) + "x");
    case "price": return x.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    case "int": return x.toLocaleString("en-US", { maximumFractionDigits: 0 });
    case "days": return x.toFixed(1);
    case "factor": return x.toFixed(4);
    case "beta": return x.toFixed(3);
    default: return typeof x === "number" ? x.toLocaleString("en-US", { maximumFractionDigits: 4 }) : String(x);
  }
}

export function colLetter(c: number): string {
  let s = "";
  while (c > 0) { const m = (c - 1) % 26; s = String.fromCharCode(65 + m) + s; c = Math.floor((c - 1) / 26); }
  return s;
}

export const pct = (x: number | null | undefined, d = 1) => (x == null ? "n/a" : `${(x * 100).toFixed(d)}%`);
export const money = (x: number | null | undefined, d = 2) => (x == null ? "n/a" : x.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }));
