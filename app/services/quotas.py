"""Les compteurs en mémoire : quotas de requêtes et présence.

TOUT CECI EST DE L'ÉTAT DE PROCESSUS, remis à zéro au redémarrage du conteneur.
C'est pour ça que l'API tourne avec UN SEUL worker : deux processus, c'est deux
compteurs, et chaque quota serait doublé en silence. Voir `app/main.py`.
"""

import config


class Quota:
    """Fenêtre glissante en mémoire : {client: [horodatages]}.

    ponytail: remise à zéro au redémarrage du conteneur, et un étudiant qui
    change de réseau repart à neuf. Les deux sont acceptables pour un régulateur
    de charge. Persister le jour où quelqu'un en fait un jeu.
    """

    def __init__(self, cooldown, hourly):
        self.cooldown = cooldown
        self.hourly = hourly
        self.seen = {}

    def check(self, who, now):
        """Retourne le nombre de secondes à attendre, ou 0 si la soumission passe.

        Enregistre le passage UNIQUEMENT si elle passe : un étudiant qui se
        heurte au cooldown ne doit pas le rallonger en réessayant.
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
    """Qui a une fenêtre ouverte, à la louche : {jeton de fenêtre -> vu à}.

    ponytail: en mémoire, RAZ au redémarrage, et le jeton vient du navigateur
    donc falsifiable. C'est un compteur affiché à tout le monde, pas un
    contrôle -- l'authentifier ou le persister le jour où le chiffre compte.
    """

    def __init__(self):
        self.seen = {}

    def touch(self, who, now):
        """Enregistre ce battement et retourne combien de fenêtres sont vivantes."""
        self.seen[who] = now
        if len(self.seen) > 5000:
            self.seen = {k: v for k, v in self.seen.items()
                         if v > now - config.PRESENCE_TTL}
        return sum(1 for v in self.seen.values() if v > now - config.PRESENCE_TTL)
