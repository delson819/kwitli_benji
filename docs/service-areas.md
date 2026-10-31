# Zones commerciales persistantes

## Fonctionnement

`service_area_configs` contient une configuration par environnement et identifiant stable. Les états sont `planned`, `recruiting`, `active` et `suspended`. La géométrie du MVP est un cercle (`center_latitude`, `center_longitude`, `radius_km`). Le modèle réserve `geometry_type` et `geometry_metadata` à une évolution future; les formes autres que cercle échouent fermées et ne sont pas administrables par l'interface actuelle.

Les règles de découverte, d'approbation et de nouveau checkout lisent PostgreSQL au moment de la décision. Aucun cache serveur ne participe à ces contrôles. Les transactions d'approbation et de checkout verrouillent les lignes actives correspondantes afin qu'une suspension concurrente soit ordonnée avant ou après la décision. La route publique `GET /api/v1/service-areas` conserve le contrat historique (`id`, `code`, `label`, pays, ville, centre sous `latitude`/`longitude`, `radius_km`, `timezone`, `active`) et ne retourne que les zones actives de l'environnement courant avec `Cache-Control: no-store`.

Une suspension retire immédiatement la zone des nouvelles décisions commerciales. Elle ne touche ni les restaurants, ni les commandes et paiements déjà créés. Il n'existe pas de suppression depuis l'interface; les modifications gardent la même clé stable, incrémentent `version` et ajoutent un événement audité. Une version obsolète est refusée.

## Chaîne de migration

La migration `c73e9f4a2b10` suit linéairement `ab71d9e4c205` (fondations KYB), elle-même après `94a1c2e7d530`. Elle est additive et ne modifie pas de table métier existante. Aucun enregistrement de zone n'est inséré par la migration : ceci évite d'activer par surprise une zone de test en staging ou production. Une base sans configuration active refuse donc l'approbation, la découverte commerciale et les nouveaux checkouts jusqu'à son initialisation explicite.

## Transition des zones historiques

La migration `c73e9f4a2b10` ne désactive pas l'ancien code : elle ajoute seulement les tables de configuration et d'audit. Elle ne sème aucune ligne. Le déploiement doit donc se faire en deux versions, avec initialisation avant le nouveau serveur.

1. **Avant la migration**, tant que l'ancienne API sert encore les constantes, relever sa réponse `GET /api/v1/service-areas` et conserver une sauvegarde DB vérifiée. Faire ce relevé séparément dans l'environnement cible. Cette réponse fournit les identifiants, codes et périmètres publics historiques.
2. Construire un manifeste JSON par environnement, revu par un opérateur. Il contient `version: 1`, `environment`, `database_name` exact, `required_area_ids` et `zones`. `required_area_ids` doit reprendre tous les identifiants présents dans la réponse historique relevée à l'étape 1 (dont `sn-dakar` lorsqu'il est renvoyé); au démarrage, tout identifiant déclaré requis doit avoir une entrée correspondante, sinon le serveur refuse le cutover. Chaque zone porte les champs historiques (`id`, `code`, `label`, centre, rayon, fuseau, `active: true`) ainsi que `source_environment`, `locale`, `currency` et `distance_unit`. Ces trois derniers champs ne font pas partie de l'ancien contrat HTTP et doivent être renseignés depuis la configuration marché approuvée, jamais devinés. Le schéma est validé par `backend.app.service_area_bootstrap`.
3. Appliquer `alembic upgrade c73e9f4a2b10` avec la configuration de la base cible explicitement contrôlée, sans arrêter l'ancienne API. La migration est additive; aucun downgrade n'est nécessaire pendant la transition.
4. Installer le manifeste cible en fichier en lecture seule, propriétaire root et mode `0444` (lecture nécessaire au compte non-root de l'API, aucune écriture pour celui-ci). Exécuter ensuite, dans un conteneur ponctuel de l'image candidate connecté seulement au réseau de données :

   ```sh
   python -m backend.app.service_area_bootstrap \
     --manifest /run/kwitli/service-areas.json \
     --database-name <base-cible> \
     --actor-id <identifiant-admin-actif> \
     --reason "Initialisation contrôlée des zones"
   ```

   Le CLI vérifie `APP_ENV`, le nom de la base et l'administrateur avant écriture. Il crée seulement les lignes absentes en état `active`, avec leurs identifiants historiques, et ajoute un événement d'audit. Une ligne existante qui diffère ou est suspendue entraîne un arrêt, jamais un écrasement ou une réactivation implicite. Toute reprise après erreur consiste à corriger la cause puis relancer cette commande : la transaction est atomique et les lignes déjà créées exactement sont ignorées.
5. Exécuter `python -m backend.app.service_area_bootstrap --manifest /run/kwitli/service-areas.json --database-name <base-cible> --verify-only`. Ce contrôle strict vérifie avant chaque bascule le contenu exact (identifiants, code, libellés et périmètres) du manifeste contre la base. Puis vérifier la réponse publique `/api/v1/service-areas` avant de remplacer l'API.
6. `init_database()` refuse le démarrage staging/production si le manifeste manque, si la base réelle ne porte pas le nom attendu, si `APP_ENV` ne correspond pas, si un identifiant requis manque ou si un périmètre diffère sans événement administratif correspondant à la version courante. Une modification administrative versionnée reste valide sans changer le manifeste/déployer; une dérive SQL non auditée échoue fermée. Une zone active `ca-sherbrooke-dev` est explicitement refusée hors développement/test.
7. Basculer l'API seulement après le bootstrap et le `--verify-only`. La route publique conserve les identifiants `sn-dakar` et autres identifiants validés; aucun nouveau système de géographie parallèle n'est introduit.

Le manifeste est un artefact de déploiement par environnement, pas une liste de villes intégrée au code. Ne jamais inclure `ca-sherbrooke-dev` dans le manifeste staging/production. Le garde-fou empêche aussi son activation via les opérations d'administration dans ces environnements.

### Retour arrière

Si le nouveau serveur échoue avant le basculement, garder l'ancienne API et les tables additives; corriger le manifeste/bootstrap puis reprendre. Après basculement, ne remettre l'ancienne image que si les zones historiques nécessaires sont encore actives avec les périmètres constants qu'elle connaît et qu'aucune décision commerciale récente ne dépend d'une nouvelle zone ou d'une suspension. L'ancien binaire ignore les statuts et les zones DB : un rollback aveugle pourrait réactiver une zone suspendue ou ignorer une ville ouverte. Si ces conditions ne sont pas réunies, couper temporairement les nouvelles approbations/commandes et faire un correctif avant remise en service; ne pas revenir à l'ancien binaire comme solution automatique. Dans tous les cas, laisser les tables et événements en place, ne pas lancer `alembic downgrade`, et ne pas supprimer/modifier les lignes par SQL. Les identifiants historiques restent inchangés, donc les commandes enregistrées gardent leurs références.

## Administration et concurrence

Les opérations passent par `/admin` et ses formulaires protégés par HTTP Basic admin, jeton CSRF signé, limitation de débit, validation serveur et justification obligatoire. Les zones sont isolées par `APP_ENV`; une requête client ne choisit jamais l'environnement. `service_area_events` conserve l'acteur, la raison, les versions et les instantanés avant/après. Des triggers PostgreSQL/SQLite interdisent la modification ou suppression des événements.

## Test et isolation

Les marchés synthétiques historiques utilisés par les tests sont créés dans la base jetable `kwitli_test` par la fixture pytest, jamais par Alembic. Les tests d'isolation vérifient que ces enregistrements ne deviennent pas visibles pour `staging`, `production` ou `development`. Aucune donnée de marché n'est semée dans une migration.

Après modification d'une zone pendant que l'application mobile était en arrière-plan, l'application recharge la liste publique au retour au premier plan. Le backend conserve l'autorité, même si un client garde momentanément une ancienne sélection.
