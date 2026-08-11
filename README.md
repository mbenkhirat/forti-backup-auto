# FortiGate GitOps Backup

Pipeline d'automatisation pour la sauvegarde quotidienne de la configuration d'un pare-feu FortiGate via l'API REST FortiOS, avec versioning Git et rétention automatique.

## Fonctionnement

1. **GitHub Actions** déclenche le pipeline chaque jour à 02h00 UTC (ou manuellement via `workflow_dispatch`).
2. Un **runner self-hosted** (VM Ubuntu locale) exécute un **playbook Ansible** qui :
   - récupère la configuration complète du FortiGate via l'API REST (`POST /api/v2/monitor/system/config/backup`),
   - écrit le fichier `.conf` dans `backups/`,
   - supprime les sauvegardes de plus de 7 jours.
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
└── backups/                       # Sauvegardes générées (.conf)
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
- ⚠️ Les fichiers de sauvegarde sont actuellement stockés **en clair** dans `backups/`. Une configuration FortiGate peut contenir des informations sensibles (certificats, clés, structure réseau interne). **Ce dépôt doit rester privé.**

## Rétention

Les sauvegardes de plus de **7 jours** (`retention_days` dans `backup_and_clean.yml`) sont automatiquement supprimées à chaque exécution. Pour conserver un historique plus long dans Git, augmenter cette valeur ou désactiver le nettoyage.

## Roadmap / améliorations possibles

- [ ] Chiffrement des sauvegardes avant commit
- [ ] Notification webhook en cas d'échec (déjà scaffoldé, à activer via secret)
- [ ] Audit automatisé des policies (`analyze_policies.py`) intégré au pipeline
- [ ] Approbation manuelle via AWX avant déploiement de changements
