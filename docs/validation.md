# Validation du MVP

Vérification locale sur macOS ARM64 et Python 3.13.7.

- Tests métier et parseurs : `pytest -q`. Les tests de stockage, pipeline et API utilisent PostgreSQL avec des schémas temporaires via `RATE_GUARD_TEST_DATABASE_URL`.
- Style et format : `ruff check .` et `ruff format --check .`.
- Démonstration complète : `rateguard demo` ; taux synthétiques, écart 10Y de 2 bps et statut OK.
- Vérification réseau Treasury : téléchargement GET du flux annuel 2025, puis exécution du parseur réel. Résultat : 996 observations (249 dates × 4 maturités), du 2 janvier au 31 décembre 2025.
- À titre de vérification du parseur, le Treasury réel donne 4,67 % pour le 10Y au 8 janvier 2025. Les taux 5,15 % / 5,13 % de la démo sont inventés pour illustrer les seuils.

Le flux utilisé : [Treasury XML 2025](https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value=2025).

La collecte FRED réelle demande une clé personnelle et n’a pas été exécutée. Ses réponses JSON, erreurs HTTP et champs de provenance sont couverts par les tests simulés. PostgreSQL et le lancement Docker sont configurés, mais n’ont pas été exécutés lors de cette validation. Python 3.11 est configuré dans la CI, mais la vérification locale porte sur Python 3.13.

`requirements.lock` contient les versions exactes des dépendances de l’environnement de validation (hors package local). Pour reproduire cet environnement avec Python 3.13 :

```bash
pip install -r requirements.lock
pip install --no-deps -e .
```

Les installations génériques utilisent les plages de compatibilité de `pyproject.toml`. Le verrou devra être régénéré et validé lors des mises à jour de dépendances et sur les autres plateformes cibles.


## Passage à PostgreSQL (14 novembre 2026)

- PostgreSQL est obligatoire ; le repli implicite vers SQLite est supprimé.
- `.env` local configuré avec une URL PostgreSQL et un mot de passe généré, sans modifier la clé FRED.
- L’ancien fichier SQLite et la commande de reprise ont été supprimés à la demande de l’utilisateur.
- Vérification locale : 41 tests réussis et 9 tests d’intégration ignorés en l’absence d’instance PostgreSQL accessible ; Ruff et la validation de configuration Compose réussissent.
- Le bac à sable interdit l’accès au socket Docker de cette machine. Démarrage de PostgreSQL et validation d’intégration à effectuer dans un environnement ayant accès à Docker. La CI est configurée pour ces tests, sans exécution de CI depuis cette session.
