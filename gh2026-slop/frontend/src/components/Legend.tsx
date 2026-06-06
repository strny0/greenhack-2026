import type { IconCategory } from "@/lib/gridmeta";
import { iconDataUrl } from "./mapIcons";

// Bus glyphs shown on the geographical map, paired with a human label.
const ICON_LEGEND: [IconCategory, string][] = [
  ["solar", "Solar"],
  ["wind", "Wind"],
  ["hydro", "Hydro"],
  ["biomass", "Biomass"],
  ["gas", "Gas"],
  ["coal", "Coal"],
  ["oil", "Oil"],
  ["geothermal", "Geothermal"],
  ["generation", "Other gen."],
  ["load", "Load"],
  ["substation", "Substation"],
  ["slack", "Slack / ext."],
];

export default function Legend({ showBusIcons = false }: { showBusIcons?: boolean }) {
  return (
    <div className="absolute left-3 top-3 z-10 max-w-[230px] rounded-lg border bg-card/90 p-3 text-[11px] shadow-md backdrop-blur">
      <h4 className="mb-1.5 text-[11px] uppercase text-muted-foreground">Line loading</h4>
      <div className="my-1 flex items-center gap-2">
        <span
          className="h-1 w-[22px] rounded-sm"
          style={{ background: "linear-gradient(90deg,#2ecc71,#9acd32,#f5b915,#ff7a45,#ff4d4f)" }}
        />
        <span>0% → 110%+</span>
      </div>
      <h4 className="mb-1.5 mt-2 text-[11px] uppercase text-muted-foreground">Nodes</h4>
      {[
        ["#2f81f7", "Generation"],
        ["#e8833a", "Load"],
        ["#b07cff", "Slack / ext. grid"],
        ["#6b7a90", "Substation"],
      ].map(([c, label]) => (
        <div key={label} className="my-1 flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full" style={{ background: c }} />
          {label}
        </div>
      ))}
      <div className="my-1 flex items-center gap-2">
        <span
          className="h-2.5 w-2.5 rounded-full"
          style={{ background: "#1a2233", border: "2px solid #ff4d4f" }}
        />
        Voltage alert ring
      </div>

      {showBusIcons && (
        <>
          <h4 className="mb-1.5 mt-2 text-[11px] uppercase text-muted-foreground">Bus type</h4>
          <div className="grid grid-cols-2 gap-x-2 gap-y-0.5">
            {ICON_LEGEND.map(([cat, label]) => (
              <div key={cat} className="flex items-center gap-1.5">
                <img src={iconDataUrl(cat, "#d4d4d8")} alt="" className="size-3.5 shrink-0" />
                <span className="truncate">{label}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
