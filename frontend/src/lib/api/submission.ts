import { request } from "./client";
import { session } from "../auth/session.svelte";
import type { PollResult, SubmissionBody } from "./types";

export interface Accepted {
  id?: string;
  ids?: string[];
  error?: string;
  retry_after?: number;
}

export function submit(body: SubmissionBody, station: string) {
  return request<Accepted>("submit?station=" + encodeURIComponent(station), {
    method: "POST",
    json: body,
    headers: session.token ? { Authorization: "Bearer " + session.token } : {},
  });
}

export const poll = (jobId: string) => request<PollResult>("r/" + encodeURIComponent(jobId));
