import type { ReactNode } from "react";
import s from "./Prose.module.css";

function slugify(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}

export function H1({ children }: { children: ReactNode }) {
  return <h1 className={s.h1}>{children}</h1>;
}

export function H2({ children }: { children: ReactNode }) {
  const id = typeof children === "string" ? slugify(children) : undefined;
  return (
    <h2 id={id} className={s.h2}>
      {children}
      {id && <a href={`#${id}`} className={s.anchor}>#</a>}
    </h2>
  );
}

export function H3({ children }: { children: ReactNode }) {
  const id = typeof children === "string" ? slugify(children) : undefined;
  return (
    <h3 id={id} className={s.h3}>
      {children}
      {id && <a href={`#${id}`} className={s.anchor}>#</a>}
    </h3>
  );
}

export function P({ children }: { children: ReactNode }) {
  return <p className={s.p}>{children}</p>;
}

export function Code({ children }: { children: ReactNode }) {
  return <code className={s.code}>{children}</code>;
}

export function CodeBlock({ children, lang }: { children: string; lang?: string }) {
  return (
    <div className={s.codeBlock}>
      {lang && <span className={s.codeBlockLang}>{lang}</span>}
      <pre className={s.codeBlockPre}>{children}</pre>
    </div>
  );
}

export function Table({ headers, rows }: { headers: string[]; rows: ReactNode[][] }) {
  return (
    <table className={s.table}>
      <thead>
        <tr>
          {headers.map((h, i) => <th key={i}>{h}</th>)}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr key={i}>
            {row.map((cell, j) => <td key={j}>{cell}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function Callout({ type, children }: { type: "info" | "warning" | "tip"; children: ReactNode }) {
  const labels = { info: "Info", warning: "Warning", tip: "Tip" };
  const cls = { info: s.calloutInfo, warning: s.calloutWarning, tip: s.calloutTip };
  return (
    <div className={`${s.callout} ${cls[type]}`}>
      <div className={s.calloutLabel}>{labels[type]}</div>
      {children}
    </div>
  );
}

export function Diagram({ children }: { children: string }) {
  return <pre className={s.diagram}>{children}</pre>;
}

export function DashboardLink({ tab, children }: { tab: string; children: ReactNode }) {
  return (
    <a href={`/?tab=${tab}`} className={s.dashboardLink} target="_blank" rel="noopener">
      {children} →
    </a>
  );
}

export function Term({ term, definition }: { term: string; definition: string }) {
  return (
    <span className={s.term}>
      {term}
      <span className={s.termTooltip}>{definition}</span>
    </span>
  );
}

export function UL({ children }: { children: ReactNode }) {
  return <ul className={s.ul}>{children}</ul>;
}

export function OL({ children }: { children: ReactNode }) {
  return <ol className={s.ol}>{children}</ol>;
}
