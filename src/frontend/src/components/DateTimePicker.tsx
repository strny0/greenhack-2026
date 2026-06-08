import { useState } from "react";
import { CalendarDays, ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

interface Props {
  /** Currently selected day (local midnight). */
  date: Date;
  /** First/last selectable days, inclusive. */
  bounds: { first: Date; last: Date };
  /** True while a new day's window is being fetched. */
  loading?: boolean;
  canPrev: boolean;
  canNext: boolean;
  onSelect: (date: Date) => void;
  onStep: (delta: -1 | 1) => void;
}

const fmtDay = (d: Date) =>
  d.toLocaleDateString("en-GB", {
    weekday: "short",
    day: "2-digit",
    month: "short",
    year: "numeric",
  });

export default function DateTimePicker({
  date,
  bounds,
  loading,
  canPrev,
  canNext,
  onSelect,
  onStep,
}: Props) {
  const [open, setOpen] = useState(false);
  return (
    <div className="flex shrink-0 items-center gap-1">
      <Button
        variant="outline"
        size="icon"
        disabled={!canPrev}
        onClick={() => onStep(-1)}
        title="Previous day"
        aria-label="Previous day"
      >
        <ChevronLeft className="size-4" />
      </Button>

      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            size="sm"
            className="min-w-[150px] justify-start gap-2"
            title="Pick a date"
          >
            {loading ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <CalendarDays className="size-4" />
            )}
            <span className="tabular-nums">{fmtDay(date)}</span>
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-auto p-0" align="start">
          <Calendar
            mode="single"
            captionLayout="dropdown"
            selected={date}
            defaultMonth={date}
            startMonth={bounds.first}
            endMonth={bounds.last}
            disabled={{ before: bounds.first, after: bounds.last }}
            onSelect={(d) => {
              if (d) {
                onSelect(d);
                setOpen(false);
              }
            }}
            autoFocus
          />
        </PopoverContent>
      </Popover>

      <Button
        variant="outline"
        size="icon"
        disabled={!canNext}
        onClick={() => onStep(1)}
        title="Next day"
        aria-label="Next day"
      >
        <ChevronRight className="size-4" />
      </Button>
    </div>
  );
}
