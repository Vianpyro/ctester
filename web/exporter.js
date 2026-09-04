// L'EXPORT D'UN TP EN UN SEUL `main.c`, au format de remise : un
// `#define exercice N` en tête qui choisit l'exercice compilé, un
// `#if exercice == N ... #endif` par exercice, et les `#include` remontés une
// seule fois au-dessus de tout. C'est le format que l'enseignant distribue et
// attend en retour ; CTester, lui, garde un exercice par brouillon, et sans ce
// bouton l'étudiant recopie huit fois à la main la veille de la remise.
//
// CHARGÉ À LA DEMANDE, comme les autres modules : ni l'anonyme, ni l'étudiant
// qui travaille un exercice sans rien remettre ne le téléchargent.
//
// SENS UNIQUE, JAMAIS DE CYCLE : `window.ctester` porte l'état partagé (le
// catalogue, les brouillons, le jeton) et les fonctions du noyau ; ce fichier
// n'est jamais importé par app.js, il s'y déclare.
(function (ctester) {

// LE FICHIER PART EN UTF-8 AVEC SA MARQUE D'ORDRE. Sans elle, Visual Studio
// lit un fichier sans en-tête dans la page de code du système (cp1252 sur les
// postes Windows du labo) et tous les accents des commentaires -- ceux que
// l'étudiant a écrits, pas les nôtres -- deviennent du charabia à l'ouverture.
// C'est exactement ce qu'on voit dans le fichier d'origine du cours. gcc et
// CLion, eux, sautent la marque sans rien dire.
const MARQUE_UTF8 = "﻿";

const NUM_RE = /-ex(\d+)$/;
const INCLUDE_RE = /^[ \t]*#[ \t]*include\b/;
// L'EN-TÊTE INCLUS, ET PAS LA LIGNE ENTIÈRE. C'est lui qui sert de clé au
// dédoublonnage : `#include <stdio.h>  // pour printf` et `#include <stdio.h>`
// sont le MÊME include, et les garder tous les deux parce qu'un étudiant a
// commenté le sien rate exactement ce que le bouton promet.
const ENTETE_RE = /^[ \t]*#[ \t]*include[ \t]*(<[^>]*>|"[^"]*")/;
const OUVRE_RE = /^[ \t]*#[ \t]*(if|ifdef|ifndef)\b/;
const FERME_RE = /^[ \t]*#[ \t]*endif\b/;
const CRT_RE = /^[ \t]*#[ \t]*define[ \t]+_CRT_SECURE_NO_WARNINGS\b/;

const AUCUN_CODE =
  "    /* Aucun code enregistré pour cet exercice dans CTester :\n"
+ "       rien n'y a été écrit, ou le brouillon est resté sur un autre poste\n"
+ "       parce qu'il n'était pas connecté. */";

const deuxChiffres = (n) => String(n).padStart(2, "0");

// LA DATE DU LECTEUR, PAS CELLE D'UTC. `toISOString()` en soirée à Montréal
// date le fichier du lendemain, et une remise datée d'un jour en avance est
// exactement le genre de détail qui se discute à l'oral.
function aujourdhui() {
  const t = new Date();
  return t.getFullYear() + "-" + deuxChiffres(t.getMonth() + 1)
       + "-" + deuxChiffres(t.getDate());
}

// LE NUMÉRO VIENT DE L'IDENTIFIANT, pas du rang : `tp2-ex0` est le préambule et
// il doit rester le 0 de l'énoncé, sinon tout le fichier est décalé d'un cran
// par rapport à ce que l'enseignant lit. Le rang ne sert que de filet pour un
// identifiant qui ne finirait pas par `-exN` -- aucun aujourd'hui, et tous les
// exercices « io » en ont un.
function numeroDe(tp, rang) {
  const trouve = NUM_RE.exec(tp.id);
  return trouve ? Number(trouve[1]) : rang;
}

function libelleDesNumeros(numeros) {
  if (!numeros.length) return "Aucun exercice";
  if (numeros.length === 1) return "Exercice " + numeros[0];
  const contigu = numeros.every((n, i) => i === 0 || n === numeros[i - 1] + 1);
  return contigu
    ? "Exercices " + numeros[0] + " à " + numeros[numeros.length - 1]
    : "Exercices " + numeros.join(", ");
}

// SÉPARER CE QUI REMONTE DE CE QUI RESTE. Les `#include` sont remontés en tête
// du fichier et dédoublonnés -- c'est ce que le format demande, et deux
// `#include <stdio.h>` dans deux blocs `#if` ne gênent personne mais huit fois
// le même en-tête rend le fichier illisible.
//
// SEULEMENT AU PREMIER NIVEAU, ET C'EST LA SUBTILITÉ. Un `#include` déjà pris
// dans un `#if` de l'étudiant est là POUR cette condition : le remonter le
// rendrait inconditionnel et changerait le sens de son code. On compte donc la
// profondeur des conditionnelles au lieu de balayer le texte à l'aveugle.
//
// Les `#define` restent où ils sont, eux : deux exercices du même TP définissent
// couramment les mêmes constantes (`DIMANCHE`, `LUNDI`, ...) et c'est justement
// le `#if` qui les empêche de se marcher dessus. Seul
// `_CRT_SECURE_NO_WARNINGS` s'en va, parce que le fichier le pose déjà en tête.
function demonter(code) {
  const includes = [];
  const lignes = [];
  let profondeur = 0;
  for (const ligne of code.split(/\r?\n/)) {
    if (FERME_RE.test(ligne)) {
      profondeur = Math.max(0, profondeur - 1);
      lignes.push(ligne);
      continue;
    }
    if (profondeur === 0 && INCLUDE_RE.test(ligne)) {
      // La LIGNE est gardée telle quelle -- son commentaire appartient à
      // l'étudiant -- mais c'est l'en-tête qui identifie le doublon.
      const trouve = ENTETE_RE.exec(ligne);
      includes.push({ cle: trouve ? trouve[1] : ligne.trim(),
                      ligne: ligne.trim() });
      continue;
    }
    if (profondeur === 0 && CRT_RE.test(ligne)) continue;
    if (OUVRE_RE.test(ligne)) profondeur += 1;
    lignes.push(ligne);
  }
  return { includes: includes, corps: lignes.join("\n") };
}

// LE TROU QUE LES INCLUDES LAISSENT DERRIÈRE EUX. Retirer trois lignes d'un
// bloc d'en-têtes laisse trois lignes vides à leur place, et le fichier remis
// s'ouvre sur un accordéon de blancs. On rabat les suites de lignes vides à
// une seule, en plus des blancs de tête et de queue.
const rogner = (texte) => texte
  .replace(/^(?:[ \t]*\r?\n)+/, "")
  .replace(/\s+$/, "")
  .replace(/\n(?:[ \t]*\n){2,}/g, "\n\n");

// Le code d'UN exercice, dans l'ordre de ses fichiers déclarés. Un exercice
// « io » tient dans un seul fichier (`submission.c`) et c'est le cas normal ; le
// jour où il en aurait deux, ils sont recollés avec leur nom en commentaire
// plutôt que perdus en silence.
function codeDe(tp, sources) {
  const fichiers = (tp.files && tp.files.length)
    ? tp.files : [{ name: "submission.c" }];
  const morceaux = [];
  for (const fichier of fichiers) {
    const texte = sources && sources[fichier.name];
    if (typeof texte !== "string" || !texte.trim()) continue;
    morceaux.push(fichiers.length > 1
      ? "/* " + fichier.name + " */\n" + texte : texte);
  }
  return morceaux.join("\n\n");
}

// LE BROUILLON LOCAL D'ABORD, LE COMPTE ENSUITE. `localStorage` a tout ce que
// cet appareil a vu, et c'est le cas de l'immense majorité ; les exercices
// travaillés ailleurs, eux, ne sont que sur le compte.
//
// UN PAR UN, ET PAS EN PARALLÈLE : `/brouillon` passe par la connexion Postgres
// unique d'`etat.py`, derrière son verrou global. Dix requêtes lancées d'un coup
// n'iraient pas plus vite et prendraient la file à tout le monde pendant qu'un
// autre étudiant soumet. Au pire c'est une seconde sur un bouton de
// téléchargement.
async function rassembler(exercices) {
  const trouves = {};
  const manquants = [];
  for (const tp of exercices) {
    const local = ctester.brouillon(tp.id);
    if (local && codeDe(tp, local)) trouves[tp.id] = local;
    else manquants.push(tp);
  }
  if (!manquants.length || !ctester.token() || !ctester.compte) return trouves;
  for (const tp of manquants) {
    const reponse = await ctester.compte.getJson(
      "brouillon?ex=" + encodeURIComponent(tp.id));
    if (reponse && reponse.sources) trouves[tp.id] = reponse.sources;
  }
  return trouves;
}

// LE NOM PRÉ-REMPLIT, IL NE S'IMPOSE PAS. CTester ne connaît de l'étudiant
// qu'un `sub` opaque : le seul nom qu'il ait jamais est celui qu'il a saisi
// dans « Mon identité », ou la proposition que Rauthy rapporte. Même traitement
// que le formulaire d'identité -- on pré-remplit un champ que l'étudiant relit
// avant de remettre, dans un fichier qui va sur SON disque et nulle part
// ailleurs. Rien n'est publié, et le champ reste vide si on ne sait pas.
async function auteur() {
  const config = ctester.oidc();
  if (!ctester.token() || !ctester.compte || !(config && config.forum)) return "";
  const profil = await ctester.compte.getJson("forum/profil");
  if (!profil || typeof profil !== "object") return "";
  return String(profil.pseudo || profil.suggestion || "").trim();
}

function entete(nom, groupe, numeros, premier) {
  return [
    "/*",
    "Fichier : main.c",
    "Auteur : " + nom,
    "Date : " + aujourdhui(),
    "Description : " + libelleDesNumeros(numeros) + " — " + groupe + " — TCH009",
    "*/",
    "/* *******************************************************",
    "* Commande de preprocesseur",
    "******************************************************* */",
    "#define _CRT_SECURE_NO_WARNINGS",
    "/* Ce numéro choisit l'exercice qui sera compilé : change-le pour tester",
    "   un autre exercice de ce fichier. */",
    "#define exercice " + premier,
  ].join("\n");
}

// LE FICHIER ENTIER, à partir du catalogue et des brouillons. Rendu séparément
// du téléchargement pour être éprouvable : c'est le texte qu'on vérifie dans
// `test_page.js`, pas le clic.
function construire(exercices, sources, nom, groupe) {
  const includes = [];
  const blocs = [];
  const numeros = [];
  const vides = [];
  // `null`, ET SURTOUT PAS `0`. Le préambule du laboratoire 2 est l'exercice
  // NUMÉRO 0 : avec un compteur initialisé à zéro, `if (!premier)` le prend
  // pour « rien trouvé » et le fichier s'ouvre sur le bloc suivant.
  let premier = null;
  exercices.forEach((tp, rang) => {
    const numero = numeroDe(tp, rang + 1);
    numeros.push(numero);
    const code = codeDe(tp, sources[tp.id]);
    const titre = "/* Exercice " + numero + " — " + (tp.short || tp.id) + " */";
    if (!code) {
      vides.push(numero);
      blocs.push(titre + "\n#if exercice == " + numero
               + "\n" + AUCUN_CODE + "\n#endif");
      return;
    }
    // LE PREMIER EXERCICE QUI A DU CODE, et pas le premier tout court : un
    // fichier qui s'ouvre sur un bloc vide ne compile pas, et l'étudiant en
    // conclut que l'export est cassé.
    if (premier === null) premier = numero;
    const piece = demonter(code);
    for (const inc of piece.includes) {
      if (!includes.some((vu) => vu.cle === inc.cle)) includes.push(inc);
    }
    blocs.push(titre + "\n#if exercice == " + numero
             + "\n" + rogner(piece.corps) + "\n#endif");
  });
  const texte = [
    entete(nom, groupe, numeros,
           premier === null ? (numeros[0] === undefined ? 1 : numeros[0]) : premier),
    includes.map((inc) => inc.ligne).join("\n"),
    blocs.join("\n\n"),
  ].filter(Boolean).join("\n\n") + "\n";
  return { texte: texte, vides: vides, total: exercices.length };
}

// UNE SEULE URL VIVANTE À LA FOIS. `revokeObjectURL` juste après le clic court
// après le téléchargement que le navigateur vient de lancer ; le poser dans un
// minuteur marche mais laisse traîner un minuteur. On révoque la PRÉCÉDENTE au
// début du prochain export : jamais de course, jamais plus d'un blob en vie.
let urlPrecedente = null;

function telecharger(fichier, texte) {
  if (urlPrecedente) URL.revokeObjectURL(urlPrecedente);
  const blob = new Blob([MARQUE_UTF8 + texte], { type: "text/plain;charset=utf-8" });
  urlPrecedente = URL.createObjectURL(blob);
  const lien = document.createElement("a");
  lien.href = urlPrecedente;
  lien.download = fichier;
  document.body.append(lien);
  lien.click();
  lien.remove();
}

// `annoncer(texte, rate)` : L'APPELANT DIT OÙ ÇA S'AFFICHE. Le bouton de la
// barre d'actions écrit sur la ligne du brouillon, celui de « Mes exercices »
// à côté de lui-même -- et `#brouillon` n'est même pas à l'écran depuis la vue
// liste. Un module qui choisirait lui-même écrirait dans le vide une fois sur
// deux.
async function exporter(groupe, annoncer) {
  const exercices = ctester.exercicesExportables(groupe);
  if (!exercices.length) {
    annoncer("rien à exporter pour " + groupe, true);
    return null;
  }
  annoncer("assemblage de " + groupe + "…");
  const sources = await rassembler(exercices);
  const fait = construire(exercices, sources, await auteur(), groupe);
  if (fait.vides.length === fait.total) {
    annoncer("aucun code enregistré pour " + groupe + " : rien à exporter", true);
    return fait;
  }
  try {
    telecharger("main.c", fait.texte);
  } catch (e) {
    annoncer("le téléchargement a échoué — copie ton code à la main", true);
    return fait;
  }
  const ecrits = fait.total - fait.vides.length;
  annoncer("main.c exporté — " + ecrits + " exercice"
         + (ecrits > 1 ? "s" : "") + " sur " + fait.total
         + (fait.vides.length
            ? " (rien pour : " + fait.vides.join(", ") + ")" : ""));
  return fait;
}

ctester.exporter = {
  exporter: exporter,
  // Exposés pour le harnais : le texte produit est ce qui compte, et il doit
  // pouvoir être éprouvé sans passer par un clic ni par un blob.
  construire: construire,
  demonter: demonter,
};
})(window.ctester);
