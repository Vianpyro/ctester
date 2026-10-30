import config


class Quota:
    """A token bucket refilled at `hourly` per hour. A sliding window made a student who spent
    the hour's quota in ten minutes of a lab wait for the rest of the hour."""

    def __init__(self, cooldown, hourly):
        self.cooldown = cooldown
        self.hourly = hourly
        self.seen = {}

    def check(self, who, now):
        tokens, last = self.seen.get(who, (self.hourly, None))
        if last is not None:
            if now - last < self.cooldown:
                return int(self.cooldown - (now - last)) + 1
            tokens = min(self.hourly, tokens + (now - last) * self.hourly / 3600)
        if tokens < 1:
            return int((1 - tokens) * 3600 / self.hourly) + 1
        self.seen[who] = (tokens - 1, now)
        if len(self.seen) > 5000:
            # An hour after its last request a bucket is full again, the same as a new one.
            self.seen = {k: v for k, v in self.seen.items() if v[1] > now - 3600}
        return 0


class Presence:
    def __init__(self):
        self.seen = {}

    def touch(self, who, now):
        self.seen[who] = now
        if len(self.seen) > 5000:
            self.seen = {k: v for k, v in self.seen.items()
                         if v > now - config.PRESENCE_TTL}
        return sum(1 for v in self.seen.values() if v > now - config.PRESENCE_TTL)
