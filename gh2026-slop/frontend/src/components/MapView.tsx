import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import type { Meta, StateFrame } from "../types";

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
}

const STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    carto: {
      type: "raster",
      tiles: ["https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© CARTO © OpenStreetMap contributors",
    },
  },
  layers: [
    { id: "bg", type: "background", paint: { "background-color": "#0a0e16" } },
    { id: "carto", type: "raster", source: "carto", paint: { "raster-opacity": 0.55 } },
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
  "#5a6677",
  [
    "interpolate",
    ["linear"],
    ["get", "loading"],
    0,
    "#2ecc71",
    50,
    "#9acd32",
    75,
    "#f5b915",
    90,
    "#ff7a45",
    110,
    "#ff4d4f",
  ],
];

export default function MapView({ frame, meta, highlight, selected, onSelect }: Props) {
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
          "line-color": "#05080f",
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
        paint: { "line-color": "#ffffff", "line-width": 12, "line-opacity": 0.45, "line-blur": 3 },
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
          "circle-color": "#ffffff",
          "circle-opacity": 0.18,
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
            "generation",
            "#2f81f7",
            "load",
            "#e8833a",
            "slack",
            "#b07cff",
            "#6b7a90",
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
            "alert",
            "#ff4d4f",
            "warn",
            "#f5b915",
            "offline",
            "#5a6677",
            "#0a0e16",
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

  return <div id="map" ref={ref} />;
}
