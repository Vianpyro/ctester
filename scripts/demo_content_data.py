"""The demo content base: one small, complete example of every shape CTester reads.

It is the worked example `docs/content/format.md` points at, and CI publishes it so the
page has something real to render. Nothing here belongs to any course: it exists to show
the format and to give the engine something to prove itself against.
"""

SKILLS = [
    {"id": "entrees-sorties", "label": "entrées/sorties"},
    {"id": "types", "label": "types"},
    {"id": "conditions", "label": "conditions"},
    {"id": "boucles", "label": "boucles"},
    {"id": "tableaux", "label": "tableaux"},
    {"id": "fonctions", "label": "fonctions"},
]

# The quiz the Lighthouse config deep-links to. Named here so the two stay in step.
QUIZ_ID = "tp1-ex3"

# Long enough to matter. The shifts this whole exercise is meant to catch come from a
# statement growing from one placeholder line into a real brief, so a one-word statement
# would measure nothing.
STATEMENT = """## Ce qu'on te demande

%s

### Comment ton programme est lu

Le juge lit les **nombres** de ta sortie, dans l'ordre où ils apparaissent. Le texte qui
les entoure est libre : `Résultat = 42` et `42` sont lus exactement pareil. Tu peux donc
écrire la phrase qui te semble la plus claire.

### Un point de départ

```c
#include <stdio.h>

int main(void) {
    int a, b;
    scanf("%%d", &a);
    scanf("%%d", &b);
    /* à toi de jouer */
    return 0;
}
```

### Ce qui coince souvent

- Oublier le `&` devant la variable dans `scanf` : le programme compile, puis plante.
- Lire les deux nombres dans le mauvais ordre. Le premier lu est le premier donné.
- Afficher autre chose que des nombres quand le calcul échoue : le juge ne verra rien à lire.

Prends le temps de tester avec de petites valeurs avant de lancer le test complet.
"""

UNITY_STATEMENT = """## Ce qu'on te demande

Écris le module `calcul`, c'est-à-dire les deux fichiers `calcul.h` et `calcul.c`, qui
offre exactement ces deux fonctions :

    int carre(int n);
    double moyenne(const int *valeurs, int nombre);

`carre` renvoie `n * n`. `moyenne` renvoie la moyenne arithmétique des `nombre` premières
valeurs du tableau, et `0.0` si `nombre` vaut zéro.

### Comment ton module est lu

Tu n'écris **pas** de `main()` : les tests en fournissent un. Ils incluent *ton*
`calcul.h`, donc les noms et les signatures ci-dessus doivent être respectés à la lettre,
sans quoi l'édition de liens échoue.

### Ce qui coince souvent

- Diviser deux `int` et attendre une fraction : `(a + b) / 2` vaut 3 pour 3 et 4.
- Oublier le cas `nombre == 0`, qui divise par zéro.
"""

LIRE = ("Le programme lit d'abord un entier `n`, puis `n` entiers, "
        "tous sur l'entrée standard.")

EXERCISES = [
    {
        "id": "tp1-ex1", "title": "Additionner deux entiers", "mode": "io",
        "skills": ["entrees-sorties", "types"], "difficulty": "intro",
        "asked": "Écris un programme qui lit deux entiers sur l'entrée standard, "
                 "puis affiche leur somme.",
        "cases": [{"stdin": "2\n3\n", "expect": [5]},
                  {"stdin": "10\n7\n", "expect": [17]},
                  {"stdin": "40\n2\n", "expect": [42]}],
        "solution": """#include <stdio.h>

int main(void)
{
    int a, b;
    scanf("%d", &a);
    scanf("%d", &b);
    printf("Somme : %d\\n", a + b);
    return 0;
}
""",
    },
    {
        "id": "tp1-ex2", "title": "Le plus grand des deux", "mode": "io",
        "skills": ["conditions", "entrees-sorties"], "difficulty": "intro",
        "asked": "Écris un programme qui lit deux entiers sur l'entrée standard, "
                 "puis affiche le plus grand des deux.",
        "cases": [{"stdin": "2\n3\n", "expect": [3]},
                  {"stdin": "10\n7\n", "expect": [10]},
                  {"stdin": "42\n42\n", "expect": [42]}],
        "solution": """#include <stdio.h>

int main(void)
{
    int a, b;
    scanf("%d", &a);
    scanf("%d", &b);
    printf("Le plus grand : %d\\n", a > b ? a : b);
    return 0;
}
""",
    },
    {
        "id": QUIZ_ID, "title": "Ce que tu as retenu", "mode": "quiz",
        "skills": ["types", "conditions"], "difficulty": "intro",
    },
    {
        "id": "tp2-ex1", "title": "Somme d'un tableau", "mode": "io",
        "skills": ["tableaux", "boucles"], "difficulty": "foundation",
        "asked": "Écris un programme qui affiche la somme des valeurs lues. " + LIRE,
        "cases": [{"stdin": "3\n1\n2\n3\n", "expect": [6]},
                  {"stdin": "4\n10\n20\n30\n40\n", "expect": [100]}],
        "solution": """#include <stdio.h>

int main(void)
{
    int nombre = 0;
    scanf("%d", &nombre);

    long long somme = 0;
    for (int i = 0; i < nombre; i++) {
        int valeur = 0;
        scanf("%d", &valeur);
        somme += valeur;
    }

    printf("Somme : %lld\\n", somme);
    return 0;
}
""",
    },
    {
        "id": "tp2-ex2", "title": "Compter les pairs", "mode": "io",
        "skills": ["boucles", "conditions"], "difficulty": "foundation",
        "asked": "Écris un programme qui affiche combien des valeurs lues sont paires. "
                 + LIRE,
        "cases": [{"stdin": "4\n1\n2\n3\n4\n", "expect": [2]},
                  {"stdin": "3\n7\n9\n11\n", "expect": [0]},
                  {"stdin": "3\n2\n4\n6\n", "expect": [3]}],
        "solution": """#include <stdio.h>

int main(void)
{
    int nombre = 0;
    scanf("%d", &nombre);

    int pairs = 0;
    for (int i = 0; i < nombre; i++) {
        int valeur = 0;
        scanf("%d", &valeur);
        if (valeur % 2 == 0) {
            pairs++;
        }
    }

    printf("Pairs : %d\\n", pairs);
    return 0;
}
""",
    },
    {
        "id": "tp2-ex3", "title": "Le module calcul", "mode": "unity",
        "skills": ["fonctions", "tableaux"], "difficulty": "intermediate",
        "files": [
            {"name": "calcul.h",
             "template": "#ifndef CALCUL_H\n#define CALCUL_H\n\n"
                         "/* Déclare ici les deux prototypes de l'énoncé. */\n\n"
                         "#endif /* CALCUL_H */\n"},
            {"name": "calcul.c", "template": '#include "calcul.h"\n\n'},
        ],
        "solution": {
            "calcul.h": "#ifndef CALCUL_H\n#define CALCUL_H\n\n"
                        "int carre(int n);\n"
                        "double moyenne(const int *valeurs, int nombre);\n\n"
                        "#endif /* CALCUL_H */\n",
            "calcul.c": '#include "calcul.h"\n\n'
                        "int carre(int n)\n{\n    return n * n;\n}\n\n"
                        "double moyenne(const int *valeurs, int nombre)\n{\n"
                        "    if (nombre <= 0) {\n        return 0.0;\n    }\n\n"
                        "    long long somme = 0;\n"
                        "    for (int i = 0; i < nombre; i++) {\n"
                        "        somme += valeurs[i];\n    }\n"
                        "    return (double)somme / nombre;\n}\n",
        },
        "tests": {
            "test_calcul.c": '''#include "unity.h"
#include "calcul.h"

void setUp(void) {}
void tearDown(void) {}

static void test_carre_dun_positif(void)
{
    TEST_ASSERT_EQUAL_INT(49, carre(7));
}

static void test_carre_dun_negatif_est_positif(void)
{
    TEST_ASSERT_EQUAL_INT(49, carre(-7));
}

static void test_moyenne_garde_la_partie_decimale(void)
{
    const int valeurs[] = {3, 4};
    TEST_ASSERT_DOUBLE_WITHIN(1e-9, 3.5, moyenne(valeurs, 2));
}

static void test_moyenne_dun_tableau_vide_vaut_zero(void)
{
    const int valeurs[] = {1};
    TEST_ASSERT_DOUBLE_WITHIN(1e-9, 0.0, moyenne(valeurs, 0));
}

int main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_carre_dun_positif);
    RUN_TEST(test_carre_dun_negatif_est_positif);
    RUN_TEST(test_moyenne_garde_la_partie_decimale);
    RUN_TEST(test_moyenne_dun_tableau_vide_vaut_zero);
    return UNITY_END();
}
''',
        },
    },
]

COLLECTIONS = [
    ("tp1", "TP 1 : premiers programmes", ["tp1-ex1", "tp1-ex2", QUIZ_ID]),
    ("tp2", "TP 2 : tableaux, boucles et modules", ["tp2-ex1", "tp2-ex2", "tp2-ex3"]),
]

CARDS = [
    {"id": "D-01", "name": "Compas", "family": "atelier", "art": "gear",
     "exercises": ["tp1-ex1"],
     "condition": "Réussir le premier exercice"},
    {"id": "D-02", "name": "Ressort", "family": "atelier", "art": "spring",
     "exercises": ["tp2-ex1", "tp2-ex2", "tp2-ex3"],
     "condition": "Réussir tout le TP 2"},
]

QUIZ_ASKED = ("Réponds aux quatre questions ci-dessous. Elles portent sur les types "
              "et sur les conditions vues dans les deux premiers exercices.")

QUIZ_QUESTIONS = [
    {"id": "q1", "group": "Exercice 1 — les types", "type": "int",
     "label": "Combien d'octets occupe un int sur la machine du juge ?", "answer": 4},
    {"id": "q2", "group": "Exercice 1 — les types", "type": "choice",
     "label": "Quel format printf affiche un entier signé ?",
     "options": ["%d", "%s", "%c", "%f"], "answer": "%d"},
    {"id": "q3", "group": "Exercice 2 — les conditions", "type": "bool",
     "label": "En C, 0 est considéré comme faux.", "answer": True},
    {"id": "q4", "group": "Exercice 2 — les conditions", "type": "int",
     "label": "Que vaut 7 / 2 en division entière ?", "answer": 3},
]
