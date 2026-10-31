# AGENTS.md — KWITLI

## 0. RÈGLE PRINCIPALE

Avant toute modification importante, lire ce fichier en entier.

KWITLI a changé de direction produit.

Ne pas continuer à développer l'ancien concept comme s'il s'agissait encore principalement d'une marketplace de cuisine maison entre particuliers.

La direction actuelle est :

KWITLI = plateforme hyperlocale de commande pour petits restaurants, commerces alimentaires indépendants et petites enseignes locales.

La priorité est de permettre à un petit commerce de :

- publier son menu ;
- recevoir les commandes ;
- être payé ;
- préparer ;
- mettre la commande prête ;
- remettre la commande au client ;

sans devoir gérer normalement les commandes par téléphone ou WhatsApp.

Toute décision importante doit être évaluée selon cette vision.

---

# 1. PORTÉE DU WORKSPACE

Travailler uniquement dans le repository `KWITLI`.

Ignorer totalement :

- KINANM ;
- les autres projets ;
- les fichiers extérieurs au repository ;
- les informations non nécessaires à KWITLI.

Ne jamais accéder à :

- ~/.ssh
- credentials cloud
- profils navigateur
- password stores
- autres repositories
- fichiers personnels

sans autorisation explicite.

---

# 2. PROMESSE PRODUIT

## Côté client

Le parcours cible est :

Découvrir
→ choisir un commerce
→ consulter son menu
→ choisir des articles
→ ajouter au panier
→ payer
→ suivre la préparation
→ récupérer
→ laisser un avis

Le client ne doit pas avoir besoin :

- d'appeler le commerce ;
- d'envoyer un message WhatsApp ;
- de négocier manuellement la disponibilité ;
- de demander manuellement si sa commande est prête.

## Côté commerce

Le parcours cible est :

Créer son commerce
→ configurer ses informations
→ publier son menu
→ recevoir une commande
→ confirmer / préparer
→ indiquer le temps de préparation
→ passer à "prête"
→ recevoir son paiement / payout
→ confirmer le retrait

---

# 3. POSITIONNEMENT VENDEUR

Les vendeurs prioritaires sont :

- `local_business`
- `small_chain`

Le système peut rester extensible à :

- `individual`

mais ne pas concevoir les nouvelles fonctionnalités principalement autour d'un particulier qui prépare quelques portions chez lui.

Le vocabulaire métier doit progressivement évoluer de :

Cook / Dish

vers :

Business / Menu / Item

sans migration brutale.

---

# 4. STRATÉGIE DE CROISSANCE

KWITLI doit :

COMMENCER PETIT
mais
POUVOIR DEVENIR GRAND.

Approche :

1. quelques commerces ;
2. un quartier ;
3. une ville ;
4. un pays ;
5. plusieurs villes ;
6. plusieurs pays.

Ne pas surarchitecturer le MVP.

Mais ne pas introduire volontairement des contraintes qui rendraient très difficile :

- plusieurs commerces ;
- plusieurs points de vente ;
- beaucoup de commandes ;
- plusieurs pays ;
- plusieurs devises ;
- plusieurs langues ;
- plusieurs fournisseurs de paiement.

Architecture simple aujourd'hui, extensible demain.

---

# 5. MARCHÉ ACTUEL

Dakar / Sénégal est actuellement le marché pilote privilégié.

Ce n'est PAS une raison pour hardcoder le Sénégal partout dans le produit.

Le Canada est actuellement le lieu depuis lequel le projet est développé / structuré.

La structure juridique finale et les flux financiers internationaux ne sont pas encore entièrement figés.

Le marché doit être configurable.

Exemple conceptuel :

MarketConfig
- country_code
- locale
- currency
- distance_unit
- payment_provider
- supported_payment_methods
- legal_config

Ne jamais considérer une configuration pays comme une vérité universelle du domaine.

---

# 6. INTERNATIONALISATION

Langue de travail du projet :
FRANÇAIS.

Documentation projet :
FRANÇAIS.

Commentaires utiles :
FRANÇAIS.

Les textes visibles par les utilisateurs doivent passer par i18n.

Ne jamais hardcoder une interface entière en :

- français ;
- espagnol ;
- wolof ;
- anglais ;

dans les composants.

La langue de développement actuelle peut rester française.

Le produit doit supporter des locales par marché.

Ne plus considérer `es-CO` comme locale centrale ou obligatoire de KWITLI.

---

# 7. STRUCTURE MÉTIER CIBLE

La direction cible est :

Business
├── Location / Branch
└── Menu
    └── Category
        └── Item

## Business

Représente la marque / entreprise.

Exemples :

Chez Awa
Maison Yassa
Dakar Grill

## Location / Branch

Représente éventuellement un point de vente.

Même si le MVP commence souvent avec :

1 Business = 1 Location

ne pas construire une architecture qui rendrait impossible :

1 Business = plusieurs Locations

Une Location peut avoir notamment :

- adresse ;
- latitude ;
- longitude ;
- horaires ;
- statut ouvert / fermé ;
- disponibilité ;
- commandes ;
- paramètres opérationnels.

Ne pas implémenter toutes les fonctions multi-branches maintenant si elles ne sont pas nécessaires.

Préserver seulement l'extensibilité.

## Menu

Un commerce peut publier un menu.

## Category

Exemples :

- Entrées
- Plats
- Desserts
- Boissons

## Item

Un item contient notamment :

- nom ;
- description ;
- photo ;
- prix ;
- disponibilité ;
- temps de préparation ;
- métadonnées promotionnelles.

---

# 8. MODÈLES LEGACY

Le projet actuel contient encore des structures provenant de l'ancien MVP :

- CookProfile
- Dish
- DishAvailability
- Order
- Review
- PayU
- logique de découverte basée sur Dish

Ces structures ne doivent PAS être supprimées brutalement.

Avant toute modification structurelle :

1. inspecter les modèles actuels ;
2. inspecter leurs usages ;
3. identifier les données à préserver ;
4. proposer une migration progressive ;
5. éviter les doublons inutiles ;
6. éviter les migrations destructives.

Le legacy est un socle temporaire, pas la direction finale.

---

# 9. COMMANDE — RÈGLE MÉTIER FONDAMENTALE

Une commande client doit représenter UNE vraie commande commerciale.

La cible est :

Order
└── OrderItem
    ├── Item A x2
    ├── Item B x1
    └── Item C x1

Une commande :

- appartient à un client ;
- appartient à un commerce / point de vente ;
- peut contenir plusieurs lignes ;
- possède un total ;
- possède un statut opérationnel.

IMPORTANT :

Le comportement actuel où un checkout multi-items peut produire une `Order` indépendante par ligne est TRANSITOIRE.

Ne pas considérer cela comme le modèle final.

La priorité structurelle est de faire évoluer le domaine vers :

1 Order
+
N OrderItems

pour une commande mono-commerce.

---

# 10. PANIER

Pour le MVP :

UN PANIER = UN SEUL COMMERCE / POINT DE VENTE.

Le panier peut contenir plusieurs items du même commerce.

Il doit gérer :

- quantité ;
- prix unitaire ;
- sous-total ;
- total ;
- suppression ;
- modification ;
- stock disponible.

Le panier doit survivre :

- aux retours de navigation ;
- à un échec de paiement ;
- à l'ouverture d'un autre écran.

Un échec de paiement ne doit pas automatiquement vider le panier.

---

# 11. TUNNEL DE COMMANDE UNIQUE

KWITLI doit parler un seul langage transactionnel.

Flow MVP :

Item
→ Ajouter au panier
→ Continuer à commander
→ Panier
→ Continuer
→ Récapitulatif
→ Payer
→ Confirmation
→ Suivi

Ne pas réintroduire un tunnel parallèle comme :

- Commander maintenant
- Acheter maintenant
- Checkout direct séparé

sans demande produit explicite.

Le panier est la source de vérité du checkout MVP.

---

# 12. DÉCOUVERTE CLIENT — ZONE STABLE

La Home et la découverte ont nécessité beaucoup d'itérations.

Considérer leur direction actuelle comme STABLE.

Ne pas redesign la Home pendant une tâche fonctionnelle.

Structure actuelle à préserver :

- header ;
- localisation ;
- hero ;
- filtres ;
- titre de section ;
- résultats ;
- liste scrollable ;
- BottomNavigation.

Le haut de la Home reste fixe selon le comportement actuel validé.

La liste de résultats peut défiler indépendamment.

---

# 13. FILTRES HOME

## Près de moi

Règle MVP actuelle :

distance <= environ 1 km.

Préférer tri du plus proche au plus éloigné.

## Tout juste cuisiné

Concept :

ready_at <= now

et

now - ready_at <= environ 30 minutes

## Presque épuisé

Règle MVP actuelle :

1 <= stock <= 5

## Nouveautés

Peut inclure notamment :

- new
- dish_of_month
- discovery
- discount

La logique doit rester extensible.

---

# 14. EMPTY STATE / CHAUDRON

Le chaudron animé est un EMPTY STATE.

Règle :

aucun résultat général
→ chaudron.

résultats disponibles
→ résultats.

Un filtre particulier vide peut afficher un petit message discret.

Ne pas utiliser automatiquement le gros chaudron pour chaque filtre vide.

Ne pas modifier :

- AnimatedCauldron
- vapeur
- dimensions
- styles
- positionnement

sans demande explicite.

---

# 15. EXPLORER PLUS LOIN

La recherche élargie existe.

Rayons actuels :

- 5 km
- 10 km
- 20 km
- 30 km

Cela ne doit pas modifier la définition permanente de :

`Près de moi`.

---

# 16. STOCK

L'ancien système utilise notamment `DishAvailability`.

Ne pas déplacer arbitrairement le stock vers un autre modèle.

Principe métier :

le stock doit représenter la quantité réellement vendable dans le contexte opérationnel approprié.

Il peut dépendre notamment :

- de l'item ;
- du point de vente ;
- de la disponibilité ;
- du créneau ;
- de la date.

Toute réservation critique doit être protégée côté backend.

Éviter :

- survente ;
- double décrément ;
- confiance dans un stock envoyé par le mobile.

Les opérations critiques doivent être transactionnelles.

---

# 17. PAIEMENT — PRINCIPE D'ARCHITECTURE

Le domaine métier ne doit pas dépendre entièrement d'un fournisseur particulier.

Direction produit : Flutterwave est le fournisseur prioritaire du MVP Sénégal / XOF.
Le routage DEV utilise Flutterwave pour XOF et conserve PayU pour COP.

Architecture existante et cible :

```text
PaymentProvider
├── PayUProvider         # existant, legacy COP
├── PayDunyaProvider     # existant, conservé / futur possible
├── PayTechProvider      # existant, conservé / alternative et test
└── FlutterwaveProvider  # v3 TEST implémenté, priorité MVP XOF, test réel à valider
```

État confirmé par le porteur du projet pour Flutterwave : compte créé,
environnement test accessible et clés API test disponibles. Le support réel du
marché sénégalais reste à évaluer dans le sandbox ; la production n'est pas validée.
L'adaptateur v3 TEST est implémenté pour Wave et Orange Money avec vérification
serveur. Ne pas confondre tests automatisés et validation réelle du compte.

Conserver intégralement PayU / COP, PayDunya et PayTech. PayTech reste une
alternative / fallback configurable pour les tests, sans bascule automatique
après un timeout susceptible de provoquer une double collecte.

Intech : aucune intégration active, accès développeur non confirmé. Ce n'est plus
la cible prioritaire ; ne pas développer tant que l'accès n'est pas disponible.

Ne pas effectuer une refonte abstraite gigantesque sans nécessité.

Découpler progressivement.

---

# 18. PAYDUNYA — OPTION CONSERVÉE / CONNAISSANCES HISTORIQUES

PayDunya est conservé pour une éventuelle utilisation future, sans priorité MVP.
Les éléments historiques ci-dessous ne valent pas sélection du fournisseur :
la priorité d'intégration MVP Sénégal / XOF est Flutterwave (section 17).

Lors d'un échange avec PayDunya, la faisabilité technique du modèle :

Collecte
+
Payout

a été confirmée.

Le payout commerçant peut techniquement être automatisé via API.

PayDunya agit comme infrastructure / pont entre KWITLI et les opérateurs de paiement.

Les coûts exacts de production ne sont PAS encore suffisamment connus.

Ils peuvent dépendre notamment :

- du pays ;
- de l'opérateur ;
- de Wave ;
- d'Orange Money ;
- du volume ;
- du contrat ;
- du type de transaction.

Par conséquent :

NE PAS hardcoder les frais PayDunya.

NE PAS considérer PayDunya comme définitivement sélectionné en production tant que :

- tarifs ;
- contrat ;
- onboarding juridique ;
- conditions opérationnelles ;

ne sont pas validés.

Sandbox/test peut être utilisé lorsque cela est approprié.

---

# 19. MODÈLE COMMERCIAL

Hypothèse actuelle de lancement :

- inscription client gratuite ;
- inscription commerce gratuite ;
- pas d'abonnement obligatoire ;
- commission plateforme cible autour de 12 % ;
- frais de paiement idéalement absorbés dans cette commission ;
- prix client aussi simple que possible.

IMPORTANT :

12 % est actuellement une HYPOTHÈSE BUSINESS.

Ce n'est PAS une constante technique.

Ne jamais écrire arbitrairement :

commission = 0.12

à plusieurs endroits du code.

Utiliser une configuration métier centralisée.

Exemple :

platform_commission_rate

Cette valeur doit pouvoir évoluer selon :

- marché ;
- contrat ;
- fournisseur ;
- période ;
- stratégie commerciale.

---

# 20. FLUX FINANCIERS

Objectif actuel :

Client
→ paiement local
→ prestataire de paiement
→ payout local du commerçant
→ commission KWITLI séparée
→ règlement KWITLI ultérieur / agrégé

KWITLI ne souhaite PAS envoyer chaque transaction individuellement vers le Canada.

Le commerçant doit idéalement recevoir sa part :

- instantanément ;
ou
- le jour même.

La destination finale de la part KWITLI n'est pas encore figée.

Ne pas hardcoder un transfert Canada à chaque transaction.

---

# 21. PAYMENT ≠ ORDER

Séparer impérativement :

## Payment

Exemples de statuts :

- pending
- paid
- failed
- refunded
- partially_refunded éventuellement

## Order

Exemples :

- ordered
- in_progress
- ready
- picked_up
- cancelled

`paid` n'est pas un OrderStatus.

Un paiement peut réussir alors que la préparation n'a pas encore commencé.

---

# 22. PAYOUT

Le payout commerçant est une opération financière distincte.

Prévoir progressivement un modèle du type :

Payout
- id
- order_id
- merchant_id
- provider
- amount
- currency
- status
- provider_reference
- created_at
- completed_at
- failure_reason

Le payout doit être IDEMPOTENT.

Jamais :

callback répété
→ deuxième paiement du commerçant.

Un payout échoué doit pouvoir être analysé / retenté selon règles métier.

---

# 23. APRÈS COMMANDE

Flow cible :

ordered
→ in_progress
→ ready
→ picked_up

Le commerce doit pouvoir indiquer un délai de préparation.

Exemples :

- 10 min
- 15 min
- 20 min
- 30 min

Prévoir progressivement :

- preparation_started_at
- estimated_ready_at
- ready_at

Le client doit voir dans KWITLI :

- le statut ;
- le timer ;
- l'estimation ;
- le passage à "prête".

Le suivi normal doit être DANS KWITLI.

WhatsApp n'est pas un composant nécessaire du suivi normal.

---

# 24. RETRAIT

Le MVP est orienté PICKUP.

Prévoir un mécanisme de confirmation de retrait.

Base possible :

pickup_code généré serveur.

Évolution possible :

QR code.

`picked_up` doit correspondre à une vraie validation.

---

# 25. LIVRAISON

Ne pas construire maintenant une infrastructure complexe de livraison.

Le MVP actuel reste centré sur :

PICKUP / RETRAIT.

La livraison pourra être ajoutée ultérieurement.

---

# 26. REMBOURSEMENT

Règle importante :

demande de remboursement
≠
remboursement exécuté.

Un remboursement financier ne peut être exécuté que lorsqu'un paiement correspondant a été confirmé.

Flow cible :

Client
→ Mes commandes
→ Demander un remboursement
→ formulaire
→ examen
→ approbation / refus
→ remboursement si approuvé

RefundRequest possible :

- id
- order_id
- customer_id
- reason
- description
- requested_amount
- status
- created_at
- reviewed_at
- reviewed_by

Statuts possibles :

- submitted
- under_review
- approved
- rejected
- refunded

Motifs possibles :

- item_missing
- wrong_order
- order_not_received
- quality_issue
- excessive_delay
- duplicate_payment
- other

Si `other` :
description requise.

Le délai cible actuellement envisagé pour le traitement peut aller jusqu'à :

7 jours.

Ce délai doit rester configurable.

Ne pas créer automatiquement un remboursement à la simple demande du client.

Au début, le traitement peut être effectué par :

admin / support.

Ne pas construire inutilement un "département remboursement" complexe dans le code.

---

# 27. KYC

Les responsabilités KYC peuvent varier selon :

- pays ;
- fournisseur de paiement ;
- contrat ;
- statut du commerce.

PayDunya a indiqué que KWITLI devra gérer certaines responsabilités KYC dans le modèle étudié.

Ne pas inventer les exigences légales.

Ne pas hardcoder un KYC universel avant validation.

Prévoir une architecture compatible avec :

- pending
- verified
- rejected
- requires_action

Les documents KYC sont sensibles.

Appliquer des règles de sécurité strictes.

---

# 28. AVIS

Les avis doivent être liés à une expérience réelle.

Idéalement :

Order.picked_up
→ possibilité de Review.

Réutiliser le système Review existant si possible.

Ne pas créer un deuxième système d'avis parallèle.

---

# 29. PRIORITÉ STRUCTURELLE ACTUELLE

Le principal risque du projet est actuellement :

l'expérience client a avancé plus vite que le modèle métier commerce.

Ne pas continuer à améliorer indéfiniment l'ancien modèle :

Cook
+
Dish
+
PayU

comme s'il s'agissait de l'architecture finale.

La transition doit maintenant aller progressivement vers :

Business
+
Location
+
Menu
+
Category
+
Item
+
Order
+
OrderItem
+
Payment
+
Payout

sans reconstruction brutale.

---

# 30. ORDRE DE TRAVAIL ACTUEL

## Étape 0 — Stabiliser

Avant gros changement :

- inspecter git status ;
- vérifier modifications non commitées ;
- préserver le travail actuel ;
- éviter les rollbacks globaux ;
- créer un point stable lorsque demandé.

## Étape 1 — Unifier la commande métier

Priorité structurelle très importante :

1 Order
+
N OrderItems.

Ne pas conserver définitivement :

1 panier multi-items
→ N Orders indépendantes.

## Étape 2 — Structure commerce

Construire progressivement :

- Business
- Location / Branch compatible
- Menu
- Category
- Item
- horaires
- disponibilité
- stock
- promotions

## Étape 3 — Mode commerce

Permettre :

- gestion profil ;
- gestion menu ;
- commandes reçues ;
- préparation ;
- timer ;
- ready ;
- pickup.

## Étape 4 — Paiement fournisseur-agnostique

- préserver PayU legacy COP, PayDunya et PayTech existants ;
- réutiliser l'abstraction PaymentProvider sans refonte inutile ;
- valider Flutterwave TEST pour le MVP Sénégal / XOF sur le compte réel de test ;
- évaluer le support Sénégal dans le sandbox Flutterwave avant toute conclusion ;
- laisser Intech en attente d'accès développeur, sans intégration active ;
- ne pas activer production sans validation.

## Étape 5 — Finance et après-commande

- payout ;
- refund request ;
- avis ;
- réconciliation ;
- erreurs financières.

Ne pas sauter plusieurs étapes sans raison claire.

---

# 31. UX — PRINCIPE ABSOLU

Avant toute nouvelle fonctionnalité demander :

1. Est-ce plus simple pour le client ?
2. Est-ce plus simple pour le commerce ?
3. Cela réduit-il les appels ?
4. Cela réduit-il WhatsApp ?
5. L'action suivante est-elle évidente ?
6. Existe-t-il deux boutons qui font presque la même chose ?
7. Le parcours tourne-t-il en boucle ?
8. Le commerce pourrait-il gérer 50 commandes avec cette UX ?

Éviter :

- CTA caché ;
- bouton redondant ;
- deux tunnels transactionnels ;
- écran sans action suivante ;
- totals ambigus ;
- paiement différent du panier ;
- opérations manuelles évitables.

---

# 32. NE PAS REDESIGNER PAR ACCIDENT

Une tâche fonctionnelle n'autorise PAS un redesign.

Ne pas modifier sans demande explicite :

- Home ;
- header ;
- hero ;
- chaudron ;
- chips ;
- couleurs ;
- fonts ;
- BottomNavigation ;
- cartes ;
- spacings validés.

Si une modification visuelle est techniquement nécessaire :

expliquer d'abord pourquoi.

---

# 33. PROCESSUS DE TRAVAIL OBLIGATOIRE POUR CODEX

Avant une tâche importante :

1. lire `AGENTS.md` ;
2. inspecter les fichiers concernés ;
3. inspecter `git status` ;
4. identifier le bloc produit concerné ;
5. identifier legacy vs cible ;
6. vérifier les conséquences sur données existantes ;
7. réutiliser ce qui existe ;
8. expliquer brièvement le plan ;
9. modifier le minimum nécessaire ;
10. tester.

Ne jamais prendre une hypothèse produit majeure sans la signaler.

Si une information est inconnue :

NE PAS l'inventer.

Utiliser :
- TODO explicite ;
- configuration ;
- abstraction raisonnable ;
- question à l'utilisateur si bloquant.

---

# 34. DOCUMENTATION

`AGENTS.md` est la source principale de direction produit pour les agents de code.

Le README peut contenir des informations historiques ou dépassées.

Si README et AGENTS sont en conflit :

AGENTS prévaut pour la direction produit actuelle.

Le README devra être réaligné progressivement.

Ne pas utiliser une ancienne documentation Colombie / cuisine maison pour annuler les règles de ce fichier.

---

# 35. STACK

Backend :

- Python
- FastAPI
- SQLAlchemy

Mobile :

- React Native
- Expo
- TypeScript

Base cible :

- PostgreSQL

Base développement actuelle :

- utiliser l'existant.

API :

- REST actuellement.

---

# 36. DATABASE SAFETY

Ne jamais :

- supprimer une DB ;
- drop une table ;
- supprimer une migration ;
- supprimer des données ;
- changer un schéma destructivement ;

sans autorisation explicite.

Avant production :

migrations obligatoires.

Les opérations critiques doivent être :

- transactionnelles ;
- idempotentes lorsque nécessaire.

---

# 37. AUTHENTIFICATION ET AUTORISATION

- hash moderne des mots de passe ;
- secrets uniquement via environnement ;
- JWT / mécanisme actuel ;
- validation serveur obligatoire.

Ne jamais faire confiance à :

- user_id
- cook_id
- merchant_id
- business_id

fourni par le mobile lorsqu'il peut être dérivé du token ou validé côté serveur.

---

# 38. SECRETS

Ne jamais hardcoder :

- API keys
- passwords
- JWT secrets
- database passwords
- payment secrets
- tokens
- private keys

Les secrets restent dans `.env`.

Ne jamais imprimer un secret dans :

- terminal ;
- logs ;
- tests ;
- README ;
- exceptions.

`.env` ne doit jamais être commité.

`.env.example` uniquement avec placeholders.

---

# 39. GIT SAFETY

Toujours vérifier :

git status

avant gros changement.

Après gros changement :

présenter un résumé du diff.

Ne jamais automatiquement :

- git push
- git push --force
- git reset --hard
- git restore .
- git checkout .
- supprimer une branche
- réécrire l'historique

sans autorisation explicite.

Pour corriger un petit problème :

préférer un patch ciblé.

Jamais de rollback global par défaut.

---

# 40. UPLOADS

Toujours :

- valider MIME ;
- valider extension ;
- limiter taille ;
- nom unique serveur ;
- empêcher path traversal ;
- ne jamais exécuter fichier uploadé ;
- ne pas faire confiance au filename client.

---

# 41. API

Toujours :

- validation request ;
- authorization serveur ;
- messages 4xx clairs ;
- pas de stack trace côté client ;
- pas de secret ;
- validation métier serveur.

---

# 42. DEPENDENCIES

Ajouter uniquement si nécessaire.

Préférer :

- packages reconnus ;
- projets maintenus ;
- versions reproductibles.

Expliquer les nouvelles dépendances importantes.

Ne pas résoudre un problème simple avec une dépendance lourde sans nécessité.

---

# 43. PAYMENT SECURITY

Zone critique.

Toujours :

- Sandbox avant production ;
- secrets backend uniquement ;
- aucun stockage de carte complet ;
- total recalculé serveur ;
- ne jamais faire confiance au total mobile ;
- vérifier signatures callbacks ;
- idempotence ;
- contrôle des montants ;
- stock cohérent ;
- Order cohérente ;
- Payment cohérent ;
- Payout idempotent.

Ne jamais effectuer un payout réel sans autorisation explicite.

---

# 44. TESTS

Avant de déclarer une tâche terminée :

Backend :
- tests concernés ;
- tests existants pertinents ;
- error paths ;
- sécurité si pertinente.

Mobile :
- tests pertinents ;
- TypeScript ;
- vérification fonctionnelle.

Commandes usuelles :

pytest

cd mobile
npx tsc --noEmit

npx expo install --check

git diff --check

IMPORTANT :

TEST PASS
≠
UI VALIDATED.

Un changement visuel doit rester :

READY FOR HUMAN REVIEW

jusqu'à validation humaine.

Ne jamais annoncer :

FIXED

uniquement parce que :
- TypeScript compile ;
- tests passent ;
- logique semble correcte.

---

# 45. DEV DATA

Les seeds / données DEV doivent :

- rester DEV ;
- ne jamais contaminer prod ;
- être clairement identifiables ;
- être reproductibles ;
- correspondre à l'environnement réellement utilisé.

Ne pas changer la logique métier pour faire passer un seed.

---

# 46. PRODUCTION

Ne jamais automatiquement :

- déployer ;
- activer secrets live ;
- connecter données clients réelles ;
- lancer payouts réels ;
- utiliser paiement production ;
- modifier infrastructure production.

Autorisation explicite requise.

---

# 47. ÉTAT RÉEL DU PROJET

KWITLI est un MVP en développement.

## Relativement avancé

- auth ;
- Home ;
- localisation ;
- découverte ;
- filtres ;
- ExploreFarther ;
- empty state ;
- DishDetail legacy ;
- panier ;
- quantités ;
- récapitulatif ;
- PayU Sandbox ;
- PaymentProvider et adaptateurs PayDunya / PayTech existants, conservés ;
- certaines règles de stock ;
- tests existants.

## À réaligner

- CookProfile ;
- Dish ;
- DishAvailability ;
- Order par ligne ;
- dépendances CO/COP ;
- dépendance PayU ;
- README historique.

## À construire / finaliser

- Business ;
- Location / Branch ;
- Menu ;
- Category ;
- Item ;
- Order + OrderItem ;
- vrai mode commerce ;
- gestion menu ;
- commandes reçues ;
- préparation ;
- timer ;
- pickup ;
- FlutterwaveProvider : v3 TEST implémenté, validation réelle Sénégal / XOF à finaliser ;
- Payout ;
- RefundRequest ;
- KYC ;
- réconciliation financière.

---

# 48. DÉFINITION DU MVP RÉUSSI

Le MVP n'est pas réussi parce qu'il possède beaucoup d'écrans.

Le test principal est :

UN PETIT COMMERCE PEUT-IL TRAITER UNE COMMANDE COMPLÈTE DANS KWITLI ?

Commerce :

publie
→ reçoit commande
→ prépare
→ indique prête
→ reçoit son payout
→ remet commande

Client :

découvre
→ commande
→ paie
→ suit
→ récupère
→ évalue

sans processus manuel extérieur nécessaire pour une commande normale.

---

# 49. RÈGLE FINALE DE RECENTRAGE

Ne cherche plus à perfectionner indéfiniment :

Cook + Dish + PayU

comme s'il s'agissait du produit final.

Utiliser ce qui fonctionne comme socle.

Faire évoluer progressivement KWITLI vers :

Business
+
Location
+
Menu
+
Category
+
Item
+
Order
+
OrderItem
+
Payment
+
Payout

sans reconstruction brutale et sans perte du travail existant.

La question avant chaque gros changement est :

"Est-ce que cela rapproche KWITLI d'un système de commande réellement utilisable par un petit commerce ?"

Si la réponse est non :

ne pas prioriser cette modification.
