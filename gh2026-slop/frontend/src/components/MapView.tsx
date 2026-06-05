import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import type { Meta, StateFrame } from "../types";
import {
  LOADING_STOPS,
  OUT_OF_SERVICE_COLOR,
  CASING_COLOR,
  NODE_TYPE_COLOR,
  STATE_STROKE_COLOR,
} from "./styling";

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

function buildGeo(frame: StateFrame, highlight: Set<string>) {
  const coord: Record<string, [number, number]> = {};
  for (const n of frame.nodes) coord[n.id] = [n.lon, n.lat];

  const lines = {
    type: "FeatureCollection" as const,
    features: frame.lines
      .map((l) => {
        const a = coord[l.from_node];
        const b = coord[l.to_node];
        if (!a || !b) return null;
        return {
          type: "Feature" as const,
          geometry: { type: "LineString" as const, coordinates: [a, b] },
          properties: {
            id: l.id,
            name: l.name,
            kind: l.kind,
            loading: l.loading_pct ?? -1,
            inservice: l.in_service ? 1 : 0,
            hl: highlight.has(l.id) ? 1 : 0,
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
        name: n.name,
        type: n.type,
        state: n.state,
        mag: Math.max(n.production_mw, n.consumption_mw, 0),
        vm: n.vm_pu ?? 0,
        hl: highlight.has(n.id) ? 1 : 0,
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

export default function MapView({ frame, meta, highlight, selected, onSelect, zoomTo }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const ready = useRef(false);

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
      const geo = buildGeo(frame, highlight);
      map.addSource("lines", { type: "geojson", data: geo.lines as any });
      map.addSource("nodes", { type: "geojson", data: geo.nodes as any });

      // dark casing underneath for contrast against the basemap
      map.addLayer({
        id: "lines-casing",
        type: "line",
        source: "lines",
        paint: {
          "line-color": CASING_COLOR,
          "line-width": [
            "case",
            ["==", ["get", "kind"], "trafo"],
            4,
            ["interpolate", ["linear"], ["get", "loading"], 0, 4, 100, 8.5],
          ],
          "line-opacity": 0.7,
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
        layout: { "line-cap": "round" },
        paint: {
          "line-color": loadingColor,
          "line-width": [
            "case",
            ["==", ["get", "kind"], "trafo"],
            2.5,
            ["interpolate", ["linear"], ["get", "loading"], 0, 2.6, 100, 6],
          ],
          "line-opacity": ["case", ["==", ["get", "inservice"], 0], 0.3, 1],
        },
      });

      map.addLayer({
        id: "node-hl",
        type: "circle",
        source: "nodes",
        filter: ["==", ["get", "hl"], 1],
        paint: {
          "circle-radius": ["+", ["interpolate", ["linear"], ["get", "mag"], 0, 6, 2000, 18], 8],
          "circle-color": "#ffd84d",
          "circle-opacity": 0.55,
        },
      });
      map.addLayer({
        id: "nodes",
        type: "circle",
        source: "nodes",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["get", "mag"], 0, 4, 500, 9, 2000, 15],
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
            3,
            ["==", ["get", "state"], "warn"],
            2,
            1,
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

      // selection ring
      map.addLayer({
        id: "node-selected",
        type: "circle",
        source: "nodes",
        filter: ["==", ["get", "id"], "__none__"],
        paint: {
          "circle-radius": 18,
          "circle-color": "rgba(0,0,0,0)",
          "circle-stroke-color": "#2f81f7",
          "circle-stroke-width": 2.5,
        },
      });
      map.addLayer({
        id: "line-selected",
        type: "line",
        source: "lines",
        filter: ["==", ["get", "id"], "__none__"],
        paint: { "line-color": "#2f81f7", "line-width": 6, "line-opacity": 0.5 },
      });

      ready.current = true;

      const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10 });
      const enter = (label: (p: any) => string) => (e: any) => {
        map.getCanvas().style.cursor = "pointer";
        const f = e.features?.[0];
        if (f) popup.setLngLat(e.lngLat).setHTML(label(f.properties)).addTo(map);
      };
      const leave = () => {
        map.getCanvas().style.cursor = "";
        popup.remove();
      };
      map.on("mouseenter", "nodes", enter((p) => `<b>${p.name}</b><br/>${p.type} · ${Number(p.vm).toFixed(3)} p.u.`));
      map.on("mousemove", "nodes", (e: any) => {
        const f = e.features?.[0];
        if (f) popup.setLngLat(e.lngLat).setHTML(`<b>${f.properties.name}</b><br/>${f.properties.type} · ${Number(f.properties.vm).toFixed(3)} p.u.`);
      });
      map.on("mouseleave", "nodes", leave);
      map.on("mouseenter", "lines", enter((p) => `<b>${p.name}</b><br/>${p.loading < 0 ? "out of service" : Number(p.loading).toFixed(0) + "% loaded"}`));
      map.on("mousemove", "lines", (e: any) => {
        const f = e.features?.[0];
        if (f) popup.setLngLat(e.lngLat).setHTML(`<b>${f.properties.name}</b><br/>${f.properties.loading < 0 ? "out of service" : Number(f.properties.loading).toFixed(0) + "% loaded"}`);
      });
      map.on("mouseleave", "lines", leave);

      map.on("click", "nodes", (e: any) => {
        const f = e.features?.[0];
        if (f) onSelect({ kind: "node", id: f.properties.id });
      });
      map.on("click", "lines", (e: any) => {
        const f = e.features?.[0];
        if (f) onSelect({ kind: "line", id: f.properties.id });
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // update data when frame/highlight changes
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready.current) return;
    const geo = buildGeo(frame, highlight);
    (map.getSource("lines") as maplibregl.GeoJSONSource)?.setData(geo.lines as any);
    (map.getSource("nodes") as maplibregl.GeoJSONSource)?.setData(geo.nodes as any);
  }, [frame, highlight]);

  // selection filters
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready.current) return;
    map.setFilter("node-selected", ["==", ["get", "id"], selected?.kind === "node" ? selected.id : "__none__"]);
    map.setFilter("line-selected", ["==", ["get", "id"], selected?.kind === "line" ? selected.id : "__none__"]);
  }, [selected]);

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
