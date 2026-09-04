# L'image de l'API. Elle ne contient QUE des dépendances : le code, lui, est
# monté en lecture seule depuis le clone git (voir le rôle `ctester` de VHome).
# Reconstruire l'image n'est donc nécessaire que pour changer une version
# épinglée -- déployer une correction de l'API reste un `git pull`.
FROM python:3.13-slim

# Pas de .pyc : le conteneur tourne en `read_only`, et Python passerait son
# temps à essayer d'écrire à côté d'un code monté en lecture seule. Pas de
# tampon non plus, sinon les erreurs n'apparaissent dans `docker logs` qu'après
# coup -- exactement quand on les cherche.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# LES DÉPENDANCES DE TEST N'ENTRENT PAS ICI : `requirements.txt` seulement,
# jamais `requirements-dev.txt`.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# `nobody`, comme dans le Compose. Le processus exposé à Internet n'a aucune
# raison d'être root, et il ne peut de toute façon rien écrire : son code est en
# lecture seule et le seul chemin inscriptible est le spool.
USER 65534:65534

WORKDIR /app
EXPOSE 8000

# `main.py` ET PAS `uvicorn --workers N` : le nombre de workers est une
# propriété de correction ici, pas de performance (quotas, présence et cache de
# jetons sont en mémoire de processus). Il est donc fixé dans le code, où
# personne ne le recopiera à côté. Voir le docstring de `app/main.py`.
CMD ["python3", "/app/main.py"]
