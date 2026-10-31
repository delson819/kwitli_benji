# Lien Expo d'origine (équipe Kwitli)

Le projet a été détaché de l'équipe Expo `kwitlis-team` le 2026-10-31 pour
pouvoir construire l'APK avec un compte Expo personnel.

Pour revenir au projet de l'équipe, remettre dans `app.json`, sous `"expo"` :

```json
"extra": {
  "eas": {
    "projectId": "244885da-8a63-43dc-92e9-7736be8c94d8"
  }
},
"owner": "kwitlis-team"
```

Et retirer le `projectId` / `owner` créés par `eas init` pour le compte personnel.
