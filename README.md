# FortiGate GitOps Backup

Pipeline d'automatisation pour la sauvegarde quotidienne de la configuration d'un pare-feu FortiGate via l'API REST FortiOS, avec versioning Git et rétention automatique.

## Fonctionnement

1. **GitHub Actions** déclenche le pipeline chaque jour à 02h00 UTC (ou manuellement via `workflow_dispatch`).
2. Un **runner self-hosted** (VM Ubuntu locale) exécute un **playbook Ansible** qui :
   - récupère la configuration complète du FortiGate via l'API REST (`POST /api/v2/monitor/system/config/backup`),
   - écrit le fichier `.conf` dans `backups/` (dépôt Git),
   - écrit une **copie locale identique** dans un dossier hors dépôt (`local_backup_dir`), non versionnée,
   - supprime les sauvegardes du dépôt de plus de 7 jours.
3. Le pipeline **commit et push** automatiquement les nouveaux fichiers de sauvegarde vers le dépôt GitHub.
4. En cas d'échec, une **notification webhook** est envoyée (optionnel).

## Structure du projet

```
.
├── .github/
│   └── workflows/
│       └── fortigate-backup.yml   # Pipeline GitHub Actions
├── backup_and_clean.yml           # Playbook Ansible (backup + rétention)
├── inventory.yml                  # Inventaire Ansible (hôte FortiGate)
└── backups/                       # Sauvegardes versionnées dans le dépôt (.conf)

# Hors dépôt (non versionné)
~/fortigate_local_backups/         # Copie locale complète des sauvegardes (archive)
```

## Prérequis

- Un runner GitHub Actions **self-hosted** avec accès réseau au FortiGate.
- Ansible installé sur le runner, avec `ansible-galaxy` disponible dans `$PATH`.
- Un **utilisateur API** créé sur le FortiGate (`config system api-user`) avec un token valide.
- Le pare-feu doit autoriser l'IP du runner dans le `trusthost` de l'utilisateur API.

## Configuration

### Secrets GitHub (Settings → Secrets and variables → Actions)

| Secret | Description |
|---|---|
| `FORTIOS_ACCESS_TOKEN` | Token API de l'utilisateur FortiGate |
| `ALERT_WEBHOOK_URL` | (optionnel) URL webhook pour notification en cas d'échec |

### Inventaire (`inventory.yml`)

Adapter `ansible_host` à l'adresse IP/hostname du FortiGate cible. Le VDOM par défaut est `root`.

## Utilisation

**Déclenchement manuel :**

```bash
gh workflow run "FortiGate GitOps Backup"
gh run watch
```

**Test local du playbook (hors CI) :**

```bash
export FORTIOS_ACCESS_TOKEN="votre_token"
ansible-playbook -i inventory.yml backup_and_clean.yml
```

## Sécurité

- Le token API n'est jamais passé en argument `-e` sur la ligne de commande (évite l'exposition via `ps aux` / logs de process).
- Les tâches manipulant le token ou le contenu de la configuration utilisent `no_log: true` pour éviter toute fuite dans les logs GitHub Actions.
- ⚠️ Les fichiers de sauvegarde sont actuellement stockés **en clair** dans `backups/` et dans la copie locale. Une configuration FortiGate peut contenir des informations sensibles (certificats, clés, structure réseau interne). **Ce dépôt doit rester privé.**
- La copie locale (`~/fortigate_local_backups/`) est créée avec des permissions restreintes (`0700` dossier, `0600` fichiers), accessibles uniquement à l'utilisateur du runner.

## Format des fichiers de sauvegarde

Chaque exécution génère un fichier nommé :

```
<inventory_hostname>_<YYYY-MM-DD>_<HHMMSS>.conf
```

Exemple : `fortigate_1_2026-08-11_143205.conf`

L'heure dans le nom évite qu'un déclenchement manuel (`workflow_dispatch`) le même jour que le run automatique n'écrase la sauvegarde existante.

## Rétention

Les sauvegardes du dépôt (`backups/`) de plus de **7 jours** (`retention_days` dans `backup_and_clean.yml`) sont automatiquement supprimées à chaque exécution. Pour conserver un historique plus long dans Git, augmenter cette valeur ou désactiver le nettoyage.

La copie locale (`~/fortigate_local_backups/`) n'a **aucune rétention** appliquée actuellement — elle grossit indéfiniment comme archive complète, indépendante de Git.

## Roadmap / améliorations possibles

- [ ] Chiffrement des sauvegardes avant commit
- [ ] Notification webhook en cas d'échec (déjà scaffoldé, à activer via secret)
- [ ] Audit automatisé des policies (`analyze_policies.py`) intégré au pipeline
- [ ] Approbation manuelle via AWX avant déploiement de changements
