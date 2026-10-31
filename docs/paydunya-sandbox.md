# Collecte PayDunya Sandbox

**Integration conservee mais en pause.** PayTech est le choix XOF par defaut.
Pour un test PayDunya explicite, configurer `XOF_PAYMENT_PROVIDER=paydunya` cote backend.
Voir [PayTech TEST](paytech-test.md) pour la priorite MVP actuelle.

Perimetre : XOF DEV/TEST uniquement, sans payout, remboursement, KYC ni production.
COP reste sur PayU. Les montants ne subissent aucune conversion de devise.

## Contrat et securite

- Le backend recalcule le panier mono-commerce/mono-devise, persiste Payment pending et les holds, puis cree une invoice.
- `provider_reference` reste la reference KWITLI. Le token de facture est conserve dans le champ unique existant `provider_transaction_id`, jamais expose au mobile.
- L'API Sandbox ne documente pas de devise dans l'invoice; elle traite les montants XOF. Toute devise contradictoire presente dans la confirmation est refusee.
- Le montant interne reste en centiemes : 450000 stocke signifie 4500 XOF envoyes au fournisseur.
- Seuls les endpoints sous `https://app.paydunya.com/sandbox-api/v1/` sont accessibles; pas de redirect ni proxy implicite.
- L'IPN est form-urlencoded. Le hash SHA-512 de la master key est compare en temps constant. Ce hash etant statique, le backend ne fait JAMAIS confiance au montant/statut du callback : il reinterroge l'API confirm.
- La reponse confirm doit correspondre au token persiste, a la reference KWITLI, au montant, et au mode test.
- `completed` devient `approved` dans le modele legacy KWITLI : c'est l'etat **paye**, pas une nouvelle valeur `paid`. `failed` devient `declined`; les etats inconnus ne valident rien.
- La confirmation reprend les verrous et transactions existants : commandes, stock et holds ne sont appliques qu'une fois. Le modele transitoire de commandes par ligne reste inchange.
- Le mobile ne confirme jamais le paiement. Son GET de statut interroge le fournisseur cote serveur; un retour navigateur n'est pas utilise.

## Configuration locale

Dans `backend/.env` uniquement, renseigner les valeurs de votre application PayDunya **test** :

```dotenv
PAYDUNYA_MODE=sandbox
PAYDUNYA_MASTER_KEY=
PAYDUNYA_PRIVATE_KEY=
PAYDUNYA_TOKEN=
PAYDUNYA_TEST_CUSTOMER_PHONE=
PAYDUNYA_TEST_CUSTOMER_EMAIL=
PAYDUNYA_TEST_CUSTOMER_PASSWORD=
```

La private key doit etre celle de test (`test_private_...`). Les trois dernieres variables
correspondent a un **compte fictif Sandbox cree dans PayDunya**, pas au compte KWITLI
ni a des identifiants de banque/operateur reels. Ne jamais les mettre dans une variable Expo.
`APP_ENV` doit rester `development` ou `test`. `PUBLIC_API_URL` doit etre votre URL
HTTPS publique active. Le callback est `/api/v1/payments/paydunya/confirmation`.
La presence de placeholders ne signifie pas que les credentials sont configures.

## Un test manuel

1. Verifier la base DEV cible et sa sauvegarde. La revision `e42b0c61af90` doit etre appliquee. Sur une base deja suivie par Alembic, utiliser `.venv/bin/alembic upgrade head` avec `ALEMBIC_DATABASE_URL` pointant explicitement vers cette base. Ne jamais lancer l'initialisation Alembic aveuglement sur une ancienne base non versionnee.
2. Relever les coordonnees utilisees dans Expo, puis charger les articles dedies :

```bash
.venv/bin/python scripts/seed_paydunya_xof.py --latitude <latitude> --longitude <longitude>
```

3. Redemarrer FastAPI apres configuration : `.venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000`. Garder le tunnel HTTPS habituel connecte. Expo doit utiliser ce meme backend.
4. Ouvrir la build Expo DEV, vider le panier COP si necessaire et ajouter un ou plusieurs articles XOF du Restaurant DEV Senegal.
5. Panier → Continuer → recapitulatif → Payer. Ce bouton cree l'invoice puis demande au backend d'effectuer **un paiement fictif** via SoftPay Sandbox. Aucun navigateur/WebView n'est ouvert et aucun credential n'est saisi dans l'app.
6. Attendre la verification serveur. Le callback ou le GET de statut valide la facture. L'etat paye est expose comme `status=approved` et les commandes existantes deviennent accessibles. Si necessaire, utiliser le bouton de verification du statut dans le recapitulatif.
7. Verifier que le panier paye est retire et que le stock n'a diminue qu'une fois. Un callback repete ne cree pas de nouvelles commandes.

## Erreurs et limites

Une erreur de creation d'invoice marque le Payment interne `error` et libere ses holds.
Si la reponse reseau s'est perdue apres creation distante, une facture orpheline peut exister :
ne pas la payer manuellement, la verifier dans le dashboard Sandbox avant un nouveau test.
Il n'y a pas de retry automatique de creation.

Avant SoftPay, le backend exige une reservation encore active. Il persiste ensuite
`softpay_requested` avant l'appel distant. Un timeout ne doit pas declencher une deuxieme
collecte : les appels suivants reconcilient le statut uniquement. Si une panne a eu lieu
entre ce marquage et l'appel, une intervention Sandbox peut etre necessaire. Aucun worker
de reconciliation durable n'est ajoute dans cette passe.

Un paiement confirme apres expiration du hold suit les regles legacy : pas de survente;
`error`/`failure_reason` peut necessiter une intervention manuelle. Ce n'est pas un remboursement.

Le compte fictif est commun au serveur DEV. L'endpoint test requiert le JWT du proprietaire,
est limite en frequence et est interdit hors DEV/TEST. La build mobile utilise ce chemin
seulement en `__DEV__`. Ce n'est pas une experience client production.

**L'UX finale sans redirection n'est pas validee** : les methodes reelles SoftPay/PSR,
leur activation par PayDunya et leurs interactions operateur devront etre choisies et
testees separement. La creation du compte fictif et des cles se fait hors app, dans PayDunya.
Pas de test reel annonce sans credentials et execution manuelle reussie.

## Sources officielles consultees

- [Sandbox SoftPay](https://developers.paydunya.com/doc/EN/sandbox_softpay) : create invoice, `phone_phone`, compte fictif et make-payment.
- [HTTP/JSON](https://developers.paydunya.com/doc/EN/http_json) : confirm, custom_data, IPN et hash SHA-512.
