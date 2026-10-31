
# Kwitli

> **État du projet — 23 octobre 2026 : consolidation du MVP et préparation d'une bêta contrôlée à Dakar.**
>
> Ce document décrit la direction produit validée et les travaux connus. Il ne constitue pas une preuve que chaque fonction est déjà déployée ou que chaque test passe sur le dernier commit. Tout élément technique doit être confronté au code avant publication.

## 1. Qu'est-ce que Kwitli ?

Kwitli est une application mobile de découverte et de commande auprès de **restaurants de proximité**.

Son premier marché pilote est **Dakar, au Sénégal**.

Le client trouve un restaurant, sélectionne des plats, passe une commande, paie et récupère sa commande au restaurant.

**Positionnement MVP : restaurants uniquement, retrait sur place uniquement (pickup), sans livraison.**

Il ne s'agit plus du projet initial de vente de plats préparés dans des cuisines domestiques en Colombie. Les références à Bogotá, à la Colombie et aux cuisiniers à domicile sont historiques et ne constituent plus des exigences du lancement actuel.

Le pilote n'a pas encore prouvé l'adoption commerciale.

L'objectif est de valider un parcours fiable avec au minimum **deux restaurants réellement engagés**, idéalement cinq, puis de mesurer les commandes abouties, les incidents et les commandes répétées.

### Critère de succès du MVP

1. Un restaurant crée et configure son établissement : description, localisation, horaires et menu.
2. L'administration vérifie et valide l'établissement.
3. Un client découvre le restaurant et sélectionne ses plats.
4. Le client réalise un paiement vérifié côté serveur.
5. Le restaurant reçoit la commande et la traite.
6. Le restaurant indique que la commande est prête.
7. Le client présente son code de retrait.
8. Le restaurant valide le retrait.
9. Le client peut laisser un avis.
10. Les montants dus au restaurant et à Kwitli sont calculables, traçables et effectivement réglés selon le mécanisme de paiement validé pour le pilote.

Voir `docs/mvp-restaurant-flow.md` pour le parcours métier en 12 étapes.

## 2. Décisions produit

| Sujet | Décision ou statut |
| --- | --- |
| Pays pilote | Sénégal |
| Ville pilote | Dakar |
| Offre | Restaurants, menus, commandes, paiements et retrait |
| Livraison | Exclue du MVP |
| Marketplace multicommerce | Vision future, hors MVP |
| Application | React Native / Expo pour iOS et Android |
| Langues | Français prioritaire, wolof à préparer et valider |
| Autres langues | Anglais, swahili, lingala, afrikaans selon les futurs marchés |
| Devise | XOF / FCFA |
| Fuseau pilote | Africa/Dakar |
| Inscription | Gratuite, sans abonnement |
| Offre de lancement | Dix premiers restaurants partenaires : six mois sans commission ni abonnement, sous réserve de financement des frais PSP |
| Commission | Configurable, non figée à 12 % |
| Split automatique | Reporté jusqu'à validation technique et commerciale |
| Prestataire de production | Non définitivement choisi : Flutterwave et PayDunya en évaluation |
| Infrastructure | Non commandée ; Hetzner reste un candidat |
| Publication | Pas de lancement public avant validation des parcours critiques |

## 3. Architecture technique

### Backend

- FastAPI
- Python
- SQLAlchemy
- Alembic
- PostgreSQL

### Mobile

- React Native
- Expo
- TypeScript
- iOS et Android avec une base de code commune

### Organisation

```text
backend/
  app/
    api/routes/
    schemas/
    services/
    repositories/
    persistence/
    database.py

mobile/
  Application Expo / React Native

docs/
  Documentation technique et produit

scripts/
  Scripts de développement, migration et tests
```

### Base de données

PostgreSQL est désormais utilisé localement pour le développement et les tests.

La migration initiale des données depuis SQLite a déjà été effectuée.

L'ancienne base SQLite est conservée comme sauvegarde historique. PostgreSQL constitue le moteur cible.

**Attention :** certains noms de modèles, routes ou fichiers peuvent encore utiliser des termes historiques comme `cook`, `dish`, `DishAvailability`, `COP` ou `PayU`.

Ces éléments ne doivent pas être supprimés ou renommés automatiquement sans vérifier leurs dépendances.

## 4. Développement local sur Mac

Depuis la racine du projet :

```bash
cp backend/.env.example backend/.env

./.venv/bin/pip install -r backend/requirements.txt

./.venv/bin/python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

API locale :

```text
http://127.0.0.1:8000
```

Documentation :

```text
http://127.0.0.1:8000/docs
```

Les clés secrètes et identifiants ne doivent jamais être enregistrés dans Git.

## 5. PostgreSQL et tests

Configuration historique locale :

- Base DEV : `kwitli_dev`
- Base TEST : `kwitli_test`
- Port : `55433`

Ne pas supposer que PostgreSQL utilise le port `5432`.

### Tests backend

```bash
export TEST_DATABASE_URL='postgresql+psycopg2:///kwitli_test?host=/tmp&port=55433'

TEST_DATABASE_URL="$TEST_DATABASE_URL" ./.venv/bin/python -m pytest backend/tests -q
```

Les tests doivent utiliser uniquement la base isolée `kwitli_test`.

**Ne jamais exécuter les tests contre `kwitli_dev` ou une base distante.**

### Migrations

Pour la base de test uniquement :

```bash
ALEMBIC_DATABASE_URL="$TEST_DATABASE_URL" ./.venv/bin/alembic upgrade head
```

Toute migration DEV nécessite :

1. Vérification de la base cible.
2. Sauvegarde préalable.
3. Vérification des révisions Alembic.
4. Analyse des impacts.
5. Autorisation explicite.

La migration d'idempotence des paiements `6d2f81a4c970` a précédemment été rapportée comme appliquée à `kwitli_test`.

Son état actuel doit être vérifié avant une intervention sur DEV.

Ne pas initialiser une base gérée par Alembic avec `create_all()` au démarrage.

Voir `docs/postgres-dev.md`.

## 6. Application mobile

```bash
cd mobile

cp .env.example .env

npm install

npm start
```

### Connexion API

Sur Mac/iOS :

```text
http://127.0.0.1:8000
```

Sur émulateur Android :

```text
http://10.0.2.2:8000
```

Selon la configuration Android, il peut être nécessaire d'utiliser :

```bash
adb reverse tcp:8000 tcp:8000
```

Sur un téléphone physique, définir une adresse API accessible depuis le téléphone.

En production, utiliser une adresse HTTPS publique via la configuration appropriée.

### Tests iOS et Android

Les deux plateformes doivent être testées.

Les parcours de paiement nécessitant des liens profonds doivent être validés avec une development build adaptée.

Expo Go ne permet pas de valider entièrement les schémas d'URL natifs personnalisés.

## 7. Fonctionnement du MVP restaurant

Le parcours métier cible est :

1. Le commerçant crée son restaurant.
2. Il configure la description, le GPS, les horaires et le menu.
3. L'administrateur valide le restaurant.
4. Le client découvre le restaurant.
5. Le client passe commande.
6. Le client paie.
7. Le commerçant reçoit la commande.
8. Le commerçant prépare les plats.
9. Le commerçant indique que la commande est prête.
10. Le client présente son code de retrait.
11. Le commerçant valide le retrait.
12. Le client peut laisser un avis.

### Règles essentielles

- Seuls les restaurants validés sont visibles publiquement.
- Les disponibilités et stocks doivent être vérifiés côté serveur.
- Les montants sont calculés par le backend.
- Une confirmation de paiement répétée ne doit jamais produire une deuxième commande.
- Les commandes sont accessibles uniquement aux personnes autorisées.
- Le code de retrait doit être contrôlé côté serveur.
- Les avis publics ne doivent pas divulguer d'informations personnelles privées.
- Les erreurs financières doivent être traçables et réconciliables.

Les états exacts des commandes et paiements doivent être vérifiés dans le code actuel.

## 8. Paiements

### Devise du pilote

```text
XOF — Franc CFA
```

### Flutterwave

Flutterwave est déjà présent dans le projet en environnement de test.

Fonctionnalités et objectifs :

- Paiements Wave Sénégal.
- Paiements Orange Money.
- Vérification des transactions côté serveur.
- Webhooks.
- Prise en charge de l'idempotence.
- Gestion des échecs et anomalies.
- Tests de retour vers l'application mobile.

L'intégration actuelle doit être auditée avant d'être déclarée prête pour la production.

Flutterwave a confirmé commercialement :

- Possibilité d'utiliser le Sandbox avant l'immatriculation.
- Documents KYB nécessaires pour la production.
- Fonctionnalité de sous-comptes et split payment.
- Tarifs standards de 2 % sur l'encaissement Mobile Money.
- Frais standards de transfert annoncés séparément.
- Absence de frais d'ouverture et d'abonnement annoncée.

**Le fonctionnement exact des frais cumulés et des règlements sur Wave/Orange Money doit encore être confirmé et testé.**

### PayDunya

PayDunya reste un prestataire envisagé pour le Sénégal.

Les accès de production et les tests réels dépendent notamment de la constitution légale de Kwitli.

Les conditions financières, techniques et contractuelles doivent être clarifiées avant de sélectionner définitivement le prestataire.

### PayTech

PayTech reste une alternative technique et commerciale potentielle.

Aucune bascule automatique vers un autre prestataire ne doit être déclenchée à la suite d'un timeout ou d'une erreur.

### Ancien périmètre Colombie

Le dépôt peut encore contenir :

- PayU
- Wompi
- COP
- Bogotá
- `es-CO`
- Scripts de démonstration historiques

Ils ne représentent plus le marché pilote actuel.

Ne pas les supprimer sans audit de leurs usages et dépendances.

## 9. Règles financières

Les principes suivants doivent être respectés :

- Pas de commission de 12 % codée en dur.
- Commission configurable.
- Conservation du taux et des frais appliqués à chaque transaction.
- Vérification des montants côté serveur.
- Aucun stockage de numéros complets de cartes bancaires ou de CVV.
- Idempotence des créations de paiement et des confirmations.
- Gestion explicite des paiements problématiques.
- Aucune commande dupliquée après webhook répété.
- Aucune décrémentation multiple du stock.
- Aucun paiement réel sans validation préalable du prestataire.
- Aucun split de production avant confirmation des conditions de règlement.

Les états d'exception connus incluent notamment :

```text
paid_stock_conflict
reconcile_required
```

Ces états doivent empêcher les opérations dangereuses tant qu'une réconciliation appropriée n'a pas été effectuée.

### Tarification commerciale

L'inscription à Kwitli est gratuite.

Il n'y a pas d'abonnement marchand prévu pour le MVP.

La commission sur les transactions constitue le modèle économique envisagé à long terme.

Le taux définitif doit être déterminé selon :

- Les coûts réels des prestataires de paiement.
- Les conditions du marché de Dakar.
- La valeur apportée aux restaurants.
- Les résultats du pilote.
- La rentabilité de Kwitli.

La gratuité promotionnelle des premiers partenaires doit être budgétée et encadrée.

## 10. Sécurité des comptes et des données

**Ce chantier constitue la priorité technique actuelle.**

### Authentification

Vérifier :

- Inscription client.
- Inscription commerçant.
- Connexion et déconnexion.
- Normalisation des adresses e-mail.
- Unicité des comptes.
- Gestion des mots de passe.
- Réinitialisation et récupération de compte.
- Expiration et révocation des tokens.
- Stockage sécurisé des sessions sur iOS et Android.

Des problèmes liés à la casse des adresses e-mail ont déjà été observés.

Ils doivent être audités et corrigés sans fusion ou suppression automatique de comptes.

### Autorisations

Vérifier qu'un client ne peut pas consulter les commandes d'un autre client.

Vérifier qu'un restaurant ne peut pas accéder aux commandes ou données privées d'un autre restaurant.

Vérifier que les routes administrateur sont protégées côté serveur.

### Données sensibles

Ne jamais exposer :

- Mots de passe.
- Hash de mots de passe.
- Clés API.
- Secrets de paiement.
- Tokens de session.
- CVV ou numéros complets de carte.
- Données privées non autorisées.

### Méthode de travail Codex

1. Examiner le code existant.
2. Identifier les vulnérabilités démontrées.
3. Évaluer leur criticité.
4. Corriger uniquement ce qui est nécessaire.
5. Ajouter les tests appropriés.
6. Vérifier les régressions.
7. Documenter les résultats.

Aucune migration DEV, suppression de données, refonte d'authentification ou modification financière sensible sans autorisation explicite.

## 11. Dépendances extérieures

### M. Guy — constitution légale

M. Guy accompagne la création de Kwitli SAS au Sénégal.

Éléments à finaliser ou confirmer :

- Contrat de domiciliation signé.
- Statuts de la société.
- Immatriculation RCCM.
- Obtention du NINEA.
- Ouverture du compte bancaire professionnel.
- RIB de la société.
- Justification et suivi des frais administratifs et notariaux.

### Prestataires de paiement

Attendre les confirmations concernant :

- Approbation du modèle marketplace.
- Conditions contractuelles.
- Split automatique.
- Frais d'encaissement.
- Frais de décaissement.
- Versement aux restaurants.
- Remboursements et litiges.
- Plafonds de transactions.
- Activation du compte de production.

Ces dépendances ne doivent pas empêcher la poursuite des travaux techniques locaux.

## 12. Travaux pouvant avancer immédiatement

### Priorité 1 — Sécurité

- Audit des comptes.
- Récupération des mots de passe.
- Sessions et tokens.
- Autorisations client/commerçant/admin.
- Protection des données personnelles.
- Contrôle des secrets et dépendances.

### Priorité 2 — Commandes et paiements

- Idempotence des paiements.
- Vérification des migrations.
- Gestion des webhooks répétés.
- Gestion des erreurs financières.
- Tests des interruptions réseau.
- Validation des commandes et codes de retrait.

### Priorité 3 — Mobile

- Tests sur iOS.
- Tests sur Android.
- Vérification des retours de paiement.
- Notifications internes.
- Horaires et fuseau horaire.
- Gestion des restaurants validés.

### Priorité 4 — Infrastructure

- Préparation du backend distant.
- Configuration PostgreSQL.
- HTTPS.
- Pare-feu.
- Gestion des secrets.
- Sauvegardes.
- Tests de restauration.
- Surveillance des erreurs.

### Priorité 5 — Commercialisation

- Préparation d'une démonstration restaurant.
- Identification d'un secteur pilote de Dakar.
- Recrutement d'au moins deux restaurants engagés.
- Objectif de cinq restaurants partenaires.
- Préparation de l'onboarding.
- Définition des indicateurs de succès du pilote.

## 13. Infrastructure et hébergement

Kwitli fonctionne actuellement en développement local sur Mac.

Le déploiement à distance doit permettre aux applications iOS et Android d'accéder à une API sécurisée.

### Hébergement envisagé

Hetzner Cloud est un candidat pour l'hébergement du backend et de PostgreSQL.

**Aucun serveur payant ne doit être commandé simplement parce que son tarif paraît intéressant.**

Avant toute dépense, vérifier :

- Coût total avec taxes et options.
- Conditions de facturation.
- Suppression effective du serveur.
- Arrêt réel de la facturation.
- Maintenance nécessaire.
- Sécurité du système.
- Sauvegardes et restauration.
- Disponibilité adaptée au pilote.
- Capacité de migration vers un autre fournisseur.

Une infrastructure gratuite peut être utilisée pour des démonstrations et des tests sans argent réel, sous réserve de ses limites.

Une infrastructure fiable sera nécessaire avant des transactions réelles.

## 14. Stratégie de lancement

Le lancement doit rester hyperlocal.

Objectif initial :

- Un secteur restreint de Dakar.
- Au minimum deux restaurants engagés.
- Idéalement cinq partenaires.
- Des clients capables de commander et retirer leurs repas.
- Des commandes payées et correctement traitées.
- Une expérience sans assistance majeure.

### Acquisition

La stratégie initiale privilégie :

- Les restaurants partenaires.
- Les recommandations.
- La clientèle existante des restaurants.
- Les démonstrations terrain.
- Le bouche-à-oreille.
- Une communication adaptée au français et au wolof.

Aucune campagne publicitaire importante n'est prévue avant une preuve d'utilisation et de fidélisation.

### Mesures du pilote

Suivre notamment :

- Restaurants réellement actifs.
- Commandes initiées.
- Commandes payées.
- Commandes retirées.
- Échecs et incidents de paiement.
- Annulations.
- Délais de traitement.
- Clients qui reviennent commander.
- Coûts réels par transaction.
- Satisfaction des commerçants.

Le nombre de téléchargements ne constitue pas, à lui seul, une preuve d'adoption.

## 15. Hors périmètre du MVP

Les fonctionnalités suivantes sont reportées :

- Livraison.
- Gestion des chauffeurs.
- Marketplace de cuisiniers particuliers.
- Produits et services hors restauration.
- Déploiement simultané dans plusieurs pays.
- Split de production non validé.
- Traductions non nécessaires au pilote.
- Campagnes publicitaires importantes.
- Fonctionnalités ajoutées sans preuve de besoin.

Ces éléments pourront être réévalués après la validation du pilote de Dakar.

## 16. Documentation du projet

Documents de référence :

- `docs/mvp-restaurant-flow.md`
- `docs/postgres-dev.md`
- `docs/flutterwave-test.md`
- `docs/pre-pilot-readiness.md`, si présent dans le dépôt

Les anciens guides PayU, PayDunya, PayTech et les scripts de seed doivent être conservés ou classés selon leur pertinence technique réelle.

## 17. Discipline de développement

Avant toute intervention :

1. Vérifier `git status`.
2. Identifier les fichiers concernés.
3. Préserver les modifications existantes.
4. Éviter la duplication de code.
5. Ne pas modifier les données métier inutilement.
6. Tester sur PostgreSQL isolé.
7. Vérifier les tests mobiles.
8. Documenter les migrations.
9. Préparer des commits cohérents.
10. Ne pas pousser ni déployer sans autorisation.

### Principe fondamental

**Kwitli doit d'abord démontrer qu'il fonctionne et que les clients et restaurants veulent réellement l'utiliser.**

Aucune dépense importante, nouvelle fonctionnalité ou expansion géographique ne doit être engagée sans justification concrète.

---

## Statut général

**Phase actuelle : consolidation technique du MVP et préparation du pilote Dakar.**

Priorité immédiate : sécurité des comptes et des données.

Dépendances externes : constitution de Kwitli SAS, activation du prestataire de paiement et recrutement des restaurants pilotes.

Objectif final :

**Client commande → client paie → restaurant reçoit et prépare → restaurant et Kwitli sont payés → client récupère sa commande.**

Ce parcours doit être validé de bout en bout avant un lancement commercial élargi.
