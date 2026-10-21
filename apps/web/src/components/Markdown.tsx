import { Fragment, ReactNode } from "react";

/**
 * Minimal Markdown for AI answers: paragraphs, headings, bullet/numbered lists, blockquotes, pipe tables, fenced code,
 * and inline bold/italic/code. Builds React elements only (no HTML injection); links stay plain text.
 */
export function Markdown({ text }: { text: string }) {
  return <div className="md">{blocks(text.replace(/\r\n?/g, "\n").split("\n"))}</div>;
}

/** The answer as plain text for the clipboard (markers removed). */
export function toPlainText(text: string): string {
  return text.replace(/\r\n?/g, "\n").split("\n")
    .map((l) => l.replace(/^\s*>\s?/, "").replace(/^#{1,6}\s+/, "").replace(/\*\*|`/g, ""))
    .join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

/** The first quoted block (e.g. a drafted message), as plain text; null when the answer has none. */
export function quotedText(text: string): string | null {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const start = lines.findIndex((l) => /^\s*>/.test(l));
  if (start < 0) return null;
  let end = start;
  while (end < lines.length && /^\s*>/.test(lines[end])) end++;
  return toPlainText(lines.slice(start, end).join("\n")) || null;
}

const BULLET = /^\s*[-*•]\s+/;
const ORDERED = /^\s*\d+[.)]\s+/;
const QUOTE = /^\s*>/;
const HEADING = /^(#{1,6})\s+(.*)$/;
const TABLE_SEP = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

function blocks(lines: string[]): ReactNode[] {
  const out: ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    const key = out.length;
    if (line.trim().startsWith("```")) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) body.push(lines[i++]);
      i++;
      out.push(<pre key={key} className="md-code">{body.join("\n")}</pre>);
    } else if (QUOTE.test(line)) {
      const body: string[] = [];
      while (i < lines.length && QUOTE.test(lines[i])) body.push(lines[i++].replace(/^\s*>\s?/, ""));
      out.push(<blockquote key={key}>{blocks(body)}</blockquote>);
    } else if (HEADING.test(line)) {
      out.push(<p key={key} className="md-h">{inline(line.match(HEADING)![2])}</p>);
      i++;
    } else if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
      out.push(<hr key={key} />);
      i++;
    } else if (line.includes("|") && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1])) {
      const head = cells(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) rows.push(cells(lines[i++]));
      out.push(
        <div key={key} className="md-table"><table className="data">
          <thead><tr>{head.map((h, j) => <th key={j}>{inline(h)}</th>)}</tr></thead>
          <tbody>{rows.map((r, j) => <tr key={j}>{r.map((c, k) => <td key={k}>{inline(c)}</td>)}</tr>)}</tbody>
        </table></div>);
    } else if (BULLET.test(line) || ORDERED.test(line)) {
      const ordered = ORDERED.test(line);
      const marker = ordered ? ORDERED : BULLET;
      const items: string[] = [];
      while (i < lines.length && lines[i].trim()) {
        if (marker.test(lines[i])) items.push(lines[i].replace(marker, ""));
        else if (BULLET.test(lines[i]) || ORDERED.test(lines[i]) || QUOTE.test(lines[i])) break;
        else items[items.length - 1] += "\n" + lines[i].trim();  // wrapped continuation of the previous item
        i++;
      }
      const lis = items.map((it, j) => <li key={j}>{withBreaks(it)}</li>);
      out.push(ordered ? <ol key={key}>{lis}</ol> : <ul key={key}>{lis}</ul>);
    } else {
      const para: string[] = [];
      while (i < lines.length && lines[i].trim() && !QUOTE.test(lines[i]) && !BULLET.test(lines[i]) && !ORDERED.test(lines[i])
             && !HEADING.test(lines[i]) && !lines[i].trim().startsWith("```")) para.push(lines[i++]);
      out.push(<p key={key}>{withBreaks(para.join("\n"))}</p>);
    }
  }
  return out;
}

function cells(row: string): string[] {
  return row.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
}

function withBreaks(s: string): ReactNode[] {
  return s.split("\n").flatMap((part, j) => {
    const span = <Fragment key={`l${j}`}>{inline(part, `l${j}`)}</Fragment>;
    return j === 0 ? [span] : [<br key={`b${j}`} />, span];
  });
}

/** Inline spans: `code`, **bold** (may contain code), *italic*. Unmatched markers stay literal. */
function inline(s: string, keyPrefix = "i"): ReactNode {
  const out: ReactNode[] = [];
  let buf = "";
  let i = 0;
  const flush = () => { if (buf) { out.push(buf); buf = ""; } };
  while (i < s.length) {
    if (s[i] === "`") {
      const end = s.indexOf("`", i + 1);
      if (end > i + 1) { flush(); out.push(<code key={`${keyPrefix}${out.length}`}>{s.slice(i + 1, end)}</code>); i = end + 1; continue; }
    } else if (s.startsWith("**", i)) {
      const end = s.indexOf("**", i + 2);
      if (end > i + 2) { flush(); out.push(<strong key={`${keyPrefix}${out.length}`}>{inline(s.slice(i + 2, end), `${keyPrefix}b`)}</strong>); i = end + 2; continue; }
    } else if (s[i] === "*" && s[i + 1] && s[i + 1] !== " ") {
      const end = s.indexOf("*", i + 1);
      if (end > i + 1 && s[end - 1] !== " ") { flush(); out.push(<em key={`${keyPrefix}${out.length}`}>{inline(s.slice(i + 1, end), `${keyPrefix}e`)}</em>); i = end + 1; continue; }
    }
    buf += s[i++];
  }
  flush();
  return <>{out}</>;
}
