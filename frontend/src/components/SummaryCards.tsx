import { money, pct } from "../format";

export function SummaryCards({ s }: { s: Record<string, any> }) {
  const up = s.upside as number;
  const cards = [
    { label: "Current price", value: `${s.currency} ${money(s.price)}`, sub: `as of ${s.price_date}` },
    { label: "DCF implied price", value: `${s.currency} ${money(s.implied_price)}`, sub: `${up >= 0 ? "upside" : "downside"} ${pct(up)}`, cls: up >= 0 ? "good" : "bad" },
    { label: "Enterprise value", value: `${money(s.enterprise_value, 0)}`, sub: s.units },
    { label: "WACC", value: pct(s.wacc, 2), sub: `cost of equity ${pct(s.cost_of_equity, 2)}` },
    { label: "Beta (relevered)", value: (s.selected_beta as number).toFixed(2), sub: `raw ${(s.raw_beta as number).toFixed(2)}, R² ${(s.r_squared as number).toFixed(2)}` },
    { label: "Terminal value share", value: pct(s.tv_share), sub: `g = ${pct(s.terminal_growth, 2)}` },
    { label: "Altman Z", value: (s.altman_z as number).toFixed(2), sub: s.piotroski != null ? `Piotroski ${s.piotroski}/9` : "" },
    { label: "Revenue " + s.labels[s.labels.length - 1], value: money(s.revenue_terminal, 0), sub: `EBITDA margin ${pct(s.ebitda_margin_terminal)}` },
  ];
  return (
    <div className="cards">
      {cards.map((c) => (
        <div className={`card ${c.cls ?? ""}`} key={c.label}>
          <div className="card-label">{c.label}</div>
          <div className="card-value">{c.value}</div>
          <div className="card-sub">{c.sub}</div>
        </div>
      ))}
    </div>
  );
}
