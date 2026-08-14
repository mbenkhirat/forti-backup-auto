# FortiGate Local Backup & Retention Runner

Pipeline d'automatisation pour la sauvegarde quotidienne de la configuration d'un pare-feu FortiGate via l'API REST FortiOS. Les sauvegardes sont stockées exclusivement en local sur le runner avec une politique de rétention automatique de **90 jours (3 mois)**[cite: 7, 8].

---

## 🚀 Fonctionnement

1. **GitHub Actions** déclenche le workflow chaque jour à 02h00 UTC (ou manuellement via `workflow_dispatch`)[cite: 8].
2. Un **runner self-hosted** (VM locale) exécute le playbook Ansible (`backup_and_clean.yml`) qui[cite: 7, 8] :
   - Récupère la configuration complète du FortiGate via l'API REST (`POST /api/v2/monitor/system/config/backup`).
   - Génère un fichier `.conf` horodaté dans un dossier local sécurisé sur le runner (`/home/mbenkhirat/ansible-projects/fortigate_local_backups/`).
   - Scanne le dossier local et **supprime automatiquement les fichiers de sauvegarde datant de plus de 90 jours**.
3. **Sécurité Git** : Aucune sauvegarde de configuration n'est stockée, commitée ou poussée sur GitHub[cite: 8].

---

## 📁 Structure du Projet

```text
.
├── .github/
│   └── workflows/
│       └── fortigate_backup.yml   # Workflow GitHub Actions (runner local)
├── backup_and_clean.yml           # Playbook Ansible (sauvegarde + purge 90j)
├── inventory.yml                  # Inventaire Ansible (FortiGate ciblé)
└── README.md                      # Documentation du projet

# Dossier hébergé en local sur le runner (hors Git)
/home/mbenkhirat/ansible-projects/fortigate_local_backups/   # Archives .conf horodatées (rétention 90j)
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