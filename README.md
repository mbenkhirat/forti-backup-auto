# FortiGate GitOps Backup

Pipeline d'automatisation pour la sauvegarde quotidienne de la configuration d'un pare-feu FortiGate via l'API REST FortiOS, avec versioning Git.

## Fonctionnement

1. **GitHub Actions** déclenche le pipeline chaque jour à 02h00 UTC (ou manuellement via `workflow_dispatch`).
2. Un **runner self-hosted** (VM Ubuntu locale) exécute un **playbook Ansible** qui :
   - récupère la configuration complète du FortiGate via l'API REST (`POST /api/v2/monitor/system/config/backup`),
   - écrit/écrase le fichier `.conf` dans `backups/` (dépôt Git) — **une seule version, toujours à jour**,
   - écrit une **copie horodatée** dans un dossier hors dépôt (`local_backup_dir`), non versionnée — **historique complet, jamais purgé**.
3. Le pipeline **commit et push** automatiquement la sauvegarde mise à jour vers le dépôt GitHub.
4. En cas d'échec, une **notification webhook** est envoyée (optionnel).

## Structure du projet

```
.
├── .github/
│   └── workflows/
│       └── fortigate-backup.yml   # Pipeline GitHub Actions
├── backup_and_clean.yml           # Playbook Ansible (backup repo + backup local)
├── inventory.yml                  # Inventaire Ansible (hôte FortiGate)
└── backups/                       # Sauvegarde versionnée dans le dépôt (1 seul fichier .conf, écrasé à chaque run)

# Hors dépôt (non versionné)
~/fortigate_local_backups/         # Archive locale complète (un fichier horodaté par exécution)
```

## Prérequis

- Un runner GitHub Actions **self-hosted** avec accès réseau au FortiGate.
- Ansible installé sur le runner, avec `ansible-galaxy` disponible dans `$PATH`.
- Un **utilisateur API** créé sur le FortiGate (`config system api-user`) avec un token valide.
- Le pare-feu doit autoriser l'IP du runner dans le `trusthost` de l'utilisateur API.

## Configuration

### Secrets GitHub (Settings → Secrets and variables → Actions)

| Secret                 | Description                                              |
| ----------------------- | --------------------------------------------------------- |
| `FORTIOS_ACCESS_TOKEN` | Token API de l'utilisateur FortiGate                     |
| `ALERT_WEBHOOK_URL`    | (optionnel) URL webhook pour notification en cas d'échec |

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

**Côté dépôt (`backups/`)** — un seul fichier, réécrit à chaque exécution :

```
<inventory_hostname>_latest.conf
```

Exemple : `fortigate_1_latest.conf`

Ce choix garde un historique Git propre (un diff par run) plutôt que d'accumuler des fichiers datés dans le dépôt.

**Côté local (`~/fortigate_local_backups/`)** — un fichier horodaté par exécution, jamais écrasé :

```
<inventory_hostname>_<YYYY-MM-DD>_<HHMMSS>.conf
```

Exemple : `fortigate_1_2026-08-14_020000.conf`

## Rétention

- **Dépôt (`backups/`)** : aucune rétention nécessaire — un seul fichier est maintenu, écrasé à chaque run. L'historique des versions reste néanmoins consultable via `git log -p backups/`.
- **Local (`~/fortigate_local_backups/`)** : aucune purge appliquée — l'archive grossit indéfiniment et sert d'historique complet indépendant de Git.

## Roadmap / améliorations possibles

- [ ] Chiffrement des sauvegardes avant commit (GPG)
- [ ] Notification webhook en cas d'échec (déjà scaffoldé, à activer via secret)
- [ ] Audit automatisé des policies (`analyze_policies.py`) intégré au pipeline
- [ ] Approbation manuelle via AWX avant déploiement de changements
- [ ] Installation du runner en tant que service systemd persistant