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

## ⚙️ Prérequis

* Un runner GitHub Actions **self-hosted** configuré avec accès réseau au FortiGate.


* Ansible et la collection `fortinet.fortios` installés sur le runner.


* Un **API User** sur le FortiGate (`config system api-user`) disposant des droits de lecture sur la configuration.


* L'adresse IP du runner autorisée dans les `trusthost` de l'API user FortiGate.



---

## 🔒 Configuration des Secrets & Inventaire

### 1. Secrets GitHub (*Settings → Secrets and variables → Actions*)



| Secret                 | Description                                              |
| ----------------------- | --------------------------------------------------------- |
| `FORTIOS_ACCESS_TOKEN` | Token API de l'utilisateur FortiGate                     |
| `ALERT_WEBHOOK_URL`    | (optionnel) URL webhook pour notification en cas d'échec |


### 2. Inventaire Ansible (`inventory.yml`)



Adaptez le paramètre `ansible_host` avec l'adresse IP de votre équipement FortiGate :

```yaml
all:
  hosts:
    fortigate_1:
      ansible_host: "192.168.239.130"
      ansible_network_os: fortinet.fortios.fortios
      ansible_connection: httpapi
      ansible_httpapi_use_ssl: true
      ansible_httpapi_validate_certs: false
      ansible_httpapi_port: 443
      vdom: "root"
      fortios_access_token: "{{ lookup('env', 'FORTIOS_ACCESS_TOKEN') }}"

```

---

## 📌 Format des Fichiers & Rétention

* **Format du nom de fichier :**
`<inventory_hostname>_<YYYY-MM-DD>_<HHMMSS>.conf`

*Exemple :* `fortigate_1_2026-08-14_020000.conf`

* **Rétention automatique :**
Les fichiers dont la date de modification dépasse **90 jours** sont automatiquement purgés à la fin de chaque exécution du playbook.


* **Permissions locales :**
Le répertoire de sauvegarde locale est restreint (`mode: '0700'`) et les fichiers de configuration sont protégés (`mode: '0600'`).



---

## 🛠️ Utilisation

### Lancement manuel via GitHub CLI



```bash
gh workflow run "FortiGate Local Backup Runner"
gh run watch

```

### Exécution locale directe (hors CI/CD)



```bash
export FORTIOS_ACCESS_TOKEN="votre_token_api"
ansible-playbook -i inventory.yml backup_and_clean.yml

```

---

## 🛡️ Sécurité

* Les jetons API sont chargés à partir de variables d'environnement (`FORTIOS_ACCESS_TOKEN`) ou secrets GitHub.


* Les tâches manipulant des identifiants sensibles et le contenu du backup exécutent la directive `no_log: true` afin de prévenir les fuites de données confidentielles dans les logs GitHub Actions.



```

```