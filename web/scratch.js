// LA CONSOLE : un terminal C interactif, chargé À LA DEMANDE et seulement
// pour un compte connecté sur un déploiement qui l'offre (`oidc.scratch`). Le
// parcours anonyme n'en télécharge pas un octet -- `test_page.js` le vérifie.
//
// SENS UNIQUE, JAMAIS DE CYCLE : ce fichier lit `window.ctester` et y dépose
// ses propres entrées ; il n'appelle `app.js` qu'à travers ce que ce contexte
// lui donne.
//
// IL A SON PROPRE ÉDITEUR, ET NE TOUCHE JAMAIS `#code`. L'éditeur d'exercice
// appartient à `currentId`, à son brouillon et, sur un devoir, au CRDT
// d'équipe ; y écrire depuis ici mettrait un second propriétaire sur le
// curseur et ferait attribuer un bout de bloc-notes à un exercice.
//
// LA SOCKET EST LA SESSION. Il n'y a pas de trame « arrête » : fermer la vue
// ferme la socket, le serveur relâche son verrou, et le worker détruit le
// conteneur. Un seul chemin de code, et il marche aussi quand l'onglet meurt
// sans prévenir.
(function (ctester) {
const $ = ctester.$;

// Ce que le serveur dit en fermant. Un étudiant dont la session a expiré et un
// étudiant qui arrive pendant que quelqu'un d'autre occupe la Console ne
// doivent pas lire la même chose.
const FERMETURES = {
  4401: "Ta session a expiré. Reconnecte-toi pour utiliser la Console.",
  4403: "Origine refusée.",
  4429: "Tu as déjà une session ouverte, ou tu en as lancé beaucoup :"
        + " attends un instant.",
  4400: "La Console n'a pas pu démarrer. Recharge la page.",
  4503: "La Console ne répond pas en ce moment. Réessaie dans une minute.",
};

// Pourquoi le programme s'est arrêté. `exited` n'est pas là : un programme qui
// se termine normalement n'a rien à expliquer, on affiche son code de sortie.
const RAISONS = {
  cpu: "Ton programme a utilisé tout son temps de calcul — boucle infinie ?",
  timeout: "La session a atteint sa durée maximale.",
  idle: "Session fermée : plus rien ne se passait.",
  output: "Ton programme a écrit beaucoup trop de texte — boucle infinie ?",
  compile_error: "La compilation a échoué (voir ci-dessus).",
  compile_timeout: "La compilation a été trop longue.",
  worker: "Le service de compilation s'est interrompu. Réessaie.",
  api: "Session interrompue.",
};

const GABARIT = '#include <stdio.h>\n\nint main(void)\n{\n'
  + '    printf("Bonjour !\\n");\n    return 0;\n}\n';

let bati = false;         // le DOM de la vue est-il déjà construit ?
let socket = null;        // la session en cours, ou null
let enregistre = null;    // le minuteur d'enregistrement du bloc-notes
let dernierCode = null;   // ce que le serveur a déjà, pour ne pas le réécrire

function node(tag, className, text) {
  const n = document.createElement(tag);
  if (className) n.className = className;
  if (text !== undefined) n.textContent = text;
  return n;
}

// --- Le terminal ---------------------------------------------------------------
// `textContent`, JAMAIS `innerHTML` : ce qui arrive ici est la sortie d'un
// programme écrit par un étudiant, c'est-à-dire une chaîne parfaitement
// arbitraire. C'est la même règle que pour les verdicts du juge dans `app.js`.

function ecrire(texte, classe) {
  const zone = $("scratchout");
  const bout = node("span", classe || "", texte);
  zone.append(bout);
  // Le terminal suit le bas, comme tout terminal.
  if (zone.scrollHeight !== undefined) zone.scrollTop = zone.scrollHeight;
}

function annoncer(texte, rate) {
  const ligne = $("scratchetat");
  ligne.textContent = texte || "";
  ligne.className = rate ? "scratchetat rate" : "scratchetat";
}

function occupe(actif) {
  $("scratchgo").disabled = actif;
  $("scratchgo").textContent = actif ? "En cours…" : "Lancer";
  $("scratchstop").hidden = !actif;
  $("scratchsaisie").disabled = !actif;
  $("scratchenvoi").disabled = !actif;
  $("scratcheof").disabled = !actif;
}

// --- La coloration -------------------------------------------------------------
// LA GRAMMAIRE VIENT DU NOYAU (`ctester.colorierC`), pas d'une seconde copie :
// c'est le même C, et deux expressions rationnelles à tenir synchronisées, c'est
// une qui dérive. Ce qui reste ici est le câblage, parce que ce sont d'autres
// nœuds -- l'éditeur de la Console ne touche JAMAIS `#code`.
//
// SEUL `innerHTML` DE CE FICHIER, et il reçoit la sortie de `colorierC()`, qui
// échappe chaque tranche. Ce que l'étudiant tape n'y arrive jamais brut.
let lignesAffichees = -1;

function peindre() {
  const texte = $("scratchcode").value;
  $("scratchhlcode").innerHTML = ctester.colorierC(texte);
  const n = texte.split("\n").length;
  if (n !== lignesAffichees) {
    lignesAffichees = n;
    let s = "";
    for (let i = 1; i <= n; i++) s += i + "\n";
    $("scratchgutter").textContent = s;
  }
  // LES TROIS TEXTES SUIVENT LE MÊME DÉFILEMENT, sinon les couleurs restent en
  // haut pendant qu'on tape en bas.
  $("scratchhl").scrollTop = $("scratchcode").scrollTop;
  $("scratchgutter").scrollTop = $("scratchcode").scrollTop;
  $("scratchhl").scrollLeft = $("scratchcode").scrollLeft;
}

// --- Le bloc-notes, enregistré SUR LE COMPTE -----------------------------------

async function charger() {
  const reponse = await ctester.compte.getJson("scratch/draft");
  // UNE BASE MUETTE N'EST PAS UN BLOC-NOTES VIDE. Écraser l'éditeur avec ""
  // au premier hoquet de Postgres effacerait le travail de quelqu'un ; on
  // laisse alors ce qui est à l'écran et on le dit.
  if (!reponse || reponse.error) {
    annoncer("Ton bloc-notes n'a pas pu être chargé — ce qui est à l'écran"
             + " reste là.", true);
    return;
  }
  dernierCode = reponse.code || "";
  $("scratchcode").value = dernierCode || GABARIT;
  peindre();
}

function enregistrer() {
  if (enregistre) clearTimeout(enregistre);
  enregistre = setTimeout(async () => {
    const code = $("scratchcode").value;
    // Rien à dire au serveur si rien n'a changé : la Console est un
    // bloc-notes, on y tape beaucoup et on y enregistre peu.
    if (code === dernierCode) return;
    dernierCode = code;
    await ctester.compte.sendJson("scratch/draft", "PUT", { code });
  }, 1500);
}

// --- La session ----------------------------------------------------------------

function lancer() {
  if (socket) return;
  const code = $("scratchcode").value;
  if (!code.trim()) {
    annoncer("Il n'y a encore rien à exécuter : écris ou colle ton programme.",
             true);
    return;
  }
  $("scratchout").textContent = "";
  annoncer("Connexion…");
  occupe(true);

  let ouvert;
  try {
    ouvert = new WebSocket(ctester.socketUrl("/scratch/live"));
  } catch (e) {
    annoncer("La Console n'a pas pu s'ouvrir.", true);
    occupe(false);
    return;
  }
  socket = ouvert;

  ouvert.onopen = () => {
    // LE JETON DANS LA PREMIÈRE TRAME, JAMAIS DANS L'URL : un navigateur ne
    // peut pas poser d'`Authorization` sur une WebSocket, et un jeton en
    // paramètre d'URL est un jeton dans tous les journaux de proxy du chemin.
    ouvert.send(JSON.stringify({ t: "hello", token: ctester.token(), code }));
  };

  ouvert.onmessage = (event) => {
    let trame;
    try {
      trame = JSON.parse(event.data);
    } catch (e) {
      return;
    }
    if (!trame || typeof trame !== "object") return;
    if (trame.t === "queued") {
      annoncer(trame.position
        ? "Dans la file : " + trame.position + (trame.eta
            ? " — environ " + Math.ceil(trame.eta / 60 * 10) / 10 + " min"
            : "")
        : "En attente…");
    } else if (trame.t === "ready") {
      annoncer("Compilation…");
    } else if (trame.t === "build") {
      // Les diagnostics de gcc, distingués de la sortie du programme : c'est
      // pour ça que le worker coupe le flux sur son marqueur de phase.
      ecrire(trame.d, "gccsortie");
    } else if (trame.t === "out") {
      annoncer("En cours — ton programme tourne.");
      ecrire(trame.d);
    } else if (trame.t === "exit") {
      const pourquoi = RAISONS[trame.reason];
      annoncer(pourquoi || ("Terminé (code " + trame.code + ")."),
               !!pourquoi && trame.reason !== "exited");
    }
  };

  ouvert.onclose = (event) => {
    if (socket === ouvert) socket = null;
    const dit = FERMETURES[event && event.code];
    if (dit) annoncer(dit, true);
    occupe(false);
    $("scratchsaisie").value = "";
  };

  ouvert.onerror = () => {
    annoncer("La connexion à la Console a été perdue.", true);
  };
}

function envoyer() {
  const champ = $("scratchsaisie");
  const texte = champ.value;
  if (!socket) return;
  // LE SAUT DE LIGNE EST AJOUTÉ ICI, et c'est ce que `scanf` attend. Sans lui
  // le programme resterait bloqué sur une entrée que l'étudiant croit avoir
  // envoyée -- l'erreur qui fait passer un terminal pour cassé.
  socket.send(JSON.stringify({ t: "stdin", d: texte + "\n" }));
  // L'ÉCHO EST LOCAL. Le programme ne réaffiche pas ce qu'on lui donne (il n'y
  // a pas de terminal pour le faire), donc sans cette ligne l'étudiant ne
  // verrait jamais ce qu'il a répondu.
  ecrire(texte + "\n", "scratchecho");
  champ.value = "";
}

function finEntree() {
  if (socket) socket.send(JSON.stringify({ t: "eof" }));
  ecrire("(fin de l'entrée)\n", "scratchecho");
}

function arreter() {
  // FERMER LA SOCKET EST L'ARRÊT. Le serveur relâche son verrou, le noyau le
  // dit au worker, le conteneur meurt -- un seul chemin, celui qui marche
  // aussi quand l'onglet disparaît sans prévenir.
  if (socket) socket.close();
  socket = null;
}

// --- La vue --------------------------------------------------------------------

function batir() {
  const vue = $("viewscratch");
  const titre = node("h2", "", "Console");
  titre.id = "scratchtitle";
  vue.append(titre);

  const intro = node("p", "explique",
    "Écris un programme C, lance-le, et réponds-lui quand il demande quelque"
    + " chose. Rien de ce qui se passe ici ne compte dans ta progression :"
    + " c'est un brouillon pour essayer.");
  vue.append(intro);

  const cadre = node("div", "plan scratchpan");
  cadre.append(node("div", "phead", "Ton programme"));

  // LA MÊME STRUCTURE QUE L'ÉDITEUR D'EXERCICE, aux mêmes classes : gouttière,
  // puis `.hl` coloré sous un `.codein` au texte transparent. Les métriques
  // sont définies UNE fois dans la feuille (`.hl, .codein`) -- les recopier ici
  // ferait dériver les deux éditeurs d'un pixel, et les couleurs se décaleraient
  // du texte sans que rien ne le dise.
  const enveloppe = node("div", "edwrap scratchedit");
  const gouttiere = node("pre", "gutter", "");
  gouttiere.id = "scratchgutter";
  gouttiere.setAttribute("aria-hidden", "true");
  const panneau = node("div", "pane");
  const couche = node("pre", "hl", "");
  couche.id = "scratchhl";
  couche.setAttribute("aria-hidden", "true");
  const colore = document.createElement("code");
  colore.id = "scratchhlcode";
  couche.append(colore);
  const zone = document.createElement("textarea");
  zone.id = "scratchcode";
  zone.className = "codein";
  zone.spellcheck = false;
  zone.placeholder = "// Écris ton programme C ici";
  panneau.append(couche, zone);
  enveloppe.append(gouttiere, panneau);
  cadre.append(enveloppe);
  vue.append(cadre);

  const barre = node("div", "scratchbarre");
  const go = node("button", "", "Lancer");
  go.id = "scratchgo";
  go.type = "button";
  const stop = node("button", "nav", "Arrêter");
  stop.id = "scratchstop";
  stop.type = "button";
  stop.hidden = true;
  const etat = node("span", "scratchetat", "");
  etat.id = "scratchetat";
  barre.append(go, stop, etat);
  vue.append(barre);

  const terminal = node("div", "plan scratchpan");
  terminal.append(node("div", "phead", "Sortie"));
  const sortie = node("pre", "scratchterm", "");
  sortie.id = "scratchout";
  terminal.append(sortie);
  const ligne = node("div", "scratchsaisiebarre");
  const champ = document.createElement("input");
  champ.id = "scratchsaisie";
  champ.type = "text";
  champ.disabled = true;
  champ.placeholder = "Réponds à ton programme, puis Entrée";
  const envoi = node("button", "nav", "Envoyer");
  envoi.id = "scratchenvoi";
  envoi.type = "button";
  envoi.disabled = true;
  const eof = node("button", "nav", "Fin d'entrée");
  eof.id = "scratcheof";
  eof.type = "button";
  eof.disabled = true;
  ligne.append(champ, envoi, eof);
  terminal.append(ligne);
  vue.append(terminal);

  // LIÉS UNE SEULE FOIS : ce fichier n'est chargé qu'une fois, mais
  // `basculer()` est rappelée à chaque ouverture de la vue.
  go.addEventListener("click", lancer);
  stop.addEventListener("click", arreter);
  envoi.addEventListener("click", envoyer);
  eof.addEventListener("click", finEntree);
  champ.addEventListener("keydown", (e) => {
    if (e && e.key === "Enter") envoyer();
  });
  zone.addEventListener("input", () => {
    peindre();
    enregistrer();
  });
  // TAPER N'EST PAS LA SEULE FAÇON DE DÉFILER : la molette, une sélection
  // tirée au clavier, un collage. Sans ça les couleurs décrochent du texte.
  zone.addEventListener("scroll", peindre);
  bati = true;
}

async function basculer() {
  if (ctester.vue() === "scratch") {
    // QUITTER LA VUE FERME LA SESSION. Sans ça, un conteneur survivrait à un
    // changement d'écran et tiendrait un cœur du serveur pendant que
    // l'étudiant fait autre chose.
    arreter();
    ctester.afficherVue("");
    return;
  }
  if (!bati) batir();
  ctester.afficherVue("scratch");
  if (dernierCode === null) await charger();
}

ctester.scratch = {
  basculer: basculer,
  // Lues par le harnais, qui a besoin de savoir s'il reste une session ouverte.
  session: () => socket,
  quitter: arreter,
};
})(window.ctester);
