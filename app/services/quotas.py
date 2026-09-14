import config


class Quota:
    def __init__(self, cooldown, hourly):
        self.cooldown = cooldown
        self.hourly = hourly
        self.seen = {}

    def check(self, who, now):
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
    def __init__(self):
        self.seen = {}

    def touch(self, who, now):
        self.seen[who] = now
        if len(self.seen) > 5000:
            self.seen = {k: v for k, v in self.seen.items()
                         if v > now - config.PRESENCE_TTL}
        return sum(1 for v in self.seen.values() if v > now - config.PRESENCE_TTL)
