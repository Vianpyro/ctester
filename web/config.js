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
