# Phase 3 — Validation des scénarios critiques du MVP restaurant

État : 15 octobre 2026. Audit de code et tests automatisés sur PostgreSQL local
`kwitli_test`. Ce rapport ne certifie ni la production, ni une transaction réelle,
ni les interfaces exécutées sur appareils.

## Cible et exécution

- Cible vérifiée avant test : `kwitli_test.public`, révision Alembic
  `f18c6a4d2b91`, PostgreSQL local via `/tmp:55433`.
- La configuration pytest refuse une autre base, un autre schéma, serveur non
  local ou révision différente. Chaque fixture vide uniquement les tables
  applicatives de `kwitli_test` avant/après le test.
- Première tentative ciblée bloquée avant setup par la sandbox
  (`Operation not permitted` sur le socket); aucune fixture n’a alors pu écrire.
  La reprise autorisée a réussi. Les invocations ont été séquentielles.
- Tests ciblés backend : **166 passed**, une mise en garde Starlette/httpx.
- Suite backend complète, une seule exécution : **387 passed**, même mise en garde.
- TypeScript : `npm run typecheck` **PASS**.
- Tests mobiles ciblés : discovery, actions panier/commande, UI panier-paiement,
  expérience client, dashboard marchand, workflow pickup/avis/messagerie,
  récupération paiement, navigateur et session : **PASS** (12 commandes).
- Révision de `kwitli_test` relue après tests : `f18c6a4d2b91`.
- Aucun test sur `kwitli_dev`, aucune migration, aucun paiement réel et aucune
  commande persistante créée hors fixtures.

## Registre des scénarios

`PASS` signifie test automatisé réussi ou vérification de code explicitement
indiquée. `FAIL` signifie que le comportement demandé n’est pas fourni ou que le
test existant confirme le risque. `NON TESTÉ` signifie absence de preuve
suffisante; une validation par lecture de code seule n’est pas présentée comme
un test runtime.

| # | Scénario | Résultat et preuve |
|---:|---|---|
| 1 | Restaurant non vérifié absent de la découverte et fiche publique inaccessible | **PASS** — `test_client_discovery.py` |
| 2 | Restaurant approuvé visible et menu public accessible | **PASS** — `test_admin_page.py`, `test_client_discovery.py` |
| 3 | Refus/suspension cachent le commerce; réactivation le rend visible | **PASS** — `test_admin_page.py` |
| 4 | Anonyme reçoit 401; client/commerçant non-admin reçoit 403; admin autorisé | **PASS** — `test_admin_page.py` |
| 5 | Checklist incomplète bloque l’approbation; motif de refus requis; CSRF invalide refusé; décision admin journalisée par les champs existants | **PASS** — `test_admin_page.py` et inspection du service |
| 6 | Soumission explicite `draft → pending_review` par le commerçant | **FAIL / écart** — aucune route/action de soumission trouvée. Toutefois `create_cook()` crée directement le profil avec le défaut ORM `pending_review`; l’admin le reçoit donc en attente dès la création. Ce n’est pas un blocage de visibilité, mais il n’existe pas d’étape distincte brouillon/soumission. Voir « Écarts ». |
| 7 | Horaire absent/jour fermé, limite d’ouverture incluse, limite de fermeture exclue, jour local et fuseau marché | **PASS** — `test_business_hours.py`, `test_market_timezone.py` |
| 8 | Restaurant fermé reste visible et paiement/commande est refusé côté serveur | **PASS** — `test_business_hours.py` |
| 9 | Restaurant ouvert et article actif autorisent la création du paiement | **PASS** — `test_business_hours.py` |
| 10 | Article inactif absent du menu public et refusé au paiement | **PASS** — `test_cart_checkout.py` |
| 11 | Quantités zéro, négatives et excessives dans le nouveau format `dish_id` | **NON TESTÉ** — le schéma commun impose 1–50 et des tests exercent ces limites sur le format legacy `availability_id`, mais l’API `dish_id` n’a pas de test négatif dédié. |
| 12 | Prix fourni par le client ne fixe pas le montant; total recalculé par le serveur | **PASS** — `test_cart_checkout.py`, `test_flutterwave.py` |
| 13 | Panier multi-articles `dish_id` sans disponibilité : total, ordre, lignes et quantités concordants | **NON TESTÉ** — le parcours multi-lignes automatisé couvre surtout le format legacy à disponibilités; le nouveau chemin `dish_id` testé porte sur un seul article. |
| 14 | Nouveau paiement `dish_id` sans `availability_id`, `StockHold` ni décrément daté | **PASS** — `test_active_dish_checkout_needs_no_availability_and_never_changes_legacy_stock` |
| 15 | Contournement du paiement via `POST /api/v1/orders` | **PASS** — la route répond 409; couvert par `test_mvp.py` / `test_order_workflow.py`. |
| 16 | Paiement pending ne crée pas encore de commande | **PASS** — tests Flutterwave/réconciliation; état vérifié avant confirmation fournisseur simulée. |
| 17 | Paiement approuvé vérifié crée une commande et ses lignes | **PASS** — tests PayU, Flutterwave et checkout panier avec fournisseurs mockés. |
| 18 | Paiement refusé/annulé ne crée pas d’Order | **PASS** — tests PayU, Flutterwave et `test_payment_reconciliation.py`. |
| 19 | Callback répété ou concurrent ne duplique pas l’approbation/commande | **PASS** — tests Flutterwave, PayTech, sécurité et workflow panier. |
| 20 | Montant, devise, référence ou identifiant fournisseur incohérents ne font pas approuver | **PASS** — tests Flutterwave et réconciliation. |
| 21 | Événement tardif d’échec ne renverse pas un paiement déjà approuvé | **PASS** — `test_flutterwave.py`. |
| 22 | Même requête de création de paiement répétée est idempotente | **FAIL — risque P0** — l’API crée deux Payments distincts pour deux POST identiques; `test_payment_attempts_use_distinct_stable_payu_references_and_preserve_ownership` le confirme et le service génère un nouvel UUID à chaque appel. Deux tentatives peuvent donc être payées séparément. Aucun double débit réel n’a été observé; le risque est dans la possibilité de deux tentatives facturables. |
| 23 | Paiement sandbox réel et retour navigateur sur build natif iOS/Android | **NON TESTÉ** — appels fournisseurs automatisés mockés; aucun build/appareil ni compte sandbox externe utilisé. |
| 24 | Commerçant ne lit que ses commandes; autre propriétaire refusé | **PASS** — `test_order_workflow.py`, `test_order_resolution.py`. |
| 25 | Alerte interne : premier chargement silencieux, nouveau batch signalé une fois, statut seul silencieux, rafraîchissement 15 s/foreground | **PASS automatisé** — `orders-workflow.test.cjs` et inspection du hook. **NON VALIDÉ runtime** sur appareils (compté au scénario 33). |
| 26 | Transitions opérationnelles autorisées, sauts interdits et timestamps préparation/prêt | **PASS** — `test_order_workflow.py`; transitions `ordered → in_progress → ready`, horodatages renseignés. |
| 27 | Code pickup faux ou lié à une autre commande refusé; commande non prête refusée | **PASS** — `test_order_workflow.py`. |
| 28 | Le client ne confirme pas le retrait; seul le commerçant propriétaire autorisé confirme | **PASS** — `test_order_workflow.py`. |
| 29 | Confirmation répétée n’effectue pas un second retrait; statut `picked_up` et `picked_up_at` persistés | **PASS** — `test_order_workflow.py`. |
| 30 | Avis prématuré, par tiers, multiple ou auto-évaluation refusé; avis après retrait autorisé | **PASS** — `test_order_workflow.py` et tests d’avis associés. |
| 31 | Messagerie propriétaire seulement; vide/231 caractères refusés, 230 acceptés | **PASS** — `test_order_messages.py`, `orders-workflow.test.cjs`. |
| 32 | Limite SQL historique 1000 vs limite API/service/mobile 230 | **PASS — écart confirmé** — modèle SQL et validation applicative inspectés; aucun changement de données/schéma. |
| 33 | Parcours bout en bout client iOS ↔ commerçant Android, son/vibration, navigateur paiement et reprise UI réelle | **NON TESTÉ** — aucune interaction simulateur/appareil pendant cette phase. |
| 34 | Payout commerçant, règlement Kwitli et disponibilité financière production | **NON TESTÉ** — hors preuve disponible; aucun payout réel exécuté. |

**Bilan du registre : 27 PASS, 2 FAIL/écarts, 5 NON TESTÉS** (34 scénarios).
Les résultats `PASS` automatisés ne remplacent pas le parcours humain natif.

## Anomalies et écarts

### P0 — Paiement : POST de création non idempotent

`POST /api/v1/payments` accepte plusieurs requêtes identiques et produit de
nouvelles références/identifiants. Les tests existants valident expressément
ces tentatives distinctes; l’idempotence testée porte sur les callbacks et la
finalisation d’un paiement, pas sur la création du checkout. Si le client
relance après une réponse perdue ou double-clique depuis plusieurs sessions,
plusieurs tentatives payables peuvent exister. Aucun double débit réel n’a été
reproduit en sandbox dans cette phase. **À résoudre avant pilote avec collecte**;
aucune correction n’est appliquée ici.

Références : `backend/app/services/payments/service.py` (`create_payment` crée un
nouvel identifiant), `backend/app/api/routes/payments.py`,
`backend/tests/test_mvp.py` (`test_payment_attempts_use_distinct_stable_payu_references_and_preserve_ownership`),
`mobile/src/payment-session.ts`.

### P2 — Soumission du restaurant

Aucune route/action `draft → pending_review` n’a été trouvée. Correction
importante à apporter au rapport Phase 2 : `CookProfile.approval_status` a un
défaut ORM et SQL `pending_review`; `create_cook()` crée donc directement un
profil en attente. L’admin peut le voir, mais une action distincte du commerçant
pour soumettre après complétion n’existe pas. Les comptes migrés peuvent encore
avoir d’autres états. Ce constat n’empêche pas le parcours courant création →
file d’attente admin, mais le statut « brouillon » n’a pas de transition métier
identifiée.

Références : `backend/app/persistence/models.py` (`CookProfile.approval_status`),
`backend/app/services/marketplace.py` (`create_cook`),
`backend/app/api/routes/cooks.py`, `backend/app/admin_page.py`. Aucune correction
ni modification du document Phase 2 n’a été faite.

## Couverture manquante à prévoir

- Ajouter une clé/idempotency key serveur au checkout avec test de deux POST
  identiques, y compris réponse perdue/reprise et absence de second encaissement.
- Tester directement `dish_id` avec quantités 0, -1, 51 et au moins deux
  articles actifs du même commerce; vérifier prix, total, `OrderItem` et absence
  de holds/décrément.
- Décider produit si une soumission explicite du profil est requise; si oui,
  définir l’état initial et le passage en file sans auto-approbation.
- Faire un test manuel natif iOS/Android avec fournisseur TEST autorisé, sans
  confondre page succès fournisseur avec état approuvé backend.
- Réaliser une revue humaine du dashboard/alerte et confirmer la visibilité
  d’une commande prête, du code et de l’avis sur les appareils visés.

## Limites avant pilote

- Pas de validation réelle sandbox iOS/Android ni de capacité du compte
  fournisseur; les tests backend mockent les appels réseau des prestataires.
- L’alerte marchand reste dans l’app : polling 15 secondes/retour foreground,
  sans push, et aucun son/vibration si le scope marchand n’est pas actif.
- PayU/Flutterwave/PayDunya/PayTech ont des chemins de test automatisés; cela ne
  valide ni contrat, ni frais, ni marché réel, ni payout.
- Aucun payout automatisé ni remboursement financier validé; la demande de
  résolution n’est pas un remboursement.
- Limite de messages SQL 1000 caractères, malgré la limite applicative 230.
- Le modèle métier est encore `CookProfile`/`Dish`; les disponibilités legacy
  restent dans le schéma. Les tests de stock legacy ne prouvent pas un stock du
  checkout MVP, qui n’en utilise pas.
- Validation manuelle admin/commerçant, restauration de session, horaires
  multi-marché et obligations légales de marché demeurent à contrôler avant un
  pilote avec de vrais commerces.

## Vérifications finales et périmètre

- Backend : ciblés `166 passed`; suite complète `387 passed`.
- Mobile : TypeScript **PASS** et 11 suites/tests mobiles ciblés **PASS**;
  avertissements Node de module typeless sur les tests TS, sans échec.
- PostgreSQL `kwitli_test` relu après tests : révision `f18c6a4d2b91`.
- `kwitli_dev` n’a été ni ciblée, ni modifiée par les commandes de cette phase;
  aucune migration ou commande de données n’a été lancée contre elle.
- Aucun paiement réel, commande manuelle, migration, correctif code/test,
  modification de donnée ou commit/push effectué.
- `git diff --check` : à vérifier après création du présent fichier; aucun fichier
  applicatif modifié.

État UI/runtime : **READY FOR HUMAN REVIEW**. Phase 3 documente des tests et
risques; elle ne déclare pas le parcours complet fiable sur appareil.
