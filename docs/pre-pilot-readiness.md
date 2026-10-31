# Stabilisation avant pilote Kwitli

État observé le 10 octobre 2026. Ce document suit les risques à régler avant
toute collecte réelle. Flutterwave reste volontairement en TEST et ce choix
n'est pas un défaut à corriger.

## Corrections appliquées

- Le fuseau métier est résolu depuis le marché (`LAUNCH_COUNTRY`) ; le Sénégal
  (`SN`) utilise `Africa/Dakar`. `MARKET_TIMEZONE` sert de fallback configurable
  pour les marchés inconnus (UTC dans `.env.example`). Les disponibilités,
  validations et seeds utilisent ce fuseau puis convertissent les instants en UTC.
- Les paiements `paid_stock_conflict`, `reconcile_required`, `refund_pending`,
  `refunded` et les statuts inconnus passent dans un état mobile bloquant. Le
  checkout n'affiche ni « Payer » ni « Réessayer » pour ces paiements.
- La liste publique `GET /api/v1/reviews/cooks/{id}` n'expose plus
  `customer_id` ni `order_id`.
- Les fichiers `kwitli-before-*.db` sont ignorés par Git. Les sauvegardes
  existantes ne sont ni supprimées ni ajoutées au dépôt.

## Paiements et argent réel

La création d'un paiement exige maintenant l'en-tête `Idempotency-Key`
(migration `6d2f81a4c970_payment_creation_idempotency`, tests
`test_payment_idempotency.py`). Un rejeu avec la même clé renvoie le même
Payment. La conception mise en œuvre est la suivante :

1. Le mobile génère une clé aléatoire par tentative et la conserve jusqu'à la
   résolution de cette tentative.
2. L'API lie la clé à l'utilisateur et à l'empreinte canonique du panier. Une
   clé répétée avec un panier différent retourne `409`.
3. Une contrainte unique en base garantit qu'une clé ne peut créer qu'un
   Payment. Un rejeu retourne le même Payment et ne rappelle jamais l'API de
   collecte du fournisseur.
4. Les réponses perdues et les appels fournisseur incertains restent attachés
   au même Payment et passent par la vérification existante. Aucun fallback
   vers un nouveau Payment ou un autre fournisseur n'est automatique.

Reste à décider : la durée de conservation des clés.

Les notifications PayTech ne signent que le montant et la référence, pas
`type_event`. Une approbation qui arrive après un état terminal passe donc en
`reconcile_required` au lieu de créer une commande. La vérification serveur via
`payment/get-status` reste à brancher dès que PayTech publie le schéma de réponse.

Le passage en argent réel est interdit avant validation complète de :

- retour Flutterwave sur iOS et Android, suivi de la vérification backend ;
- rejeu/idempotence et réconciliation des paiements incertains ;
- remboursement contrôlé et procédure de litige/support ;
- payout marchand idempotent, rapprochement et preuve de réception ;
- responsabilités légales, contrat, KYC et frais du marché pilote.

L'absence de paiement réel et de payout réel est attendue pour le MVP de test.

## Alertes npm

`npm audit` sur le lockfile mobile a rapporté 41 vulnérabilités : 13 modérées,
27 élevées et 1 critique. Les chemins les plus visibles concernent Expo CLI,
Metro, la configuration/build Xcode, `image-size`, `compression`, `undici`,
`postcss`, ainsi que `shell-quote` via React DevTools. Ces composants servent
principalement au développement et au build local; les alertes de ces chemins
ne prouvent pas qu'un binaire publié embarque le code vulnérable.

Le rapport mentionne aussi Expo, React Native et Expo Linking comme dépendances
directes. Il faut donc vérifier le graphe du build natif avant distribution.
Les remédiations globales proposées par npm basculent vers des versions
majeures hors du SDK Expo actuel; aucun `npm audit fix` n'a été exécuté. Garder
Metro et les outils de développement sur une interface locale/de confiance,
puis traiter les alertes lors d'une mise à niveau Expo planifiée et testée sur
iOS et Android.

## Commandes reçues et fonctionnement en arrière-plan

Le marchand interroge les commandes toutes les 15 secondes lorsque son espace
est actif. Une reprise au premier plan déclenche aussi un rafraîchissement. En
arrière-plan, le polling et les alertes locales s'arrêtent; aucune notification
système distante n'est configurée.

Procédure MVP avant notification push : garder l'application marchand ouverte
et active pendant les heures de service, activer le son/vibreur de l'appareil,
et vérifier l'écran Commandes reçues à la prise de poste et après toute perte de
réseau ou redémarrage. Le commerce doit disposer d'un contact opérationnel
Kwitli pour signaler une commande manquée. Avant d'ajouter du push, définir les
propriétaires de la livraison, les reprises après reconnexion et la déduplication
des alertes.

## Checklist opérationnelle avant pilote

Chaque case est un critère de lancement, pas une fonctionnalité réputée déjà
installée. Garder un responsable, une date et une preuve pour chaque validation.

### PostgreSQL et sauvegardes

- [ ] `kwitli_dev` et `kwitli_test` sont des bases distinctes; les tests refusent
  toute cible qui n'est pas explicitement locale et nommée `kwitli_test`.
- [ ] La révision Alembic de la base de test est la tête du dépôt avant les tests.
- [ ] La stratégie de sauvegarde de la base pilote est définie : fréquence,
  rétention, chiffrement, accès restreint et responsable.
- [ ] Une restauration réelle a été répétée sur une instance isolée; le temps de
  restauration et la cohérence FK sont consignés.
- [ ] Les photos de `backend/uploads/` sont sauvegardées et restaurables avec les
  références enregistrées en base.

### Journaux, alertes et incidents

- [ ] Les logs ne contiennent ni mots de passe, JWT, secrets fournisseurs,
  en-têtes d'authentification, données de carte ou contenu complet des payloads.
- [ ] L'accès aux logs est limité et une durée de conservation est décidée.
- [ ] Une alerte surveille indisponibilité API/DB et erreurs répétées de paiement,
  webhook, upload et création de commande; les seuils et destinataires sont
  définis avant le pilote.
- [ ] Un paiement `pending` ou à résultat incertain est vérifié auprès du
  fournisseur pour le même Payment; aucun nouveau paiement n'est lancé à
  l'aveugle.
- [ ] `paid_stock_conflict` / `reconcile_required` déclenche une escalade support;
  aucun stock n'est décrémenté manuellement et aucun remboursement automatique
  n'est lancé.
- [ ] Le support sait retrouver `tx_ref`, Payment, Order, réponse fournisseur et
  historique webhook sans communiquer de secret au client.

### Comptes support et commerce

- [ ] Les comptes admin sont nominatifs, attribués via une procédure hors
  inscription publique, au moindre privilège et avec révocation testée.
- [ ] Les décisions support sont traçables (acteur, date, note); un second
  contrôle est défini pour toute décision financière.
- [ ] Le contact opérationnel Kwitli, les heures de couverture, la procédure de
  commande manquée et le canal de signalement sont communiqués au commerce.
- [ ] Les commerces pilotes ont accepté le processus de collecte, payout,
  réclamation, remboursement et traitement des incidents.

### Validation technique PostgreSQL

- [ ] La base isolée `kwitli_test` est joignable localement et migrée par Alembic
  jusqu'à la tête courante. Ne jamais lancer les tests sur `kwitli_dev`.
- [ ] La suite backend complète passe sur PostgreSQL, y compris verrous,
  transactions concurrentes, FK, unicité, contraintes `CHECK` et stock.
- [ ] `kwitli_dev` est sauvegardée avant toute migration; sa révision réelle,
  son intégrité et ses FK sont vérifiées. Une migration DEV requiert une
  autorisation distincte.
- [ ] Les scénarios natifs iOS et Android couvrent commande multi-articles,
  paiement sandbox, retour automatique, confirmation serveur, décrément unique,
  retrait et avis. Un retour navigateur seul ne prouve jamais le paiement.
- [ ] Flutterwave XOF reste en TEST jusqu'à validation fournisseur, cadre légal,
  KYC, frais, collecte, payout et remboursements du marché choisi.

## État Git

Le checkpoint `6a774c9` est déjà poussé sur `origin/main`. Les sauvegardes
SQLite locales restent hors suivi Git et sont maintenant couvertes par
`.gitignore`.
