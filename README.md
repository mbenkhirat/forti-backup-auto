# FortiGate Multi-Site Backup Automation

Automation pipeline for the daily backup of multiple FortiGate firewall configurations via the FortiOS REST API, with structured local storage, automatic retention, and an execution report.

## How it works

1. **GitHub Actions** triggers the pipeline every day at 02:00 UTC (or manually via `workflow_dispatch`).
2. A **self-hosted runner** (local Ubuntu VM) executes an **Ansible playbook** that, for **each FortiGate in the inventory**:
   - retrieves its full configuration via the REST API (`POST /api/v2/monitor/system/config/backup`),
   - writes a timestamped `.conf` file into a **dedicated per-device subfolder**, locally, outside the Git repo,
   - continues execution even if a device fails (`ignore_errors: true`), so that a single site failure doesn't block backups for the others.
3. A **90-day retention** policy is applied globally (across all devices): older files are automatically deleted on every run.
4. A summary **execution report** (success/failure per device) is generated and saved locally on every run.
5. On job failure, a **webhook notification** is sent with a direct link to the GitHub Actions run.

⚠️ **No configuration data is stored or versioned in the GitHub repository.** Only the automation code (playbook, inventory, workflow) lives there. Backups and reports remain exclusively on the runner machine.

## Devices covered

| Site | Hostname (inventory) |
|---|---|
| Kenitra | `fortigate_kenitra_01` |
| Rabat | `fortigate_rabat_01` |
| Datacenter | `fortigate_datacenter_01` |

## Project structure

```
.
├── .github/
│   └── workflows/
│       └── fortigate_backup.yml   # GitHub Actions pipeline
├── backup_and_clean.yml           # Ansible playbook (multi-site backup + retention + report)
├── inventory.yml                  # Ansible inventory (3 FortiGate devices)

# Outside the repo (not versioned, local to the runner)
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

## Requirements

- A **self-hosted** GitHub Actions runner with network access to all three FortiGate devices.
- Ansible installed on the runner (`ansible-galaxy` available in `$PATH`).
- The **`fortinet.fortios`** collection (installed automatically by the pipeline on every run).
- An **API user** created on each FortiGate (`config system api-user`) with a valid token.
- Each firewall must allow the runner's IP in its API user's `trusthost`.

## Configuration

### GitHub Secrets (Settings → Secrets and variables → Actions)

| Secret | Description |
|---|---|
| `FORTIOS_TOKENS_JSON` | JSON object containing one API token per site (see format below) |
| `ALERT_WEBHOOK_URL` | (optional) Webhook URL for failure notifications |

**`FORTIOS_TOKENS_JSON` format:**

```json
{
  "FORTIOS_TOKEN_SITE_KEN": "kenitra_api_token",
  "FORTIOS_TOKEN_SITE_RBT": "rabat_api_token",
  "FORTIOS_TOKEN_DC": "datacenter_api_token"
}
```

Each inventory host references its matching key through a Jinja lookup:

```yaml
fortios_access_token: "{{ (lookup('env', 'FORTIOS_TOKENS_JSON') | from_json)['FORTIOS_TOKEN_SITE_KEN'] }}"
```

This centralizes every token in a single secret instead of one secret per device, which simplifies adding a new site to the inventory (only one GitHub variable to update).

### Inventory (`inventory.yml`)

Group `fortigates`, one host per site. Adding a new device = add a `hosts` entry + its token key in `FORTIOS_TOKENS_JSON`.

## Usage

**Manual trigger:**

```bash
gh workflow run "FortiGate Multi-Device Backup Runner"
gh run watch
```

**Local playbook test (outside CI):**

```bash
export FORTIOS_TOKENS_JSON='{"FORTIOS_TOKEN_SITE_KEN":"...","FORTIOS_TOKEN_SITE_RBT":"...","FORTIOS_TOKEN_DC":"..."}'
ansible-playbook -i inventory.yml backup_and_clean.yml
```

## Security

- The API token is never passed as a command-line `-e` argument (avoids exposure via `ps aux` / process logs).
- Tasks handling a token or configuration content use `no_log: true` to prevent any leakage into GitHub Actions logs.
- **No FortiGate configuration is ever written to the Git repo** — eliminates the risk of leaking sensitive data (certificates, keys, internal network layout) through Git history, even if the repo were compromised in the future.
- Local backup files are created with restricted permissions (`0700` directory, `0600` files), accessible only to the runner's user.
- A device failure (`ignore_errors: true`) doesn't expose token or configuration details in the logs — only the ✅/❌ status appears in the report.

## Backup file format

One timestamped file per device and per run, in its dedicated subfolder:

```
<inventory_hostname>_<YYYY-MM-DD>_<HHMMSS>.conf
```

Example: `fortigate_kenitra_01_2026-08-15_020000.conf`

## Retention

A **90-day** retention policy (`retention_days` in `backup_and_clean.yml`) is applied across the entirety of `~/fortigate_local_backups/` (recursive search across all device subfolders): any `.conf` file older than that is automatically deleted on every run. The number of deleted files is shown in the run logs.

## Execution report

On every run, a summary text report is generated in `~/fortigate_reports/`, listing the status (✅ Success / ❌ Failed) of each device:

```
==================================================
         FORTIGATE BACKUP REPORT
         Date: 2026-08-15 02:00:00
==================================================
  fortigate_kenitra_01      : ✅ Success
  fortigate_rabat_01        : ✅ Success
  fortigate_datacenter_01   : ❌ Failed
==================================================
```

This report stays local (not versioned) and allows for a quick diagnosis without needing to review the full GitHub Actions run logs.

## Roadmap / possible improvements

- [ ] GPG encryption of local backups
- [ ] Replication of the local archive to remote storage (S3 / Azure Blob) for resilience in case the runner is lost
- [ ] Sending the execution report by email or webhook (beyond the current failure-only notification)
- [ ] Automated policy audit (`analyze_policies.py`) integrated into the pipeline
- [ ] Adding new sites via a simple inventory entry (already largely enabled by the `FORTIOS_TOKENS_JSON` format)
