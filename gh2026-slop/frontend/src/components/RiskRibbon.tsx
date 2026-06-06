import { useMemo } from "react";
import type { DeviationRecord, Meta, StateFrame } from "../types";
import { combinedLevel, LEVEL_FILL } from "@/lib/deviation";

interface Props {
  frames: StateFrame[];
  devByTs: Map<string, DeviationRecord>;
  idx: number;
  meta: Meta;
  onJump: (i: number) => void;
}

const fmtShort = (ts: string) =>
  new Date(ts).toLocaleString("en-GB", {
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
  });

/**
 * History-so-far risk ribbon under the timeline scrubber.
 *
 * One stripe per loaded hour. Hours up to "now" (idx) are coloured by the worst of
 * their grid alerts/warnings and their plan-deviation risk tier; future hours stay
 * blank because their actuals haven't happened yet (online-operation framing).
 * Click any stripe to move "now" there. The loaded window is small (tens of hours),
 * so simple DOM stripes are cheaper and more interactive than a canvas here.
 */
export default function RiskRibbon({ frames, devByTs, idx, meta, onJump }: Props) {
  const stripes = useMemo(
    () =>
      frames.map((f, i) => {
        const dev = devByTs.get(f.timestamp) ?? null;
        const past = i <= idx;
        const level = past ? combinedLevel(f, dev, meta) : 0;
        return {
          i,
          fill: past ? LEVEL_FILL[level] : "transparent",
          tip: dev?.headline
            ? `${fmtShort(f.timestamp)} — ${dev.headline}`
            : fmtShort(f.timestamp),
        };
      }),
    [frames, devByTs, idx, meta],
  );

  if (!frames.length) return null;

  return (
    <div
      className="relative flex h-2 w-full overflow-hidden rounded-sm bg-muted"
      role="group"
      aria-label="Deviation risk history"
    >
      {stripes.map((s) => (
        <button
          key={s.i}
          type="button"
          title={s.tip}
          aria-label={s.tip}
          onClick={() => onJump(s.i)}
          className="h-full min-w-0 flex-1 transition-opacity hover:opacity-70"
          style={{ backgroundColor: s.fill }}
        />
      ))}
      {/* "now" caret */}
      <div
        className="pointer-events-none absolute top-0 h-full w-0.5 bg-foreground/80"
        style={{
          left: `${frames.length > 1 ? (idx / (frames.length - 1)) * 100 : 0}%`,
          transform: "translateX(-50%)",
        }}
      />
    </div>
  );
}
