import type { ReactNode } from "react";
import type { Tone } from "./riskUtils";

/** Status pill: colour is reserved for verdicts / statuses and is always accompanied by the text. */
export function Pill({ tone, children, title }: { tone: Tone | string; children: ReactNode; title?: string }) {
  return <span className={`pill tone-${tone}`} title={title}>{children}</span>;
}

export function Stat({ label, value, sub, tone, tag, children, className }: { label: string; value: ReactNode; sub?: ReactNode; tone?: Tone; tag?: string; children?: ReactNode; className?: string }) {
  return (
    <div className={`stat ${className ?? ""}`}>
      <div className="stat-label">{label}{tag && <span className="stat-tag">{tag}</span>}</div>
      <div className={`stat-value${tone ? ` tone-${tone}` : ""}`}>{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
      {children}
    </div>
  );
}

export function Section({ title, aside, children, className }: { title: ReactNode; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rsec ${className ?? ""}`}>
      <div className="rsec-head"><h3>{title}</h3>{aside && <div className="rsec-aside">{aside}</div>}</div>
      {children}
    </section>
  );
}

export function Kv({ rows }: { rows: { k: ReactNode; v: ReactNode; note?: ReactNode; tone?: Tone }[] }) {
  return (
    <table className="kv">
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}><th scope="row">{r.k}{r.note && <div className="kv-note">{r.note}</div>}</th><td className={r.tone ? `tone-${r.tone}` : ""}>{r.v}</td></tr>
        ))}
      </tbody>
    </table>
  );
}
