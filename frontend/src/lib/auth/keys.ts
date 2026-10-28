export const TOKEN_KEY = "ctester.token";
export const REFRESH_KEY = "ctester.refresh";
export const EXPIRY_KEY = "ctester.expiry";
export const DEADLINE_KEY = "ctester.until";
export const PKCE_KEY = "ctester.pkce";
export const RETURN_KEY = "ctester.return";
// The state of a GitHub link in progress: a returning ?code= is GitHub's, not the sign-in's.
export const GITHUB_STATE_KEY = "ctester.github";

// Must match Rauthy's refresh_token_lifetime (240 h).
export const SESSION_MAX_DAYS = 10;
