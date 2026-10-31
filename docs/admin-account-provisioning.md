# Provisionnement du compte administrateur staging

Ce CLI est une opération serveur ponctuelle. Il ne crée aucun endpoint et
l'inscription publique ne peut pas attribuer `is_admin`. Il ne doit être lancé
qu'après approbation d'une image qui contient `backend.app.admin_cli`.

## Protections

- Refuse tout contexte autre que `APP_ENV=staging`, l'URL PostgreSQL Compose
  `postgres`, l'utilisateur `kwitli_preproduction` et la base effective
  `kwitli_preproduction`.
- Demande l'e-mail masqué deux fois; la création refuse toute adresse déjà
  présente, quelle que soit sa casse. L'index PostgreSQL unique insensible à la
  casse reste la protection contre les créations concurrentes.
- Le mot de passe est saisi deux fois via `getpass`, jamais dans les arguments,
  l'environnement, l'historique ou les journaux. Minimum 16 caractères, maximum
  128. Le hash utilise `backend.app.security.hash_password`. Si Python ne peut
  pas désactiver l'écho du terminal, le CLI refuse la saisie avant de lire le
  secret; il n'utilise jamais le repli `getpass` qui pourrait afficher l'entrée.
- La récupération ne cible qu'un admin actif et incrémente `auth_version`.
- La révocation exige la confirmation exacte de l'identifiant de compte,
  enlève uniquement `is_admin`, incrémente `auth_version` et ne supprime pas le
  compte.
- Les événements JSON ne contiennent ni e-mail, ni mot de passe, ni hash, ni
  URL de base; ils contiennent l'action, le résultat, l'opérateur OS et l'UUID
  cible. Ils restent dans les logs Docker bornés du conteneur ponctuel, puis
  seule la ligne d'audit est transférée au journal systemd.

Aucune migration ni modification du schéma n'est nécessaire. Les fonctions de
création, récupération et révocation doivent être testées seulement sur une base
PostgreSQL temporaire isolée avant de publier une image.

## Image et périmètre Git

Une nouvelle image API est nécessaire : `backend/Dockerfile` copie
`backend/` dans l'image et Compose ne monte pas le code source. Le fichier
`backend/app/admin_cli.py` est donc inclus à la prochaine construction; aucun
changement Dockerfile ou Compose n'est requis. `backend/tests/` et `docs/` sont
exclus de l'image, mais le workflow CI exécute `backend/tests`, et le guide reste
dans le dépôt.

Le CLI dépend uniquement des champs `User` déjà présents dans le schéma staging
(`is_admin`, `auth_version`), du hachage existant, des settings et de la base.
La migration KYB locale et les autres changements non validés ne sont pas des
dépendances du CLI. Pour une publication ciblée, ne construire qu'un commit
contenant explicitement `backend/app/admin_cli.py`,
`backend/tests/test_admin_cli.py` et ce guide; ne construire aucune image depuis
le répertoire de travail actuel tant qu'il contient d'autres modifications.
La CI doit réussir avant que l'image au tag SHA soit publiée.

Quand le propriétaire autorisera la publication, les changements étant
actuellement mélangés à d'autres fichiers staged/non committés, ajouter puis
committer explicitement uniquement ces chemins. `--only` préserve les autres
entrées déjà staged :

```bash
git add -- backend/app/admin_cli.py backend/tests/test_admin_cli.py docs/admin-account-provisioning.md
git commit --only -m "Add secure staging admin CLI" -- \
  backend/app/admin_cli.py backend/tests/test_admin_cli.py docs/admin-account-provisioning.md
git show --stat --oneline HEAD
git status --short
```

Ne pas construire depuis le working tree local. Le workflow doit publier le tag
SHA de ce commit après `backend-tests` PASS; relever son digest multiarchitecture
depuis le résumé GitHub Actions.

## Préparation ultérieure sur Hetzner

Après autorisation distincte de publier/déployer l'image, ouvrir un terminal
SSH interactif sur Hetzner et se placer dans `/opt/kwitli`. Le PostgreSQL
staging doit déjà être healthy. Le démarrage est direct dans le terminal : ne
pas envelopper la saisie avec `script`, `tee`, une redirection ou un outil
d'enregistrement de session. Une capture de sortie de pseudo-terminal peut
enregistrer les caractères que le terminal aurait ré-echoés si le masquage
échouait. Le CLI refuse désormais le fallback de `getpass`; Compose conserve
son allocation TTY auto-détectée et `--interactive` garde l'entrée ouverte.

Avant l'opération, prendre une sauvegarde staging avec le script Restic déjà
validé. Il n'existe pas d'unité staging dédiée; ne pas démarrer le timer
générique de production. La commande transitoire ci-dessous charge les secrets
depuis le fichier root-only et force le projet, l'env Compose et l'absence de
rétention. Elle n'a pas été exécutée pendant cet audit : vérifier son code de
retour, le snapshot sous `/staging/`, puis `restic check` avant de poursuivre.

```bash
BACKUP_UNIT="kwitli-preproduction-admin-backup-$(date -u +%Y%m%dT%H%M%SZ)"
sudo systemd-run --wait --collect --pipe --unit="$BACKUP_UNIT" \
  --property=WorkingDirectory=/opt/kwitli \
  --property=EnvironmentFile=/etc/kwitli/preproduction.backup.env \
  --setenv=KWITLI_COMPOSE_PROJECT_NAME=kwitli-preproduction \
  --setenv=KWITLI_COMPOSE_ENV_FILE=/etc/kwitli/preproduction.compose.env \
  --setenv=KWITLI_BACKUP_SKIP_RETENTION=1 \
  /usr/bin/bash /opt/kwitli/deploy/backup-postgres.sh
```

Le déploiement du seul CLI ne nécessite pas de redémarrer l'API en service :
mettre temporairement `KWITLI_IMAGE` au digest publié dans le fichier Compose,
faire `pull api`, puis lancer le one-off. Le fichier d'environnement est
sauvegardé root-only avant édition et restauré après; ne pas exécuter `up`.
Compose réutilise néanmoins les réseaux et montages du service `api`; le
PostgreSQL doit donc être healthy. `--no-deps` ne démarre ni ne recrée les
services, aucun port n'est publié. Le conteneur ponctuel est conservé après sa
sortie afin de vérifier son code et transférer l'événement d'audit. La
configuration Docker borne ses logs `json-file`.

```bash
cd /opt/kwitli
test -t 0 && test -t 1 || { echo 'Terminal SSH direct requis.' >&2; exit 2; }
ENV_BACKUP="/etc/kwitli/preproduction.compose.env.before-admin-$(date -u +%Y%m%dT%H%M%SZ)"
sudo install -o root -g root -m 0600 /etc/kwitli/preproduction.compose.env "$ENV_BACKUP"
sudoedit /etc/kwitli/preproduction.compose.env
sudo docker compose --project-name kwitli-preproduction \
  --env-file /etc/kwitli/preproduction.compose.env \
  -f /opt/kwitli/deploy/compose.production.yaml pull api
OPERATOR="$(id -un)"
RUN_NAME="kwitli-admin-create-$(date -u +%Y%m%dT%H%M%SZ)-$$"
sudo -v
sudo docker compose --project-name kwitli-preproduction \
  --env-file /etc/kwitli/preproduction.compose.env \
  -f /opt/kwitli/deploy/compose.production.yaml \
  run --interactive --no-deps --name "$RUN_NAME" \
  -e "KWITLI_ADMIN_OPERATOR=$OPERATOR" \
  api python -m backend.app.admin_cli create
sudo docker inspect --format '{{.State.ExitCode}}' "$RUN_NAME"
sudo docker logs "$RUN_NAME" 2>&1 | grep -E '^\{"action":' | sudo logger --tag kwitli-admin-account
sudo journalctl -t kwitli-admin-account --since today --no-pager
sudo install -o root -g root -m 0600 "$ENV_BACKUP" /etc/kwitli/preproduction.compose.env
```

Dans `sudoedit`, changer uniquement `KWITLI_IMAGE` pour le digest publié; ne
pas afficher le fichier. Après le `pull`, le one-off utilise cette image, mais
le conteneur API déjà actif reste sur son image actuelle. Le script ci-dessus
doit être lancé dans un terminal SSH normal, sans wrapper ni redirection. Le
`sudo -v` peut demander le mot de passe système `kwitliadmin`; l'adresse et le
mot de passe de compte sont saisis ensuite, masqués par le CLI.

Compose auto-alloue son TTY lorsque l'entrée et la sortie sont des terminaux;
ne pas ajouter `--no-tty` ni exécuter par un pipe. Le CLI demande deux fois l'adresse dédiée,
puis deux fois le mot de passe; toutes ces saisies sont masquées. Le conteneur
conservé permet de vérifier le code de sortie et de transférer uniquement les
lignes JSON d'audit (sans recopier les prompts) vers journald. Vérifier le
journal, puis supprimer seulement ce conteneur arrêté avec
`sudo docker rm "$RUN_NAME"`. Si le code de sortie est non nul ou si aucun
événement d'audit attendu n'est présent, ne pas relancer à l'aveugle : inspecter
l'état de ce conteneur et vérifier si l'opération a déjà abouti.

Si la création est confirmée mais que l'accès échoue, conserver l'image publiée
et refaire le même one-off avec `revoke` pour ce compte; cela retire son rôle et
révoque ses sessions sans supprimer le compte. Si l'opération est incertaine,
ne pas la répéter : consulter d'abord le code de sortie, le journal d'audit et
la page admin. Pour un échec avant la création, restaurer immédiatement
`$ENV_BACKUP`; l'API en service n'a pas été redémarrée et reste inchangée.

Pour récupérer le mot de passe d'un compte déjà admin, remplacer `create` par
`recover` et `RUN_NAME` par un nom distinct; pour révoquer son rôle sans
supprimer le compte, utiliser `revoke`.
Ces actions demandent l'adresse masquée et une confirmation explicite liée à
l'UUID cible. Elles ne peuvent pas promouvoir un compte existant.

## Vérifications après opération

Dans le terminal SSH, vérifier le résultat audité sans afficher d'identifiants :

```bash
sudo journalctl -t kwitli-admin-account --since today --no-pager
```

Puis ouvrir `https://api.kwitli.app/admin` dans une fenêtre privée et tester
l'authentification Basic avec le compte dédié. Vérifier aussi qu'un compte
client/commerçant non admin reste refusé. Ne pas transmettre la sortie du
journal, l'adresse ou les identifiants dans un ticket public.

Si l'adresse saisie était incorrecte, utiliser `revoke` pour retirer le rôle;
le compte est conservé, aucune donnée n'est supprimée. Une récupération de mot
de passe ne change jamais le rôle.

Ce runbook ne publie pas l'image et n'exécute aucune opération sur staging.
