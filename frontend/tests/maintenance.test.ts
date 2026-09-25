import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { maintenance } from "../src/lib/state/maintenance.svelte";

class FakeSource {
  static CLOSED = 2;
  static opened: FakeSource[] = [];
  readyState = 0;
  onerror: (() => void) | null = null;
  listeners: Record<string, ((event: { data: string }) => void)[]> = {};

  constructor(public url: string) {
    FakeSource.opened.push(this);
  }

  addEventListener(name: string, fn: (event: { data: string }) => void): void {
    (this.listeners[name] ??= []).push(fn);
  }

  close(): void {
    this.readyState = FakeSource.CLOSED;
  }

  send(maintenance: boolean): void {
    for (const fn of this.listeners.state ?? []) fn({ data: JSON.stringify({ maintenance }) });
  }

  fail(): void {
    this.readyState = FakeSource.CLOSED;
    this.onerror?.();
  }
}

let stop: () => void;

beforeEach(() => {
  vi.useFakeTimers();
  FakeSource.opened = [];
  vi.stubGlobal("EventSource", FakeSource);
  maintenance.phase = "idle";
  stop = maintenance.start();
});

afterEach(() => {
  stop();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const last = () => FakeSource.opened[FakeSource.opened.length - 1];

describe("the update notice", () => {
  it("says nothing while the server is up and was never down", () => {
    last().send(false);
    expect(maintenance.phase).toBe("idle");
  });

  it("goes down, stays down across the restart, and says back only from a live server", () => {
    last().send(true);
    expect(maintenance.phase).toBe("down");
    last().fail();
    expect(maintenance.phase, "a dropped stream is not the end of the update").toBe("down");
    vi.advanceTimersByTime(2000);
    expect(FakeSource.opened).toHaveLength(2);
    last().send(false);
    expect(maintenance.phase).toBe("back");
    vi.advanceTimersByTime(10_000);
    expect(maintenance.phase).toBe("idle");
  });

  it("stays down when the restarted server still holds the flag", () => {
    last().send(true);
    last().fail();
    vi.advanceTimersByTime(2000);
    last().send(true);
    expect(maintenance.phase).toBe("down");
  });

  it("backs off while the proxy keeps refusing, and resets once a server answers", () => {
    last().fail();
    vi.advanceTimersByTime(2000);
    last().fail();
    vi.advanceTimersByTime(3999);
    expect(FakeSource.opened, "the second wait is twice the first").toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(FakeSource.opened).toHaveLength(3);
    last().send(false);
    last().fail();
    vi.advanceTimersByTime(2000);
    expect(FakeSource.opened).toHaveLength(4);
  });

  it("reopens nothing once stopped", () => {
    last().fail();
    stop();
    vi.advanceTimersByTime(60_000);
    expect(FakeSource.opened).toHaveLength(1);
  });
});
