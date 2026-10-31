# Collecte PayTech TEST

**Priorite actuelle : XOF → PayTech, COP → PayU.** PayDunya est conserve,
selectionnable explicitement avec `XOF_PAYMENT_PROVIDER=paydunya`; les paiements
deja crees gardent leur fournisseur. Aucune conversion de devise ou migration DB.

## Contrat officiel

[Documentation officielle](https://doc.paytech.sn/doc_paytech.php) consultee pour
la base `https://paytech.sn/api`, les headers `API_KEY`/`API_SECRET`,
`POST /payment/request-payment`, `env=test`, `target_payment` et l'IPN HMAC-SHA256.
Les methodes demandees sont uniquement `Wave, Orange Money`.

**Attention : PayTech annonce un debit reel entre 100 et 150 FCFA en mode test.**
Ne pas assimiler ce test au compte client fictif PayDunya. Ne pas ouvrir ce flow au public.
Le checkout est externe temporairement; aucune WebView ni donnee bancaire collectee par KWITLI.

## Procedure manuelle

1. Creer son compte PayTech, puis recuperer les cles dans le dashboard, Parametres → API.
2. Renseigner uniquement `backend/.env` local :

```dotenv
XOF_PAYMENT_PROVIDER=paytech
PAYTECH_ENV=test
PAYTECH_API_KEY=
PAYTECH_API_SECRET=
```

3. Garder `APP_ENV=development`, un `PUBLIC_API_URL` HTTPS actif, et le tunnel habituel connecte.
   `env=prod` est refuse par la configuration et le provider. Aucune activation production necessaire ici.
4. Verifier la base DEV active et sa revision COP/XOF `e42b0c61af90`. Ne pas initialiser Alembic aveuglement sur une ancienne base non versionnee. Le seed existant est reutilise, malgre son nom historique :

```bash
.venv/bin/python scripts/seed_paydunya_xof.py --latitude <latitude_simulateur> --longitude <longitude_simulateur>
.venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

5. Dans un autre terminal : `cd mobile` puis `npx expo start`. Expo doit utiliser le meme backend et donc la meme base DEV.
6. Vider le panier COP si necessaire. Ajouter un ou plusieurs plats XOF du Restaurant DEV Senegal. Ouvrir le panier, puis Continuer et Payer.
7. Accepter consciemment l'avertissement de debit reel possible. La selection Wave/Orange Money se fait **sur le checkout PayTech**, apres son ouverture, pas dans un nouvel ecran KWITLI.
8. Verifier le montant affiche et completer manuellement le test. Aucun paiement n'est declenche automatiquement par les scripts/tests KWITLI.
9. PayTech appelle `POST /api/v1/payments/paytech/confirmation` en HTTPS. Revenir dans KWITLI et utiliser la verification de statut si necessaire.
10. Verifier `provider=paytech`, `currency=XOF`, `status=approved` (equivalent legacy de paye), les commandes et le stock. Les confirmations repetees doivent laisser les memes commandes et quantites.

## Garanties KWITLI

Le total provient exclusivement des disponibilites chargees en DB. Le panier reste
mono-commerce et mono-devise. Payment pending et les holds sont persistes avant
l'appel fournisseur. La reference interne reste dans `provider_reference`, le token
PayTech dans le champ unique existant `provider_transaction_id`.

Le mobile recoit uniquement l'URL checkout HTTPS validee et les champs publics habituels.
Les cles ne quittent pas le backend. Pas de journalisation du token, des payloads IPN
ou des reponses fournisseur. Le transport refuse redirects et proxies implicites.

L'IPN JSON ou form-urlencoded doit porter un HMAC valide, la reference et le token
exacts, le montant commande, XOF et env=test. Aucun fallback aux simples hashes
statiques des cles. Les montants promotionnels divergents sont rejetes : pas de remise
ou conversion silencieuse. Un montant IPN reduit a 100–150 au lieu du total commande
est egalement rejete; verifier ce comportement avec PayTech lors du premier test.

La transaction d'approbation existante traite stock, holds et commandes. Une notification
repetee ou concurrente ne double pas les effets. Une annulation tardive ne degrade pas
un paiement approuve. Le retour navigateur ne modifie aucun statut.

## Limites connues

- `GET /payment/get-status?token_payment=...` est documente, mais son schema de reponse n'est pas publie et la collection Postman officielle ne fournit aucun exemple. Le provider expose le transport, sans mapping invente. **La reconciliation automatique via cette API n'est pas activee** : le GET KWITLI lit le statut persiste par IPN.
- Le HMAC documente signe montant/reference/cle, pas tous les champs de l'IPN. Garder le canal HTTPS et les notifications strictement confidentiels. Une verification independante du statut reste souhaitable des que PayTech confirme son contrat de reponse.
- Sans IPN valide, le paiement reste non approuve. Une erreur de creation ou un timeout libere les holds locaux, mais peut laisser une demande distante orpheline. Ne pas la payer manuellement; verifier le dashboard avant une nouvelle tentative.
- Apres expiration du hold, une approbation distante peut mener a une erreur operationnelle legacy : pas de survente, mais intervention manuelle requise. Pas de remboursement automatique.
- `sale_complete` correspond a `approved`, `sale_canceled` a `cancelled`. Les evenements inconnus et de remboursement sont refuses sur ce endpoint de collecte; aucun payout/refund n'est implemente.
- Le compte PayTech et ses cles doivent etre configures manuellement. Les tests automatises utilisent des mocks, jamais un compte operateur reel.
- L'UX finale sans redirection reste non validee. Cette documentation de checkout standard ne suffit pas a garantir un flow natif : faire confirmer l'offre/API directe appropriee (eventuellement Intech cash-in) par PayTech. Aucun Intech cash-out n'est ajoute.

Sources : [documentation PayTech](https://doc.paytech.sn/doc_paytech.php),
[collection officielle liee](https://doc.intech.sn/PayTech%20x%20DOC.postman_collection.json).
