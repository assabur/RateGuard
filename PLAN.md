# Plan de livraison

## Phase 1 — MVP US

- [x] Package Python, CLI et configuration par environnement.
- [x] Ingestion du flux XML Treasury et des séries FRED DGS2/5/10/30.
- [x] Archivage des réponses, SHA-256, horodatage UTC et provenance des observations.
- [x] Normalisation sur date, fournisseur, maturité et taux en pourcentage.
- [x] Contrôles : valeurs absentes/invalides, doublons, bornes, ancienneté, variations.
- [x] Réconciliation à date identique, seuils en bps, pistes d’investigation.
- [x] Détection des changements de valeur entre deux runs pour la même date.
- [x] Courbes US à quatre points, spreads et classification 10Y-2Y.
- [x] Parquet et PostgreSQL obligatoire via SQLAlchemy.
- [x] API FastAPI, documentation OpenAPI, historique des exécutions.
- [x] Démonstration sans clé API, tests métier et CI.

## Phase 1.1 — Exploitation

- [ ] Valider les collectes réelles avec une clé FRED et tester les SLA de publication.
- [ ] Valider le déploiement PostgreSQL/Docker sur l’environnement cible.
- [ ] Ajouter un calendrier des jours de publication H.15/Treasury et des SLA horaires.
- [ ] Calibrer les seuils avec un Quant Researcher ; enrichir les règles de conventions.
- [ ] Ajouter des migrations SQL avant évolution du schéma en environnement partagé.
- [x] Conserver les versions exactes de l’environnement local dans `requirements.lock`.
- [ ] Valider le verrou sur les autres plateformes cibles.
- [ ] Ajouter métriques, rétention des fichiers et gestion des collectes concurrentes.

## Phase 2 — Orchestration et observabilité

- [ ] DAG Airflow : collecte → qualité → réconciliation → publication, avec retries et backfills.
- [ ] Métriques Prometheus et dashboard Grafana : fraîcheur, disponibilité, écarts et anomalies.
- [ ] Alertes avec acquittement et statut de résolution ; investigation documentée des révisions.

## Phase 3 — EUR

- [ ] Sélectionner un dataset ECB de courbes de taux compatible avec le cas métier EUR.
- [ ] Documenter identifiants, unités, calendriers, conventions et licences.
- [ ] Étendre le modèle à la devise, au type de courbe et à la provenance de la source.
- [ ] Ajouter les connecteurs et tests de comparabilité avant toute réconciliation EUR.
