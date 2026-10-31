# Conteneuriser le backend Kwitli

Cette configuration prépare un lancement Docker local ou futur sur un serveur. Elle ne déploie rien et n'exécute aucune migration au démarrage.

## Configuration

Depuis la racine du dépôt, copier `.env.example` vers `.env` uniquement si `.env` n'existe pas déjà, puis remplacer les valeurs factices. Ne jamais écraser un `.env` existant ni commiter ce fichier. Compose doit être en version 2.24 ou ultérieure pour accepter le fichier d'environnement facultatif.

`DATABASE_URL` doit utiliser le nom du service Compose `postgres` et le port interne `5432`, pas `localhost`, le port hôte `5433` ou le serveur local `55433`. Le mot de passe doit être URL-encodé s'il contient des caractères réservés. `KWITLI_POSTGRES_PASSWORD` et le mot de passe dans `DATABASE_URL` doivent désigner le même secret. L'exemple utilise la base isolée `kwitli_docker`, jamais `kwitli_dev` ou `kwitli_test`.

Le service API reçoit `DATABASE_URL` ainsi que `ALEMBIC_DATABASE_URL`, explicitement alignés. Cela évite que Alembic utilise par défaut la valeur de test inscrite dans `alembic.ini`. Aucun service de test Docker n'est défini et le dossier des tests est exclu de l'image. Pour valider Compose sans modifier `.env`, les variables interpolées peuvent être fournies dans l'environnement du shell. Le fichier `.env` reste facultatif et, s'il existe, fournit les paramètres optionnels au conteneur.

## Construire et démarrer

```sh
docker compose build api
docker compose up -d postgres
docker compose ps
```

Avant toute migration, vérifier le nom de la base et l'hôte affichés par `docker compose config`. La migration est une opération séparée et explicite, jamais exécutée par l'entrypoint :

```sh
docker compose run --rm api alembic upgrade head
docker compose up -d api
```

L'API est publiée uniquement sur `127.0.0.1:8000`, pour permettre un reverse proxy local sans exposer directement Uvicorn sur Internet. Le healthcheck appelle `GET /api/v1/health` depuis le conteneur. Les fichiers téléversés sont conservés dans le volume Docker `kwitli_uploads`.

## Exploitation

```sh
docker compose logs -f api
docker compose logs -f postgres
docker compose stop api
docker compose stop
```

`docker compose stop` conserve les volumes et les données. Ne pas utiliser `docker compose down -v`.

## Limites avant Hetzner

Cette configuration ne fournit ni TLS/reverse proxy, ni sauvegarde PostgreSQL, ni rotation de secrets, ni supervision. Elle ne constitue pas une configuration de production prête à exposer. Les tests backend restent sur `kwitli_test` hors de cette pile; ne jamais remplacer leur `TEST_DATABASE_URL` par `DATABASE_URL`, `kwitli_dev` ou une base de production.
