# Socle KYB Kwitli

## État et limites

Le workflow KYB est séparé de `CookProfile.approval_status` (approbation commerciale). Une décision KYB ne modifie jamais cette approbation. La découverte et le checkout ne sont filtrés par KYB que pour un pays explicitement listé dans `KYB_ENFORCED_COUNTRIES`, avec une politique active et juridiquement confirmée. Le défaut est vide : aucun commerce existant n'est affecté.

La politique Sénégal `sn-food-service-draft-1` est **inactive** et `pending_legal_review`. NINEA, RCCM selon le statut, identité du responsable, autorisations d'exploitation et justificatifs sanitaires ne sont que des catégories de travail soumises à Me Guy. Aucun de ces éléments n'est déclaré obligatoire. Aucun registre public n'est interrogé ni intégré.

## Données et pièces

- Les dossiers stockent une copie JSON versionnée de la politique et les données légales sous forme AES-256-GCM chiffrée.
- La clé est fournie hors Git et hors base (`KYB_ENCRYPTION_KEY` ou trousseau `KYB_ENCRYPTION_KEYS` au format JSON avec versions hex de 32 octets); la version courante est `KYB_ENCRYPTION_KEY_VERSION`. Conserver les anciennes versions disponibles jusqu'au rechiffrement contrôlé de toutes les pièces.
- Les pièces sont chiffrées dans `KYB_PRIVATE_STORAGE_DIR`, distinct de `UPLOAD_DIR`, fichier aléatoire, mode 0600; répertoire dédié mode 0700. Elles ne sont jamais montées sous `/uploads`.
- Le serveur refuse la collecte si KYB est désactivé, si la clé/chiffrement n'est pas disponible, si ClamAV (`clamdscan`) n'est pas présent, ou si le stockage privé est mal séparé. Les fichiers sont limités en taille et acceptés seulement pour PDF, JPEG, PNG avec signature correspondante; ClamAV analyse le fichier temporaire avant chiffrement. Les sorties brutes d'Antivirus et les données personnelles ne sont pas journalisées.
- Les administrateurs authentifiés peuvent consulter une pièce propre avec réponse `no-store`. Chaque consultation et action est journalisée. L'examen visuel n'est pas une confirmation d'authenticité; `source_verified` exige une action admin déclarant une source autorisée. L'application ne valide pas indépendamment la source ou un registre externe.
- Remplacer une pièce conserve l'ancienne version marquée remplacée et lie la nouvelle. Une pièce expirée n'est plus consultable et ne satisfait pas l'approbation.

## Workflow

Routes sous `/api/v1/kyb` : lecture des règles, création et lecture du dossier propriétaire, modification des données avant soumission, dépôt d'une pièce, soumission. L'identifiant du commerce vient du compte authentifié; un autre commerçant reçoit un refus/not-found.

`/admin` contient les dossiers KYB, les pièces, les examens et les décisions avec CSRF. Les actions sont transactionnelles et les événements ont un trigger PostgreSQL interdisant UPDATE/DELETE. L'approbation est refusée tant que la version courante n'est pas active et confirmée légalement, puis exige toutes les pièces marquées obligatoires et vérifiées par source, propres et non expirées. Une demande de correction peut ajouter une pièce requise au dossier et laisse une trace.

## Activation et opérations

`KYB_ENABLED=false` reste la configuration de base. Avant collecte réelle, l'équipe d'exploitation doit installer/maintenir ClamAV, créer le répertoire privé avec propriétaire dédié et mode 0700, fournir les clés via un gestionnaire de secrets et planifier leur sauvegarde/rotation, puis vérifier le TLS externe, les limites de requêtes et la restauration des pièces chiffrées. Un stockage local implique que les sauvegardes chiffrées couvrent ce chemin privé.

Ne pas activer la collecte avec des secrets d'exemple. Ne pas définir `KYB_ENFORCED_COUNTRIES` avant validation des exigences par juridiction, configuration d'une politique active et procédure de décision approuvée. `KYB_RETENTION_DAYS=0` signifie qu'aucune purge automatique n'est faite; durée, suppression, accès et obligations de conservation attendent validation juridique. Aucune suppression automatique n'est implémentée.

La migration `ab71d9e4c205` est additive. Elle n'est pas appliquée par ce changement à une base partagée. La tester d'abord sur PostgreSQL jetable, puis appliquer séparément selon la procédure de déploiement approuvée.
