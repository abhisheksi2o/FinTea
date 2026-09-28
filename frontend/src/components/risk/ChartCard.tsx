import { useMemo } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart, PolarAngleAxis, PolarGrid, PolarRadiusAxis,
  Radar, RadarChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import type { ChartSeries, ChartSpec } from "../../types";
import { fmtAxis, fmtRisk, isNum } from "./riskUtils";

const INK = "#1a1a1a", MUTED = "#5f6b7a", LINE = "#d9dee7", GRID = "#eef1f6", SURFACE = "#ffffff";
/** Used only when the spec gives no colour; fixed order so a series keeps its hue between renders. */
const FALLBACK = ["#2e75b6", "#c55a11", "#548235", "#7030a0", "#bf8f00", "#1f3864", "#7f7f7f", "#3e8e9b"];

export const seriesColor = (hex: string | null | undefined, i: number) => (hex ? (hex.startsWith("#") ? hex : `#${hex}`) : FALLBACK[i % FALLBACK.length]);

/** Constant "zone" / "threshold" series are drawn as dashed reference lines without markers. */
const isThreshold = (s: ChartSeries) => {
  const nums = s.values.filter(isNum);
  return nums.length > 0 && nums.every((v) => v === nums[0]) && /zone|threshold|cut-?off|limit|target|line/i.test(s.name);
};

interface Row { i: number; label: string; [k: string]: unknown }

function wrapText(text: string, width: number): string[] {
  const words = text.split(/\s+/);
  const lines: string[] = [];
  let cur = "";
  for (const w of words) {
    if ((cur + " " + w).trim().length > width && cur) { lines.push(cur); cur = w; } else cur = (cur + " " + w).trim();
  }
  if (cur) lines.push(cur);
  return lines.slice(0, 4);
}

function RadarTick(props: any) {
  const { x, y, cy, payload, textAnchor } = props;
  const lines = wrapText(String(payload?.value ?? ""), 20);
  const above = y < cy - 4;
  const start = above ? -(lines.length - 1) * 12 : Math.abs(y - cy) < 4 ? -((lines.length - 1) * 6) + 4 : 12;
  return (
    <text x={x} y={y} textAnchor={textAnchor} fill={MUTED} fontSize={11} fontFamily="inherit">
      {lines.map((l, i) => <tspan key={i} x={x} dy={i === 0 ? start : 12}>{l}</tspan>)}
    </text>
  );
}

function ChartTip({ active, payload, label, fmt, rows }: { active?: boolean; payload?: ReadonlyArray<any>; label?: string | number; fmt: string; rows: Row[] }) {
  if (!active || !payload || payload.length === 0) return null;
  const row = payload[0]?.payload as Row | undefined;
  const lbl = label ?? row?.label ?? "";
  return (
    <div className="chart-tip" role="status">
      <div className="chart-tip-label">{String(lbl)}</div>
      {payload.map((p, i) => {
        const text = row?.[`t${String(p.dataKey).slice(1)}`];
        const val = isNum(p.value) ? fmtRisk(p.value, fmt) : typeof text === "string" ? text : "n/a";
        return (
          <div key={i} className="chart-tip-row">
            <span className="chart-tip-key" style={{ background: p.color ?? p.stroke ?? p.fill ?? MUTED }} />
            <b>{val}</b><span>{String(p.name ?? "")}</span>
          </div>
        );
      })}
      {rows.length === 0 && null}
    </div>
  );
}

const legendText = (value: unknown) => <span className="chart-legend-text">{String(value)}</span>;

export function ChartCard({ spec, height, className }: { spec: ChartSpec; height?: number; className?: string }) {
  const cats = spec.categories ?? [];
  const rows: Row[] = useMemo(() => cats.map((c, i) => {
    const row: Row = { i, label: String(c ?? "") };
    spec.series.forEach((s, j) => {
      const v = s.values[i];
      row[`s${j}`] = isNum(v) ? v : null;
      if (typeof v === "string" && v) row[`t${j}`] = v;
    });
    return row;
  }), [cats, spec.series]);

  const allValues = spec.series.flatMap((s) => s.values.filter(isNum));
  const hasData = allValues.length > 0;
  const hasNeg = allValues.some((v) => v < 0);
  const yMin = spec.y_min ?? (hasNeg ? "auto" : 0);
  const yMax = spec.y_max ?? "auto";
  const domain: [number | "auto", number | "auto"] = [yMin, yMax];
  const longCats = cats.some((c) => String(c ?? "").length > 14);
  const horizontal = spec.type === "bar" && longCats;
  const dataSeries = spec.series.filter((s) => !isThreshold(s));
  const showLegend = spec.series.length >= 2;
  const singlePoint = cats.length === 1 && (spec.type === "line" || spec.type === "area");
  const h = height ?? (spec.type === "radar" ? 340 : horizontal ? Math.max(220, 40 * cats.length + 70) : 260);
  const tick = { fill: MUTED, fontSize: 11 };
  const tipFmt = spec.fmt || "general";
  const tooltip = <Tooltip content={(p: any) => <ChartTip {...p} fmt={tipFmt} rows={rows} />} cursor={spec.type === "bar" ? { fill: "rgba(46,117,182,0.07)" } : { stroke: LINE, strokeWidth: 1 }} isAnimationActive={false} />;
  const legend = showLegend ? <Legend iconType={spec.type === "bar" ? "square" : "plainline"} iconSize={spec.type === "bar" ? 10 : 14} formatter={legendText} wrapperStyle={{ fontSize: 12, paddingTop: 6 }} /> : null;
  const margin = { top: 8, right: 16, bottom: 4, left: 0 };

  let body: JSX.Element;
  if (!hasData) {
    body = <div className="chart-empty">No data available for this chart.</div>;
  } else if (spec.type === "radar") {
    const c = seriesColor(spec.series[0]?.color, 0);
    body = (
      <ResponsiveContainer width="100%" height="100%">
        <RadarChart data={rows} outerRadius="66%" margin={{ top: 24, right: 40, bottom: 24, left: 40 }}>
          <PolarGrid stroke={GRID} />
          <PolarAngleAxis dataKey="label" tick={<RadarTick />} />
          <PolarRadiusAxis angle={90} domain={[spec.y_min ?? 0, spec.y_max ?? "auto"]} tick={{ fill: MUTED, fontSize: 10 }} axisLine={false} tickCount={5} tickFormatter={(v: number) => fmtAxis(v, tipFmt)} />
          {spec.series.map((s, j) => {
            const col = seriesColor(s.color, j);
            return <Radar key={j} name={s.name} dataKey={`s${j}`} stroke={col} fill={col} fillOpacity={0.15} strokeWidth={2} dot={{ r: 4, fill: col, stroke: SURFACE, strokeWidth: 2 }} isAnimationActive={false} />;
          })}
          {tooltip}
          {legend}
        </RadarChart>
      </ResponsiveContainer>
    );
    void c;
  } else if (spec.type === "bar") {
    body = (
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} layout={horizontal ? "vertical" : "horizontal"} margin={horizontal ? { top: 8, right: 24, bottom: 4, left: 8 } : margin} barGap={2} barCategoryGap="28%">
          <CartesianGrid stroke={GRID} horizontal={!horizontal} vertical={horizontal} />
          {horizontal ? (
            <>
              <XAxis type="number" domain={domain} tick={tick} axisLine={{ stroke: LINE }} tickLine={false} tickFormatter={(v: number) => fmtAxis(v, tipFmt)} />
              <YAxis type="category" dataKey="label" width={210} tick={{ ...tick, width: 200 }} axisLine={false} tickLine={false} interval={0} />
            </>
          ) : (
            <>
              <XAxis dataKey="label" tick={tick} axisLine={{ stroke: LINE }} tickLine={false} interval={0} />
              <YAxis domain={domain} width="auto" tick={tick} axisLine={false} tickLine={false} tickFormatter={(v: number) => fmtAxis(v, tipFmt)} />
            </>
          )}
          {hasNeg && <ReferenceLine {...(horizontal ? { x: 0 } : { y: 0 })} stroke={MUTED} strokeWidth={1} />}
          {spec.series.map((s, j) => (
            <Bar key={j} name={s.name} dataKey={`s${j}`} fill={seriesColor(s.color, j)} stackId={spec.stacked ? "a" : undefined} maxBarSize={horizontal ? 22 : 26}
              radius={horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]} stroke={SURFACE} strokeWidth={spec.stacked ? 2 : 0} isAnimationActive={false} />
          ))}
          {tooltip}
          {legend}
        </BarChart>
      </ResponsiveContainer>
    );
  } else {
    const Chart = spec.type === "area" ? AreaChart : LineChart;
    body = (
      <ResponsiveContainer width="100%" height="100%">
        <Chart data={rows} margin={margin}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="label" tick={tick} axisLine={{ stroke: LINE }} tickLine={false} interval={0} padding={{ left: 16, right: 16 }} />
          <YAxis domain={domain} width="auto" tick={tick} axisLine={false} tickLine={false} tickFormatter={(v: number) => fmtAxis(v, tipFmt)} />
          {hasNeg && <ReferenceLine y={0} stroke={MUTED} strokeWidth={1} />}
          {spec.series.map((s, j) => {
            const col = seriesColor(s.color, j);
            if (isThreshold(s)) {
              return <Line key={j} type="linear" name={s.name} dataKey={`s${j}`} stroke={col} strokeWidth={1.5} strokeDasharray="6 4" dot={singlePoint ? { r: 3, fill: col, stroke: SURFACE, strokeWidth: 2 } : false} activeDot={{ r: 4 }} isAnimationActive={false} connectNulls={false} />;
            }
            if (spec.type === "area") {
              return <Area key={j} type="monotone" name={s.name} dataKey={`s${j}`} stroke={col} fill={col} fillOpacity={0.12} strokeWidth={2} stackId={spec.stacked ? "a" : undefined}
                dot={{ r: 4, fill: col, stroke: SURFACE, strokeWidth: 2 }} activeDot={{ r: 6, stroke: SURFACE, strokeWidth: 2 }} isAnimationActive={false} connectNulls={false} />;
            }
            return <Line key={j} type="monotone" name={s.name} dataKey={`s${j}`} stroke={col} strokeWidth={2} dot={{ r: 4, fill: col, stroke: SURFACE, strokeWidth: 2 }} activeDot={{ r: 6, stroke: SURFACE, strokeWidth: 2 }} isAnimationActive={false} connectNulls={false} />;
          })}
          {tooltip}
          {legend}
        </Chart>
      </ResponsiveContainer>
    );
  }

  const missing = dataSeries.filter((s) => s.values.some((v) => v === null || typeof v === "string")).length > 0;
  return (
    <figure className={`chart-card ${className ?? ""}`}>
      <figcaption className="chart-head">
        <div className="chart-title">{spec.title}</div>
        {(spec.y_title || spec.x_title) && <div className="chart-units">{[spec.y_title, spec.x_title].filter(Boolean).join(" · ")}</div>}
      </figcaption>
      <div className="chart-body" style={{ height: h }}>{body}</div>
      {(spec.note || singlePoint || missing) && (
        <div className="chart-note">
          {spec.note}
          {singlePoint && <> {spec.note ? "· " : ""}Only one fiscal year of statements is available, so the trend is a single point.</>}
          {missing && !singlePoint && <> {spec.note ? "· " : ""}Gaps mark years for which a model could not be computed (e.g. no prior-year data).</>}
        </div>
      )}
    </figure>
  );
}

export { INK };
