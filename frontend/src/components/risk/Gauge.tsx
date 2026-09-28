import { GRADES, gradeColor, isNum } from "./riskUtils";

/** Semicircular gauge for the 0-100 composite default risk score, coloured by grade (a status colour). */
export function Gauge({ score, grade, width = 220 }: { score: number | null | undefined; grade: string | null | undefined; width?: number }) {
  const cx = 110, cy = 100, r = 84, sw = 16;
  const point = (frac: number, rad = r) => { const a = Math.PI * (1 - frac); return [cx + rad * Math.cos(a), cy - rad * Math.sin(a)] as const; };
  const arc = (from: number, to: number, rad = r) => {
    const f = Math.max(0, Math.min(0.9999, from)), t = Math.max(f, Math.min(0.9999, to));
    const [x0, y0] = point(f, rad), [x1, y1] = point(t, rad);
    return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${rad} ${rad} 0 ${t - f > 0.5 ? 1 : 0} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
  };
  const ok = isNum(score);
  const frac = ok ? Math.max(0, Math.min(1, (score as number) / 100)) : 0;
  const color = gradeColor(grade);
  const [nx, ny] = point(frac, r - sw / 2 - 6);
  return (
    <svg className="gauge" viewBox="0 0 220 118" width={width} height={(width * 118) / 220} role="img"
      aria-label={ok ? `Composite default risk score ${(score as number).toFixed(0)} of 100, ${grade ?? ""} grade` : "Composite default risk score not available"}>
      {/* track split into the five grade bands, as faint tints */}
      {GRADES.map((g) => <path key={g.name} d={arc(g.from / 100 + 0.004, g.to / 100 - 0.004)} stroke={gradeColor(g.name)} strokeOpacity={0.16} strokeWidth={sw} fill="none" strokeLinecap="butt" />)}
      {/* the score arc */}
      {ok && frac > 0.002 && <path d={arc(0, frac)} stroke={color} strokeWidth={sw} fill="none" strokeLinecap="butt" />}
      {ok && <circle cx={nx} cy={ny} r={4.5} fill={color} stroke="#fff" strokeWidth={2} />}
      <text x={cx} y={cy - 12} textAnchor="middle" className="gauge-score">{ok ? (score as number).toFixed(0) : "n/a"}</text>
      <text x={cx} y={cy + 6} textAnchor="middle" className="gauge-sub">composite score / 100</text>
      <text x={cx - r - sw / 2} y={cy + 16} textAnchor="start" className="gauge-end">0 minimal</text>
      <text x={cx + r + sw / 2} y={cy + 16} textAnchor="end" className="gauge-end">100 severe</text>
    </svg>
  );
}

/** Horizontal grade scale (0-100) with the current band emphasised. */
export function GradeScale({ score, grade }: { score: number | null | undefined; grade: string | null | undefined }) {
  return (
    <div className="grade-scale" aria-hidden="true">
      {GRADES.map((g) => (
        <div key={g.name} className={`grade-seg ${g.name === grade ? "on" : ""}`} style={{ ["--seg" as any]: gradeColor(g.name) }}>
          <span>{g.name}</span><small>{g.from}-{g.to}</small>
        </div>
      ))}
      {isNum(score) && <div className="grade-marker" style={{ left: `${Math.max(0, Math.min(100, score))}%` }} />}
    </div>
  );
}
