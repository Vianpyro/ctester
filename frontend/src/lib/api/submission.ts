// SUBMIT, AND READ THE VERDICT. Anonymous by default: the session key in
// Moodle's link is the access control, and an account -- when there is one -- only
// adds memory (progression, drafts) on top.
//
// THE TOKEN IS ATTACHED HERE AND NOT THROUGH `authRequest`, and that difference
// matters: `/submit` ACCEPTS an anonymous job, so an expired token is not REFUSED,
// it is IGNORED -- the job is recorded with no owner, the status, the attempt and
// the XP never happen, and nothing on screen says a word about it. A 401 would at
// least have been visible. So the caller renews BEFORE submitting; see
// `state/submission.svelte.ts`.

import { request } from "./client";
import { session } from "../auth/session.svelte";
import type { PollResult, SubmissionBody } from "./types";

export interface Accepted {
  id?: string;
  error?: string;
  /** Seconds, on a 429. The API always sent it; the page used to discard it. */
  retry_after?: number;
}

/** `station` separates two anonymous visitors behind one NATed IP. */
export function submit(body: SubmissionBody, station: string) {
  return request<Accepted>("submit?poste=" + encodeURIComponent(station), {
    method: "POST",
    json: body,
    // Signing in is optional: with no token the submission stays anonymous. With
    // one, the API can attach the job to the account and record practice and
    // status from its OWN reading of the verdict -- never from the browser's.
    headers: session.token ? { Authorization: "Bearer " + session.token } : {},
  });
}

/** A job's verdict, or its position in the queue. Anonymous, like `/submit`. */
export const poll = (jobId: string) => request<PollResult>("r/" + encodeURIComponent(jobId));
