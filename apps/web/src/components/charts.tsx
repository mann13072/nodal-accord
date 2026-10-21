import cytoscape from "cytoscape";
import * as echarts from "echarts";
import { useEffect, useRef } from "react";
import { Graph, ItemLedger } from "../api";

function cssVar(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** Baseline vs disrupted projection for one item. All numbers come from the server ledger. */
export function LedgerChart({ item }: { item: ItemLedger }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: "svg" });
    const weeks = item.baseline.map((w) => w.week_start.slice(5));
    const text = cssVar("--text-2");
    chart.setOption({
      animation: false,
      textStyle: { color: text, fontFamily: "inherit" },
      tooltip: { trigger: "axis" },
      legend: { top: 0, textStyle: { color: text } },
      grid: { left: 48, right: 16, top: 32, bottom: 28 },
      xAxis: { type: "category", data: weeks, axisLabel: { color: text } },
      yAxis: { type: "value", name: "units (EA)", nameTextStyle: { color: text }, axisLabel: { color: text },
               splitLine: { lineStyle: { color: cssVar("--border") } } },
      series: [
        { name: "Demand", type: "bar", data: item.disrupted.map((w) => w.demand), itemStyle: { color: cssVar("--border-strong") } },
        { name: "Confirmed receipts (plan)", type: "line", step: "middle", data: item.baseline.map((w) => w.receipts), lineStyle: { type: "dashed" }, itemStyle: { color: cssVar("--accent") } },
        { name: "Receipts after disruption", type: "line", step: "middle", data: item.disrupted.map((w) => w.receipts), itemStyle: { color: cssVar("--amber") } },
        { name: "Backlog after disruption", type: "line", data: item.disrupted.map((w) => w.closing_backlog), areaStyle: { opacity: 0.15 }, itemStyle: { color: cssVar("--red") } },
        { name: "Usable stock after disruption", type: "line", data: item.disrupted.map((w) => w.closing_usable), itemStyle: { color: cssVar("--green") } },
      ],
    });
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => { ro.disconnect(); chart.dispose(); };
  }, [item]);
  return <div ref={ref} className="chart" role="img" aria-label={`Time-phased supply chart for ${item.part_id} at ${item.plant_id}`} />;
}

/** Bounded, tenant-filtered impact subgraph (never the full network). */
export function ImpactGraph({ graph, onSelect }: { graph: Graph; onSelect?: (id: string | null) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const colors: Record<string, string> = { SUPPLIER: cssVar("--accent"), PART: cssVar("--text-2"), PLANT: cssVar("--green"), RESOURCE: cssVar("--red") };
    const cy = cytoscape({
      container: ref.current,
      elements: [
        ...graph.nodes.map((n) => ({ data: { id: n.id, label: `${n.kind === "SUPPLIER" ? n.label : n.id}`, kind: n.kind, hl: n.highlighted ? 1 : 0 } })),
        ...graph.edges.map((e, i) => ({ data: { id: `e${i}`, source: e.source, target: e.target, kind: e.kind, alt: e.role === "ALTERNATE" ? 1 : 0 } })),
      ],
      style: [
        { selector: "node", style: { label: "data(label)", "font-size": 10, color: cssVar("--text"), "text-valign": "bottom", "text-margin-y": 4,
          width: 18, height: 18, "background-color": (n: cytoscape.NodeSingular) => colors[n.data("kind")] ?? "#888" } },
        { selector: "node[kind = 'RESOURCE']", style: { shape: "diamond", width: 24, height: 24 } },
        { selector: "node[kind = 'PLANT']", style: { shape: "round-rectangle" } },
        { selector: "node[hl = 1]", style: { "border-width": 3, "border-color": cssVar("--amber") } },
        { selector: "edge", style: { width: 1.4, "line-color": cssVar("--border-strong"), "target-arrow-shape": "triangle",
          "target-arrow-color": cssVar("--border-strong"), "curve-style": "bezier" } },
        { selector: "edge[alt = 1]", style: { "line-style": "dashed", "line-color": cssVar("--accent"), "target-arrow-color": cssVar("--accent") } },
        { selector: "edge[kind = 'CONSTRAINS']", style: { "line-color": cssVar("--red"), "target-arrow-color": cssVar("--red") } },
        { selector: ":selected", style: { "border-width": 3, "border-color": cssVar("--focus") } },
      ],
      layout: { name: "breadthfirst", directed: true, spacingFactor: 1.1, padding: 16 },
      wheelSensitivity: 0.2,
    });
    cy.on("tap", "node", (ev) => onSelect?.(ev.target.id()));
    cy.on("tap", (ev) => { if (ev.target === cy) onSelect?.(null); });
    return () => cy.destroy();
  }, [graph, onSelect]);
  return <div ref={ref} className="graph" role="img" aria-label="Affected network subgraph" />;
}
