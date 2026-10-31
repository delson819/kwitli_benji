# Flutterwave TEST : Senegal / XOF

Integration v3 uniquement. Aucun cash-out, payout, remboursement ou changement
Business/Menu/OrderItem. PayU COP, PayDunya et PayTech restent conserves.

## Contrats officiels

- [Francophone Mobile Money](https://developer.flutterwave.com/docs/francophone)
- [Charge v3](https://developer.flutterwave.com/reference/charge-via-francophone-mobile-money)
- [Verification serveur](https://developer.flutterwave.com/docs/transaction-verification)
- [Verification par reference](https://developer.flutterwave.com/reference/verify-transaction-with-tx_ref)
- [Webhooks v3](https://developer.flutterwave.com/docs/webhooks)
- [Donnees de test](https://developer.flutterwave.com/docs/testing)

Le backend appelle `POST https://api.flutterwave.com/v3/charges?type=mobile_money_franco`
avec `country=SN`, `currency=XOF`, le reseau choisi et `use_qr=false`.
L'autorisation peut etre externe : `meta.authorization.redirect_url` devient
`next_action={type: external, url: ...}`. Le mode callback devient `type: wait`.
L'app utilise un navigateur systeme, jamais une WebView. L'ancien flow push Orange Senegal
n'est pas retenu. Aucun retour mobile n'approuve un paiement.

## Retour navigateur vers Kwitli

- Le mobile transmet `ExpoLinking.createURL("payment-return")`. Le backend ajoute
  `payment_id` et transmet cette URL comme `redirect_url` a Flutterwave.
- En build native (y compris development build), le scheme declare est `kwitli` :
  `kwitli://payment-return?payment_id=<id>`. `expo-web-browser` ouvre une session
  `openAuthSessionAsync`, fermee lorsque le fournisseur emet ce retour.
  Sur iOS, le systeme peut demander une autorisation avant ouverture.
- Le resultat de la session rejoint le meme handler que les deep links ; la
  correlation et la verification serveur existantes restent seules autoritaires.
  Annuler/fermer le navigateur ne signifie jamais que le paiement a echoue.
- Expo Go utilise `exp://<hote>:<port>/--/payment-return`, pas le scheme propre
  de l'app. L'ouverture externe est conservee dans cet environnement ; le retour
  et la fermeture automatiques ne sont pas garantis. Valider ce parcours dans
  un build natif reconstruit avec `expo-web-browser`, pas seulement dans Expo Go.
- La session navigateur ne peut pas inventer une redirection que Flutterwave
  n'emet pas. Si la page fournisseur reste sur "Thanks for your payment!", relever
  l'URL finale et verifier l'emission du retour ; ne pas relancer un paiement.
  Une page de succes fournisseur n'est jamais une preuve de confirmation Kwitli.

Sources officielles : [Expo WebBrowser SDK 54](https://docs.expo.dev/versions/v54.0.0/sdk/webbrowser/)
et [liens Expo vers une app](https://docs.expo.dev/linking/into-other-apps/).

## Configuration locale

Dans `backend/.env` ignore par Git, conserver les secrets existants et configurer :

```dotenv
XOF_PAYMENT_PROVIDER=flutterwave
FLUTTERWAVE_ENV=test
FLUTTERWAVE_SECRET_KEY=
FLUTTERWAVE_WEBHOOK_SECRET=
```

Renseigner la cle secrete TEST v3 depuis le dashboard, sans la copier dans des logs.
La cle publique n'est pas necessaire pour ces appels serveur directs ; si elle
existe deja localement, elle reste inchangee et n'est pas transmise au mobile.
L'adaptateur refuse les cles sans prefixe TEST et les environnements production.
Le montant XOF est entier, minimum 100 XOF. La convention interne historique
`amount_in_cents` est divisee par 100 a l'envoi, sans conversion monetaire.

## Test manuel : Wave d'abord

1. Dans le dashboard Flutterwave en TEST, configurer le webhook :
   `https://api-dev.kwitli.app/api/v1/payments/flutterwave/webhook`.
   Activer les notifications et leurs retries. Le Secret hash doit correspondre
   exactement a `FLUTTERWAVE_WEBHOOK_SECRET` local, sans publier sa valeur.
2. Garder le tunnel HTTPS connecte. Redemarrer le backend :
   `.venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000`.
3. Utiliser la base DEV active deja compatible XOF ; ne pas appliquer de migration
   aveuglement a une base ancienne. Charger autour de la position du simulateur :
   `.venv/bin/python scripts/seed_paydunya_xof.py --latitude <latitude> --longitude <longitude>`.
   Le nom historique du script n'impose pas PayDunya.
4. Dans `mobile`, lancer `npx expo start`. Verifier que l'app utilise ce backend.
5. Creer un panier XOF, continuer vers le recapitulatif, choisir Wave, saisir un
   numero fictif de test avec indicatif (par exemple `221770000000`), puis Payer.
   La documentation permet n'importe quel numero pour simuler Wave en test.
6. Completer uniquement l'autorisation demandee par Flutterwave. Si aucune action
   externe n'est renvoyee, attendre la simulation et utiliser Verifier le paiement.
7. Verifier HTTP 200 sur le webhook et le statut serveur `approved` : commandes
   legacy par ligne, holds consommes et stock decremente une seule fois. Un
   nouvel appel de verification ne doit produire aucun effet supplementaire.
8. Seulement apres reussite Wave, faire une nouvelle tentative Orange Money.
   Si le fournisseur demande un OTP dans son interface test, la documentation
   indique `123456` pour les simulations Mobile Money. Ne pas saisir de PIN reel.

## Confirmation et erreurs

Le header `verif-hash` est compare en temps constant. Il ne suffit pas a confirmer :
le backend consulte `/v3/transactions/{id}/verify` puis compare reference exacte,
identifiant, montant exact, devise et statut. Sans identifiant connu, le polling
utilise `/v3/transactions/verify_by_reference?tx_ref=...`.
Un webhook anterieur a la reponse de creation retrouve le Payment par `tx_ref`.
La finalisation reutilise les verrous et transactions existants ; aucun statut
final n'est ecrase par la reponse de creation retardee.

Timeout, reponse invalide ou creation incertaine : Payment reste pending, pas de
nouvelle collecte automatique, pas de fallback. Les holds expirent selon les
regles existantes. Une verification indisponible ne signifie pas paiement refuse.
Un echec financier verifie libere les holds ; le panier reste disponible.

## Limites avant validation humaine

- Les tests automatises mockent tous les appels Flutterwave. Ils ne prouvent ni
  l'habilitation du compte ni une transaction reelle dans son environnement TEST.
- Aucun job de reconciliation permanent : webhook, polling mobile borne et
  verification manuelle. Si la reponse HTTP vers le mobile est perdue ou l'app
  redemarree, retrouver le paiement pending avant de lancer une nouvelle tentative.
- Une autorisation externe perdue au redemarrage n'est pas stockee en DB ; ne pas
  refaire une collecte pour la regenerer sans verifier l'ancienne transaction.
- Un succes apres expiration du hold suit l'anomalie existante, sans survente ni
  remboursement automatique. La reconciliation operationnelle reste a definir.
- Les URLs externes doivent appartenir aux domaines HTTPS Flutterwave / Wave /
  Orange Money autorises. Un nouveau domaine requiert verification avant ajout.
- Aucun changement du schema, aucune promesse de production ni d'UX sans sortie
  d'application. Les donnees COP ne sont jamais converties en XOF.
- Alternatives manuelles : `XOF_PAYMENT_PROVIDER=paytech` ou `paydunya`, seulement
  pour de nouvelles tentatives dont les paiements precedents sont reconcilies.
