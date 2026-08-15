# FortiGate Multi-Site Backup Automation

Pipeline d'automatisation pour la sauvegarde quotidienne de la configuration de plusieurs pare-feux FortiGate via l'API REST FortiOS, avec stockage local structuré, rétention automatique et rapport d'exécution.

## Fonctionnement

1. **GitHub Actions** déclenche le pipeline chaque jour à 02h00 UTC (ou manuellement via `workflow_dispatch`).
2. Un **runner self-hosted** (VM Ubuntu locale) exécute un **playbook Ansible** qui, pour **chaque FortiGate de l'inventaire** :
   - récupère sa configuration complète via l'API REST (`POST /api/v2/monitor/system/config/backup`),
   - écrit un fichier `.conf` horodaté dans un **sous-dossier dédié à l'équipement**, en local, hors dépôt Git,
   - continue l'exécution même si un équipement échoue (`ignore_errors: true`), pour ne pas bloquer la sauvegarde des autres sites.
3. Une **rétention de 90 jours** est appliquée globalement (tous équipements confondus) : les fichiers plus anciens sont supprimés à chaque run.
4. Un **rapport d'exécution** récapitulatif (succès/échec par équipement) est généré et enregistré en local à chaque run.
5. En cas d'échec du job, une **notification webhook** est envoyée avec un lien direct vers le run GitHub Actions.

⚠️ **Aucune donnée de configuration n'est stockée ou versionnée dans le dépôt GitHub.** Seul le code d'automatisation (playbook, inventaire, workflow) y est présent. Les sauvegardes et rapports restent exclusivement sur la machine du runner.

## Équipements couverts

| Site | Hostname (inventaire) |
|---|---|
| Kenitra | `fortigate_kenitra_01` |
| Rabat | `fortigate_rabat_01` |
| Datacenter | `fortigate_datacenter_01` |

## Structure du projet

```
.
├── .github/
│   └── workflows/
│       └── fortigate_backup.yml   # Pipeline GitHub Actions
├── backup_and_clean.yml           # Playbook Ansible (backup multi-sites + rétention + rapport)
├── inventory.yml                  # Inventaire Ansible (3 FortiGate)

# Hors dépôt (non versionné, local au runner)
~/fortigate_local_backups/
├── fortigate_kenitra_01/
│   └── fortigate_kenitra_01_2026-08-15_020000.conf
├── fortigate_rabat_01/
│   └── fortigate_rabat_01_2026-08-15_020000.conf
└── fortigate_datacenter_01/
    └── fortigate_datacenter_01_2026-08-15_020000.conf

~/fortigate_reports/
└── rapport_sauvegarde_2026-08-15_020000.txt
```

## Prérequis

- Un runner GitHub Actions **self-hosted** avec accès réseau aux trois FortiGate.
- Ansible installé sur le runner (`ansible-galaxy` disponible dans `$PATH`).
- La collection **`fortinet.fortios`** (installée automatiquement par le pipeline à chaque run).
- Un **utilisateur API** créé sur chaque FortiGate (`config system api-user`) avec un token valide.
- Chaque pare-feu doit autoriser l'IP du runner dans le `trusthost` de son utilisateur API.

## Configuration

### Secrets GitHub (Settings → Secrets and variables → Actions)

| Secret | Description |
|---|---|
| `FORTIOS_TOKENS_JSON` | Objet JSON contenant un token API par site (voir format ci-dessous) |
| `ALERT_WEBHOOK_URL` | (optionnel) URL webhook pour notification en cas d'échec du job |

**Format de `FORTIOS_TOKENS_JSON`** :

```json
{
  "FORTIOS_TOKEN_SITE_KEN": "token_api_kenitra",
  "FORTIOS_TOKEN_SITE_RBT": "token_api_rabat",
  "FORTIOS_TOKEN_DC": "token_api_datacenter"
}
```

Chaque hôte de l'inventaire référence sa clé correspondante via un lookup Jinja :

```yaml
fortios_access_token: "{{ (lookup('env', 'FORTIOS_TOKENS_JSON') | from_json)['FORTIOS_TOKEN_SITE_KEN'] }}"
```

Ce format centralise tous les tokens dans un seul secret plutôt qu'un secret par équipement, ce qui simplifie l'ajout d'un nouveau site à l'inventaire (une seule variable GitHub à mettre à jour).

### Inventaire (`inventory.yml`)

Groupe `fortigates`, un hôte par site. Ajouter un nouvel équipement = ajouter une entrée `hosts` + sa clé de token dans `FORTIOS_TOKENS_JSON`.

## Utilisation

**Déclenchement manuel :**

```bash
gh workflow run "FortiGate Multi-Device Backup Runner"
gh run watch
```

**Test local du playbook (hors CI) :**

```bash
export FORTIOS_TOKENS_JSON='{"FORTIOS_TOKEN_SITE_KEN":"...","FORTIOS_TOKEN_SITE_RBT":"...","FORTIOS_TOKEN_DC":"..."}'
ansible-playbook -i inventory.yml backup_and_clean.yml
```

## Sécurité

- Le token API n'est jamais passé en argument `-e` sur la ligne de commande (évite l'exposition via `ps aux` / logs de process).
- Les tâches manipulant un token ou le contenu d'une configuration utilisent `no_log: true` pour éviter toute fuite dans les logs GitHub Actions.
- **Aucune configuration FortiGate n'est écrite dans le dépôt Git** — élimine le risque de fuite de données sensibles (certificats, clés, structure réseau interne) via l'historique Git, même en cas de compromission future du repo.
- Les fichiers de sauvegarde locaux sont créés avec des permissions restreintes (`0700` dossier, `0600` fichiers), accessibles uniquement à l'utilisateur du runner.
- L'échec d'un équipement (`ignore_errors: true`) n'expose pas de détails du token ou de la config dans les logs — seul le statut ✅/❌ apparaît dans le rapport.

## Format des fichiers de sauvegarde

Un fichier horodaté par équipement et par exécution, dans son sous-dossier dédié :

```
<inventory_hostname>_<YYYY-MM-DD>_<HHMMSS>.conf
```

Exemple : `fortigate_kenitra_01_2026-08-15_020000.conf`

## Rétention

Une rétention de **90 jours** (`retention_days` dans `backup_and_clean.yml`) est appliquée à l'ensemble de `~/fortigate_local_backups/` (recherche récursive dans tous les sous-dossiers d'équipement) : tout fichier `.conf` plus ancien est supprimé automatiquement à chaque exécution. Le nombre de fichiers supprimés est affiché dans les logs du run.

## Rapport d'exécution

À chaque run, un rapport texte récapitulatif est généré dans `~/fortigate_reports/`, listant le statut (✅ Réussi / ❌ Échoué) de chaque équipement :

```
==================================================
         RAPPORT DE SAUVEGARDE FORTIGATE
         Date: 2026-08-15 02:00:00
==================================================
  fortigate_kenitra_01      : ✅ Réussi
  fortigate_rabat_01        : ✅ Réussi
  fortigate_datacenter_01   : ❌ Échoué
==================================================
```

Ce rapport reste local (non versionné) et permet un diagnostic rapide sans avoir à consulter les logs complets du run GitHub Actions.

## Roadmap / améliorations possibles

- [ ] Chiffrement GPG des sauvegardes locales
- [ ] Réplication de l'archive locale vers un stockage distant (S3 / Azure Blob) pour la résilience en cas de perte du runner
- [ ] Envoi du rapport d'exécution par email ou webhook (au-delà de la simple notification d'échec)
- [ ] Audit automatisé des policies (`analyze_policies.py`) intégré au pipeline
- [ ] Ajout de nouveaux sites via une entrée d'inventaire simple (déjà largement facilité par le format `FORTIOS_TOKENS_JSON`)
