// LE PREMIER SCRIPT DE LA PAGE, ET LE SEUL QUI TOURNE AVANT LE PREMIER RENDU.
// Il porte deux reglages de demarrage : le theme et l'adresse de l'API.
//
// IL EST EXTERNE ET PAS INLINE, ET C'EST DELIBERE. Servi par GitHub Pages, ce
// document ne peut porter aucun en-tete : sa CSP passe donc en <meta>, et un
// <meta> ne peut pas porter un hachage calcule sur le corps servi comme
// `csp()` le faisait. Le choix etait entre recopier un hachage a la main --
// qui se perime a la premiere virgule changee, en silence, et emporte le theme
// avec lui -- et n'avoir plus aucun script inline. La deuxieme option supprime
// le probleme au lieu d'ajouter un test pour le surveiller : `script-src
// 'self'` suffit, sans hachage, et un inline ajoute par distraction est ALORS
// bloque bruyamment.
//
// Charge SANS `defer` en tout debut de <head> : un <script src> classique
// bloque le rendu jusqu'a son execution, donc le theme est pose avant la
// premiere peinture exactement comme le faisait l'inline. Ce qu'il en coute est
// une requete sur une connexion deja ouverte, pour un fichier d'un kilo-octet.
try {
  var t = localStorage.getItem("ctester.theme");
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
} catch (e) {}

// L'ADRESSE DE L'API, UN SEUL ENDROIT. Pas de build, pas de substitution : ce
// que le dépôt contient est ce que le navigateur reçoit.
//
// La page part de GitHub Pages sous `tch009.thevhome.com` -- le nom que les
// étudiants connaissent, inchangé, donc leurs brouillons `localStorage` et la
// `redirect_uri` de Rauthy le sont aussi. Seule l'API déménage, sous un nom
// qu'elle seule connaît.
//
// `tch099` et non `api.tch009` : le certificat universel de Cloudflare couvre
// `thevhome.com` et `*.thevhome.com`, UNE seule étiquette. `api.tch009` en fait
// deux et n'aurait pas de certificat valide sans Advanced Certificate Manager.
window.CTESTER_API = (() => {
  const h = location.hostname;
  // LES DEUX ORIGINES DE LA PAGE pointent la meme API. `tch009` est le nom que
  // les etudiants connaissent, servi par GitHub Pages ; `github.io` est le
  // deploiement de preparation, qui sert a eprouver la page avant le DNS.
  if (h === "tch009.thevhome.com") return "https://tch099.thevhome.com";
  if (h.endsWith(".github.io")) return "https://tch099.thevhome.com";
  // Développement local : `app.py` sert encore la page, donc chemins relatifs.
  // C'est ce repli qui garde `CTESTER_PAGE=web python3 app/app.py` vivant, et
  // qui rend la bascule réversible en changeant une ligne.
  return "";
})();

// Le préfixe des appels d'API, et rien d'autre. Les modules chargés à la
// demande et les deux bibliothèques vendor sont sur Pages, à côté de cette
// page : ils restent relatifs, `charger()` ne change pas.
window.API = (chemin) => window.CTESTER_API ? window.CTESTER_API + "/" + chemin
                                            : chemin;
