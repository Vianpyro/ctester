// « Discussions » : un fil d'entraide par exercice, pour les comptes connectés.
// Chargé AU CLIC, jamais avant -- l'anonyme n'en télécharge rien, et un
// étudiant connecté qui ne l'ouvre pas non plus. Même contrat que progres.js,
// mêmes raisons.
//
// SENS UNIQUE : ce fichier lit `window.ctester` et y dépose son entrée ; le
// noyau ne le connaît que par `ctester.forum`, jamais par un import.
//
// CE FICHIER NE DÉCIDE DE RIEN sur les droits. Qui est modérateur, quels
// messages sont visibles, qui a le droit de supprimer ou de masquer : tout est
// tranché par l'API à partir du `sub` authentifié. Le drapeau `moderateur` qui
// arrive ici ne sert qu'à savoir quoi DESSINER -- chaque route le recalcule.
//
// LA MODÉRATION EST HUMAINE, ET LA PAGE LE DIT. Aucun texte d'ici ne promet
// qu'une solution partagée serait détectée automatiquement : elle ne le serait
// pas. C'est ce qui rend le bouton « Signaler » utile plutôt que décoratif.
(function (ctester) {
const $ = ctester.$;

// LA CHARTE, EN UN SEUL ENDROIT. Elle s'affiche dans la vue ET avant la
// première publication de la session ; deux copies du texte finiraient par se
// contredire, et c'est la copie oubliée qu'on lirait au moment qui compte.
const CHARTE = [
  "Entraide conceptuelle : une question, une idée, ce que tu observes, "
  + "ce que tu as déjà essayé.",
  "Pas de solution complète, pas d'extrait de code, aucun fichier déposé.",
  "Pas de capture d'écran.",
  "Pas de lien vers une solution — un lien vers un corrigé sera masqué.",
  "Respect mutuel : on parle du problème, jamais de la personne.",
  "Tu vois passer une solution ? Signale-la plutôt que d'y répondre.",
];

const CHARTE_VUE = "ctester.charte";

// --- Le rendu, et c'est la partie qui compte -------------------------------
// LES MESSAGES SONT DU MARKDOWN RESTREINT, STOCKÉS SOUS LEUR FORME SOURCE. Le
// serveur ne rend rien et n'assainit rien : il borne. Tout le rendu se fait
// ici, à CHAQUE affichage -- le fil, l'aperçu de rédaction, et la file de
// modération. Assainir une seule fois, à l'écriture, aurait laissé les messages
// déjà en base hors de portée de toute règle resserrée ensuite.
//
// DEUX BARRIÈRES, DANS CET ORDRE :
//   1. le HTML brut est ÉCHAPPÉ AVANT l'analyse Markdown, donc `marked` ne voit
//      jamais une balise et n'en émet jamais une qui vienne d'un étudiant ;
//   2. la sortie de `marked` passe par DOMPurify avec une allow-list fermée.
// La CSP du document est une troisième couche, et elle n'est pas la défense
// principale : ce sont ces deux-ci.
const MARKED = "vendor/marked-18.0.11.umd.js";
const PURIFY = "vendor/purify-3.4.14.min.js";

// L'ALLOW-LIST. Rien d'autre ne survit : ni `style`, `class`, `id` ou
// événement, ni SVG, MathML, image, média, iframe, formulaire ou élément
// personnalisé. `pre` n'y est pas non plus -- pas de bloc de code rendu, un
// bloc clôturé retombe donc en texte.
const BALISES = ["p", "br", "strong", "em", "ul", "ol", "li", "blockquote",
                 "code", "a"];
// `href` pour les liens, `rel` parce que le crochet ci-dessous l'écrit. Pas de
// `target` : un lien du forum n'ouvre pas de cible nommée.
const ATTRIBUTS = ["href", "rel"];
const NETTOYAGE = {
  ALLOWED_TAGS: BALISES,
  ALLOWED_ATTR: ATTRIBUTS,
  // http(s) ABSOLUS SEULEMENT. Tout le reste -- `javascript:`, `data:`,
  // `vbscript:`, un relatif -- perd son `href` et retombe en texte.
  ALLOWED_URI_REGEXP: /^https?:\/\//i,
  ALLOW_DATA_ATTR: false,
  ALLOW_ARIA_ATTR: false,
  ALLOW_UNKNOWN_PROTOCOLS: false,
};

const MARKDOWN = { gfm: true, breaks: true };

// AVANT L'ANALYSE, PAS APRÈS. Un `<` qui n'atteint jamais l'analyseur ne peut
// pas en ressortir en balise, quelle que soit la subtilité de l'extension
// Markdown du jour.
//
// `<` SEULEMENT, ET C'EST EXACT : une balise HTML commence par `<`, y compris
// un commentaire (`<!--`) et une instruction de traitement. Échapper AUSSI `>`
// a été essayé et tuait la citation Markdown (`> comme ceci`), qui est dans
// l'allow-list -- on aurait retiré une fonctionnalité annoncée pour un gain
// nul. `marked` échappe lui-même les `>` du texte qu'il rend. `&` n'est pas
// touché non plus : le toucher casserait les entités qu'un étudiant écrit à la
// main, et une entité est du texte, pas une balise.
const echapper = (s) => s.replace(/</g, "&lt;");

let bibliotheques = null;
let rendu = false;       // le Markdown est-il réellement disponible ?

function chargerBibliotheques() {
  if (!bibliotheques) {
    bibliotheques = Promise.all([ctester.charger(MARKED), ctester.charger(PURIFY)])
      // ON OUBLIE L'ÉCHEC, comme le chargeur du noyau : une coupure d'une
      // seconde ne doit pas condamner le rendu pour toute la visite.
      .catch((e) => { bibliotheques = null; throw e; });
  }
  return bibliotheques;
}

let crochetPose = false;

function assainisseur() {
  const p = window.DOMPurify;
  // `isSupported` est faux quand DOMPurify n'a pas trouvé de vrai DOM. Dans cet
  // état, `sanitize()` REND SON ENTRÉE TELLE QUELLE -- s'en servir reviendrait
  // à écrire le HTML d'un étudiant dans la page sans le moindre filtre. On
  // préfère ne pas rendre de Markdown du tout.
  if (!p || !p.isSupported || typeof p.sanitize !== "function") return null;
  if (!crochetPose && typeof p.addHook === "function") {
    crochetPose = true;
    // `rel` POSÉ ICI ET PAS ESPÉRÉ DE L'AUTEUR : un lien du forum sort toujours
    // avec `noopener noreferrer`, et jamais avec une cible nommée -- `target`
    // n'est de toute façon pas dans l'allow-list, ceci le dit deux fois.
    p.addHook("afterSanitizeAttributes", (node) => {
      if (node.tagName === "A") {
        node.setAttribute("rel", "noopener noreferrer");
        node.removeAttribute("target");
      }
    });
  }
  return p;
}

function rendreMarkdown(cible, source) {
  // LE TEXTE BRUT D'ABORD, TOUJOURS. Si une bibliothèque manque, si l'analyse
  // lève, si l'assainisseur n'est pas utilisable : ce qui reste à l'écran est
  // du texte, jamais du HTML non filtré.
  cible.textContent = source;
  const purify = assainisseur();
  const md = window.marked;
  if (!purify || !md || typeof md.parse !== "function") return false;
  let propre;
  try {
    propre = purify.sanitize(md.parse(echapper(source), MARKDOWN), NETTOYAGE);
  } catch (e) {
    return false;
  }
  cible.textContent = "";
  // LE SEUL `innerHTML` DE TOUT LE CLIENT, et il reçoit la sortie de
  // l'assainisseur À L'INSTANT MÊME : pas de variable qui traîne, pas de
  // concaténation, pas de cache. Ce qui est écrit est ce que DOMPurify vient
  // de rendre, sur cette source-là.
  cible.innerHTML = propre;
  return true;
}

// L'état de la vue. `fil === null` avec une `erreur` veut dire « on ne sait
// pas » : ça ne s'affiche jamais comme un fil vide. Annoncer « aucun message »
// pendant une panne, c'est faire croire que personne n'a répondu.
let fil = null;
let signalements = null;
let nomsSignales = null;
// Le profil de CE compte : le nom qu'il s'est donné, son équipe, et ce qu'il a
// choisi d'afficher. `null` tant qu'on ne l'a pas lu -- on n'invente pas un
// profil vide, ça reviendrait à annoncer « tu n'as pas de nom » pendant une
// panne.
let profil = null;
let moderateur = false;
let maxTexte = 0;
let erreur = "";
let annonce = "";
let exercice = "";
let saisie = "";
let titre = null;
let zone = null;
let apercu = null;
// Le champ « Nom affiché » de la vue courante, pour que « Mon identité » du
// menu Compte y amène le focus. Une RÉFÉRENCE et pas un getElementById : le
// bloc n'existe pas toujours (panne de lecture du profil).
let champPseudo = null;

// --- Réseau ---------------------------------------------------------------

function exerciceCourant() {
  const cat = ctester.catalogue();
  const vise = exercice || ctester.exerciceOuvert() || $("ex").value;
  const trouve = cat.find(t => t.id === vise) || cat[0];
  return trouve ? trouve.id : "";
}

const INDISPO = "Les discussions ne sont pas disponibles pour l'instant. "
              + "L'exercice et le bouton « Tester », eux, fonctionnent "
              + "normalement.";

async function charger(id) {
  fil = null;
  signalements = null;
  nomsSignales = null;
  exercice = id;
  if (!ctester.compte) {
    erreur = "Reconnecte-toi pour ouvrir les discussions.";
    return;
  }
  if (!id) {
    erreur = "Aucun exercice n'est publié pour l'instant.";
    return;
  }
  const reponse = await ctester.compte.getJson(
    "forum?ex=" + encodeURIComponent(id));
  if (!reponse || !Array.isArray(reponse.messages)) {
    erreur = INDISPO;
    return;
  }
  fil = reponse.messages;
  moderateur = !!reponse.moderateur;
  maxTexte = reponse.max || 0;
  erreur = "";
  // La file de signalements n'est demandée QUE par un modérateur, et le
  // serveur la refuse à tout le monde d'autre : ce test-ci évite un 403
  // inutile, il ne protège rien à lui seul.
  if (moderateur) {
    const file = await ctester.compte.getJson("forum/moderation");
    signalements = file && Array.isArray(file.signalements)
      ? file.signalements : null;
    nomsSignales = file && Array.isArray(file.noms) ? file.noms : null;
  }
  await chargerProfil();
}

// LE PROFIL SE LIT SEUL. « Mon identité » s'ouvre depuis le menu Compte, sans
// fil ni exercice : le charger avec le fil aurait rendu le réglage dépendant
// d'une vue qu'on n'a pas forcément ouverte.
async function chargerProfil() {
  if (!ctester.compte) return;
  const mien = await ctester.compte.getJson("forum/profil");
  profil = mien && typeof mien === "object" ? mien : null;
}

// Le message d'erreur de l'API est REPRIS TEL QUEL quand il y en a un :
// « message trop long », « trop de messages d'un coup ». Le remplacer par
// « échec » ferait recommencer quelqu'un à l'identique.
function pourquoi(reponse, defaut) {
  if (!reponse) return "le serveur est injoignable";
  if (reponse.corps && reponse.corps.error) return reponse.corps.error;
  return defaut + " (réponse " + reponse.status + ")";
}

async function ecrire(chemin, methode, charge, succes, echec) {
  const reponse = await ctester.compte.sendJson(chemin, methode, charge);
  const ok = !!(reponse && reponse.ok);
  annonce = ok ? succes : echec + " : " + pourquoi(reponse, "refusé");
  if (ok) await charger(exercice);
  dessiner();
  return ok;
}

async function publier(texte) {
  const ok = await ecrire("forum", "POST", { tp: exercice, texte: texte },
                          "Message publié.", "Message non publié");
  // VIDER APRÈS COUP, ET SEULEMENT SI C'EST PARTI. `ecrire` a déjà redessiné,
  // donc `zone` est le nouveau champ. Un refus -- message trop long, quota --
  // doit laisser le texte à l'écran : le perdre ferait retaper la même chose à
  // quelqu'un qui n'a plus la règle sous les yeux.
  if (ok) {
    saisie = "";
    if (zone) zone.value = "";
    if (apercu) rendreMarkdown(apercu, "");
  }
}

const supprimer = (id) => ecrire(
  "forum?id=" + encodeURIComponent(id), "DELETE", undefined,
  "Ton message a été supprimé.", "Suppression impossible");

const signaler = (id) => ecrire(
  "forum/signalement", "POST", { id: id },
  "Signalé. Un responsable du cours va le lire.", "Signalement impossible");

const signalerNom = (id) => ecrire(
  "forum/signalement", "POST", { id: id, quoi: "nom" },
  "Nom signalé. Un responsable du cours va le lire.", "Signalement impossible");

const effacerNom = (id) => ecrire(
  "forum/moderation", "POST", { id: id, action: "effacer-nom" },
  "Nom effacé.", "Action impossible");

// DEUX SURFACES POSSIBLES, UNE SEULE ÉCRITURE : le panneau du menu Compte, et
// le fil si on l'a ouvert (les noms affichés peuvent changer). `ecrire` ne
// suffisait plus -- il redessine la vue forum, qui n'est pas forcément là.
async function enregistrerProfil(charge) {
  const reponse = await ctester.compte.sendJson("forum/profil", "POST", charge);
  const ok = !!(reponse && reponse.ok);
  annonce = ok ? "Identité enregistrée."
               : "Identité non enregistrée : " + pourquoi(reponse, "refusé");
  await chargerProfil();
  if (ctester.vue() === "forum") {
    await charger(exercice);
    dessiner();
  }
  if (!$("identitepanneau").hidden) dessinerPanneau();
  return ok;
}

const moderer = (id, action) => ecrire(
  "forum/moderation", "POST", { id: id, action: action },
  action === "masquer" ? "Message masqué." : "Message rétabli.",
  "Action impossible");

// --- Rendu de la vue -------------------------------------------------------
// `textContent` pour TOUT ce qui n'est pas un message. Les messages, eux,
// passent par `rendreMarkdown` ci-dessus, et par rien d'autre.

function noeud(balise, classe, texte) {
  const n = document.createElement(balise);
  if (classe) n.className = classe;
  if (texte !== undefined) n.textContent = texte;
  return n;
}

function bouton(texte, classe, quoi) {
  const b = noeud("button", classe, texte);
  b.type = "button";
  b.addEventListener("click", quoi);
  return b;
}

function listeCharte() {
  const ul = noeud("ul", "regles");
  for (const regle of CHARTE) ul.append(noeud("li", "", regle));
  return ul;
}

// LA CHARTE AVANT LA PREMIÈRE PUBLICATION de la session, dans le même encart
// que le consentement de connexion. Une fois lue, elle ne réapparaît plus à
// chaque message -- elle reste sous les yeux dans la vue, plus haut.
function montrerCharte(ensuite) {
  const boite = $("charte");
  boite.innerHTML = "";
  boite.append(noeud("h2", "", "Avant de publier"));
  boite.append(listeCharte());
  boite.append(noeud("p", "", "Les messages sont lus et modérés par des "
    + "personnes, pas par un automate. Un message qui contient une solution "
    + "peut être masqué."));
  const rangee = noeud("div", "row");
  rangee.append(bouton("J'ai compris — publier", "", () => {
    boite.hidden = true;
    ctester.sessionSet(CHARTE_VUE, "1");
    ensuite();
  }));
  rangee.append(bouton("Annuler", "nav", () => { boite.hidden = true; }));
  boite.append(rangee);
  boite.hidden = false;
}

// Deux chiffres, comme sur un plan de cours : « 7 » s'affiche « 07 ».
const numeroEquipe = (n) => "équipe " + String(n).padStart(2, "0");

// MON IDENTITÉ. Le nom et l'équipe sont FACULTATIFS et INVISIBLES par défaut :
// cocher est un geste, ne rien faire reste l'anonymat. Le serveur revalide tout
// -- ce formulaire borne pour éviter un aller-retour, il n'autorise rien.
function monIdentite() {
  const bloc = noeud("div", "");
  bloc.append(noeud("h2", "", "Mon identité"));
  if (annonce) bloc.append(noeud("p", "annonce", annonce));
  if (profil === null) {
    bloc.append(noeud("p", "rate", "Ton identité n'a pas pu être lue."));
    bloc.append(fermeture());
    return bloc;
  }

  const nomId = "forumpseudo";
  const etiqNom = noeud("label", "", "Nom affiché (facultatif)");
  etiqNom.setAttribute("for", nomId);
  const champNom = noeud("input");
  champNom.id = nomId;
  champNom.type = "text";
  champNom.autocomplete = "off";
  champNom.maxLength = profil.max_pseudo || 24;
  // LA SUGGESTION DE RAUTHY NE SERT QU'À PRÉ-REMPLIR, et seulement tant qu'on
  // n'a pas choisi de nom. Elle n'est ni enregistrée ni affichée aux autres
  // avant un clic sur « Enregistrer » avec la case cochée : le nom d'ouverture
  // de session de quelqu'un ne se publie pas tout seul.
  champNom.value = profil.pseudo || profil.suggestion || "";
  champNom.placeholder = "Participant";
  champPseudo = champNom;

  const groupeId = "forumgroupe";
  const etiqGroupe = noeud("label", "", "Numéro d'équipe (1 à 99, facultatif)");
  etiqGroupe.setAttribute("for", groupeId);
  const champGroupe = noeud("input");
  champGroupe.id = groupeId;
  champGroupe.type = "number";
  champGroupe.min = "1";
  champGroupe.max = "99";
  champGroupe.value = profil.groupe === null || profil.groupe === undefined
    ? "" : String(profil.groupe);

  const [voirNom, ligneNom] = caseACocher(
    "forumvoirnom", "Afficher mon nom dans les discussions",
    profil.pseudo_public);
  const [voirGroupe, ligneGroupe] = caseACocher(
    "forumvoirgroupe", "Afficher mon numéro d'équipe",
    profil.groupe_public);

  bloc.append(etiqNom, champNom, etiqGroupe, champGroupe, ligneNom, ligneGroupe);
  // CE QUE LA CASE NE COUVRE PAS, ET IL FAUT LE DIRE : l'équipe du cours voit
  // le numéro d'équipe en tout temps. Le laisser croire l'inverse serait un
  // consentement obtenu de travers.
  if (!profil.pseudo && profil.suggestion) {
    bloc.append(noeud("p", "aide", "Nom proposé par ta connexion — modifie-le "
      + "si tu veux, il ne s'affiche qu'une fois enregistré et coché."));
  }
  bloc.append(noeud("p", "aide", "Décoché, rien de tout ça n'apparaît aux "
    + "autres. L'équipe du cours, elle, voit toujours ton numéro d'équipe — "
    + "jamais ton nom si tu ne l'affiches pas."));
  const rangee = noeud("div", "row");
  rangee.append(bouton("Enregistrer", "", () => enregistrerProfil({
    pseudo: champNom.value,
    groupe: champGroupe.value,
    pseudo_public: voirNom.checked,
    groupe_public: voirGroupe.checked,
  })));
  rangee.append(bouton("Fermer", "nav", fermerIdentite));
  bloc.append(rangee);
  return bloc;
}

function fermeture() {
  const rangee = noeud("div", "row");
  rangee.append(bouton("Fermer", "nav", fermerIdentite));
  return rangee;
}

function fermerIdentite() {
  annonce = "";
  champPseudo = null;
  $("identitepanneau").hidden = true;
}

function dessinerPanneau() {
  const boite = $("identitepanneau");
  boite.innerHTML = "";
  boite.append(monIdentite());
  boite.hidden = false;
}

function caseACocher(id, texte, coche) {
  const ligne = noeud("label", "coche");
  ligne.setAttribute("for", id);
  const boite = noeud("input");
  boite.id = id;
  boite.type = "checkbox";
  boite.checked = !!coche;
  ligne.append(boite, noeud("span", "", texte));
  return [boite, ligne];
}

function choixExercice() {
  const bloc = noeud("div", "bloc");
  const etiquette = noeud("label", "", "Exercice");
  etiquette.setAttribute("for", "forumex");
  const menu = document.createElement("select");
  menu.id = "forumex";
  for (const tp of ctester.catalogue()) {
    const option = document.createElement("option");
    option.value = tp.id;
    option.textContent = tp.group + " — " + (tp.short || tp.label);
    menu.append(option);
  }
  menu.value = exercice;
  menu.addEventListener("change", async () => {
    annonce = "";
    await charger(menu.value);
    dessiner();
  });
  bloc.append(etiquette, menu);
  return bloc;
}

function formulaire() {
  const bloc = noeud("div", "bloc");
  bloc.append(noeud("h3", "soustitre", "Poser une question"));
  const etiquette = noeud("label", "", "Ta question ou ton explication"
    + (maxTexte ? " (" + maxTexte + " caractères au plus)" : ""));
  etiquette.setAttribute("for", "forumtexte");
  zone = document.createElement("textarea");
  zone.id = "forumtexte";
  zone.value = saisie;
  zone.setAttribute("rows", "4");
  bloc.append(etiquette, zone);

  bloc.append(noeud("p", "aide", rendu
    ? "Mise en forme simple : **gras**, *italique*, listes, > citation, "
      + "`code court`. Le HTML n'est jamais interprété."
    : "Le rendu enrichi n'a pas pu être chargé : ton message part quand même, "
      + "et il s'affiche en texte brut."));

  if (rendu) {
    // L'APERÇU N'EST PAS `aria-live`. Annoncer chaque frappe à un lecteur
    // d'écran rendrait le champ inutilisable ; l'aperçu est une région
    // étiquetée, qu'on va lire quand on veut.
    const titreApercu = noeud("h4", "soustitre", "Aperçu");
    titreApercu.id = "forumapercutitre";
    apercu = noeud("div", "md apercu");
    apercu.setAttribute("role", "region");
    apercu.setAttribute("aria-labelledby", "forumapercutitre");
    rendreMarkdown(apercu, saisie);
    zone.addEventListener("input", () => {
      saisie = zone.value;
      rendreMarkdown(apercu, saisie);
    });
    bloc.append(titreApercu, apercu);
  } else {
    apercu = null;
    zone.addEventListener("input", () => { saisie = zone.value; });
  }

  bloc.append(bouton("Publier", "", () => {
    saisie = zone.value;
    const texte = saisie;
    if (ctester.sessionGet(CHARTE_VUE)) publier(texte);
    else montrerCharte(() => publier(texte));
  }));
  return bloc;
}

// L'HEURE DU LECTEUR, PAS CELLE DU SERVEUR. Celui-ci envoie l'instant en UTC
// (« ...T18:45Z ») ; seul le navigateur sait dans quel fuseau on le lit. Une
// chaîne qu'on n'arrive pas à relire s'affiche telle quelle -- un vieux message
// vaut mieux qu'un « Invalid Date ».
function quandLocal(instant) {
  const d = new Date(instant);
  if (isNaN(d.getTime())) return String(instant);
  return d.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
}

function corpsDuMessage(texte) {
  const corps = noeud("div", "texte md");
  rendreMarkdown(corps, texte);
  return corps;
}

function unMessage(m) {
  const item = document.createElement("li");
  item.className = "message";
  // L'AUTEUR EST UN MOT, PAS UN IDENTIFIANT : « Vous », « Participant » ou
  // « Équipe du cours », dérivés par le serveur. Rien ici ne permet de
  // recoller deux messages au même étudiant.
  const tete = noeud("p", "qui");
  tete.append(noeud("span", "auteur", m.auteur));
  if (m.groupe) tete.append(noeud("span", "equipe", numeroEquipe(m.groupe)));
  const quand = noeud("time", "quand", quandLocal(m.cree_le));
  quand.setAttribute("datetime", String(m.cree_le).replace(" ", "T"));
  tete.append(quand);
  // « Masqué » EN TOUTES LETTRES, pas seulement en gris : un état qui ne se
  // lit qu'à la couleur ne se lit pas du tout pour une partie des gens.
  if (m.masque) tete.append(noeud("span", "etat", "masqué"));
  item.append(tete, corpsDuMessage(m.texte));

  const actions = noeud("div", "row");
  if (m.mien) {
    actions.append(bouton("Supprimer mon message", "nav", () => supprimer(m.id)));
  } else {
    actions.append(bouton("Signaler", "nav", () => signaler(m.id)));
  }
  // ON NE SIGNALE QUE CE QUI S'AFFICHE : le bouton n'existe que sur un nom
  // choisi par quelqu'un d'autre. « Participant » n'est pas signalable, il n'y
  // a rien dedans.
  if (m.nom_signalable) {
    actions.append(bouton("Signaler le nom", "nav", () => signalerNom(m.id)));
  }
  if (moderateur) {
    actions.append(m.masque
      ? bouton("Rétablir", "nav", () => moderer(m.id, "retablir"))
      : bouton("Masquer", "nav", () => moderer(m.id, "masquer")));
  }
  item.append(actions);
  return item;
}

function leFil() {
  const bloc = noeud("div", "bloc");
  bloc.append(noeud("h3", "soustitre", "Le fil"));
  if (!fil.length) {
    bloc.append(noeud("p", "aide", "Personne n'a encore écrit sur cet "
      + "exercice. Une question bien posée en aide souvent plusieurs."));
    return bloc;
  }
  const liste = noeud("ul", "fil");
  for (const m of fil) liste.append(unMessage(m));
  bloc.append(liste);
  return bloc;
}

function fileModeration() {
  const bloc = noeud("div", "bloc second");
  bloc.append(noeud("h3", "soustitre", "Signalements"));
  if (signalements === null) {
    bloc.append(noeud("p", "rate",
      "La file de signalements n'a pas pu être lue."));
    return bloc;
  }
  if (!signalements.length) {
    bloc.append(noeud("p", "aide", "Aucun signalement en attente."));
    return bloc;
  }
  const liste = noeud("ul", "fil");
  for (const s of signalements) {
    const item = document.createElement("li");
    item.className = "message";
    const tete = noeud("p", "qui");
    tete.append(noeud("span", "auteur", s.exercice_id));
    tete.append(noeud("time", "quand", quandLocal(s.cree_le)));
    tete.append(noeud("span", "etat", s.signalements + " signalement"
      + (s.signalements > 1 ? "s" : "") + (s.masque ? " — masqué" : "")));
    // MÊME PIPELINE QU'AILLEURS. Un modérateur lit exactement ce qu'un étudiant
    // lit, assaini de la même façon : une vue de modération qui rendrait le
    // HTML brut « pour voir ce qu'il y a dedans » serait la page la plus facile
    // à attaquer du site, et celle dont l'attaque paierait le plus.
    item.append(tete, corpsDuMessage(s.texte));
    const actions = noeud("div", "row");
    actions.append(s.masque
      ? bouton("Rétablir", "nav", () => moderer(s.id, "retablir"))
      : bouton("Masquer", "nav", () => moderer(s.id, "masquer")));
    item.append(actions);
    liste.append(item);
  }
  bloc.append(liste);
  return bloc;
}

// LES NOMS SIGNALÉS, à côté des messages signalés et pas dedans : ce n'est pas
// le message qui pose problème, c'est le nom, et l'action n'est pas la même.
function fileNoms() {
  const bloc = noeud("div", "bloc second");
  bloc.append(noeud("h3", "soustitre", "Noms signalés"));
  if (nomsSignales === null) {
    bloc.append(noeud("p", "rate", "La file des noms n'a pas pu être lue."));
    return bloc;
  }
  if (!nomsSignales.length) {
    bloc.append(noeud("p", "aide", "Aucun nom signalé."));
    return bloc;
  }
  const liste = noeud("ul", "fil");
  for (const n of nomsSignales) {
    const item = document.createElement("li");
    item.className = "message";
    const tete = noeud("p", "qui");
    tete.append(noeud("span", "auteur", n.pseudo || "(nom déjà effacé)"));
    if (n.groupe) tete.append(noeud("span", "equipe", numeroEquipe(n.groupe)));
    tete.append(noeud("time", "quand", quandLocal(n.cree_le)));
    tete.append(noeud("span", "etat", n.signalements + " signalement"
      + (n.signalements > 1 ? "s" : "")));
    item.append(tete);
    const actions = noeud("div", "row");
    actions.append(bouton("Effacer le nom", "nav", () => effacerNom(n.id)));
    item.append(actions);
    liste.append(item);
  }
  bloc.append(liste);
  return bloc;
}

function dessiner() {
  const box = $("vueforum");
  box.innerHTML = "";
  zone = null;
  apercu = null;
  champPseudo = null;
  titre = noeud("h2", "", "Discussions");
  titre.id = "forumtitre";
  titre.tabIndex = -1;
  box.append(titre);
  box.append(noeud("p", "aide", "Visible par les autres comptes connectés du "
    + "cours. Ce n'est pas une note, et ça n'a aucun effet sur tes progrès. "
    + "Tu y apparais comme « Participant » tant que tu n'as pas choisi de nom "
    + "dans Compte → Mon identité."));

  const etat = noeud("p", "annonce", annonce);
  etat.setAttribute("aria-live", "polite");
  box.append(etat);

  // DEUX COLONNES SUR UN GRAND ÉCRAN, une seule sur un petit, et c'est la
  // grille CSS qui décide : ce qu'on écrit à gauche, ce qu'on lit à droite.
  // Empilé, le fil commençait sous trois cadres et laissait les deux tiers de
  // l'écran vides.
  const gauche = noeud("div", "colonne");
  const droite = noeud("div", "colonne large");
  box.append(gauche, droite);

  if (ctester.catalogue().length) gauche.append(choixExercice());

  const regles = noeud("div", "bloc second");
  regles.append(noeud("h3", "soustitre", "Ce qui se publie ici"));
  regles.append(listeCharte());
  regles.append(noeud("p", "aide", "Modération humaine : rien n'est vérifié "
    + "automatiquement. Signale plutôt que de répondre à une fuite."));
  gauche.append(regles);

  if (fil === null) {
    // ON N'INVENTE PAS UN FIL VIDE. « Aucun message » pendant une panne dit à
    // quelqu'un que personne ne lui a répondu, et c'est faux.
    droite.append(noeud("p", "rate", erreur));
    return;
  }
  gauche.append(formulaire());
  droite.append(leFil());
  if (moderateur) droite.append(fileModeration(), fileNoms());
}

// --- Entrées ---------------------------------------------------------------

async function basculer() {
  if (ctester.vue() === "forum") { ctester.afficherVue(""); return; }
  annonce = "";
  // LES BIBLIOTHÈQUES ARRIVENT AVEC LA VUE, pas avec la page. Un échec n'est
  // pas bloquant : `rendu` reste faux et tout s'affiche en texte brut.
  try {
    await chargerBibliotheques();
    rendu = !!(window.marked && assainisseur());
  } catch (e) {
    rendu = false;
  }
  await charger(exerciceCourant());
  dessiner();
  ctester.afficherVue("forum");
  // Le focus suit la vue : sans ça, la tabulation repartirait du haut de la
  // page et un lecteur d'écran n'annoncerait pas le changement d'écran.
  if (titre && titre.focus) titre.focus();
}

function oublier() {
  fil = null;
  signalements = null;
  moderateur = false;
  erreur = "";
  annonce = "";
  saisie = "";
  profil = null;
  nomsSignales = null;
  $("charte").hidden = true;
  // LE PANNEAU D'IDENTITÉ PART AVEC LA SESSION : il porte le nom de quelqu'un,
  // et se déconnecter ne doit pas le laisser ouvert à l'écran.
  fermerIdentite();
  if (ctester.vue() === "forum") ctester.afficherVue("");
}

// « MON IDENTITÉ » DU MENU COMPTE, et NULLE PART AILLEURS. C'est un réglage,
// pas une étape de lecture : dans la colonne du fil, il poussait la charte et
// le formulaire vers le bas à chaque visite. Un seul endroit, donc un seul
// endroit où la visibilité peut diverger de ce que la base dit.
async function ouvrirIdentite() {
  if (!$("identitepanneau").hidden) { fermerIdentite(); return; }
  annonce = "";
  await chargerProfil();
  dessinerPanneau();
  if (champPseudo) champPseudo.focus();
}

ctester.forum = {
  basculer: basculer,
  ouvrirIdentite: ouvrirIdentite,
  oublier: oublier,
  fil: () => fil,
  // Exposé pour le harnais de test : c'est LA fonction dont dépend toute la
  // sûreté du rendu, et elle doit pouvoir être éprouvée sur de vraies charges
  // hostiles plutôt que par inspection du code.
  rendreMarkdown: rendreMarkdown,
  // Exposé pour la même raison : le fuseau est la sorte de bogue qui ne se
  // voit qu'au moment où quelqu'un lit « dans quatre heures ».
  quandLocal: quandLocal,
};
})(window.ctester);
