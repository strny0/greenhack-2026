import type {
  Alert,
  ContingencyResult,
  DeviationAssessment,
  DeviationRecord,
  Meta,
  StateFrame,
  WeatherPoint,
  WhatIfResponse,
} from "./types";

const J = async (r: Response) => {
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
};

export const api = {
  meta: (): Promise<Meta> => fetch("/api/meta").then(J),

  frame: (timestamp: string): Promise<StateFrame> =>
    fetch(`/api/frame?timestamp=${encodeURIComponent(timestamp)}`).then(J),

  window: (start: number, count: number): Promise<StateFrame[]> =>
    fetch(`/api/window?start=${start}&count=${count}`).then(J),

  // Same as window(), but streams the (large) response body and reports a
  // 0..1 download fraction. Note: with gzip on the wire, Content-Length is the
  // compressed size while the body stream yields decompressed bytes, so we
  // estimate the total from the frame count (~78 KB/frame) rather than trust
  // the header. Snaps to 1 once the JSON is fully received.
  windowProgress: async (
    start: number,
    count: number,
    onProgress?: (fraction: number) => void,
  ): Promise<StateFrame[]> => {
    const res = await fetch(`/api/window?start=${start}&count=${count}`);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const reader = res.body?.getReader();
    if (!reader) return res.json(); // no streaming support — just parse
    const estTotal = Math.max(1, count * 78_000);
    const chunks: Uint8Array[] = [];
    let received = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      received += value.length;
      onProgress?.(Math.min(0.99, received / estTotal));
    }
    const buf = new Uint8Array(received);
    let off = 0;
    for (const c of chunks) {
      buf.set(c, off);
      off += c.length;
    }
    onProgress?.(1);
    return JSON.parse(new TextDecoder().decode(buf));
  },

  alerts: (timestamp: string): Promise<{ timestamp: string; alerts: Alert[] }> =>
    fetch(`/api/alerts?timestamp=${encodeURIComponent(timestamp)}`).then(J),

  timeseries: (
    elementId: string,
    kind: "line" | "node",
    metric: string,
    start: string,
    count: number,
  ): Promise<{ t: string[]; v: (number | null)[]; metric: string }> =>
    fetch(
      `/api/timeseries?element_id=${encodeURIComponent(elementId)}&kind=${kind}&metric=${metric}&start=${encodeURIComponent(start)}&count=${count}`,
    ).then(J),

  n1: (
    timestamp: string,
    limit = 60,
  ): Promise<{ timestamp: string; n_analyzed: number; results: ContingencyResult[] }> =>
    fetch(`/api/n1?timestamp=${encodeURIComponent(timestamp)}&limit=${limit}`).then(J),

  whatif: (body: {
    timestamp: string;
    disconnect_lines?: string[];
    trip_nodes?: string[];
    load_scale?: number;
  }): Promise<WhatIfResponse> =>
    fetch("/api/whatif", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }).then(J),

  weather: (): Promise<{ points: WeatherPoint[]; summary: string }> =>
    fetch("/api/weather").then(J),

  // Whole-year deterministic deviation-risk timeline (loaded once, indexed by ts).
  deviationTimeline: (): Promise<{ records: DeviationRecord[]; built_at: string }> =>
    fetch("/api/deviation/timeline").then(J),

  // Finest-granularity per-generator assessment for one settled hour (real solve).
  deviationTriage: (timestamp: string): Promise<DeviationAssessment> =>
    fetch(`/api/deviation/triage?timestamp=${encodeURIComponent(timestamp)}`).then(J),

  chat: (
    timestamp: string,
    messages: { role: string; content: string }[],
  ): Promise<{ reply: string; model: string | null; grounded: boolean }> =>
    fetch("/api/chat", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ timestamp, messages }),
    }).then(J),
};
