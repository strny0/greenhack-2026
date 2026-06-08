import type maplibregl from "maplibre-gl";
import type { IconCategory } from "@/lib/gridmeta";

/**
 * White line-glyphs (lucide paths) drawn on top of the colored bus circles so a
 * bus's type is readable at a glance: sun = solar, droplet = hydro, leaf =
 * biomass, etc. Registered once per map via `loadGridIcons`.
 */
const GLYPHS: Record<IconCategory, string> = {
  solar:
    '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
  wind: '<path d="M12.8 19.6A2 2 0 1 0 14 16H2"/><path d="M17.5 8a2.5 2.5 0 1 1 2 4H2"/><path d="M9.8 4.4A2 2 0 1 1 11 8H2"/>',
  hydro:
    '<path d="M12 22a7 7 0 0 0 7-7c0-2-1-3.9-3-5.5s-3.5-4-4-6.5c-.5 2.5-2 4.9-4 6.5C6 11.1 5 13 5 15a7 7 0 0 0 7 7z"/>',
  biomass:
    '<path d="M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.48 19 2c1 2 2 4.18 2 8 0 5.5-4.78 10-10 10Z"/><path d="M2 21c0-3 1.85-5.36 5.08-6"/>',
  geothermal: '<path d="m8 3 4 8 5-5 5 15H2L8 3z"/>',
  coal:
    '<path d="M2 20a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8l-7 5V8l-7 5V4a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z"/><path d="M17 18h1M12 18h1M7 18h1"/>',
  gas: '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>',
  oil: '<line x1="3" x2="15" y1="22" y2="22"/><line x1="4" x2="14" y1="9" y2="9"/><path d="M14 22V4a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v18"/><path d="M14 13h2a2 2 0 0 1 2 2v2a2 2 0 0 0 2 2 2 2 0 0 0 2-2V9.83a2 2 0 0 0-.59-1.42L18 5"/>',
  generation:
    '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>',
  load: '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M9 22V12h6v10"/>',
  substation:
    '<path d="M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
  slack: '<path d="M12 2v10"/><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/>',
};

const RENDER_PX = 48; // backing resolution; displayed via pixelRatio + icon-size

function svgDataUrl(glyph: string): string {
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${RENDER_PX}" height="${RENDER_PX}" viewBox="0 0 24 24" ` +
    `fill="none" stroke="#ffffff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">${glyph}</svg>`;
  return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image(RENDER_PX, RENDER_PX);
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = url;
  });
}

/** Register every type glyph on the map (id = IconCategory). Idempotent. */
export async function loadGridIcons(map: maplibregl.Map): Promise<void> {
  await Promise.all(
    (Object.keys(GLYPHS) as IconCategory[]).map(async (key) => {
      if (map.hasImage(key)) return;
      try {
        const img = await loadImage(svgDataUrl(GLYPHS[key]));
        if (!map.hasImage(key)) map.addImage(key, img, { pixelRatio: 2 });
      } catch {
        /* a missing glyph just leaves the bare circle — non-fatal */
      }
    }),
  );
}

export const ICON_CATEGORIES = Object.keys(GLYPHS) as IconCategory[];

/** Same glyph as the map, tinted for use in the legend (white on the dark card). */
export function iconDataUrl(cat: IconCategory, stroke = "currentColor"): string {
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" ` +
    `fill="none" stroke="${stroke}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">${GLYPHS[cat]}</svg>`;
  return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
}
