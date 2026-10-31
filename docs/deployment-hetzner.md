# Préparer le déploiement Hetzner

Ce document prépare une procédure, il ne crée ni serveur ni ressource cloud. Le workflow publie une image; il ne déploie jamais l'application.

## État et blocage de mise en production

Le backend est encore configuré pour les fournisseurs de paiement en mode test/sandbox (`WOMPI_ENV=sandbox`, `PAYU_ENV=sandbox`, `PAYDUNYA_MODE=sandbox`, Flutterwave et PayTech limités au test). Le code refuse aussi XOF hors des environnements development/test. Il ne faut donc pas utiliser cette configuration pour recevoir de vrais paiements ni lancer un pilote payant. La production restera bloquée jusqu'à une validation séparée du mode live, du parcours financier et des secrets fournisseur. Ce chantier ne modifie aucun flux de paiement.

Aucun middleware CORS n'est actuellement configuré dans l'API; aucune règle permissive `*` n'est donc active. L'application mobile native n'en a pas besoin. Si un client web est introduit, ajouter alors des origines HTTPS explicites, jamais `*` avec des credentials.

## Premier démarrage : préproduction contrôlée

La première instance Hetzner est une préproduction à données fictives, pas une production commerciale. Utiliser les modèles `deploy/preproduction.compose.env.example` et `deploy/preproduction.api.env.example` comme liste de variables, puis créer les vrais fichiers uniquement sous `/etc/kwitli` avec propriétaire `root:root` et mode `0600`. Remplacer les placeholders sur le serveur; ne pas copier de secrets dans le dépôt. Définir explicitement `KWITLI_APP_ENV=staging`. Compose refuse désormais une valeur implicite de l'environnement.

Le code réserve actuellement le checkout XOF à `development` et `test`, et les adaptateurs Flutterwave, PayTech et PayDunya refusent aussi `staging`. Ne pas changer `APP_ENV` en `development` ou `test` pour contourner cette protection sur une machine publique. Les clés de tous les fournisseurs et Resend restent vides dans le profil initial; les paiements, remboursements, payouts et envois de courriel ne sont pas validés ni activés. Aucun appel de paiement ou courriel ne fait partie du démarrage contrôlé.

Avant le premier `up`, sélectionner un manifeste GHCR multiarchitecture par digest issu d'un workflow réussi et vérifier qu'il contient `linux/arm64`. Contrôler le rendu Compose et l'absence d'un volume préexistant sous le nom du projet choisi. Le premier `docker compose up -d postgres` créera un volume PostgreSQL persistant; l'application d'Alembic est une étape d'écriture ultérieure distincte. Ces deux opérations restent en attente d'une autorisation explicite. Ne pas démarrer Caddy tant que le DNS et l'émission HTTPS ne sont pas autorisés : son démarrage publie les ports web et déclenche l'obtention d'un certificat.

Après autorisation du premier démarrage, la procédure staging se déroule depuis `/opt/kwitli`. Installer les deux modèles comme fichiers root-only, les éditer sur le serveur, sélectionner un nom de projet neuf et vérifier l'image par digest avant toute création de volume :

```sh
sudo install -d -o root -g root -m 0700 /etc/kwitli
sudo install -o root -g root -m 0600 deploy/preproduction.compose.env.example /etc/kwitli/preproduction.compose.env
sudo install -o root -g root -m 0600 deploy/preproduction.api.env.example /etc/kwitli/preproduction.api.env
sudoedit /etc/kwitli/preproduction.compose.env
sudoedit /etc/kwitli/preproduction.api.env
sudo docker buildx imagetools inspect "$(sudo sed -n 's/^KWITLI_IMAGE=//p' /etc/kwitli/preproduction.compose.env)"
sudo docker compose --project-name kwitli-preproduction --env-file /etc/kwitli/preproduction.compose.env -f deploy/compose.production.yaml config --quiet
sudo docker volume inspect kwitli-preproduction_postgres_data
```

La dernière commande doit indiquer que le volume n'existe pas encore; si elle le trouve, arrêter et inspecter avant d'utiliser ce nom de projet. Générer les deux secrets uniquement sur le serveur avec `openssl rand -hex 32`, puis saisir la valeur PostgreSQL identique dans `KWITLI_POSTGRES_PASSWORD` et `DATABASE_URL`; ne jamais afficher ces valeurs ou les transmettre à Codex. Vérifier manuellement que le digest est celui du manifeste `linux/arm64` publié après CI. Les commandes qui suivent modifient l'état serveur :

```sh
sudo docker compose --project-name kwitli-preproduction --env-file /etc/kwitli/preproduction.compose.env -f deploy/compose.production.yaml pull api
sudo docker compose --project-name kwitli-preproduction --env-file /etc/kwitli/preproduction.compose.env -f deploy/compose.production.yaml up -d postgres
sudo docker compose --project-name kwitli-preproduction --env-file /etc/kwitli/preproduction.compose.env -f deploy/compose.production.yaml run --rm --no-deps api alembic upgrade head
sudo docker compose --project-name kwitli-preproduction --env-file /etc/kwitli/preproduction.compose.env -f deploy/compose.production.yaml up -d api
sudo docker compose --project-name kwitli-preproduction --env-file /etc/kwitli/preproduction.compose.env -f deploy/compose.production.yaml ps
sudo docker inspect --format '{{json .State.Health}}' kwitli-preproduction-api-1
```

`up -d postgres` initialise la base et crée son volume; `alembic upgrade head` écrit le schéma; ces deux étapes exigent l'autorisation explicite déjà demandée. Ce profil ne lance pas Caddy, ne configure pas le DNS et ne permet pas les paiements XOF. Après validation du healthcheck interne, l'exposition HTTPS et un parcours avec PSP de test nécessitent une décision et une préparation séparées.

## Phase D : DNS, HTTPS et accès mobile — préparation seulement

La phase C n'a pas encore été confirmée sur Hetzner : PostgreSQL, migration Alembic, API et healthcheck interne restent **non vérifiés sur le serveur**. Aucun DNS, certificat, port public ou service ne doit être activé avant cette validation et une autorisation explicite.

La configuration Caddy existante reçoit `api.kwitli.app` et relaie vers `api:8000` sur le réseau `edge`. Caddy active automatiquement HTTPS et la redirection HTTP vers HTTPS pour ce nom public, conserve l'état des certificats dans `caddy_data` et `caddy_config`, et `reverse_proxy` transmet les en-têtes proxy usuels dont `Host` et `X-Forwarded-Proto`. Le fichier remplace `CF-Connecting-IP` par l'hôte source observé par Caddy. Cela correspond au mode DNS-only prévu : ne pas activer le proxy Cloudflare sans revoir explicitement la chaîne de confiance des IP clientes. [Documentation Automatic HTTPS](https://caddyserver.com/docs/automatic-https), [documentation reverse_proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy).

Compose ne publie maintenant que TCP 80 et 443 pour Caddy. UDP 443 n'est pas publié : HTTP/3 n'est donc pas proposé dans cette première mise en service et aucune règle pare-feu UDP n'est requise. PostgreSQL et l'API n'ont aucun port hôte publié. Garder TCP 22 pour l'administration; avant activation, vérifier dans la console Hetzner les règles IPv4/IPv6 de TCP 80/443 et l'absence d'accès public à 5432/8000. L'état actuel du pare-feu n'a pas été vérifié dans cette phase. Sans validation de l'IPv6 côté serveur et pare-feu, ne pas créer d'enregistrement AAAA.

Enregistrement prévu, non créé : `A api.kwitli.app → 159.69.252.236`, proxy Cloudflare désactivé (DNS-only). Aucun changement à `api-dev.kwitli.app`, aux tunnels ou aux règles Cloudflare. Les requêtes DNS publiques et l'accès à la zone Cloudflare n'ont pas pu être vérifiés depuis l'environnement de travail; confirmer les enregistrements A, AAAA, CNAME, CAA et NS dans le dashboard avant activation.

L'application mobile a une configuration partagée : `mobile/src/config.ts` résout les URL DEV, tandis que `mobile/eas.json` définit le profil `preview-android` en APK interne avec `https://api.kwitli.app` injecté au build. Ce profil n'a pas encore été exécuté; il faut lier le projet à EAS et vérifier le quota/coût du compte avant de lancer le build. Les URL locales iOS/Android restent réservées au code DEV. Aucun parcours plateforme distinct n'est ajouté.

Ordre d'activation après autorisations : confirmer les conteneurs et le healthcheck interne de la phase C; contrôler le pare-feu Hetzner et l'IPv6; vérifier les DNS existants puis, après accord, créer uniquement l'enregistrement A DNS-only; vérifier sa propagation; après accord, démarrer Caddy avec ses volumes persistants; contrôler le certificat, la redirection HTTP, `/api/v1/health`, et l'absence d'accès externe à 5432/8000; enfin tester l'URL HTTPS depuis un appareil iOS et un Android avec la même configuration d'environnement. Toute étape publique demeure en attente.

## GitHub Actions et GHCR

`.github/workflows/backend-image.yml` lance la suite backend sur un PostgreSQL éphémère local au runner, puis publie un manifeste `linux/amd64` + `linux/arm64` seulement si les tests réussissent et seulement pour `main` ou un lancement manuel sur `main`. Les deux architectures partagent le tag immuable `sha-<commit-complet>`; Buildx publie le manifeste et ses deux images enfants. Il n'y a aucune étape de déploiement.

La suite migre uniquement sa base CI jetable `kwitli_test`. Le conteneur PostgreSQL CI écoute sur le loopback du runner et un port isolé afin de satisfaire la protection de `backend/tests/conftest.py`; il n'utilise jamais les bases du Mac.

Le job de test n'a que `contents: read`. Le job de publication reçoit `contents: read` et `packages: write`, utilise le `GITHUB_TOKEN` du dépôt et publie uniquement `ghcr.io/<owner>/kwitli-api:sha-<commit-complet>`. Le workflow interroge GHCR et refuse de pousser si ce tag existe déjà; les exécutions d'une branche sont sérialisées. Aucun tag mutable `latest` n'est publié. Le digest affiché dans le résumé de l'étape Buildx identifie le manifeste multiarchitecture; enregistrer et déployer `ghcr.io/<owner>/kwitli-api@sha256:...` plutôt que le tag. Les tags SHA AMD64 déjà publiés ne sont ni remplacés ni modifiés : la première image multiarchitecture sera attachée à un nouveau SHA après cette modification. Le package GHCR créé par le workflow doit rester lié au dépôt Kwitli et sa visibilité doit être choisie avant le premier push CI.

### Compatibilité ARM64 préparée

Le Dockerfile reste unique et ne fixe pas de plateforme : Buildx construit le même backend Python pour `linux/amd64` et `linux/arm64`. Vérification runtime locale du 25 octobre 2026 : image `linux/arm64`, Python 3.14.3, FastAPI 0.141.1, SQLAlchemy 2.0.52, psycopg2-binary 2.9.12 et Pillow 12.3.0 importés et exécutés sur un daemon Linux ARM64; Pillow a également encodé/décodé une image. Aucune dépendance n'a été changée. `cryptography` n'est pas dans `backend/requirements.txt` et n'est pas importé par le backend; il n'est donc pas nécessaire à l'image.

Le test a appliqué explicitement toutes les migrations à un PostgreSQL 18.3 jetable, démarré FastAPI, reçu HTTP 200 sur `/api/v1/health`, puis vérifié le reverse proxy Caddy. PostgreSQL était sur un réseau Docker interne sans port publié. Le scan du système de fichiers applicatif n'a trouvé ni `.env`, base SQLite, sauvegarde ni fichier de clé/certificat. Le compte runtime reste `kwitli` non-root. Il s'agit d'une validation d'image et d'exécution locale ARM64, pas d'un essai sur un serveur CAX21.

L'image officielle PostgreSQL 18.3 et l'image Caddy utilisées par Compose sont multiarchitecture; Restic est un binaire Go disponible pour Linux ARM64. Docker Engine officiel prend en charge Ubuntu ARM64, y compris Ubuntu 26.04 LTS selon sa documentation actuelle. Aucun réglage `platform:` ou changement applicatif n'est requis dans Compose : le manifeste choisit l'image API correspondant à l'architecture du serveur. Sur la machine cible, confirmer toutefois la version Ubuntu proposée par Hetzner, installer Docker Engine/Compose officiels et vérifier par `docker image inspect` que le digest tiré expose `linux/arm64`.

Si le package reste privé, le serveur doit s'authentifier avec un compte technique/token limité à `read:packages`; effectuer `docker login ghcr.io --username <compte> --password-stdin` en passant le token par stdin. Garder l'authentification Docker sous `/root` (permissions restrictives), jamais dans le dépôt, les logs ou `production.env`.

## Serveur, réseau et HTTPS

Au moment du déploiement, choisir une image Ubuntu LTS encore prise en charge, installer Docker Engine et le plugin Compose depuis le dépôt officiel Docker, puis appliquer les mises à jour de sécurité. Docker Engine officiel prend en charge Ubuntu 26.04 LTS sur ARM64; confirmer que cette image est proposée pour le CAX21 à Falkenstein au moment de la commande.

Avant de créer les réseaux Compose, vérifier qu'aucun réseau Docker/hôte ne chevauche `172.30.0.0/24`. Caddy reçoit `172.30.0.2`; l'API reçoit `172.30.0.3`. Le serveur doit définir `TRUSTED_PROXY_IPS=172.30.0.2`. Caddy réécrit `CF-Connecting-IP` depuis l'adresse de connexion entrante; l'API ne doit faire confiance qu'à ce proxy précis. Si le subnet est changé, changer les IP statiques et `TRUSTED_PROXY_IPS` ensemble.

Dans le pare-feu Hetzner, autoriser TCP 80/443 et UDP 443 depuis Internet; autoriser SSH TCP 22 uniquement depuis l'adresse/CIDR d'administration. Configurer les règles IPv4 et IPv6. Ne pas publier 8000 ni 5432. Le pare-feu cloud est important car les ports publiés par Docker peuvent contourner certaines règles UFW/nftables locales.

Créer l'enregistrement DNS `A api.kwitli.app` vers l'IPv4 du serveur. N'ajouter un `AAAA` que si IPv6 est effectivement configuré et filtré. Caddy demande et renouvelle automatiquement le certificat ACME; conserver ses volumes `caddy_data` et `caddy_config`. Les ports 80/443 doivent être joignables pour l'émission et le renouvellement.

Installer la copie du dépôt dans `/opt/kwitli`. Créer deux fichiers `root:root`, mode `0600`, hors du dépôt et hors du contexte/image Docker. `/etc/kwitli/production.env` sert uniquement à l'interpolation Compose; `/etc/kwitli/api.env` contient les secrets applicatifs. Le mot de passe PostgreSQL ne doit pas être copié dans `api.env` :

```dotenv
KWITLI_APP_ENV=production
KWITLI_IMAGE=ghcr.io/<owner>/kwitli-api@sha256:<digest-du-manifeste-multiarchitecture>
KWITLI_API_ENV_FILE=/etc/kwitli/api.env
KWITLI_POSTGRES_DB=kwitli
KWITLI_POSTGRES_USER=kwitli
KWITLI_POSTGRES_PASSWORD=<secret-aleatoire-url-safe>
DATABASE_URL=postgresql+psycopg2://kwitli:<meme-secret>@postgres:5432/kwitli
PUBLIC_API_URL=https://api.kwitli.app
TRUSTED_PROXY_IPS=172.30.0.2
```

Dans `/etc/kwitli/api.env`, placer seulement `SECRET_KEY=<secret-aleatoire-distinct-de-64-caracteres-hex>` et les futurs secrets applicatifs requis. Ne pas y placer `POSTGRES_PASSWORD`, `DATABASE_URL`, `ALEMBIC_DATABASE_URL` ni les paramètres Compose. Compose injecte séparément les deux URLs DB dans l'API; PostgreSQL seul reçoit `POSTGRES_PASSWORD`.

Générer les valeurs avec un générateur cryptographique (`openssl rand -hex 32`), jamais avec un mot de passe du dépôt. Le mot de passe PostgreSQL de l'URL doit être URL-encodé si des caractères non URL-safe sont employés. Ne pas placer de clés sandbox/test comme clés live; en l'état, aucun secret de paiement live ne doit être injecté.

## Premier démarrage

Les commandes ci-dessous sont préparées, pas exécutées. Vérifier les valeurs et la cible avant de les lancer.

```sh
cd /opt/kwitli
sudo docker compose --env-file /etc/kwitli/production.env -f deploy/compose.production.yaml config --quiet
sudo docker compose --env-file /etc/kwitli/production.env -f deploy/compose.production.yaml pull api
sudo docker compose --env-file /etc/kwitli/production.env -f deploy/compose.production.yaml up -d postgres
sudo docker compose --env-file /etc/kwitli/production.env -f deploy/compose.production.yaml run --rm --no-deps api alembic upgrade head
sudo docker compose --env-file /etc/kwitli/production.env -f deploy/compose.production.yaml up -d api caddy
sudo docker compose --env-file /etc/kwitli/production.env -f deploy/compose.production.yaml ps
curl --fail --show-error https://api.kwitli.app/api/v1/health
```

La migration est une commande explicite distincte. Aucun entrypoint ne lance Alembic. Pour une première installation, sauvegarder également l'état initial et vérifier les logs API/Caddy avant d'ouvrir le trafic pilote.

## Mise à jour contrôlée

1. Vérifier que le CI du commit ciblé est vert et que son image `sha-...` existe dans GHCR.
2. Réaliser une sauvegarde PostgreSQL et vérifier son succès avant toute migration.
3. Obtenir le digest multiarchitecture du SHA validé dans le résumé GitHub Actions et mettre `KWITLI_IMAGE` à `ghcr.io/<owner>/kwitli-api@sha256:<digest>` dans le fichier protégé.
4. `docker compose pull api`, lancer `run --rm --no-deps api alembic upgrade head`, puis `up -d api`.
5. Vérifier `ps`, `/api/v1/health`, les logs et un parcours métier de test autorisé.

Ne pas faire de `docker compose down -v`. Ne pas faire tourner deux versions concurrentes sur la même base si les changements de schéma ne sont pas compatibles.

## Retour arrière

Pour un défaut applicatif sans changement de schéma incompatible, remettre `KWITLI_IMAGE` au digest précédent, `pull api`, puis `up -d api`. Ne pas lancer automatiquement `alembic downgrade` : les migrations peuvent être irréversibles ou destructives. Si une migration a changé le schéma de façon incompatible, arrêter les écritures et restaurer une sauvegarde validée dans une base/volume isolé, vérifier cette copie, puis planifier un cutover contrôlé. Ne jamais restaurer directement par-dessus la base en service sans procédure spécifique approuvée.

## Sauvegardes PostgreSQL chiffrées dans Cloudflare R2

Le script `deploy/backup-postgres.sh` effectue `pg_dump -Fc` depuis le conteneur PostgreSQL et transmet le dump sur stdin à `restic backup`. Il archive aussi le volume persistant d'uploads depuis le conteneur API avec le module Python `tarfile`, puis envoie cette archive sur stdin à Restic. Aucun dump ou tar temporaire n'est écrit sur le serveur. Les deux sauvegardes sont des snapshots Restic séparés; la base est cohérente grâce à `pg_dump`, et les fichiers image sont ajoutés de façon atomique par l'application. `set -Eeuo pipefail` fait échouer le service si une lecture, Restic ou la rétention échoue. Les noms internes fixes conservent le même chemin Restic à chaque exécution; `forget --group-by host,tags` applique séparément la rétention aux snapshots marqués `postgres` et `uploads`. Restic chiffre et authentifie les données côté serveur avant envoi; le bucket doit rester privé.

Le volume `uploads` contient les images applicatives et est inclus. Les volumes `caddy_data` et `caddy_config` ne le sont pas : la configuration Caddy est dans le dépôt et ses certificats peuvent être réémis par ACME au rétablissement du service. La restauration décrite ci-dessous couvre la base et les uploads; elle ne restaure pas l'état local des certificats TLS.

Le bucket fourni est `kwitli-restic-backups`, juridiction UE et classe Standard. Pour une juridiction UE, l'endpoint doit inclure `.eu.` : `https://<ACCOUNT_ID>.eu.r2.cloudflarestorage.com`; la région S3 est `auto`. La configuration complète sans secret est dans [`deploy/backup.env.example`](../deploy/backup.env.example). Son dépôt actif est sous `/production`; tout test doit employer un chemin différent sous `/validation/<identifiant-unique>`. Restic documente la forme `s3:https://endpoint/bucket/path`, `AWS_DEFAULT_REGION` et `RESTIC_PASSWORD_FILE` pour les backends compatibles S3 ([Restic](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html)); Cloudflare impose l'endpoint de juridiction correspondant ([R2 data location](https://developers.cloudflare.com/r2/reference/data-location/)).

Le jeton R2 utilisé par le serveur doit conserver le droit **Object Read & Write**, limité à ce seul bucket; ne pas lui donner d'accès de gestion de compte ou de buckets. Le secret S3 et le mot de passe Restic sont deux identifiants différents. Ne jamais les mettre dans le dépôt, une commande en clair, les logs ou l'image.

Le timer `kwitli-backup.timer` charge `/etc/kwitli/backup.env`, mais le script cible par défaut `/etc/kwitli/production.env` et le projet Compose implicite : il ne sauvegarde donc pas automatiquement `kwitli_preproduction`. Pour la première sauvegarde staging, utiliser un dépôt neuf sous `/staging/`, définir explicitement `KWITLI_COMPOSE_PROJECT_NAME=kwitli-preproduction` et `KWITLI_COMPOSE_ENV_FILE=/etc/kwitli/preproduction.compose.env`, puis lancer `backup-postgres.sh` avec `KWITLI_BACKUP_SKIP_RETENTION=1`. Le script vérifie alors le nom de base, les volumes PostgreSQL/uploads attendus et l'absence de ports hôte; il refuse les dépôts hors `/staging/` et omet `forget --prune`. La valeur par défaut reste `0` pour préserver la rétention existante. Ne pas créer ni activer un timer staging avant une sauvegarde, un `restic check` et une restauration isolée réussis. Les erreurs systemd sont visibles dans son état et son journal, mais aucune alerte externe n'est configurée.

### Saisie locale des secrets

À faire directement sur le futur serveur, sans transmettre les valeurs à Codex :

```sh
sudo install -d -o root -g root -m 0700 /etc/kwitli
sudo install -o root -g root -m 0600 /opt/kwitli/deploy/backup.env.example /etc/kwitli/backup.env
sudoedit /etc/kwitli/backup.env
sudo sh -c 'umask 077; openssl rand -base64 48 > /etc/kwitli/restic-password'
sudo chown root:root /etc/kwitli/backup.env /etc/kwitli/restic-password
sudo chmod 0600 /etc/kwitli/backup.env /etc/kwitli/restic-password
```

Dans `backup.env`, remplacer localement `<ACCOUNT_ID>` et les deux placeholders R2 à partir du gestionnaire de mots de passe; ne pas copier le mot de passe PostgreSQL dans ce fichier. Garder une copie de récupération du mot de passe Restic dans le gestionnaire de mots de passe. Sa perte rend les données chiffrées irrécupérables. Le motif `/deploy/backup*.env` dans `.gitignore` protège les fichiers locaux portant ce nom; seul le modèle `.env.example` est suivi par Git.

### Validation R2 isolée avant initialisation de production

Les identifiants R2 n'étaient pas présents dans l'environnement de développement lors de la préparation. Aucune connexion R2, initialisation distante, sauvegarde ou restauration R2 n'est donc déclarée réussie. Après saisie locale des secrets, créer la configuration et un mot de passe Restic de test distinct. Ne jamais réutiliser le dépôt `/production` pour ce test :

```sh
sudo install -o root -g root -m 0600 /opt/kwitli/deploy/backup.env.example /etc/kwitli/backup-r2-validation.env
sudoedit /etc/kwitli/backup-r2-validation.env
sudo sh -c 'umask 077; openssl rand -base64 48 > /etc/kwitli/restic-validation-password'
sudo chown root:root /etc/kwitli/backup-r2-validation.env /etc/kwitli/restic-validation-password
sudo chmod 0600 /etc/kwitli/backup-r2-validation.env /etc/kwitli/restic-validation-password
```

Dans ce fichier de validation, régler `RESTIC_REPOSITORY` sur un dépôt neuf sous `.../kwitli-restic-backups/validation/<identifiant-aléatoire>` et `RESTIC_PASSWORD_FILE=/etc/kwitli/restic-validation-password`. Conserver l'endpoint et les variables AWS du modèle. Vérifier le chemin `validation/` avant chaque `init`.

Créer un petit fichier temporaire et lancer les opérations à travers une unité transitoire systemd. `EnvironmentFile` charge les secrets sans les placer dans les arguments ou l'historique du shell :

```sh
sudo install -d -o root -g root -m 0700 /var/tmp/kwitli-r2-validation
sudo sh -c 'umask 077; printf "validation R2 initiale\\n" > /var/tmp/kwitli-r2-validation/payload.txt'
sudo systemd-run --wait --pipe --collect \
  --property=EnvironmentFile=/etc/kwitli/backup-r2-validation.env \
  /usr/bin/restic init
sudo systemd-run --wait --pipe --collect \
  --property=EnvironmentFile=/etc/kwitli/backup-r2-validation.env \
  /usr/bin/bash -c '/usr/bin/restic backup --stdin --stdin-filename payload.txt --tag r2-validation < /var/tmp/kwitli-r2-validation/payload.txt'
sudo sh -c 'printf "validation R2 mise a jour\\n" > /var/tmp/kwitli-r2-validation/payload.txt'
sudo systemd-run --wait --pipe --collect \
  --property=EnvironmentFile=/etc/kwitli/backup-r2-validation.env \
  /usr/bin/bash -c '/usr/bin/restic backup --stdin --stdin-filename payload.txt --tag r2-validation < /var/tmp/kwitli-r2-validation/payload.txt'
sudo systemd-run --wait --pipe --collect \
  --property=EnvironmentFile=/etc/kwitli/backup-r2-validation.env \
  /usr/bin/restic forget --tag r2-validation --keep-last 1 --prune
sudo systemd-run --wait --pipe --collect \
  --property=EnvironmentFile=/etc/kwitli/backup-r2-validation.env \
  /usr/bin/restic check --read-data
sudo systemd-run --wait --pipe --collect \
  --property=EnvironmentFile=/etc/kwitli/backup-r2-validation.env \
  /usr/bin/restic restore latest --target /var/tmp/kwitli-r2-validation/restore
sudo cmp /var/tmp/kwitli-r2-validation/payload.txt \
  /var/tmp/kwitli-r2-validation/restore/payload.txt
```

Les commandes doivent réussir, `restic check --read-data` doit terminer sans erreur, et `cmp` doit retourner 0. Ce test valide aussi les droits d'écriture/suppression nécessaires au `forget --prune` de production. Il laisse son dépôt distant sous le seul préfixe `/validation/<identifiant-aléatoire>`; après vérification, supprimer éventuellement ce préfixe de test explicitement dans Cloudflare en contrôlant le chemin complet. Ne supprimer aucun autre objet. Les fichiers locaux de validation peuvent ensuite être retirés par leur chemin exact.

Après ce test seulement, configurer `/etc/kwitli/backup.env` sur `/production`, vérifier visuellement le chemin, puis initialiser le dépôt de production une seule fois :

```sh
sudo systemd-run --wait --pipe --collect \
  --property=EnvironmentFile=/etc/kwitli/backup.env \
  /usr/bin/restic init
sudo install -o root -g root -m 0644 /opt/kwitli/deploy/systemd/kwitli-backup.service /etc/systemd/system/kwitli-backup.service
sudo install -o root -g root -m 0644 /opt/kwitli/deploy/systemd/kwitli-backup.timer /etc/systemd/system/kwitli-backup.timer
sudo systemctl daemon-reload
sudo systemctl enable --now kwitli-backup.timer
```

Systemd et le journal détectent et conservent l'échec du service, mais aucune notification externe n'est configurée ici; prévoir une vérification/alerte opérationnelle avant de dépendre de ces sauvegardes.

### Rétention, contrôle et restauration PostgreSQL

`kwitli-backup.timer` est déjà planifié chaque jour à 02:30 UTC avec `Persistent=true`. Une seule instance de `kwitli-backup.service` tourne à la fois; Restic ajoute son verrou de dépôt. Le service est `Type=oneshot` : un code d'erreur du script place l'unité en échec et les sorties sont consultables dans le journal systemd. Contrôler régulièrement `systemctl status kwitli-backup.service`, `journalctl -u kwitli-backup.service` et la dernière sauvegarde avec `restic snapshots`. La rétention existante reste 7 quotidiennes, 5 hebdomadaires et 12 mensuelles. Pour contrôler l'intégrité sans télécharger chaque pack à chaque exécution, lancer périodiquement `restic check`, puis répartir une lecture complète avec `restic check --read-data-subset=1/4` à `4/4`; le test initial isolé ci-dessus utilise `--read-data` sur un dépôt minuscule. Une restauration de contrôle réelle reste nécessaire régulièrement.

Pour restaurer, démarrer un conteneur PostgreSQL 18.3 temporaire sur un réseau Docker `--internal`, sans option `-p` ni volume existant, et créer une base vierge dédiée au contrôle. Lister les snapshots avec `restic snapshots --tag postgres` et `restic snapshots --tag uploads`, puis sélectionner séparément les identifiants des snapshots les plus récents réussis. Dans un shell avec `set -o pipefail`, exécuter `restic dump <id-postgres> kwitli-postgres.dump | docker exec -i <conteneur-temporaire> pg_restore --no-owner --dbname=<base-de-controle>`. Extraire `restic dump <id-uploads> kwitli-uploads.tar` dans un répertoire temporaire vide et vérifier les fichiers avant toute remise en service. Vérifier schéma, données et fichiers, puis supprimer uniquement le conteneur, le réseau et les fichiers temporaires créés pour ce contrôle. Ne jamais connecter cette procédure à `kwitli_dev`, `kwitli_test` ou à la base de production; ne lancer aucune migration sur une base existante.

### Suppression, chiffrement et protection contre la compromission

Restic chiffre les données avant leur transfert. La clé Restic n'est pas fournie à Cloudflare. Garder le bucket privé et protéger le compte Cloudflare par MFA. Un jeton limité à un bucket réduit l'impact, mais un jeton objet Read & Write compromis peut permettre de supprimer les objets de ce dépôt; Restic `forget --prune` a lui-même besoin de supprimer des objets.

R2 propose des règles Bucket Lock de rétention configurées côté Cloudflare, mais elles empêchent les suppressions/écrasements, tandis que l'API S3 R2 n'implémente pas les headers S3 Object Lock. Ne pas appliquer une règle au dépôt Restic actif sans test isolé : elle peut bloquer les verrous éphémères ou le `prune`. Mesure de départ sans service supplémentaire : accès R2 bucket-scoped, jeton uniquement sur le serveur, MFA, mot de passe Restic sauvegardé hors serveur, contrôles réguliers et rotation immédiate du jeton en cas de compromission. Pour une résistance à l'effacement par un hôte compromis, évaluer ensuite un dépôt d'archive séparé sous un préfixe verrouillé, sans `forget/prune`, et valider son fonctionnement Restic avant usage; les données supplémentaires peuvent être facturées.

### Coûts et surveillance R2

Le bucket Standard utilise le niveau par défaut, sans frais de sortie ni frais de récupération; ne pas le passer à Infrequent Access sans calcul préalable (récupération facturée et durée minimale de stockage de 30 jours). La documentation Cloudflare, consultée le 25 octobre 2026, indique pour Standard un quota mensuel inclus de 10 GB-month, 1 million d'opérations A et 10 millions d'opérations B; au-delà, tarifs publiés de 0,015 $ US/GB-month, 4,50 $ US/million d'opérations A et 0,36 $ US/million d'opérations B. Cloudflare arrondit aux unités de facturation. Les sauvegardes Restic sont incrémentales et dédupliquées, mais la croissance exacte dépend du volume et des changements PostgreSQL. Vérifier chaque mois l'usage R2 et les opérations dans le dashboard; activer une alerte budgétaire Cloudflare à un seuil choisi par le porteur du compte. Ces alertes sont disponibles aux comptes Pay-as-you-go, envoient un courriel et n'arrêtent pas la consommation ([tarifs R2](https://developers.cloudflare.com/r2/pricing/), [alertes budgétaires](https://developers.cloudflare.com/billing/manage/budget-alerts/)).

## Vérifications et arrêt des coûts

```sh
sudo docker compose --env-file /etc/kwitli/production.env -f deploy/compose.production.yaml ps
sudo docker compose --env-file /etc/kwitli/production.env -f deploy/compose.production.yaml logs --since=15m api caddy postgres
sudo systemctl list-timers kwitli-backup.timer
sudo systemctl status kwitli-backup.service
```

Pour arrêter sans supprimer les données : `docker compose stop`. Pour mettre fin à la facturation serveur, supprimer le serveur dans Hetzner Cloud Console; l'arrêt seul ne suffit pas. Vérifier et supprimer séparément, après sauvegarde vérifiée, les volumes additionnels, snapshots, adresses IP, volumes cloud, firewalls et buckets devenus inutiles. Ne supprimer ni dépôt de sauvegarde ni volumes de données sans décision explicite.

## Coûts indicatifs et points bloquants

Le serveur envisagé est Hetzner CAX21 à Falkenstein : 4 vCPU ARM64, 8 Go RAM, 80 Go SSD, prix indicatif fourni pour ce projet de 12,49 $ US/mois + 0,60 $ pour l'IPv4, hors taxes. Aucun serveur n'a été commandé; confirmer tarif, taxes et disponibilité au moment d'un éventuel achat. Caddy et Let's Encrypt n'ajoutent pas de frais de licence. GitHub Actions/Packages et le stockage Restic peuvent entraîner des coûts selon le plan, la visibilité, le volume et le fournisseur retenu.

Avant achat : confirmer l'emplacement et la latence vers Dakar, la disponibilité Ubuntu ARM64 à Falkenstein, les règles KYC/juridiques du marché, le support production du fournisseur de paiement, la procédure d'urgence SSH, la disponibilité DNS `api.kwitli.app`, la politique d'accès GHCR depuis le serveur et la restauration hors serveur.
