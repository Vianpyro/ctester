// « Mes progrès » : la vue privée d'un compte connecté. Chargée AU CLIC, jamais
// avant -- l'anonyme n'en télécharge rien, et un étudiant connecté qui ne
// l'ouvre pas non plus. Même contrat que compte.js, mêmes raisons.
//
// SENS UNIQUE : ce fichier lit `window.ctester` et y dépose son entrée ; le
// noyau ne le connaît que par `ctester.progres`, jamais par un import.
//
// RIEN NE SE CALCULE ICI. Le solde, le niveau, les compétences, les succès et
// la recommandation arrivent tout faits de `GET /progres`, qui les dérive de
// faits que le serveur a lui-même écrits. Une page qui calculerait son propre
// XP serait une page où l'on se le donne depuis la console.
(function (ctester) {
const $ = ctester.$;

// La dernière projection reçue, ou null quand on n'a rien de fiable à montrer.
// LES DEUX SONT DISTINCTS : `null` avec un message d'erreur veut dire « on ne
// sait pas », et ça ne s'affiche pas comme un zéro. Annoncer 0 XP à quelqu'un
// dont la base est en panne, c'est lui dire que son travail a disparu.
let projection = null;
let erreur = "";

async function charger() {
  if (!ctester.compte) {
    projection = null;
    erreur = "Reconnecte-toi pour voir tes progrès.";
    return;
  }
  const reponse = await ctester.compte.getJson("progres");
  if (!reponse || typeof reponse.xp !== "number") {
    projection = null;
    erreur = "Tes progrès ne sont pas disponibles pour l'instant. "
           + "L'exercice et le bouton « Tester », eux, fonctionnent normalement.";
    return;
  }
  projection = reponse;
  erreur = "";
}

// --- Rendu ----------------------------------------------------------------
// `textContent` PARTOUT : les identifiants de compétence viennent du dépôt de
// tests et les libellés de succès de la politique du serveur. Rien de tout ça
// n'est du HTML, et le jour où l'un d'eux contient un chevron, il doit
// s'afficher comme un chevron.

function noeud(balise, classe, texte) {
  const n = document.createElement(balise);
  if (classe) n.className = classe;
  if (texte !== undefined) n.textContent = texte;
  return n;
}

function titre(texte) {
  return noeud("h3", "soustitre", texte);
}

function jauge(fait, total) {
  // DÉCORATIVE, et déclarée comme telle : la même information est écrite en
  // toutes lettres juste au-dessus. Un lecteur d'écran n'a rien à annoncer ici.
  const barre = noeud("span", "jauge");
  barre.setAttribute("aria-hidden", "true");
  const rempli = document.createElement("i");
  rempli.setAttribute("style",
    "width:" + (total ? Math.round(fait / total * 100) : 0) + "%");
  barre.append(rempli);
  return barre;
}

const pluriel = (n, mot) => n + " " + mot + (n > 1 ? "s" : "");

function exerciceLibelle(id) {
  const tp = ctester.catalogue().find(t => t.id === id);
  return tp ? (tp.label || tp.short || id) : id;
}

function actionSuivante(vue) {
  const bloc = noeud("div", "bloc");
  bloc.append(titre("Action suivante"));
  const suivant = vue.suivant;
  if (!suivant) {
    bloc.append(noeud("p", "", vue.exercices.total
      ? "Tu as réussi tous les exercices publiés. Rien de neuf à proposer "
        + "pour l'instant."
      : "Aucun exercice n'est publié pour l'instant."));
    return bloc;
  }
  const quoi = exerciceLibelle(suivant.exercice_id);
  bloc.append(noeud("p", "", suivant.competence
    ? "Tu as déjà pratiqué « " + ctester.skillLabel(suivant.competence)
      + " » : continue avec « " + quoi + " »."
    : "Commence par « " + quoi + " »."));
  const bouton = noeud("button", "", "Ouvrir « " + quoi + " »");
  bouton.type = "button";
  bouton.addEventListener("click", () => ouvrir(suivant.exercice_id));
  bloc.append(bouton);
  return bloc;
}

function ouvrir(id) {
  const tp = ctester.catalogue().find(t => t.id === id);
  if (!tp) return;
  ctester.fillExercises(tp.id);
  ctester.afficherVue("");
}

function pratique(vue) {
  const bloc = noeud("div", "bloc");
  bloc.append(titre("Ce que tu as pratiqué"));
  const ex = vue.exercices;
  bloc.append(noeud("p", "", pluriel(ex.pratiques, "exercice") + " pratiqué"
    + (ex.pratiques > 1 ? "s" : "") + " sur " + ex.total + " publié"
    + (ex.total > 1 ? "s" : "") + ", dont " + ex.reussis + " réussi"
    + (ex.reussis > 1 ? "s" : "") + "."));

  if (!vue.competences.length) {
    bloc.append(noeud("p", "aide",
      "Les exercices que tu as ouverts n'annoncent pas encore de compétence."));
    return bloc;
  }
  // UNE LISTE, PAS UN GRAPHIQUE. Chaque ligne porte ses valeurs en toutes
  // lettres : c'est ce qu'un lecteur d'écran lit, ce qu'un zoom à 400 % garde,
  // et ce qui reste vrai sans couleur.
  const liste = noeud("ul", "competences");
  for (const c of vue.competences) {
    const item = document.createElement("li");
    item.append(noeud("span", "nom", ctester.skillLabel(c.id)));
    item.append(noeud("span", "chiffres",
      c.pratiques + " exercice" + (c.pratiques > 1 ? "s" : "")
      + " pratiqué" + (c.pratiques > 1 ? "s" : "") + " sur " + c.total
      + ", dont " + c.reussis + " réussi" + (c.reussis > 1 ? "s" : "")));
    item.append(jauge(c.pratiques, c.total));
    liste.append(item);
  }
  bloc.append(liste);
  bloc.append(noeud("p", "aide",
    "« Pratiquée » veut dire que tu as soumis un exercice qui porte cette "
    + "compétence. Ce n'est pas une maîtrise vérifiée."));
  return bloc;
}

function niveau(vue) {
  // AU SECOND PLAN, et la phrase qui suit n'est pas décorative : c'est la
  // seule chose qui empêche un compteur d'activité de se lire comme une note.
  const bloc = noeud("div", "bloc second");
  bloc.append(titre("Niveau et XP"));
  const n = vue.niveau;
  bloc.append(noeud("p", "", "Niveau " + n.rang + " — " + vue.xp + " XP."
    + (n.prochain === null
       ? " C'est le dernier niveau de la politique en cours."
       : " Encore " + n.restant + " XP avant le niveau " + (n.rang + 1) + ".")));
  bloc.append(jauge(vue.xp - n.depuis,
                    (n.prochain === null ? vue.xp : n.prochain) - n.depuis));
  bloc.append(noeud("p", "aide", "Les XP reflètent l'activité de pratique ; "
    + "ce ne sont ni une note ni une maîtrise vérifiée."));
  return bloc;
}

function succes(vue) {
  const bloc = noeud("div", "bloc");
  bloc.append(titre("Accomplissements"));
  if (!vue.succes.length) {
    bloc.append(noeud("p", "aide",
      "Aucun pour l'instant. Ils arrivent en pratiquant ; aucun n'est "
      + "obligatoire."));
    return bloc;
  }
  // TITRE, DESCRIPTION ET DATE, en texte. Ni pastille de couleur seule, ni
  // icône seule : les trois se lisent à voix haute et survivent au noir et
  // blanc.
  const liste = noeud("dl", "succes");
  for (const s of vue.succes) {
    liste.append(noeud("dt", "", s.titre));
    const quoi = document.createElement("dd");
    quoi.append(noeud("span", "quoi", s.description));
    const quand = noeud("time", "quand", "obtenu le " + s.obtenu_le);
    quand.setAttribute("datetime", s.obtenu_le);
    quoi.append(quand);
    liste.append(quoi);
  }
  bloc.append(liste);
  return bloc;
}

// --- LA LISTE DES EXERCICES, VENUE DE « MES EXERCICES » --------------------
// Les deux destinations répondaient à la même question -- « où j'en suis » --
// dans deux écrans, avec deux comptes différents des mêmes exercices. Le
// statut, lui, a rejoint la bande du laboratoire et le menu du catalogue : ce
// qui restait ici de vraiment unique, c'est la vue d'ensemble et l'export.
//
// ELLE NE DÉPEND PAS DE `GET /progres`. Une base muette fait disparaître les
// chiffres de la projection, pas cette liste : elle se dessine depuis ce que
// `compte.js` a déjà lu, et l'export doit rester atteignable un soir de panne.
const ETAT_MOT = { valide: "validé", essaye: "essayé" };

function ligneExport(groupe) {
  const bloc = noeud("div", "exportligne");
  const bouton = noeud("button", "nav", "Exporter le " + groupe + " en main.c");
  bouton.type = "button";
  const etat = noeud("span", "exportetat");
  etat.setAttribute("aria-live", "polite");
  const annoncer = (texte, rate) => {
    etat.textContent = texte;
    etat.className = rate ? "exportetat rate" : "exportetat";
  };
  bouton.addEventListener("click", async () => {
    // `activerModule` dit deja ce qui n'est pas arrive -- mais il le dit dans
    // le bandeau systeme. On le redit sur place, sinon le bouton reste inerte.
    if (!await ctester.activerModule("exporter", "l'export du TP")) {
      annoncer("l'export n'a pas pu être chargé — réessaie", true);
      return;
    }
    await ctester.exporter.exporter(groupe, annoncer);
  });
  bloc.append(bouton, etat);
  return bloc;
}

function listeExercices() {
  // L'IDENTIFIANT `liste` EST CONSERVÉ : toute la mise en forme de l'ancienne
  // destination s'y accroche, et la recopier sous un autre nom aurait fait deux
  // feuilles à tenir d'accord pour zéro changement visible.
  const box = noeud("div");
  box.id = "liste";
  const etats = ctester.compte ? ctester.compte.etats() : {};
  const stats = ctester.compte ? ctester.compte.pratique() : {};
  const tps = ctester.catalogue();
  for (let rang = 0; rang < tps.length; rang++) {
    const tp = tps[rang];
    const row = noeud("button", "ligne");
    row.type = "button";
    row.append(noeud("span", "tpname", tp.group));
    row.append(noeud("span", "titre", tp.short || tp.label));
    const compte = stats[tp.id];
    const statut = etats[tp.id] || "";
    const dot = noeud("span", "puce " + (compte && compte.reussites ? "valide" : statut),
      compte
        ? compte.tentatives + " tentative" + (compte.tentatives > 1 ? "s" : "")
          + (compte.reussites ? " — réussie" + (compte.reussites > 1 ? "s" : "") : "")
        : ETAT_MOT[statut] || "à faire");
    row.append(dot);
    row.addEventListener("click", () => ouvrir(tp.id));
    box.append(row);
    // LE BOUTON FERME LE GROUPE, il ne l'ouvre pas : il arrive apres la
    // derniere ligne du TP, quand on vient de lire ce qui y reste a faire.
    const suivant = tps[rang + 1];
    if ((!suivant || suivant.group !== tp.group)
        && ctester.groupeExportable(tp.group)) {
      box.append(ligneExport(tp.group));
    }
  }
  const bloc = noeud("div", "bloc");
  bloc.append(titre("Tes exercices"));
  bloc.append(box);
  return bloc;
}

function dessiner() {
  const box = $("vueprogres");
  box.innerHTML = "";
  const entete = noeud("h2", "", "Mes progrès");
  entete.id = "progrestitre";
  entete.tabIndex = -1;
  box.append(entete);
  box.append(noeud("p", "aide", "Cette page n'est visible que par toi. Rien "
    + "n'est transmis à ton enseignant, et ce n'est pas une note."));
  if (!projection) {
    // ON N'INVENTE PAS UN ZÉRO. Un solde à zéro affiché pendant une panne de
    // base se lit « tout mon travail a disparu », et c'est faux.
    //
    // MAIS LA LISTE RESTE : elle ne vient pas de la projection, et l'export
    // d'un TP ne doit pas disparaître le soir où Postgres tousse.
    box.append(noeud("p", "rate", erreur), listeExercices());
    return;
  }
  box.append(actionSuivante(projection), listeExercices(),
             pratique(projection), niveau(projection), succes(projection));
}

// --- Entrées ---------------------------------------------------------------

async function basculer() {
  if (ctester.vue() === "progres") { ctester.afficherVue(""); return; }
  await charger();
  dessiner();
  ctester.afficherVue("progres");
  // Le focus suit la vue : sans ça, la tabulation repartirait du haut de la
  // page et un lecteur d'écran n'annoncerait pas le changement d'écran.
  const entete = $("progrestitre");
  if (entete.focus) entete.focus();
}

// APRÈS UN VERDICT. La projection est refaite même quand la vue est fermée :
// l'ouvrir ensuite ne doit pas montrer l'avant-dernière soumission.
async function rafraichir() {
  await charger();
  if (ctester.vue() === "progres") dessiner();
}

function oublier() {
  projection = null;
  erreur = "";
  if (ctester.vue() === "progres") ctester.afficherVue("");
}

ctester.progres = {
  basculer: basculer,
  rafraichir: rafraichir,
  oublier: oublier,
  projection: () => projection,
};
})(window.ctester);
