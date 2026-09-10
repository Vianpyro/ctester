// THE WIRE, WRITTEN DOWN. These types describe what the API actually returns,
// read off `app/routers/` -- not what would be convenient here. Where the
// server can answer "it is unknown" (a mute database), the field is nullable
// and the page has to say so rather than show a zero.
//
// NOTHING HERE CARRIES AN IDENTITY. No `sub`, no `account`, no `owner`: the
// server refuses to send one and no request may claim one. That is the same
// invariant `app/schemas.py` holds on the way in, stated on the way out.

// --- /oidc.json --------------------------------------------------------------

/** What this deployment offers. An empty object means "nothing more". */
export interface Deployment {
  issuer?: string;
  client_id?: string;
  /** False or absent: the button does not exist, so the module is never fetched. */
  forum?: boolean;
  scratch?: boolean;
  /** The course Discord's invitation, independent of the bridge. */
  discord?: string;
}

// --- /catalog.json -----------------------------------------------------------

export type Access = "available" | "scheduled" | "archived";

export type ExerciseMode = "io" | "unity" | "quiz";

export interface PublishedRelease {
  collections?: PublishedCollection[];
  exercises?: PublishedExercise[];
  assignments?: PublishedAssignment[];
}

export interface PublishedCollection {
  id?: string;
  title?: string;
  items?: string[];
  access?: Access;
  release?: { available_from?: string };
}

export interface PublishedExercise {
  id: string;
  title?: string;
  mode: ExerciseMode;
  files?: { name: string }[];
  skills?: string[];
  contexts?: string[];
  difficulty?: string;
  /** Absent from the published catalog when false -- hence every double bang. */
  verification?: boolean;
  /** Which assignment this exercise belongs to, or absent. */
  assignment?: string;
  access?: Access;
  release?: { available_from?: string };
}

export interface HandinFile {
  name: string;
  exercise?: string;
  file?: string;
}

export interface PublishedAssignment {
  id: string;
  title?: string;
  description?: string;
  deadline?: string | null;
  team?: { min: number; max: number; count?: number };
  handin?: { files?: HandinFile[] };
  items?: string[];
  access?: Access;
}

/** `/tp/<id>.json`: the statement and the templates, fetched when opened. */
export interface ExerciseDetail {
  statement: string;
  files: { name: string; template?: string }[];
  /** Set by the client when the fetch failed: NOT a property of the exercise. */
  offline?: boolean;
}

/** `/quiz/<id>.json` */
export interface QuizPayload {
  questions: { id: string; label: string; group: string }[];
}

// --- /submit and /r/<id> -----------------------------------------------------

export interface SubmissionBody {
  key: string;
  exercise_id: string;
  files?: Record<string, string>;
  answers?: Record<string, string>;
}

export type VerdictStatus =
  | "ok"
  | "forbidden_include"
  | "compile_error"
  | "compile_timeout"
  | "link_error"
  | "memory_error"
  | "timeout"
  | "error";

export interface FailedCase {
  case: number;
  reason: string;
  stdin?: string;
  stdout?: string;
  stderr?: string;
  /** The numbers the judge actually read out of the output. */
  nombres?: (string | number)[];
}

export interface WrongAnswer {
  id: string;
  label: string;
  given?: string;
  hint?: string;
}

/** `state: "done"` -- the verdict itself. */
export interface Verdict {
  state: "done";
  status: VerdictStatus;
  kind: ExerciseMode;
  message?: string;
  gcc?: string;
  warnings?: string;
  passed?: number;
  total?: number;
  cases?: FailedCase[];
  failed?: string[];
  wrong?: WrongAnswer[];
  /** Set by the worker on any verdict it refuses to cache: do not keep it. */
  rejouer?: boolean;
}

export type PollResult =
  | Verdict
  | { state: "running" }
  | { state: "queued"; position: number; eta?: number }
  | { state: "error"; error?: string };

// --- Account -----------------------------------------------------------------

export type ExerciseStatus = "solved" | "attempted";

export interface StatesPayload {
  states: { exercise_id: string; status: ExerciseStatus }[];
}

export interface PracticeRow {
  exercise_id: string;
  attempts: number;
  successes: number;
}

export interface PracticePayload {
  practice: PracticeRow[];
}

export interface DraftPayload {
  /** `null` is a first visit, not an error. */
  sources: Record<string, string> | null;
}

export interface PreferencesPayload {
  /** `""` means "no choice recorded", which is NOT the same as a 503. */
  theme: string;
}

// --- /progres ----------------------------------------------------------------

export interface MasterySkill {
  id: string;
  band: "verifie" | "en-progression" | "a-consolider" | "non-verifie";
  passed: number;
  attempted: number;
  total: number;
}

export interface ProgressPayload {
  policy: string;
  xp: number;
  level: { rank: number; since: number; next: number | null; remaining: number };
  exercises: { total: number; practiced: number; solved: number };
  skills: { id: string; practiced: number; solved: number; total: number }[];
  mastery: {
    bands: { id: string; title: string; description: string }[];
    skills: MasterySkill[];
  };
  achievements: {
    id: string;
    title: string;
    description: string;
    unlocked_at: string;
  }[];
  cards: number;
  next: { exercise_id: string; skill?: string } | null;
  practice_days: { date: string; attempts: number }[];
}

// --- /collection -------------------------------------------------------------

export interface Card {
  id: string;
  name: string;
  condition: string;
  held: boolean;
  /** `null` means "too few accounts to say" -- never print it as 0. */
  rarity: number | null;
}

export interface CollectionPayload {
  policy: string;
  cards: Card[];
  /** False under the minimum cohort: rarities are then withheld entirely. */
  cohort: boolean;
}

// --- /leaderboard ------------------------------------------------------------

export interface LeaderboardRow {
  rank: number;
  alias: string;
  solved: number;
  mine: boolean;
}

export interface LeaderboardPayload {
  group: number | null;
  window_days: number;
  cohort: number;
  minimum: number;
  participating: boolean;
  rows: LeaderboardRow[];
  me: { rank: number } | null;
  gap: { solved: number; rank: number } | null;
  alias?: string;
  scope: "group" | "course";
  moderator?: boolean;
  groups?: number[];
  division?: { id: string };
  divisions?: { id: string; title: string; accounts: number }[];
}

// --- Forum -------------------------------------------------------------------

export type Visibility = "thread" | "group" | "private";

export interface ForumMessage {
  id: string;
  text: string;
  created_at: string;
  /** "Vous", "Enseignant", a chosen name, or the masked alias. Never a `sub`. */
  author: string;
  group: number | null;
  reportable_name: boolean;
  mine: boolean;
  hidden: boolean;
  step?: string | null;
  blocked_kind?: string | null;
  visibility: Visibility;
  retained: boolean;
  /** Always the ROOT: the server flattens, so a thread is one level deep. */
  reply_to: string | null;
  upvotes: number;
  downvotes: number;
  my_vote: number;
}

export interface Legend {
  id: string;
  title: string;
}

export interface ThreadState {
  unanswered: number;
  answered: number;
  resolved: number;
}

export interface ThreadPayload {
  exercise_id: string;
  /** The server says which space this is; the page never re-derives it. */
  chat: boolean;
  moderator: boolean;
  max: number;
  messages: ForumMessage[];
  state: ThreadState | null;
  steps: Legend[];
  blocked_kinds: Legend[];
}

export interface ForumProfile {
  display_name: string | null;
  group_number: number | null;
  display_name_public: boolean;
  group_number_public: boolean;
  badges_public: boolean;
  leaderboard_opt_in: boolean;
  plate_frame: string | null;
  /** Drawn from a closed vocabulary server-side: nothing typed can reach it. */
  alias: string | null;
  max_display_name: number;
  group_numbers: number[];
  frames: { id: string; title: string }[];
  /** Rauthy's `preferred_username`, and it only ever PRE-FILLS. */
  suggestion: string;
}

/** What `POST /forum/profil` takes. A profile is rewritten IN FULL. */
export interface ForumProfileIn {
  display_name: string;
  group_number: string;
  display_name_public: boolean;
  group_number_public: boolean;
  badges_public: boolean;
  leaderboard_opt_in: boolean;
  plate_frame: string;
}

export interface SearchResult {
  id: string;
  exercise_id: string;
  extrait: string;
  replies: number;
  upvotes: number;
}

export interface ModerationPayload {
  reports: {
    id: string;
    exercise_id: string;
    text: string;
    created_at: string;
    report_count: number;
    hidden: boolean;
  }[];
  reported_names: {
    id: string;
    display_name: string | null;
    group_number: number | null;
    created_at: string;
    report_count: number;
  }[];
}

export interface HelpPayload {
  hours: number;
  rows: {
    exercise_id: string;
    step: string;
    blocked_kind: string | null;
    people: number;
    opened: number;
    since: string;
  }[];
}

export interface TopPayload {
  hours: number;
  rows: {
    id: string;
    exercise_id: string;
    text: string;
    upvotes: number;
    replies: number;
    visibility: Visibility;
    step?: string | null;
  }[];
}

// --- Teams -------------------------------------------------------------------

export interface TeamMember {
  /** THE POSITION, never the account: m1..m4. Presence and carets use it. */
  id: string;
  name: string;
  color: string;
  you: boolean;
}

export interface AssignmentView {
  id: string;
  title: string;
  description: string;
  items: string[];
  team: { min: number; max: number; count?: number };
  deadline: string | null;
  deadline_passed: boolean;
  access: Access;
  handin: HandinFile[];
}

export interface TeamContext {
  assignment: AssignmentView;
  team: {
    id: string;
    label: string;
    number: number;
    group_number: number;
    members: TeamMember[];
  };
  submission: { submitted_at?: string } | null;
}

export interface MyTeam {
  assignment_id: string;
  assignment_title: string;
  team_id: string;
  label: string;
  number: number;
  group_number: number;
  members: TeamMember[];
  joinable: boolean;
  access: Access;
  available_from?: string;
}

export interface AvailableTeams {
  assignment_id: string;
  group_number: number;
  /** The number of the team this account is on, or null. */
  mine: number | null;
  teams: {
    number: number;
    name: string;
    members: number;
    max: number;
    full: boolean;
  }[];
}

export interface TeamDocument {
  exercise_id: string;
  sources: Record<string, string>;
}

export interface TeamRevision {
  id: string;
  author: string;
  created_at: string;
  bytes: number;
}

// --- The Console (scratch) ---------------------------------------------------

export interface ScratchDraft {
  code: string;
  error?: string;
}

/** What `WS /scratch/live` sends. */
export type ScratchFrame =
  | { t: "queued"; position?: number; eta?: number }
  | { t: "ready" }
  | { t: "build"; d: string }
  | { t: "out"; d: string }
  | { t: "exit"; code: number; reason: string };
