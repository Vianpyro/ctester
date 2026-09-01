#!/bin/bash
# Mode io : ce qui tourne DANS le bac à sable. Réglé par variables
# d'environnement (bas de cet en-tête).
#
# Pour les laboratoires où l'étudiant écrit un PROGRAMME COMPLET, avec son
# main(), qui lit sur l'entrée standard et écrit sur la sortie standard. C'est
# la forme de tout le laboratoire 2, et c'est exactement ce que le mode Unity
# refuse (deux main() ne s'éditent pas ensemble).
#
# CE SCRIPT NE VOIT AUCUN SECRET, contrairement à build-unity.sh. Les valeurs
# attendues restent dans io.json, sur l'hôte : le conteneur ne reçoit que les
# ENTRÉES, déjà extraites dans /in/cases par le worker. Il n'y a donc rien à
# taire ici, et la stderr de gcc peut remonter entière -- elle ne parle que du
# fichier de l'étudiant.
#
# CODES DE SORTIE, lus par le worker :
#   10  la compilation a échoué (stdout = la stderr de gcc)
#   12  la compilation a dépassé $COMPILE_TIMEOUT s
#   0   les cas ont été exécutés -- le verdict se lit dans les marqueurs
#
# LE PROTOCOLE DE SORTIE. Chaque exécution est encadrée par un nonce tiré par
# job et passé en variable d'environnement :
#
#   <nonce> BEGIN 01
#   ...ce que le programme a écrit...
#   <nonce> END 01 <code de sortie>
#
# Le nonce, et pas un marqueur fixe : l'étudiant ne le connaît pas, donc il ne
# peut pas imprimer de faux séparateurs et se fabriquer des cas réussis.

set -u

# --- Réglages ---------------------------------------------------------------
# Passés par le worker au conteneur (`docker run -e`, voir runner.py). Les
# valeurs par défaut ci-dessous sont celles du rôle Ansible : ce script tourne
# donc tel quel hors déploiement, ce dont test_bac_a_sable.py se sert pour
# l'éprouver avec un vrai gcc et sans Docker.
#
# DEUX PRÉCAUTIONS AUTOUR DE $SANITIZERS, ET AUCUNE DES DEUX N'EST DU STYLE.
# Le repli prévu si gVisor refuse la réserve d'adressage d'ASan est de VIDER
# CTESTER_SANITIZERS, pas de la supprimer -- l'unité systemd la définit toujours.
#
#   `-` et non `:-` : avec `:-`, bash considère une variable vide comme absente
#   et remet le défaut, donc le repli ne désactivait rien du tout. Mesuré.
#
#   pas de guillemets À L'USAGE, plus bas : une expansion entre guillemets d'une
#   valeur vide passerait un argument VIDE à gcc, qui échouerait sur « no input
#   file » au lieu de compiler sans sanitizers.
C_STD="${CTESTER_C_STD:-gnu23}"
SANITIZERS="${CTESTER_SANITIZERS-"-fsanitize=address,undefined"}"
ASAN_OPTS="${CTESTER_ASAN_OPTIONS:-exitcode=86:detect_leaks=0}"
COMPILE_TIMEOUT="${CTESTER_COMPILE_TIMEOUT:-10}"
RUN_TIMEOUT="${CTESTER_RUN_TIMEOUT:-5}"

cd /work || exit 70

# -lm inconditionnel : les exercices 4 et 5 utilisent pow() et sqrt(), et lier
# la bibliothèque mathématique ne coûte rien aux autres.
#
# /in/src ET PAS UN FICHIER : depuis le laboratoire 5 une soumission peut être
# un module (calendrier.h + calendrier.c + main.c). Tous les .c du répertoire
# sont compilés ensemble, et -I/in/src fait résoudre les `#include "..."` de
# l'étudiant vers ses propres en-têtes.
#
# LES SANITIZERS SONT SÛRS ICI, ET SEULEMENT ICI. Ce conteneur ne contient
# aucun test : le rapport d'ASan peut donc être rendu entier à l'étudiant, sur
# la stderr du cas. En mode unity la même pile d'appels nommerait la fonction
# de test appelante, d'où le traitement différent dans build-unity.sh.
timeout -s KILL $COMPILE_TIMEOUT \
    gcc -std=$C_STD -Wall -Wextra $SANITIZERS -I/in/src \
        /in/src/*.c -o /work/t -lm 2>/work/gcc.err
rc=$?
if [ $rc -eq 124 ] || [ $rc -eq 137 ]; then
    exit 12
fi
if [ $rc -ne 0 ]; then
    cat /work/gcc.err
    exit 10
fi

# LES AVERTISSEMENTS D'UNE COMPILATION RÉUSSIE, qui étaient jetés jusqu'ici.
# `warning: 'x' is used uninitialized`, `format '%d' expects int *` (le scanf
# sans &), `suggest parentheses around assignment` (le if (x = 5))... gcc nomme
# déjà les deux erreurs les plus classiques du cours, et on les mettait à la
# poubelle. Elles portent sur les fichiers de l'étudiant SEULS -- rien des tests
# n'entre dans cette compilation -- donc elles ne peuvent rien révéler.
if [ -s /work/gcc.err ]; then
    printf '%s WARN\n' "$CTESTER_NONCE"
    cat /work/gcc.err
    printf '\n%s ENDWARN\n' "$CTESTER_NONCE"
fi

for case_file in /in/cases/*.in; do
    # Le glob ne s'étend pas quand il ne correspond à rien : sans ce garde-fou,
    # un TP sans cas exécuterait le programme avec un nom de fichier littéral.
    [ -e "$case_file" ] || continue
    name=$(basename "$case_file" .in)
    printf '%s BEGIN %s\n' "$CTESTER_NONCE" "$name"
    ASAN_OPTIONS="$ASAN_OPTS" \
        timeout -s KILL $RUN_TIMEOUT /work/t < "$case_file" 2>/work/err
    # Le code de sortie DOIT être saisi avant tout autre commande, sinon c'est
    # celui du printf qu'on rapporterait.
    code=$?
    # La stderr du programme : c'est là qu'atterrissent ses propres
    # fprintf(stderr, ...) de débogage et les messages de la bibliothèque C.
    # Elle lui appartient, elle ne contient rien de secret.
    printf '\n%s ERR %s\n' "$CTESTER_NONCE" "$name"
    cat /work/err
    # Le \n de tête garantit que le marqueur commence sa propre ligne, même
    # quand le programme oublie le \n final -- ce que fait la moitié d'un
    # groupe de première session.
    printf '\n%s END %s %s\n' "$CTESTER_NONCE" "$name" "$code"
done

exit 0
