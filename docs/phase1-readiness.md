# Bilan de phase 1 — Kwitli

État relevé le 15 octobre 2026. Ce document décrit le dépôt et les bases locales
au moment de la vérification; il ne constitue pas une validation de production.

## Résumé de validation

- Backend : `387 passed` sur PostgreSQL `kwitli_test` (port local `55433`).
- Mobile : TypeScript et tests automatisés ciblés passent.
- Aucune migration n'a été lancée pendant cette vérification.
- `kwitli_dev` et `kwitli_test` sont toutes deux à `f18c6a4d2b91` au relevé.
- Aucun parcours natif iOS/Android ni paiement sandbox réel n'a été exécuté ici;
  l'interface reste à revoir humainement sur les simulateurs.

Une exécution pytest précédente s'est chevauchée avec une autre invocation et a
produit des deadlocks dans le nettoyage de la même base de test. Ce résultat a
été écarté. La validation `387 passed` provient d'une seule exécution séquentielle
terminée avec code de sortie 0.

## Parcours et contrôles

### Checkout MVP sans disponibilité datée

Le checkout MVP accepte un article actif sans `availability_id`, conserve les
quantités de lignes fournies par le client, recalcule prix et total côté serveur,
et n'ajoute pas de `StockHold`/décrément de `DishAvailability` pour ce flux. Un
commerce non validé, fermé ou un article inactif est refusé côté serveur. Les
structures et données legacy de stock restent présentes; le chemin legacy n'est
pas supprimé par ce travail.

### Horaires

`CookProfileHour` stocke les sept jours par commerce. La décision ouvert/fermé
utilise le fuseau du marché configuré, puis le fallback de marché existant. Le
commerce validé demeure découvrable lorsqu'il est fermé, mais le checkout est
bloqué avec une erreur métier claire. Précommandes, jours fériés et horaires
spéciaux ne sont pas couverts.

### Validation et administration

`/admin` est une page HTML minimale protégée par HTTP Basic, vérification
`is_admin`, restriction réseau (loopback en HTTP ou HTTPS hors loopback),
limitation de débit et jeton CSRF signé à durée limitée pour les décisions POST.
Les actions approuver/refuser/suspendre/réactiver passent par le service métier;
approbation/refus exigent l'état et les conditions attendus. La découverte, la
fiche publique et le checkout vérifient `is_verified`; les actions d'approbation
maintiennent aussi `approval_status`.

La migration renseigne l'état initial depuis `is_verified`; aucun commerce n'a
été approuvé manuellement pendant cette vérification. `Restaurant Sénégal` est
actuellement `approved` et vérifié dans DEV, résultat du backfill de migration
déjà autorisée antérieurement. Au relevé, DEV comptait 1 commerce approuvé, 1 en
attente et 2 brouillons.

### Messagerie et alertes commerçant

Les endpoints `/api/v1/orders/{order_id}/messages` n'autorisent que le client de
la commande et le propriétaire du commerce. Les messages sont textuels, non
vides, limités à 230 caractères par validation API/service et ordonnés sur les
50 derniers. Le mobile impose aussi `maxLength=230`. La contrainte historique en
base autorise jusqu'à 1000 caractères; les écritures normales passent par
l'API stricte. Une migration de resserrement en base n'a pas été créée, afin de
ne pas invalider des messages historiques sans audit préalable.

Le scope Commerce actualise les commandes toutes les 15 secondes et au retour au
premier plan. Le premier chargement est silencieux; seuls les nouveaux IDs
actifs déclenchent l'indicateur/alerte, et l'ouverture de la liste marque les
arrivées comme vues. C'est une notification interne à l'application, pas une
notification push iOS/Android. Elle ne tourne pas lorsque le scope marchand est
démonté ou que l'application est en arrière-plan.

## Migrations Alembic

Ordre linéaire constaté dans `migrations/versions` :

| Révision | Objet |
| --- | --- |
| `8d76ca917ecc` | Schéma initial renforcé |
| `c912d44fd821` | Métadonnées de découverte |
| `d35c092b1a74` | Lignes d'articles d'un paiement legacy |
| `e42b0c61af90` | Devise COP/XOF |
| `f63a1b82c907` | Fondations `OrderItem` et preuve de retrait |
| `a74d2c93e018` | Commande unifiée multi-lignes |
| `b85e3d04f129` | Horodatages opérationnels de commande |
| `3f9a2b7c1d6e` | Verticale principale du commerce |
| `4c1a7f9e2b63` | Résolutions de commande et marqueur admin |
| `9a3e6d2f1c80` | Messages liés à une commande |
| `c2f4a8b19d30` | Checkout actif sans stock daté requis |
| `e7b4c12a9f60` | Horaires hebdomadaires du commerce |
| `f18c6a4d2b91` | Statuts de validation des restaurants |

La révision a été lue dans les deux bases locales via le socket `/tmp`, port
`55433` : `kwitli_dev=f18c6a4d2b91`, `kwitli_test=f18c6a4d2b91`. Aucune migration
ne reste à appliquer dans ces deux bases au relevé. Cela ne dit rien d'une base
de production.

La migration `f18c6a4d2b91` a reçu un chemin Alembic `batch_alter_table` réservé
à SQLite pour créer/supprimer les contraintes; la branche PostgreSQL reste le
même ensemble d'opérations qu'avant. Elle avait déjà été appliquée aux bases
locales : aucun changement de schéma n'a été exécuté en conséquence. Le modèle
ORM déclare également le défaut `pending_review` côté serveur pour que les
insertions sans ORM restent cohérentes.

## Comptes et scénarios de test

Ne pas stocker de mot de passe, hash, jeton ou secret dans la documentation.

| Scénario | Compte/environnement relevé | Usage |
| --- | --- | --- |
| Administrateur DEV | `Mkwitli509@gmail.com`, actif, `is_admin=true` | Page `/admin`; aucun secret n'est consigné ici |
| Commerce approuvé DEV | `Saxophone509@gmail.com`, propriétaire de Restaurant Sénégal | Parcours commerçant; le compte ne remplace pas un compte client distinct |
| Client | Fixtures backend `kwitli_test`, créées durant chaque test | Auth, découverte, commande, messages et permissions |
| Commerce en attente/refusé | Fixtures backend `kwitli_test` | Décisions admin et invisibilité publique |

Après le nettoyage des tests, `kwitli_test` contenait 0 utilisateur persistant;
les fixtures ne sont donc pas des comptes manuels réutilisables. Dans DEV, les
statuts de commerce relevés étaient 1 approuvé, 1 en attente et 2 brouillons;
aucun compte refusé n'est documenté comme fixture persistante DEV.

## Vérifications exécutées

- Suite backend complète, séquentielle sur `kwitli_test` : `387 passed`, une
  mise en garde de dépréciation Starlette/httpx.
- `npm run typecheck` : PASS.
- Tests mobiles : discovery, actions de commande, checkout/paiement UI, location,
  timezone, session, menu/expérience client, dashboard commerçant, workflow des
  commandes, URL API, picker image, navigateur de paiement et récupération : PASS.
- `git diff --check` et `git diff --cached --check` : PASS après les correctifs.

La commande générique `node src/payment-flow.test.ts` a d'abord échoué parce que
son import TypeScript sans extension n'est pas résolu par Node strip-types. Le
test importe maintenant `payment-flow.ts` explicitement et passe avec
`node --experimental-strip-types src/payment-flow.test.ts`.

## Limites / étapes encore nécessaires

- Revue humaine des parcours sur iOS et Android, dont approbation HTML et
  notification commerçant; aucun simulateur n'a été manipulé durant cet audit.
- Exécuter un parcours complet client/commerçant avec paiement sandbox sur builds
  natifs; Expo Go ne prouve pas les retours natifs de paiement.
- Définir les comptes de test manuels réutilisables et leur gestion sans
  enregistrer de secrets dans Git.
- Évaluer une contrainte DB `<=230` pour les nouveaux messages seulement après
  audit des valeurs historiques et approbation d'une migration additive.
- Confirmer séparément contrat, payout, remboursements, conformité et marché
  avant tout pilote réel. Aucun service push n'est installé.

Statut UI : **READY FOR HUMAN REVIEW**. Aucun commit ni push n'est inclus dans
ce relevé.
