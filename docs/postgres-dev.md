# PostgreSQL local en developpement

La base SQLite historique `kwitli.db` reste intacte. Ne pas executer le seed sur
une base deja peuplee. Arreter le backend et toute autre ecriture avant l'import.
Le script refuse les cibles PostgreSQL non locales et exige le meme HEAD Alembic
des deux cotes. Il compare ensuite toutes les colonnes, tous les identifiants et
les nombres de lignes des 12 tables metier. Une seconde execution identique ne
cree aucun doublon. Les dates SQLite sans fuseau sont interpretees en UTC,
conformement a `backend.app.core.time.as_utc`.

## Sur cette machine (PostgreSQL 18 installe)

Le cluster DEV est dans `.local/postgres` (ignore par Git), avec authentification
locale `peer`, socket Unix `/tmp`, port `55433` et base `kwitli_dev`. Apres un
redemarrage de la machine, le relancer depuis la racine du depot :

```bash
/Library/PostgreSQL/18/bin/pg_ctl -D .local/postgres -o "-k /tmp -p 55433 -h ''" -l .local/postgres.log start
```

`backend/.env` pointe deja vers
`postgresql+psycopg2:///kwitli_dev?host=/tmp&port=55433`. Les donnees SQLite
ont ete importees, puis comparees a PostgreSQL. Le backend se lance avec la
commande habituelle du README. La base SQLite et son backup coherent restent
respectivement `kwitli.db` et
`.local/backups/kwitli-before-postgres-20261009.db`.

## Tests backend PostgreSQL

Le backend utilise PostgreSQL comme base DEV par défaut. Les tests applicatifs
utilisent exclusivement une base locale distincte `kwitli_test`; ils refusent
toute URL de test vers `kwitli_dev`, une base distante ou un autre nom. Le
harnais tronque les tables applicatives avant et après chaque test uniquement
dans `kwitli_test`. Ne lance jamais pytest avec `TEST_DATABASE_URL` vers des
données de développement ou de production.

Créer la base une seule fois (ne pas la supprimer/recréer si elle existe) :

```bash
/Library/PostgreSQL/18/bin/createdb -h /tmp -p 55433 -U kwitli kwitli_test
```

Configurer les URL locales sans secret :

```bash
export DATABASE_URL='postgresql+psycopg2:///kwitli_dev?host=/tmp&port=55433'
export TEST_DATABASE_URL='postgresql+psycopg2:///kwitli_test?host=/tmp&port=55433'
```

Initialiser/mettre à niveau uniquement la base de test, puis lancer la suite :

```bash
ALEMBIC_DATABASE_URL="$TEST_DATABASE_URL" ./.venv/bin/alembic upgrade head
TEST_DATABASE_URL="$TEST_DATABASE_URL" ./.venv/bin/python -m pytest backend/tests -q
```

Le harnais vérifie que `TEST_DATABASE_URL` désigne exactement PostgreSQL local
`kwitli_test`, puis exige que cette base soit migrée par Alembic avant les
tests. Les tests spécialisés du migrateur ou des migrations peuvent encore
utiliser SQLite temporaire comme fixture de compatibilité; ils ne constituent
pas la validation backend finale.

## Installation reproductible avec Docker Compose

Sur une autre machine, installer Docker Compose, copier `.env.example` vers
`.env` a la racine et remplacer le mot de passe factice par un mot de passe
local unique. Ne pas committer `.env`. Le compose expose PostgreSQL seulement
sur `127.0.0.1:5433`.

```bash
docker compose up -d postgres
docker compose ps
```

Dans `backend/.env`, configurer `DATABASE_URL` avec l'utilisateur `kwitli`, le
mot de passe local encode pour une URL, l'hote `127.0.0.1`, le port `5433` et la
base `kwitli_dev`. Ne pas mettre ce mot de passe dans un fichier suivi par Git.

## Migration d'une autre copie SQLite DEV

Ces commandes supposent que PostgreSQL local est demarre et que la cible est
une base vide. La variable `POSTGRES_URL` doit contenir l'URL locale de la cible.
Ne pas pointer vers une base de production.

```bash
mkdir -p .local/backups
sqlite3 kwitli.db ".backup '.local/backups/kwitli-before-postgres.db'"
sqlite3 'file:kwitli.db?mode=ro' 'PRAGMA integrity_check; PRAGMA foreign_key_check; SELECT version_num FROM alembic_version;'
ALEMBIC_DATABASE_URL="$POSTGRES_URL" ./.venv/bin/alembic upgrade head
./.venv/bin/python scripts/migrate_sqlite_to_postgres.py --sqlite kwitli.db --postgres-url "$POSTGRES_URL"
./.venv/bin/python scripts/migrate_sqlite_to_postgres.py --sqlite kwitli.db --postgres-url "$POSTGRES_URL" --apply
```

L'import exige une cible vide ou deja strictement identique. En cas d'echec,
la transaction PostgreSQL est annulee et `kwitli.db` n'est pas ecrite. Ne
changer `DATABASE_URL` dans `backend/.env` qu'apres la comparaison reussie.
Pour les migrations futures sur PostgreSQL, definir explicitement
`ALEMBIC_DATABASE_URL` avec l'URL de la base voulue. `alembic.ini` cible par
défaut `kwitli_test` pour éviter qu'une commande implicite ne modifie `kwitli_dev`.

La base SQLite historique reste une source d'archive/migration uniquement.
Ne pas l'utiliser pour la validation backend courante. Pour revenir
temporairement a SQLite, arreter le backend, remettre
`DATABASE_URL=sqlite:///./kwitli.db` dans `backend/.env`, puis redemarrer.
**Attention :** les ecritures faites sur PostgreSQL apres la bascule ne sont
pas recopiees automatiquement vers SQLite. Le retour arriere exige un choix
explicite de reconciliation des donnees ; ne pas alterner les deux bases en
service.

Les images sont stockees dans `backend/uploads/`, pas dans la base. Conserver ce
repertoire avec ses URL pour que les photos existantes restent accessibles.
