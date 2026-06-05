import type {
  Alert,
  ContingencyResult,
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
