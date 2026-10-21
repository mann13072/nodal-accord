import cytoscape from "cytoscape";
import * as echarts from "echarts";
import { useEffect, useRef, useState } from "react";
import { Graph, ItemLedger } from "../api";

function cssVar(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

type SeriesKey = "demand" | "plan" | "after" | "backlog" | "stock";
const LEDGER_SERIES: { key: SeriesKey; name: string; color: string; mark: "bar" | "line" | "dashed" | "area" }[] = [
  { key: "demand", name: "Demand", color: "--border-strong", mark: "bar" },
  { key: "plan", name: "Confirmed receipts (plan)", color: "--accent", mark: "dashed" },
  { key: "after", name: "Receipts after disruption", color: "--amber", mark: "line" },
  { key: "backlog", name: "Backlog after disruption", color: "--red", mark: "area" },
  { key: "stock", name: "Usable stock after disruption", color: "--green", mark: "line" },
];

/**
 * Baseline vs disrupted projection for one item. All numbers come from the server ledger.
 * The legend is HTML above the canvas (wraps with the width, never overlaps the plot); clicking toggles a series.
 */
export function LedgerChart({ item }: { item: ItemLedger }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: "svg" });
    chartRef.current = chart;
    const weeks = item.baseline.map((w) => w.week_start.slice(5));
    const text = cssVar("--text-2");
    const color = (k: SeriesKey) => cssVar(LEDGER_SERIES.find((s) => s.key === k)!.color);
    const name = (k: SeriesKey) => LEDGER_SERIES.find((s) => s.key === k)!.name;
    chart.setOption({
      animation: false,
      textStyle: { color: text, fontFamily: "inherit" },
      tooltip: { trigger: "axis", confine: true },
      legend: { show: false },  // rendered as HTML; kept so legendToggleSelect works
      grid: { left: 4, right: 12, top: 12, bottom: 4, containLabel: true },
      xAxis: { type: "category", data: weeks, axisLabel: { color: text, hideOverlap: true } },
      yAxis: { type: "value", axisLabel: { color: text, hideOverlap: true }, splitLine: { lineStyle: { color: cssVar("--border") } } },
      series: [
        { name: name("demand"), type: "bar", data: item.disrupted.map((w) => w.demand), itemStyle: { color: color("demand") } },
        { name: name("plan"), type: "line", step: "middle", data: item.baseline.map((w) => w.receipts), lineStyle: { type: "dashed" }, itemStyle: { color: color("plan") } },
        { name: name("after"), type: "line", step: "middle", data: item.disrupted.map((w) => w.receipts), itemStyle: { color: color("after") } },
        { name: name("backlog"), type: "line", data: item.disrupted.map((w) => w.closing_backlog), areaStyle: { opacity: 0.15 }, itemStyle: { color: color("backlog") } },
        { name: name("stock"), type: "line", data: item.disrupted.map((w) => w.closing_usable), itemStyle: { color: color("stock") } },
      ],
    });
    setHidden(new Set());
    let timer = 0;
    const ro = new ResizeObserver(() => { clearTimeout(timer); timer = window.setTimeout(() => chart.resize(), 50); });
    ro.observe(ref.current);
    return () => { clearTimeout(timer); ro.disconnect(); chart.dispose(); chartRef.current = null; };
  }, [item]);

  const toggle = (seriesName: string) => {
    chartRef.current?.dispatchAction({ type: "legendToggleSelect", name: seriesName });
    setHidden((h) => { const n = new Set(h); if (n.has(seriesName)) n.delete(seriesName); else n.add(seriesName); return n; });
  };

  return (
    <div className="chart-wrap">
      <div className="chart-legend" aria-label="Chart series">
        <span className="chart-unit">Units (EA)</span>
        {LEDGER_SERIES.map((s) => (
          <button key={s.key} type="button" className={`legend-item${hidden.has(s.name) ? " off" : ""}`} aria-pressed={!hidden.has(s.name)}
                  onClick={() => toggle(s.name)} title={hidden.has(s.name) ? "Show series" : "Hide series"}>
            <span className={`swatch ${s.mark}`} style={{ color: `var(${s.color})` }} />{s.name}
          </button>))}
      </div>
      <div ref={ref} className="chart" role="img" aria-label={`Time-phased supply chart for ${item.part_id} at ${item.plant_id}, in units (EA)`} />
    </div>
  );
}

/** Bounded, tenant-filtered impact subgraph (never the full network). Flows left to right: supplier → part → plant. */
export function ImpactGraph({ graph, onSelect }: { graph: Graph; onSelect?: (id: string | null) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [cropped, setCropped] = useState(false);
  useEffect(() => {
    if (!ref.current) return;
    const colors: Record<string, string> = { SUPPLIER: cssVar("--accent"), PART: cssVar("--text-2"), PLANT: cssVar("--green"), RESOURCE: cssVar("--red") };
    const cy = cytoscape({
      container: ref.current,
      elements: [
        ...graph.nodes.map((n) => ({ data: { id: n.id, label: `${n.kind === "SUPPLIER" ? n.label : n.id}`, kind: n.kind, hl: n.highlighted ? 1 : 0 } })),
        // Parallel links of the same kind (e.g. one OPERATES edge per lane) are drawn once; bundled curves would sweep across labels.
        ...[...new Map(graph.edges.map((e) => [`${e.source}|${e.target}|${e.kind}|${e.role === "ALTERNATE"}`, e])).values()]
          .map((e, i) => ({ data: { id: `e${i}`, source: e.source, target: e.target, kind: e.kind, alt: e.role === "ALTERNATE" ? 1 : 0 } })),
      ],
      style: [
        { selector: "node", style: { label: "data(label)", "font-size": 10, color: cssVar("--text"), "text-valign": "bottom", "text-margin-y": 3,
          "text-wrap": "wrap", "text-max-width": "84px", "text-background-color": cssVar("--surface"), "text-background-opacity": 1,
          "text-background-padding": "2px", "text-background-shape": "roundrectangle", width: 16, height: 16, "background-color": (n: cytoscape.NodeSingular) => colors[n.data("kind")] ?? "#888" } },
        { selector: "node[kind = 'RESOURCE']", style: { shape: "diamond", width: 22, height: 22 } },
        { selector: "node[kind = 'PLANT']", style: { shape: "round-rectangle" } },
        { selector: "node[hl = 1]", style: { "border-width": 3, "border-color": cssVar("--amber") } },
        { selector: "edge", style: { width: 1.2, "line-color": cssVar("--border-strong"), "target-arrow-shape": "triangle", "arrow-scale": 0.8,
          "target-arrow-color": cssVar("--border-strong"), "curve-style": "bezier" } },
        { selector: "edge[alt = 1]", style: { "line-style": "dashed", "line-color": cssVar("--accent"), "target-arrow-color": cssVar("--accent") } },
        { selector: "edge[kind = 'CONSTRAINS']", style: { "line-color": cssVar("--red"), "target-arrow-color": cssVar("--red") } },
        { selector: ":selected", style: { "border-width": 3, "border-color": cssVar("--focus") } },
      ],
      minZoom: 0.3, maxZoom: 1.6, wheelSensitivity: 0.2,
    });
    cy.on("tap", "node", (ev) => onSelect?.(ev.target.id()));
    cy.on("tap", (ev) => { if (ev.target === cy) onSelect?.(null); });
    const place = () => {
      cy.resize();
      cy.layout({ name: "preset", positions: columnPositions(cy, ref.current?.clientWidth ?? 600), fit: true, padding: 14 }).run();
      // On very narrow screens keep labels readable (≥ ~7.5px) and let the user drag, rather than shrinking text to fit.
      const tooSmall = cy.zoom() < MIN_READABLE_ZOOM;
      if (tooSmall) {
        const bb = cy.elements().boundingBox({ includeLabels: true });
        cy.zoom(MIN_READABLE_ZOOM);
        cy.pan({ x: 14 - bb.x1 * MIN_READABLE_ZOOM, y: cy.height() / 2 - ((bb.y1 + bb.y2) / 2) * MIN_READABLE_ZOOM });
      }
      setCropped(tooSmall);
    };
    place();
    let timer = 0;
    const ro = new ResizeObserver(() => { clearTimeout(timer); timer = window.setTimeout(place, 50); });
    ro.observe(ref.current);
    return () => { clearTimeout(timer); ro.disconnect(); cy.destroy(); };
  }, [graph, onSelect]);
  return (
    <div className="chart-wrap">
      <div ref={ref} className="graph" role="img" aria-label="Affected network subgraph" />
      {cropped && <p className="small muted" style={{ margin: "4px 0 0" }}>Drag to see the rest of the network; pinch or scroll to zoom.</p>}
    </div>
  );
}

const MIN_READABLE_ZOOM = 0.75;
const COLUMN_ORDER = ["SUPPLIER", "RESOURCE", "PART", "PLANT"];

/**
 * Columns by node kind (supplier → resource → part → plant). Rows are spaced for label height and columns for the
 * available width, so labels never collide; each column is ordered by its neighbours' rows to limit edge crossings.
 */
function columnPositions(cy: cytoscape.Core, width: number): Record<string, cytoscape.Position> {
  const kinds = [...COLUMN_ORDER, ...new Set(cy.nodes().map((n) => n.data("kind") as string).filter((k) => !COLUMN_ORDER.includes(k)))];
  const columns = kinds.map((k) => cy.nodes().filter((n) => n.data("kind") === k).toArray() as cytoscape.NodeSingular[]).filter((c) => c.length > 0);
  const colGap = Math.max(100, Math.min(180, (width - 110) / Math.max(1, columns.length - 1)));
  const row = new Map<string, number>();
  const pos: Record<string, cytoscape.Position> = {};
  columns.forEach((col, c) => {
    if (c > 0) {
      const score = (n: cytoscape.NodeSingular) => {
        const placed = n.neighborhood("node").toArray().map((m) => row.get(m.id())).filter((v): v is number => v !== undefined);
        return placed.length ? placed.reduce((a, b) => a + b, 0) / placed.length : Number.MAX_SAFE_INTEGER;
      };
      col.sort((a, b) => score(a) - score(b));
    }
    const twoLines = col.some((n) => String(n.data("label")).length > 14);
    const rowGap = twoLines ? 50 : 38;
    col.forEach((n, i) => {
      const y = (i - (col.length - 1) / 2) * rowGap;
      row.set(n.id(), y);
      pos[n.id()] = { x: c * colGap, y };
    });
  });
  return pos;
}
