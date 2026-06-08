import { useEffect, useMemo, useRef } from "react";
import maplibregl from "maplibre-gl";
import type { Meta, StateFrame } from "../types";
import {
  LOADING_STOPS,
  OUT_OF_SERVICE_COLOR,
  CASING_COLOR,
  NODE_TYPE_COLOR,
  STATE_STROKE_COLOR,
} from "./styling";
import { formatGenTypes, iconCategoryForNode, labelOf, NODE_KIND_LABEL } from "@/lib/gridmeta";
import { loadGridIcons } from "./mapIcons";
import { lineDeltas, nodeDeltas, type LineDelta, type NodeDelta } from "@/lib/simdelta";

export interface Selection {
  kind: "node" | "line";
  id: string;
}

interface Props {
  frame: StateFrame;
  meta: Meta;
  highlight: Set<string>;
  selected: Selection | null;
  onSelect: (s: Selection | null) => void;
  /** A "fly the camera here" request; the nonce re-triggers repeated jumps. */
  zoomTo: { kind: "node" | "line"; id: string; nonce: number } | null;
  /** Pre-failure frame for the delta overlay; null when not simulating. */
  baseFrame?: StateFrame | null;
  simulating?: boolean;
}

const STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    carto: {
      type: "raster",
      tiles: ["https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© CARTO © OpenStreetMap contributors",
    },
  },
  layers: [
    { id: "bg", type: "background", paint: { "background-color": "#f5f6f8" } },
    { id: "carto", type: "raster", source: "carto", paint: { "raster-opacity": 0.95 } },
  ],
};

// Sample a quadratic-bezier arc between two points. The bow direction is
// canonicalized so the curve always bows northward (positive lat) regardless of
// chord ordering — this prevents the chaotic look of arcs flipping based on
// from/to direction in the dataset.
//
// `circuit` lets parallel circuits between the same pair fan out instead of
// overlapping: circuit N gets bow * (1 + (N-1) * 0.18).
function arcPath(
  a: [number, number],
  b: [number, number],
  circuit = 1,
  samples = 20,
): [number, number][] {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len = Math.hypot(dx, dy);
  if (len === 0) return [a, b];
  // Perpendicular unit vector (rotate 90° CCW from chord direction).
  let px = -dy / len;
  let py = dx / len;
  // Force the bow to point northward (positive lat) so all arcs curve the
  // same way regardless of how the chord is oriented.
  if (py < 0) { px = -px; py = -py; }
  // Bow magnitude scales with chord length but tapers on very long spans so the
  // SF→SD line doesn't balloon into the Pacific. Stagger parallel circuits.
  const baseBow = Math.min(len * 0.22, 1.6) * (1 + (circuit - 1) * 0.18);
  const cx = (a[0] + b[0]) / 2 + px * baseBow;
  const cy = (a[1] + b[1]) / 2 + py * baseBow;
  const pts: [number, number][] = [];
  for (let i = 0; i <= samples; i++) {
    const t = i / samples;
    const u = 1 - t;
    pts.push([u * u * a[0] + 2 * u * t * cx + t * t * b[0], u * u * a[1] + 2 * u * t * cy + t * t * b[1]]);
  }
  return pts;
}

// Pull the circuit number off the end of an id like `branch_001_050_2` → 2.
function circuitNum(id: string): number {
  const m = id.match(/_(\d+)$/);
  return m ? parseInt(m[1], 10) : 1;
}

function buildGeo(
  frame: StateFrame,
  highlight: Set<string>,
  deltas: { lines: Record<string, LineDelta>; nodes: Record<string, NodeDelta> } | null,
) {
  const coord: Record<string, [number, number]> = {};
  const zoneOf: Record<string, string> = {};
  for (const n of frame.nodes) {
    coord[n.id] = [n.lon, n.lat];
    zoneOf[n.id] = n.zone || "";
  }

  const lines = {
    type: "FeatureCollection" as const,
    features: frame.lines
      .map((l) => {
        const a = coord[l.from_node];
        const b = coord[l.to_node];
        if (!a || !b) return null;
        const d = deltas?.lines[l.id];
        const za = zoneOf[l.from_node];
        const zb = zoneOf[l.to_node];
        const inter = za && zb && za !== zb ? 1 : 0;
        let coords = inter ? arcPath(a, b, circuitNum(l.id)) : [a, b];
        // Reverse geometry when flow is from b→a so the animated marching
        // dashes on the overlay layer naturally show the real flow direction.
        if ((l.p_from_mw ?? 0) < 0) coords = coords.slice().reverse();
        return {
          type: "Feature" as const,
          geometry: { type: "LineString" as const, coordinates: coords },
          properties: {
            id: l.id,
            name: labelOf(l),
            kind: l.kind,
            loading: l.loading_pct ?? -1,
            cap: l.max_i_ka || 0,
            inservice: l.in_service ? 1 : 0,
            inter,
            hl: highlight.has(l.id) ? 1 : 0,
            dload: d?.deltaLoading ?? 0,
            mover: d?.mover ? 1 : 0,
            tripped: d?.tripped ? 1 : 0,
          },
        };
      })
      .filter(Boolean),
  };

  const nodes = {
    type: "FeatureCollection" as const,
    features: frame.nodes.map((n) => ({
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: [n.lon, n.lat] },
      properties: {
        id: n.id,
        name: labelOf(n),
        type: n.type,
        kind: n.is_slack ? "Slack bus" : NODE_KIND_LABEL[n.type],
        gen: formatGenTypes(n.gen_types),
        icon: iconCategoryForNode(n),
        state: n.state,
        mag: Math.max(n.production_mw, n.consumption_mw, 0),
        vm: n.vm_pu ?? 0,
        hl: highlight.has(n.id) ? 1 : 0,
        worsened: deltas?.nodes[n.id]?.worsened ? 1 : 0,
      },
    })),
  };
  return { lines, nodes };
}

const loadingColor: maplibregl.ExpressionSpecification = [
  "case",
  ["<", ["get", "loading"], 0],
  OUT_OF_SERVICE_COLOR,
  [
    "interpolate",
    ["linear"],
    ["get", "loading"],
    ...LOADING_STOPS.flatMap((s) => [s.pct, s.color]),
  ] as any,
];

export default function MapView({ frame, meta, highlight, selected, onSelect, zoomTo, baseFrame, simulating }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const ready = useRef(false);

  // Delta overlay vs the pre-failure frame (null when not simulating). Recomputed
  // whenever the rendered frame changes so it tracks the time scrubber.
  const deltas = useMemo(
    () =>
      simulating && baseFrame
        ? { lines: lineDeltas(baseFrame, frame), nodes: nodeDeltas(baseFrame, frame) }
        : null,
    [simulating, baseFrame, frame],
  );
  // `deltasRef` lets the once-only map-load handler read the latest deltas.
  const deltasRef = useRef(deltas);
  deltasRef.current = deltas;

  // init once
  useEffect(() => {
    if (!ref.current || mapRef.current) return;
    const b = meta.bbox;
    const map = new maplibregl.Map({
      container: ref.current,
      style: STYLE,
      bounds: [
        [b.lon_min, b.lat_min],
        [b.lon_max, b.lat_max],
      ],
      fitBoundsOptions: { padding: 60 },
      attributionControl: false,
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
    mapRef.current = map;

    map.on("load", () => {
      const geo = buildGeo(frame, highlight, deltasRef.current);
      map.addSource("lines", { type: "geojson", data: geo.lines as any });
      map.addSource("nodes", { type: "geojson", data: geo.nodes as any });

      // Stroke width encodes thermal capacity (max_i_ka), color encodes
      // current loading. A thick green line is a fat idle highway; a thin red
      // one is an overloaded feeder — capacity stays visible regardless of load.
      // max_i_ka distribution: median ~2.5 kA, max ~14.6 kA.
      map.addLayer({
        id: "lines-casing",
        type: "line",
        source: "lines",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": CASING_COLOR,
          "line-width": [
            "case",
            ["==", ["get", "inter"], 1],
            ["interpolate", ["linear"], ["get", "cap"], 1, 1.8, 3, 2.6, 8, 4.0, 15, 5.6],
            ["case",
              ["==", ["get", "kind"], "trafo"],
              2.4,
              ["interpolate", ["linear"], ["get", "cap"], 1, 1.8, 3, 2.8, 8, 4.4, 15, 6.2],
            ],
          ],
          "line-opacity": [
            "case",
            ["==", ["get", "inter"], 1], 0.45,
            0.7,
          ],
        },
      });
      map.addLayer({
        id: "line-hl",
        type: "line",
        source: "lines",
        filter: ["==", ["get", "hl"], 1],
        paint: { "line-color": "#ffd84d", "line-width": 12, "line-opacity": 0.65, "line-blur": 3 },
      });
      map.addLayer({
        id: "lines",
        type: "line",
        source: "lines",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": loadingColor,
          "line-width": [
            "case",
            ["==", ["get", "inter"], 1],
            ["interpolate", ["linear"], ["get", "cap"], 1, 1.0, 3, 1.8, 8, 2.8, 15, 4.0],
            ["case",
              ["==", ["get", "kind"], "trafo"],
              1.4,
              ["interpolate", ["linear"], ["get", "cap"], 1, 1.2, 3, 2.0, 8, 3.2, 15, 4.6],
            ],
          ],
          "line-opacity": [
            "case",
            ["==", ["get", "inservice"], 0], 0.3,
            ["==", ["get", "inter"], 1], 0.7,
            1,
          ],
        },
      });

      // Marching-ants flow overlay on every in-service line. Dasharray is
      // shifted on a timer (see useEffect below) to animate. Geometry direction
      // is reversed upstream when p_from_mw < 0 (buildGeo) so the dashes always
      // march in the direction power is actually flowing.
      map.addLayer({
        id: "lines-flow",
        type: "line",
        source: "lines",
        filter: ["==", ["get", "inservice"], 1],
        layout: { "line-cap": "butt", "line-join": "round" },
        paint: {
          "line-color": "#ffffff",
          "line-width": [
            "interpolate", ["linear"], ["get", "cap"],
            1, 0.9, 3, 1.6, 8, 2.5, 15, 3.6,
          ],
          "line-opacity": 0.7,
          "line-dasharray": [0, 4, 3],
        },
      });

      map.addLayer({
        id: "node-hl",
        type: "circle",
        source: "nodes",
        filter: ["==", ["get", "hl"], 1],
        paint: {
          "circle-radius": ["+", ["interpolate", ["linear"], ["get", "mag"], 0, 11, 2000, 26], 9],
          "circle-color": "#ffd84d",
          "circle-opacity": 0.55,
        },
      });
      map.addLayer({
        id: "nodes",
        type: "circle",
        source: "nodes",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["get", "mag"], 0, 8, 500, 14, 2000, 24],
          "circle-color": [
            "match",
            ["get", "type"],
            "generation", NODE_TYPE_COLOR.generation,
            "load", NODE_TYPE_COLOR.load,
            "slack", NODE_TYPE_COLOR.slack,
            NODE_TYPE_COLOR.substation,
          ],
          "circle-stroke-width": [
            "case",
            ["==", ["get", "state"], "alert"],
            4,
            ["==", ["get", "state"], "warn"],
            3,
            1.5,
          ],
          "circle-stroke-color": [
            "match",
            ["get", "state"],
            "alert", STATE_STROKE_COLOR.alert,
            "warn", STATE_STROKE_COLOR.warn,
            "offline", STATE_STROKE_COLOR.offline,
            STATE_STROKE_COLOR.ok,
          ],
        },
      });

      // --- simulation overlay layers (hidden until a sim is active) ---
      // Hot glow beneath branches whose loading jumped (drawn under "lines" so
      // the loading color still reads on top). Opacity is pulsed from an effect.
      map.addLayer(
        {
          id: "lines-mover-glow",
          type: "line",
          source: "lines",
          filter: ["==", ["get", "mover"], 1],
          layout: { "line-cap": "round", visibility: "none" },
          paint: {
            "line-color": "#ff1f1f",
            "line-width": ["interpolate", ["linear"], ["get", "loading"], 0, 12, 100, 24],
            "line-opacity": 0.7,
            "line-blur": 3,
          },
        },
        "lines",
      );
      // Tripped (out-of-service) branches: bold dashed grey on top.
      map.addLayer({
        id: "lines-tripped",
        type: "line",
        source: "lines",
        filter: ["==", ["get", "tripped"], 1],
        layout: { visibility: "none", "line-cap": "round" },
        paint: {
          "line-color": OUT_OF_SERVICE_COLOR,
          "line-width": 5,
          "line-dasharray": [1.6, 1.4],
          "line-opacity": 1,
        },
      });
      // Buses whose state worsened: a bold pulsing red ring.
      map.addLayer({
        id: "nodes-worsened",
        type: "circle",
        source: "nodes",
        filter: ["==", ["get", "worsened"], 1],
        layout: { visibility: "none" },
        paint: {
          "circle-radius": ["+", ["interpolate", ["linear"], ["get", "mag"], 0, 8, 500, 14, 2000, 24], 11],
          "circle-color": "rgba(255,31,31,0.12)",
          "circle-stroke-color": "#ff1f1f",
          "circle-stroke-width": 5,
          "circle-stroke-opacity": 0.9,
        },
      });

      // Selection ring — scales with the bus so it always hugs the circle.
      map.addLayer({
        id: "node-selected",
        type: "circle",
        source: "nodes",
        filter: ["==", ["get", "id"], "__none__"],
        paint: {
          "circle-radius": ["+", ["interpolate", ["linear"], ["get", "mag"], 0, 8, 500, 14, 2000, 24], 6],
          "circle-color": "rgba(0,0,0,0)",
          "circle-stroke-color": "#3aa0ff",
          "circle-stroke-width": 4,
        },
      });
      // Bright halo drawn *beneath* the colored line (beforeId "lines") so the
      // selected branch lights up without hiding its loading color.
      map.addLayer(
        {
          id: "line-selected",
          type: "line",
          source: "lines",
          filter: ["==", ["get", "id"], "__none__"],
          layout: { "line-cap": "round" },
          paint: { "line-color": "#3aa0ff", "line-width": 9, "line-opacity": 0.9, "line-blur": 0.4 },
        },
        "lines",
      );

      // Invisible, enlarged hit target around every bus: makes buses easy to
      // grab and (via the query order below) gives them priority over lines.
      map.addLayer({
        id: "nodes-hit",
        type: "circle",
        source: "nodes",
        paint: {
          "circle-radius": ["+", ["interpolate", ["linear"], ["get", "mag"], 0, 8, 500, 14, 2000, 24], 11],
          "circle-color": "#000000",
          "circle-opacity": 0,
        },
      });

      // Type glyphs (sun/leaf/droplet/…) drawn on top of the bus circles. The
      // images load asynchronously, so add the symbol layer once they're ready.
      loadGridIcons(map).then(() => {
        if (!map.getLayer("node-icons") && map.getSource("nodes")) {
          map.addLayer({
            id: "node-icons",
            type: "symbol",
            source: "nodes",
            layout: {
              "icon-image": ["get", "icon"],
              // Scale the glyph with the bus circle so it stays legible inside it.
              "icon-size": ["interpolate", ["linear"], ["get", "mag"], 0, 0.62, 500, 0.9, 2000, 1.3],
              "icon-allow-overlap": true,
              "icon-ignore-placement": true,
            },
          });
        }
      });

      ready.current = true;

      const nodePopup = (p: any) =>
        `<b>${p.name}</b><br/>${p.kind}${p.gen ? ` · ${p.gen}` : ""} · ${Number(p.vm).toFixed(3)} p.u.`;
      const linePopup = (p: any) =>
        `<b>${p.name}</b><br/>${p.loading < 0 ? "out of service" : Number(p.loading).toFixed(0) + "% loaded"}`;

      const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10 });
      const clearPopup = () => {
        map.getCanvas().style.cursor = "";
        popup.remove();
      };
      // Buses win over lines: probe the enlarged bus hit area first, fall back to
      // lines only when no bus is under the cursor.
      const hitNode = (pt: maplibregl.PointLike) =>
        map.queryRenderedFeatures(pt, { layers: ["nodes-hit"] })[0];
      const hitLine = (pt: maplibregl.PointLike) =>
        map.queryRenderedFeatures(pt, { layers: ["lines"] })[0];

      map.on("mousemove", (e) => {
        const n = hitNode(e.point);
        const l = n ? undefined : hitLine(e.point);
        const f = n ?? l;
        if (!f) return clearPopup();
        map.getCanvas().style.cursor = "pointer";
        popup.setLngLat(e.lngLat).setHTML((n ? nodePopup : linePopup)(f.properties)).addTo(map);
      });
      map.on("mouseout", clearPopup);

      map.on("click", (e) => {
        const n = hitNode(e.point);
        if (n) return onSelect({ kind: "node", id: n.properties!.id });
        const l = hitLine(e.point);
        if (l) onSelect({ kind: "line", id: l.properties!.id });
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // update data when frame/highlight/deltas change
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready.current) return;
    const geo = buildGeo(frame, highlight, deltas);
    (map.getSource("lines") as maplibregl.GeoJSONSource)?.setData(geo.lines as any);
    (map.getSource("nodes") as maplibregl.GeoJSONSource)?.setData(geo.nodes as any);
  }, [frame, highlight, deltas]);

  // simulation overlay: pulse the "mover" glow + worsened-bus ring while a sim is
  // active, and toggle the overlay layers' visibility.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready.current) return;
    const vis = simulating ? "visible" : "none";
    for (const id of ["lines-mover-glow", "lines-tripped", "nodes-worsened"]) {
      if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", vis);
    }
    if (!simulating) return;
    let on = true;
    const tick = () => {
      on = !on;
      if (map.getLayer("lines-mover-glow"))
        map.setPaintProperty("lines-mover-glow", "line-opacity", on ? 0.9 : 0.3);
      if (map.getLayer("nodes-worsened"))
        map.setPaintProperty("nodes-worsened", "circle-stroke-opacity", on ? 1 : 0.35);
    };
    const iv = window.setInterval(tick, 600);
    return () => window.clearInterval(iv);
  }, [simulating]);

  // selection filters
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready.current) return;
    map.setFilter("node-selected", ["==", ["get", "id"], selected?.kind === "node" ? selected.id : "__none__"]);
    map.setFilter("line-selected", ["==", ["get", "id"], selected?.kind === "line" ? selected.id : "__none__"]);
  }, [selected]);

  // Marching-ants dash animation on the inter-region flow overlay. Cycles a
  // dasharray pattern through 14 frames giving a continuous flow effect; arc
  // geometry direction matches actual power flow (see buildGeo).
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    // Pattern alternates dash-then-gap; shifting through these 14 phases makes
    // a 7-unit period appear to translate one unit per frame.
    const DASH_SEQ: number[][] = [
      [0, 4, 3],     [0.5, 4, 2.5], [1, 4, 2],     [1.5, 4, 1.5],
      [2, 4, 1],     [2.5, 4, 0.5], [3, 4, 0],
      [0, 0.5, 3, 3.5], [0, 1, 3, 3], [0, 1.5, 3, 2.5],
      [0, 2, 3, 2],  [0, 2.5, 3, 1.5], [0, 3, 3, 1], [0, 3.5, 3, 0.5],
    ];
    let step = 0;
    const iv = window.setInterval(() => {
      if (!map.getLayer("lines-flow")) return; // not loaded yet
      step = (step + 1) % DASH_SEQ.length;
      map.setPaintProperty("lines-flow", "line-dasharray", DASH_SEQ[step]);
    }, 70);
    return () => window.clearInterval(iv);
  }, []);

  // fly the camera to a requested element (chat chip double-click / reticle)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready.current || !zoomTo) return;
    if (zoomTo.kind === "node") {
      const n = frame.nodes.find((x) => x.id === zoomTo.id);
      if (!n) return;
      map.flyTo({ center: [n.lon, n.lat], zoom: Math.max(map.getZoom(), 12), duration: 800 });
    } else {
      const l = frame.lines.find((x) => x.id === zoomTo.id);
      if (!l) return;
      const a = frame.nodes.find((x) => x.id === l.from_node);
      const b = frame.nodes.find((x) => x.id === l.to_node);
      if (!a || !b) return;
      const bounds = new maplibregl.LngLatBounds([a.lon, a.lat], [a.lon, a.lat]).extend([b.lon, b.lat]);
      map.fitBounds(bounds, { padding: 140, maxZoom: 13, duration: 800 });
    }
    // frame intentionally omitted: re-fly only when a new zoom request arrives.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [zoomTo]);

  return <div id="map" ref={ref} />;
}
