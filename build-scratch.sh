#!/bin/bash
# Mode console : ce qui tourne DANS le bac à sable pour un programme LIBRE.
# Réglé par variables d'environnement (bas de cet en-tête).
#
# Pour la Console : l'étudiant écrit un programme C quelconque, qui n'appartient
# à aucun exercice, et DIALOGUE avec lui pendant qu'il tourne. Il n'y a ni cas
# de test, ni valeur attendue, ni verdict.
#
# CE SCRIPT NE VOIT RIEN DU TOUT, et c'est plus fort que build-io.sh : celui-là
# ne voit pas les valeurs attendues mais reçoit les ENTRÉES d'un exercice ;
# celui-ci ne reçoit que le fichier de l'étudiant. Aucun montage du contenu
# privé, pas de /in/cases, pas de /in/tests, pas de /in/unity. Il n'y a donc
# rien à taire, et toute la stderr de gcc remonte.
#
# CE N'EST PAS build-io.sh AVEC UN `if`, ET ÇA NE DOIT PAS LE DEVENIR.
# build-io.sh implémente un PROTOCOLE DE CORRECTION : un chronomètre mural par
# cas, un cadrage BEGIN/ERR/END, des valeurs comparées sur l'hôte. Ce script
# n'implémente aucune correction et n'a délibérément AUCUN chronomètre mural --
# attendre un humain est son état normal. Les fusionner mettrait un
# `if [ -d /in/cases ]` entre « un verdict noté » et « un programme libre qui
# peut bloquer pour toujours », c'est-à-dire ferait dépendre la différence
# entre les deux de la présence d'un montage.
#
# CODES DE SORTIE, lus par le worker :
#   10  la compilation a échoué (stdout = la stderr de gcc)
#   12  la compilation a dépassé $COMPILE_TIMEOUT s
#   70  /work est inaccessible
#   *   sinon, le code de sortie DU PROGRAMME DE L'ÉTUDIANT
#
# LE MARQUEUR DE PHASE. Une seule ligne, encadrée par le nonce du job :
#
#   ...la sortie de gcc, s'il a dit quelque chose...
#   <nonce> RUN
#   ...ce que le programme écrit, jusqu'à sa mort...
#
# Le worker coupe le flux UNE FOIS sur ce marqueur : ce qui précède est un
# diagnostic de compilation, ce qui suit appartient au programme. Le nonce, et
# pas un marqueur fixe : l'étudiant ne le connaît pas, donc il ne peut pas
# imprimer un faux marqueur et faire passer sa propre sortie pour du gcc.

set -u

# --- Réglages ---------------------------------------------------------------
# Mêmes conventions que build-io.sh, y compris les deux précautions autour de
# $SANITIZERS : `-` et non `:-` (le repli prévu est de VIDER la variable, pas de
# la supprimer), et pas de guillemets à l'usage (une valeur vide entre
# guillemets passerait un argument vide à gcc).
C_STD="${CTESTER_C_STD:-gnu23}"
SANITIZERS="${CTESTER_SANITIZERS--fsanitize=address,undefined}"
ASAN_OPTS="${CTESTER_ASAN_OPTIONS:-exitcode=86:detect_leaks=0}"
COMPILE_TIMEOUT="${CTESTER_COMPILE_TIMEOUT:-10}"
# LE TEMPS CPU, ET C'EST LA SEULE HORLOGE QUI SAIT RÉPONDRE À `while (1);`.
# Le temps mural ne distingue pas « l'étudiant réfléchit » de « le programme
# tourne en rond » -- c'est précisément pour ça qu'un job noté peut se contenter
# d'un `timeout -s KILL 5` et pas une session interactive. Le temps CPU, lui, le
# distingue : un programme bloqué dans scanf n'en consomme aucun.
#
# ATTENTION : ça NE COUVRE PAS la bombe à fork. RLIMIT_CPU est PAR PROCESSUS, et
# chaque enfant repart avec un budget neuf. Ce qui arrête une bombe à fork, c'est
# --pids-limit sous runc et le plafond mémoire du cgroup sous runsc.
CPU_SECONDS="${CTESTER_CPU_SECONDS:-10}"

cd /work || exit 70

# LE TAMPON DE SORTIE, ET C'EST TOUTE LA FONCTIONNALITÉ. Sans ces trois lignes,
# la glibc met stdout en tampon de BLOC dès qu'il n'est pas un terminal :
# `printf("Entrez : ")` suivi d'un `scanf` n'apparaîtrait JAMAIS avant la fin du
# programme, et le terminal aurait l'air gelé au moment précis où il demande
# quelque chose. Mesuré : sans ce fichier, aucune invite en 25 secondes.
#
# UN CONSTRUCTEUR, ET PAS `stdbuf`. stdbuf agit par LD_PRELOAD -- un
# préchargement de plus à côté du runtime d'ASan, une dépendance à coreutils
# DANS l'image, et un mécanisme que test_sandbox.py (vrai gcc, sans Docker)
# éprouverait autrement qu'en production. Ici c'est du gcc pur.
#
# ET C'EST PLUS FORT QU'UN VRAI TERMINAL : un TTY donne un tampon de LIGNE, qui
# ne vide toujours pas un printf sans \n. _IONBF met l'invite sur le fil quand
# printf revient, que le programme lise ensuite ou non.
#
# `static` : le symbole ne peut pas entrer en collision avec celui d'un étudiant.
cat > /work/ctester_rt.c <<'EOF'
#include <stdio.h>
__attribute__((constructor)) static void ctester_rt_unbuffer(void)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    setvbuf(stderr, NULL, _IONBF, 0);
}
EOF

# -lm inconditionnel et /in/src en entier : mêmes raisons qu'en mode io.
# LES SANITIZERS SONT SÛRS ICI, comme en mode io et pour une raison plus forte :
# ce conteneur ne contient aucun test, donc le rapport d'ASan ne peut nommer que
# le code de l'étudiant. Dans une console d'apprentissage, un rapport de
# débordement vaut mieux qu'un « Segmentation fault ».
timeout -s KILL $COMPILE_TIMEOUT \
    gcc -std=$C_STD -Wall -Wextra $SANITIZERS -I/in/src \
        /in/src/*.c /work/ctester_rt.c -o /work/t -lm 2>/work/gcc.err
rc=$?
if [ $rc -eq 124 ] || [ $rc -eq 137 ]; then
    exit 12
fi
if [ $rc -ne 0 ]; then
    cat /work/gcc.err
    exit 10
fi

# Les avertissements d'une compilation réussie, comme en mode io -- et ils
# comptent encore plus ici, où il n'y a aucun verdict à lire à la place.
if [ -s /work/gcc.err ]; then
    cat /work/gcc.err
fi

printf '%s RUN\n' "$CTESTER_NONCE"

# `ulimit` PUIS `exec`, ET SURTOUT PAS UN SOUS-SHELL. Les trois raisons :
#
#   1. le programme prend la place de bash, donc `docker rm -f` et les signaux
#      l'atteignent directement, et le code de sortie du conteneur EST le sien.
#      Sans exec, un `while (1);` survivrait à son parent ;
#   2. la limite est posée sur ce shell-ci et SURVIT à l'exec (les rlimits sont
#      héritées), donc elle s'applique bien au programme -- et pas à gcc, qui a
#      déjà fini ;
#   3. il ne reste aucun bash pour rapporter la mort de son enfant. Avec un
#      sous-shell, bash écrivait `/in/build.sh: line NN: 16 Killed ( ulimit ...)`
#      dans la sortie de l'étudiant : du bruit qui nomme les entrailles du
#      script au moment précis où il faut lui expliquer sa boucle infinie.
#      Mesuré.
export ASAN_OPTIONS="$ASAN_OPTS"
ulimit -t $CPU_SECONDS
exec /work/t
