"""In-memory counters: request quotas and presence.

ALL OF THIS IS PROCESS STATE, reset to zero when the container restarts. That
is why the API runs with a SINGLE worker: two processes means two counters,
and every quota would silently double. See `app/main.py`.
"""

import config


class Quota:
    """Sliding window in memory: {client: [timestamps]}.

    ponytail: reset on container restart, and a student switching networks
    starts fresh. Both are acceptable for a load regulator. Persist it the
    day someone turns it into a game.
    """

    def __init__(self, cooldown, hourly):
        self.cooldown = cooldown
        self.hourly = hourly
        self.seen = {}

    def check(self, who, now):
        """Returns the number of seconds to wait, or 0 if the submission passes.

        Records the hit ONLY if it passes: a student who hits the cooldown
        must not extend it by retrying.
        """
        hits = [t for t in self.seen.get(who, ()) if t > now - 3600]
        if hits and now - hits[-1] < self.cooldown:
            return int(self.cooldown - (now - hits[-1])) + 1
        if len(hits) >= self.hourly:
            return int(3600 - (now - hits[0])) + 1
        hits.append(now)
        self.seen[who] = hits
        if len(self.seen) > 5000:
            self.seen = {
                k: v for k, v in self.seen.items() if v and v[-1] > now - 3600
            }
        return 0


class Presence:
    """Who has an open window, roughly: {window token -> last seen at}.

    ponytail: in memory, reset on restart, and the token comes from the
    browser so it is falsifiable. This is a counter displayed to everyone, not
    a control -- authenticate or persist it the day the number matters.
    """

    def __init__(self):
        self.seen = {}

    def touch(self, who, now):
        """Records this heartbeat and returns how many windows are alive."""
        self.seen[who] = now
        if len(self.seen) > 5000:
            self.seen = {k: v for k, v in self.seen.items()
                         if v > now - config.PRESENCE_TTL}
        return sum(1 for v in self.seen.values() if v > now - config.PRESENCE_TTL)
