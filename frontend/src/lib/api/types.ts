export interface Deployment {
  issuer?: string;
  client_id?: string;
  forum?: boolean;
  scratch?: boolean;
  discord?: string;
}

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
  verification?: boolean;
  bonus?: boolean;
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

export interface ExerciseDetail {
  statement: string;
  statement_format?: "typst";
  statement_pages?: number;
  statement_html?: boolean;
  files: { name: string; template?: string }[];
  offline?: boolean;
}

export interface PublishedQuestion {
  id: string;
  label: string;
  group: string;
  /** Set together, they place the question in a cell of its group's table. */
  row?: string;
  col?: string;
  type?: string;
  /** Characters the answer is expected to have; 0 when nobody said. */
  width?: number;
  options?: string[];
  prompts?: string[];
  template?: string;
  gaps?: string[][];
}

export interface QuizPayload {
  questions: PublishedQuestion[];
}

export interface SubmissionBody {
  key: string;
  exercise_id: string;
  files?: Record<string, string>;
  answers?: Record<string, string | string[] | Record<string, string>>;
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
  numbers?: (string | number)[];
  /** The same field in verdicts written before it was renamed. */
  nombres?: (string | number)[];
}

export interface WrongAnswer {
  id: string;
  label: string;
  given?: string;
  hint?: string;
}

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
  rerun?: boolean;
}

export type PollResult =
  | Verdict
  | { state: "running" }
  | { state: "queued"; position: number; eta?: number }
  | { state: "error"; error?: string };

export type ExerciseStatus = "solved" | "attempted";

export interface StatesPayload {
  states: { exercise_id: string; status: ExerciseStatus }[];
  moderator?: boolean;
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
  sources: Record<string, string> | null;
}

export interface PreferencesPayload {
  theme: string;
}

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

export interface Card {
  id: string;
  name: string;
  condition: string;
  held: boolean;
  rarity: number | null;
}

export interface CollectionPayload {
  policy: string;
  cards: Card[];
  cohort: boolean;
}

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

export type Visibility = "thread" | "group" | "private";

export interface ForumMessage {
  id: string;
  text: string;
  created_at: string;
  author: string;
  group: number | null;
  reportable_name: boolean;
  mine: boolean;
  hidden: boolean;
  step?: string | null;
  blocked_kind?: string | null;
  visibility: Visibility;
  retained: boolean;
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

export interface ActivityPayload {
  threads: Record<string, string>;
}

export interface ThreadPayload {
  exercise_id: string;
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
  alias: string | null;
  max_display_name: number;
  group_numbers: number[];
  frames: { id: string; title: string }[];
  suggestion: string;
}

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
  excerpt: string;
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

export interface TeamMember {
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

export interface ScratchDraft {
  code: string;
  header_name?: string;
  header?: string;
  error?: string;
}

export type ScratchFrame =
  | { t: "queued"; position?: number; eta?: number }
  | { t: "ready" }
  | { t: "running" }
  | { t: "build"; d: string }
  | { t: "out"; d: string }
  | { t: "exit"; code: number; reason: string };
