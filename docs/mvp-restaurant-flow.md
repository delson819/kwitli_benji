# Parcours MVP restaurant Kwitli

Référence fonctionnelle établie le 15 octobre 2026 par inspection du backend,
du mobile et de `docs/phase1-readiness.md`. Elle décrit le chemin de commande
restaurant pickup actuel, pas une validation de production ni une preuve de test
manuel sur appareil.

## Modèle et portée

Le produit expose encore le modèle legacy `CookProfile` / `Dish`; le vocabulaire
« commerce » et « article » du mobile représente ce modèle, sans tables Business,
Location, Menu ou Category dédiées. Une commande payée par le chemin MVP contient
une `Order` mono-commerce et plusieurs `OrderItem`. Le code garde aussi les
chemins legacy basés sur `DishAvailability`; ils ne sont pas le chemin décrit
ci-dessous.

Pour les erreurs métier, l’API renvoie généralement `401` pour une session
absente/invalide, `403` pour un acteur non autorisé, `404` pour une ressource
introuvable, `409` pour un conflit d’état ou une règle métier et `422` pour une
requête invalide. Les détails ci-dessous précisent les réponses connues du code.

## Parcours en 12 étapes

### 1. Le commerçant crée son restaurant

- **Acteur/action :** commerçant connecté; crée son profil depuis Commerce.
- **Règle :** un profil par utilisateur; `display_name`, latitude et longitude
  sont requis par la requête. Un nouveau profil n’est pas public par défaut.
- **État :** création du profil; l’approbation reste à faire par Kwitli. La
  création ne change pas de commande.
- **API/mobile :** `POST /api/v1/cooks`, `createCook()` et le formulaire Commerce.
- **Échecs :** profil déjà existant `409`; validation des champs `422`; profil
  propriétaire requis pour la suite.

### 2. Il complète la fiche, les horaires et le menu

- **Acteur/action :** propriétaire; renseigne nom, description, GPS, photo,
  horaires hebdomadaires et articles, puis active les articles publiés.
- **Règle :** le GPS est celui du point de retrait. Les sept jours doivent être
  soumis; un jour fermé n’a pas d’heures, un jour ouvert a une plage où l’heure
  de fermeture est strictement après l’ouverture. Les horaires traversant
  minuit ne sont donc pas pris en charge.
- **État :** les modifications de fiche/menu ne rendent pas à elles seules le
  commerce visible.
- **API/mobile :** `PATCH /api/v1/cooks/me`, `POST /api/v1/cooks/me/photo`,
  `GET`/`PUT /api/v1/cooks/me/hours`, `POST /api/v1/dishes`,
  `PATCH /api/v1/dishes/{dish_id}` et `POST /api/v1/dishes/{dish_id}/photo`;
  sections Mon établissement et Menu dans `MerchantDashboard.tsx`.
- **Échecs :** champs/heures invalides `422`; utilisateur sans profil ou non
  propriétaire `403`; erreurs d’upload sont renvoyées par la route image.

### 3. L’administrateur examine et décide

- **Acteur/action :** administrateur Kwitli; consulte la page HTML et approuve,
  refuse, suspend ou réactive une fiche selon son état.
- **Règle :** `/admin` utilise HTTP Basic et exige `is_admin=true`. L’approbation
  est disponible pour `pending_review` seulement et requiert nom, description,
  GPS, sept jours d’horaires, au moins un article actif et un compte propriétaire
  actif. Le refus demande un motif. Le commerçant ne possède pas cette action.
- **État :** approbation met `approval_status=approved` et `is_verified=true`;
  refus donne `rejected`/`false`; suspension donne `suspended`/`false`;
  réactivation donne `approved`/`true`. Aucun statut de commande n’est changé.
- **API/fichiers :** `GET /admin`; formulaire `POST
  /admin/restaurants/{cook_id}/decision`; `admin_page.py` et les méthodes
  d’administration de `MarketplaceService`. POST protégé par jeton CSRF signé
  à durée limitée.
- **Échecs :** anonyme `401`, non-admin `403`; fiche incomplète ou décision
  incompatible avec l’état `409`; ressource non admissible `404`.

### 4. Le client découvre le restaurant approuvé

- **Acteur/action :** client; ouvre Accueil, choisit sa zone/position puis une
  fiche de restaurant.
- **Règle :** le filtre public du dépôt utilise `CookProfile.is_verified`, le
  compte propriétaire actif et exclut les adresses `.invalid`; il ne vérifie pas
  directement `approval_status`. Les actions admin maintiennent les deux champs
  synchronisés. La découverte calcule la distance, applique le rayon demandé et
  inclut un indicateur `is_open`; le profil public ne renvoie que les articles
  actifs. Un restaurant fermé reste présent si les autres filtres correspondent.
- **État :** aucun changement de commande.
- **API/mobile :** `GET /api/v1/discover?latitude=…&longitude=…&radius_km=…`,
  `GET /api/v1/cooks/{cook_id}/public`; Home, `BusinessDiscoveryCard.tsx` et
  `PublicBusinessProfile.tsx`.
- **Échecs :** un profil non vérifié/inactif ou sans article actif est absent;
  hors rayon ou filtre incompatible, il n’est pas dans les résultats. Les
  coordonnées de découverte doivent être valides.

### 5. Le client choisit les articles et quantités

- **Acteur/action :** client; choisit un article de la fiche restaurant, ajuste
  sa quantité et l’ajoute au panier.
- **Règle :** le panier est limité à un commerce et une devise. Les articles
  inactifs ne font pas partie du menu public. Les quantités sont validées par le
  backend au paiement, entre 1 et 50 par ligne. Aucun stock artificiel ni
  disponibilité datée n’est requis dans le chemin `dish_id` MVP.
- **État :** aucun changement de commande ni paiement tant que le paiement n’est
  pas créé.
- **API/mobile :** profil public; `DishDetail.tsx`, `CartScreen.tsx`, état panier
  mobile. Le contrôle serveur définitif intervient à la prochaine étape.
- **Échecs :** restaurant fermé, article désactivé ou quantité hors limites
  bloque le checkout côté serveur; l’écran panier indique le restaurant fermé.

### 6. Le client confirme le panier et paie

- **Acteur/action :** client; choisit un moyen proposé, puis paie depuis le
  récapitulatif.
- **Règle :** le chemin mobile appelle `POST /api/v1/payments` avec des lignes
  `dish_id` + `quantity` pour le nouveau checkout. Le serveur relit les prix,
  calcule les montants et crée un `Payment` pending avec des `PaymentItem`; il
  ne crée ni `StockHold` ni décrément de `DishAvailability` pour ce chemin. Le
  panier est mono-commerce/mono-devise. Le client ne crée pas lui-même l’Order :
  une Order et ses OrderItems sont créés lors de l’approbation serveur du
  paiement. Aucun pourboire n’est inclus.
- **Statuts :** avant, aucune commande issue de ce paiement; après création,
  `Payment=pending`; après confirmation serveur réussie, `Payment=approved` et
  `Order=ordered`. Un retour navigateur seul ne vaut pas approbation.
- **API/mobile :** `POST /api/v1/payments`, puis `GET /api/v1/payments/{id}` pour
  récupération/vérification; `CartSummary.tsx`, `payment-session.ts` et le
  service paiement backend. Écran de commande créé seulement à la confirmation.
- **Échecs :** commerce non vérifié, fermé, article inactif, quantité invalide,
  devise/montant ou fournisseur non disponible sont refusés. Une réponse
  fournisseur incertaine peut laisser le paiement pending; pas de nouvelle
  collecte automatique. Declined/cancelled ne crée pas d’Order. Le traitement
  précis dépend du fournisseur configuré.

### 7. Le commerçant reçoit la commande et une alerte interne

- **Acteur/action :** commerçant; Commerce ouvert dans l’app, voit la nouvelle
  commande dans Commandes reçues.
- **Règle :** le scope marchand charge `GET /api/v1/orders?scope=cook`, interroge
  toutes les 15 secondes et actualise au retour au premier plan. Le premier
  chargement est silencieux; les nouveaux IDs de commandes actives déclenchent
  une alerte interne, son/vibration tentés sans bloquer le flux et un compteur
  visible. Ouvrir la liste marque les arrivées vues.
- **État :** `ordered`, sans transition au simple chargement.
- **Mobile :** `MerchantDashboard.tsx`, hook `useMerchantOrdersMonitor` et
  `OrdersScreen.tsx`.
- **Échecs/limites :** erreur réseau/API affiche un échec de chargement et la
  commande n’est pas consultable tant que la liste ne recharge pas. Pas de push;
  l’écoute ne tourne pas lorsque le scope marchand est démonté ou l’app en
  arrière-plan. L’audio/vibration peut ne pas être disponible ou audible.

### 8. Le commerçant commence la préparation

- **Acteur/action :** propriétaire du commerce; ouvre la commande et démarre la
  préparation.
- **Règle :** seule la transition `ordered → in_progress` est autorisée dans le
  nouveau parcours. L’identité propriétaire est dérivée de la session.
- **Statut/horodatage :** `ordered → in_progress`; `in_progress_at` est renseigné.
- **API/mobile :** `PATCH /api/v1/orders/{order_id}/status` avec
  `{"status":"in_progress"}`; détail dans `OrdersScreen.tsx`.
- **Échecs :** autre utilisateur `403`; ordre absent `404`; transition invalide
  `409`.

### 9. Le commerçant marque la commande prête

- **Acteur/action :** commerçant; marque la commande prête après préparation.
- **Règle :** transition `in_progress → ready`; aucune confirmation client n’est
  nécessaire pour rendre l’état prêt.
- **Statut/horodatage :** `ready_at` est renseigné; la commande et le code de
  retrait sont ensuite disponibles au parcours pickup.
- **API/mobile :** même endpoint `PATCH /api/v1/orders/{order_id}/status` avec
  `{"status":"ready"}`; bouton « Marquer prête ».
- **Échecs :** utilisateur non propriétaire `403`; statut précédent incorrect
  `409`.

### 10. Le client affiche son code de retrait

- **Acteur/action :** client propriétaire de la commande; ouvre le détail prêt et
  demande l’affichage du code.
- **Règle :** seulement le client de cette commande peut demander le code et
  seulement à l’état `ready`. Le client ne change pas le statut.
- **Statut :** reste `ready`; `POST /api/v1/orders/{order_id}/pickup/code` renvoie
  le détail et le code au client autorisé.
- **Mobile :** `ClientOrderDetail` dans `ClientOrderViews.tsx`; appel depuis
  `OrdersScreen.tsx`.
- **Échecs :** mauvais utilisateur `403`; commande absente `404`; pas prête ou
  période/code expiré `409`. La route est limitée en débit.

### 11. Le commerçant vérifie le code et confirme la récupération

- **Acteur/action :** client présente le code; commerçant le saisit et confirme.
- **Règle :** seul le propriétaire du commerce peut confirmer; le code à six
  chiffres doit correspondre, la commande doit être `ready` et la fenêtre de
  retrait ne doit pas être expirée. Le client ne peut pas appeler la confirmation
  pour faire passer lui-même la commande à `picked_up`.
- **Statut/horodatage :** nouvelle commande MVP sans `availability_id` :
  `ready → picked_up`, `picked_up_at` et `picked_up_by` renseignés. Le traitement
  des commandes legacy avec `availability_id` conserve un chemin historique
  pouvant donner `completed` directement.
- **API/mobile :** `POST /api/v1/orders/{order_id}/pickup/confirm` avec
  `{"pickup_code":"123456"}`; champ de saisie dans le détail commerçant de
  `OrdersScreen.tsx`.
- **Échecs :** utilisateur non autorisé `403`; code faux, non prêt, déjà traité
  ou expiré `409`; commande absente `404`. La route est limitée en débit.

### 12. Le client laisse un avis après retrait

- **Acteur/action :** client propriétaire; laisse une note/commentaire après le
  retrait et consulte ensuite l’avis publié.
- **Règle :** le service autorise `picked_up` ou `completed`, refuse un avis avant
  récupération et limite à un avis par commande. Un commerçant ne peut pas
  évaluer sa propre commande.
- **Statut :** reste `picked_up`/`completed`; l’avis ne change pas l’ordre ni le
  paiement.
- **API/mobile :** `POST /api/v1/reviews`; section avis du détail dans
  `ClientOrderViews.tsx` et chargement des avis publics dans la fiche commerce.
- **Échecs :** commande d’un autre client `403`; commande pas récupérée ou avis
  déjà créé `409`; champs invalides `422`.

## Règles publiques et opérationnelles vérifiées

| Sujet | Comportement du code observé |
| --- | --- |
| Visibilité | `is_verified=true`, propriétaire actif et filtre anti-compte `.invalid`; les décisions admin synchronisent `approval_status` et `is_verified`. `approval_status` n’est pas la condition directe des requêtes publiques. |
| Horaires | Sept jours stockés dans `CookProfileHour`; heure locale du marché (`launch_country`, fuseau configuré en fallback); intervalle ouvert `[ouverture, fermeture)`. Horaire absent, jour fermé ou hors plage signifie fermé. Pas de précommande ni de gestion d’horaires spéciaux. |
| Commerce fermé | Reste découvrable et le profil public expose `is_open=false`; panier/checkout doit être bloqué. Le serveur vérifie de nouveau l’ouverture au début du paiement. |
| Menu | Découverte et profil public filtrent les articles actifs; le nouveau paiement revalide l’activité. Le prix des lignes et le total sont calculés côté serveur. |
| Stock | Chemin de paiement `dish_id`: pas de disponibilité requise, de hold ou de décrément de stock daté. Les tables, endpoints et chemins legacy restent présents. |
| Commande | Une confirmation serveur du paiement crée une seule Order mono-commerce avec N OrderItems. `confirmed_at` correspond à la création après paiement; `in_progress_at`, `ready_at`, `picked_up_at` suivent les actions opérationnelles. |
| Paiement | En DEV/TEST, COP est routé vers PayU; XOF vers le fournisseur configuré (`XOF_PAYMENT_PROVIDER`, défaut Flutterwave). Flutterwave est limité au mode `test`; XOF est refusé hors `development`/`test`. PayDunya et PayTech ont des adaptateurs conservés/configurables. Aucun paiement production ni payout n’est déclaré validé. |
| Messagerie | `GET/POST /api/v1/orders/{order_id}/messages`; client de la commande et propriétaire du commerce seulement; 50 messages récents triés ancien→récent; texte non vide. Validation service/API et UI à 230 caractères, contrainte SQL historique à 1000. Les messages ne changent ni statut ni paiement. |
| Remboursement / litige | Une demande de résolution est distincte d’un remboursement. La décision support enregistrée ne modifie pas automatiquement la commande ou le paiement. |
| Pourboire | Aucun champ ou calcul de pourboire dans le parcours MVP documenté. |

### Modes de paiement : précision d’environnement

Le chemin moderne XOF utilise Flutterwave TEST par défaut et autorise Wave ou
Orange Money selon la configuration et la réponse d’action du fournisseur. La
vérification backend, et non la page de succès du navigateur, décide si le
paiement est approuvé. Les appels fournisseur des tests automatisés sont mockés.
Le compte test, le retour automatique sur un build natif et une transaction
sandbox réelle doivent être validés manuellement avant de conclure que le parcours
est opérationnel sur appareil. Expo Go ne garantit pas le retour par scheme natif.

## Cas d’erreur et réponse courante

| Cas | Réponse actuelle / effet |
| --- | --- |
| Restaurant non approuvé | Découverte/publicité filtrée par `is_verified`; création du paiement refusée avec erreur métier, pas d’Order. Admin seulement peut approuver. |
| Restaurant refusé/suspendu | Admin synchronise `is_verified=false`; invisible dans les requêtes publiques; checkout refusé. |
| Restaurant fermé | `is_open=false` côté découverte/profil; checkout refusé avec « Ce restaurant est fermé pour le moment. »; aucune précommande. |
| Article inactif | Absent du menu public; le service de création du paiement refuse explicitement et ne crée pas d’Order. |
| Quantité invalide | Schéma/service refuse quantité hors 1–50; requête rejetée, pas de commande. |
| Paiement échoué/annulé | Le statut de paiement est réconcilié depuis le fournisseur. Declined/cancelled ne crée pas d’Order; panier mobile est conservé selon le parcours checkout. Une réponse incertaine peut rester pending, sans nouvelle collecte automatique. |
| Commande absente de la liste | Le mobile affiche une erreur générique de chargement et permet de réessayer; la surveillance marchand retente au polling ou au retour au premier plan. Les causes 401/403/réseau restent distinctes dans les logs DEV, mais l’interface ne fournit pas nécessairement le détail technique. |
| Code pickup faux | `409` « Code de retrait invalide. »; la commande reste ready. |
| Pickup par non-propriétaire/client | `403` pour acteur non autorisé; le client ne peut pas finaliser le retrait. |
| Avis avant récupération | `409`; aucun avis n’est créé. |
| Messagerie par autre utilisateur | `403`; ressource de commande inexistante `404`; corps vide ou >230 rejeté (`422` via schéma ou erreur métier selon le chemin). |

## Écarts constatés et limites connues avant pilote

- Le modèle et les API restent `CookProfile`/`Dish`; le domaine cible Business / Location / Menu / Item n’est pas encore réalisé.
- `GET /api/v1/orders` existe, mais l’ancienne route `POST /api/v1/orders` est
  volontairement désactivée et renvoie `409`; la création normale de commande
  se fait après approbation d’un `Payment`.
- Les routes et structures `DishAvailability`/`StockHold` persistent pour le
  legacy. Le code de découverte a encore une jointure externe vers des
  disponibilités, et le filtre backend legacy `low_stock` est toujours reconnu;
  les écrans MVP ne doivent pas en déduire un stock opérationnel moderne. Ce
  reliquat mérite une tâche séparée, pas une modification dans cette phase doc.
- Le code d’approbation admin exige une fiche complète, mais les nouvelles
  créations sont directement en `draft` selon le défaut actuel; une action de
  soumission `draft → pending_review` n’a pas été identifiée dans les routes
  examinées. Vérifier le processus de soumission manuellement avant le pilote.
- La découverte renvoie des éléments par article; le regroupement par commerce
  est effectué côté mobile et n’est pas un catalogue multi-branches.
- Le code accepte les horaires journaliers simples, sans plage traversant
  minuit, jours fériés ou exceptions.
- Il n’y a pas de notification push native. L’alerte de nouvelle commande
  dépend du scope marchand monté et d’un cycle polling/foreground.
- La validation d’une transaction Flutterwave réelle dans l’environnement TEST
  et le retour automatique d’un build natif iOS/Android restent à confirmer.
- Le payout commerçant, la réconciliation financière, le traitement opérationnel
  des paiements en conflit, les remboursements exécutés et les obligations
  marché/juridiques ne sont pas validés. Une demande de résolution n’est pas un
  remboursement.
- Le mobile et les règles de service limitent les messages à 230 caractères,
  mais la contrainte SQL historique autorise 1000; les données existantes n’ont
  pas été auditées ni resserrées dans cette phase.
- La phase 1 a indiqué 387 tests backend réussis sur `kwitli_test`, TypeScript et
  tests mobiles ciblés réussis, mais aucun parcours natif complet. Cette phase
  est une inspection documentaire; elle n’ajoute pas un résultat de test runtime.

## Références de code inspectées

- `backend/app/api/routes/cooks.py`, `business_hours.py`, `discover.py`,
  `orders.py`, `payments.py`, `reviews.py`;
- `backend/app/admin_page.py`, `backend/app/services/marketplace.py`,
  `backend/app/services/payments/service.py`,
  `backend/app/repositories/sqlalchemy.py`,
  `backend/app/core/business_hours.py`, `backend/app/core/time.py`;
- `backend/app/schemas/cooks.py`, `business_hours.py`, `orders.py`, `payments.py`;
- `mobile/src/services/api.ts`, `components/MerchantDashboard.tsx`,
  `OrdersScreen.tsx`, `ClientOrderViews.tsx`, `PublicBusinessProfile.tsx`,
  `CartScreen.tsx`, `CartSummary.tsx`, `payment-session.ts`;
- `docs/phase1-readiness.md`, `docs/flutterwave-test.md`.

## Statut de validation

Documentation seulement. Aucun code, test, migration, base de données, compte,
commande ou paiement n’a été modifié. Les vérifications de phase 1 et les
révisions DB citées ci-dessus sont celles consignées dans
`docs/phase1-readiness.md`, relevé du 15 octobre 2026; aucune nouvelle connexion
aux bases n’a été effectuée pour cette rédaction.

Statut UI/runtime : **READY FOR HUMAN REVIEW**. Aucun commit ni push inclus.
