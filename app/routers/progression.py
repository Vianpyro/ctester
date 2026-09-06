"""La progression d'un compte : XP, niveau, compétences, succès, recommandation.

RIEN N'EST CALCULÉ PAR LE NAVIGATEUR. Tout arrive tout fait de cette route, qui
recalcule la projection à chaque appel depuis trois tables de faits en ajout
seul et le catalogue public. Une page qui calculerait son propre XP serait une
page où l'on se le donne depuis la console.

UNE PROJECTION ABSENTE N'EST PAS UN ZÉRO. Base en panne : 503 et aucun chiffre.
Annoncer « 0 XP » pendant une panne, c'est dire à quelqu'un que son travail a
disparu.

ponytail: six allers-retours SQL sérialisés derrière le verrou unique
d'`state.py`. Les regrouper en une lecture est faisable et pas fait -- à 27
étudiants la file derrière ce verrou est vide, et une requête groupée est plus
dure à relire. Le seuil est un p95 de cette route au-dessus d'une seconde, que
`charge.py` signale tout seul.
"""

import state
import headers
from deps import Sub
from fastapi import APIRouter
from services import catalogue, progression

router = APIRouter(tags=["progression"])


@router.get("/progres")
def progres(sub: Sub):
    faits = state.read_progress(sub)
    etats = state.read_states(sub)
    pratique = state.read_practice_summary(sub)
    # Les évidences de maîtrise, traitées comme le reste : muette -> 503, jamais
    # une bande « pas encore vérifié » qui serait le zéro déguisé d'une panne.
    evidences = state.read_events(sub, progression.VERIFICATION)
    if faits is None or etats is None or pratique is None or evidences is None:
        return headers.erreur(503, "la base ne répond pas")
    return progression.progress_payload(catalogue.exercices_ouverts(), faits,
                                        etats, pratique, evidences)
