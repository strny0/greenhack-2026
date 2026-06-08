import { useMemo, useState } from "react";
import { Bookmark, Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { dateToKey, keyToDate } from "@/lib/datetime";

interface Entry {
  /** Day key, "YYYY-MM-DD". */
  key: string;
  /** Short headline. */
  title: string;
  /** One-line description shown under the title (optional). */
  subtitle?: string;
}

/**
 * Hand-picked "interesting" days, surfaced from the dataset's surprise/loading
 * statistics. Order here doesn't matter — the list is always sorted by date.
 */
const SEED: Entry[] = [
  {
    key: "2024-01-07",
    title: "Winter wind whiplash",
    subtitle: "Wind shock on a 59%-loaded grid",
  },
  {
    key: "2024-05-05",
    title: "Spring demand spike",
    subtitle: "Load far above forecast",
  },
  {
    key: "2024-07-17",
    title: "Heatwave load shock",
    subtitle: "Biggest demand surprise of the year",
  },
  {
    key: "2024-08-28",
    title: "Late-summer crunch",
    subtitle: "Sustained high demand, 12.3 GW peak",
  },
  {
    key: "2024-09-13",
    title: "Autumn wind surge",
    subtitle: "Record wind swing meets 12.4 GW peak",
  },
];

const fmtDay = (d: Date) =>
  d.toLocaleDateString("en-GB", {
    weekday: "short",
    day: "2-digit",
    month: "short",
    year: "numeric",
  });

interface Props {
  /** Currently selected day (local midnight). */
  currentDate: Date;
  /** Navigate the app to a bookmarked day. */
  onSelect: (date: Date) => void;
}

export default function BookmarksMenu({ currentDate, onSelect }: Props) {
  const [open, setOpen] = useState(false);
  // In-memory only (demo): seeded with the hand-picked days, mutated locally.
  const [entries, setEntries] = useState<Entry[]>(SEED);

  const sorted = useMemo(
    () => [...entries].sort((a, b) => a.key.localeCompare(b.key)),
    [entries],
  );

  const currentKey = dateToKey(currentDate);
  const alreadyBookmarked = entries.some((e) => e.key === currentKey);

  const addCurrent = () => {
    if (alreadyBookmarked) return;
    setEntries((prev) => [
      ...prev,
      { key: currentKey, title: fmtDay(currentDate) },
    ]);
  };

  const remove = (key: string) =>
    setEntries((prev) => prev.filter((e) => e.key !== key));

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="icon"
          title="Bookmarked days"
          aria-label="Bookmarked days"
        >
          <Bookmark className="size-4" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-72 p-0" align="start">
        <div className="border-b p-2">
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start gap-2"
            disabled={alreadyBookmarked}
            onClick={addCurrent}
          >
            <Plus className="size-4" />
            {alreadyBookmarked ? "Current day bookmarked" : "Add current day"}
          </Button>
        </div>
        <ul className="max-h-80 overflow-y-auto py-1">
          {sorted.length === 0 && (
            <li className="px-3 py-4 text-center text-sm text-muted-foreground">
              No bookmarks yet
            </li>
          )}
          {sorted.map((e) => {
            const isCurrent = e.key === currentKey;
            return (
              <li key={e.key} className="group relative">
                <button
                  type="button"
                  className={
                    "flex w-full flex-col items-start gap-0.5 px-3 py-2 pr-9 text-left transition-colors hover:bg-accent" +
                    (isCurrent ? " bg-accent/50" : "")
                  }
                  onClick={() => {
                    onSelect(keyToDate(e.key));
                    setOpen(false);
                  }}
                >
                  <span className="text-sm font-medium leading-tight">
                    {e.title}
                  </span>
                  {e.subtitle && (
                    <span className="text-xs leading-snug text-muted-foreground">
                      {e.subtitle}
                    </span>
                  )}
                  <span className="text-[11px] tabular-nums text-muted-foreground/70">
                    {fmtDay(keyToDate(e.key))}
                  </span>
                </button>
                <button
                  type="button"
                  className="absolute right-2 top-2 rounded p-1 text-muted-foreground opacity-0 transition-opacity hover:bg-muted hover:text-foreground focus:opacity-100 group-hover:opacity-100"
                  title="Remove bookmark"
                  aria-label={`Remove ${e.title}`}
                  onClick={(ev) => {
                    ev.stopPropagation();
                    remove(e.key);
                  }}
                >
                  <X className="size-3.5" />
                </button>
              </li>
            );
          })}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
