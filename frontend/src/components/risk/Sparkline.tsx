import { isNum } from "./riskUtils";

/** Tiny trend line for a table row; gaps break the line, the last point is marked. */
export function Sparkline({ values, width = 96, height = 26, color = "#2e75b6" }: { values: (number | null)[]; width?: number; height?: number; color?: string }) {
  const nums = values.filter(isNum);
  if (nums.length === 0) return <span className="spark-empty">-</span>;
  const pad = 4;
  let lo = Math.min(...nums), hi = Math.max(...nums);
  if (hi - lo < 1e-12) { lo -= 1; hi += 1; }
  const n = values.length;
  const x = (i: number) => (n === 1 ? width / 2 : pad + (i * (width - 2 * pad)) / (n - 1));
  const y = (v: number) => height - pad - ((v - lo) / (hi - lo)) * (height - 2 * pad);
  const segments: string[] = [];
  let cur: string[] = [];
  values.forEach((v, i) => {
    if (isNum(v)) cur.push(`${x(i).toFixed(1)},${y(v).toFixed(1)}`);
    else { if (cur.length) segments.push(cur.join(" ")); cur = []; }
  });
  if (cur.length) segments.push(cur.join(" "));
  const lastIdx = values.map((v, i) => (isNum(v) ? i : -1)).filter((i) => i >= 0).pop() as number;
  const lastV = values[lastIdx] as number;
  const zeroY = lo < 0 && hi > 0 ? y(0) : null;
  return (
    <svg className="spark" width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      {zeroY != null && <line x1={0} x2={width} y1={zeroY} y2={zeroY} stroke="#d9dee7" strokeWidth={1} />}
      {segments.map((pts, i) => pts.includes(" ") ? <polyline key={i} points={pts} fill="none" stroke={color} strokeWidth={1.8} strokeLinejoin="round" strokeLinecap="round" /> : null)}
      {values.map((v, i) => (isNum(v) && (n === 1 || !segments.some((s) => s.includes(" ") && s.includes(`${x(i).toFixed(1)},${y(v).toFixed(1)}`))) ? <circle key={i} cx={x(i)} cy={y(v)} r={2.5} fill={color} /> : null))}
      <circle cx={x(lastIdx)} cy={y(lastV)} r={3} fill={color} stroke="#fff" strokeWidth={1.5} />
    </svg>
  );
}
