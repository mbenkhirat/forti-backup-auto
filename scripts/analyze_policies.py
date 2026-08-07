#!/usr/bin/env python3
"""
analyze_policies.py

Analyse les policies FortiGate extraites via l'API (cmdb + monitor) et détecte :
  - les règles jamais utilisées (hit_count = 0)
  - les règles trop permissives (any/any/ALL en accept)
  - les objets adresses/groupes orphelins (non référencés par aucune policy)
  - les règles potentiellement en doublon ou "shadowées" par une règle plus large
    placée avant elles dans l'ordre d'évaluation

Produit :
  - reports/<host>_report.json   : rapport complet structuré
  - reports/<host>_report.csv    : liste plate des findings, pour Excel/revue
  - generated/<host>_cleanup.yml : playbook Ansible de nettoyage (désactivation),
                                    à relire et valider manuellement avant exécution

Rien n'est appliqué automatiquement sur les firewalls : ce script ne fait que lire
des fichiers JSON déjà extraits et écrire des fichiers locaux.
"""

import argparse
import csv
import json
import os
from datetime import datetime, timezone


def load_json(path):
    """Charge un fichier JSON produit par le module uri (contient un champ 'results')."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("results", data if isinstance(data, list) else [])


def as_list(value):
    """Normalise les champs FortiOS qui peuvent être une liste de dicts {'name': ...}."""
    if value is None:
        return []
    if isinstance(value, list):
        return [v.get("name", v) if isinstance(v, dict) else v for v in value]
    if isinstance(value, dict):
        return [value.get("name", value)]
    return [value]


def is_permissive(policy):
    """Une policy est jugée trop permissive si elle autorise tout, de partout, vers partout."""
    src = set(as_list(policy.get("srcaddr")))
    dst = set(as_list(policy.get("dstaddr")))
    svc = set(as_list(policy.get("service")))
    action = policy.get("action", "").lower()
    return (
        action == "accept"
        and ("all" in {s.lower() for s in src})
        and ("all" in {d.lower() for d in dst})
        and ("all" in {s.lower() for s in svc} or "any" in {s.lower() for s in svc})
    )


def merge_stats(policies, stats):
    """Fusionne les stats (hit_count, last_used) dans les policies via policyid."""
    stats_by_id = {}
    for s in stats:
        pid = s.get("policyid") or s.get("policy_id") or s.get("id")
        if pid is not None:
            stats_by_id[str(pid)] = s

    for p in policies:
        pid = str(p.get("policyid"))
        s = stats_by_id.get(pid, {})
        p["hit_count"] = s.get("hit_count", s.get("packets", None))
        p["last_used"] = s.get("last_used")
    return policies


def find_unused(policies, min_hit_count=0):
    """Règles avec hit_count connu et égal à 0 (jamais matchées)."""
    unused = []
    for p in policies:
        hc = p.get("hit_count")
        if hc is not None and hc <= min_hit_count:
            unused.append(p)
    return unused


def find_permissive(policies):
    return [p for p in policies if is_permissive(p)]


def find_disabled(policies):
    return [p for p in policies if p.get("status", "").lower() == "disable"]


def find_shadowed(policies):
    """
    Heuristique simple de shadowing : pour deux policies enabled de même action,
    si la policy A (placée avant, id d'ordre plus petit dans la liste retournée
    par l'API, qui respecte l'ordre d'évaluation) couvre au moins autant que B
    en src/dst/service (via 'all'/'any' ou égalité stricte), alors B est
    potentiellement inatteignable.
    Ceci est une aide au diagnostic, pas une preuve formelle : à valider à la main.
    """
    shadowed = []
    enabled = [p for p in policies if p.get("status", "").lower() != "disable"]

    def covers(broad_field, narrow_field):
        broad = {v.lower() for v in as_list(broad_field)}
        narrow = {v.lower() for v in as_list(narrow_field)}
        if "all" in broad or "any" in broad:
            return True
        return broad == narrow

    for i, a in enumerate(enabled):
        for b in enabled[i + 1:]:
            if a.get("action") != b.get("action"):
                continue
            if (
                covers(a.get("srcaddr"), b.get("srcaddr"))
                and covers(a.get("dstaddr"), b.get("dstaddr"))
                and covers(a.get("service"), b.get("service"))
            ):
                shadowed.append({
                    "shadowed_policy": b.get("policyid"),
                    "shadowed_name": b.get("name"),
                    "shadowed_by_policy": a.get("policyid"),
                    "shadowed_by_name": a.get("name"),
                })
    return shadowed


def find_duplicates(policies):
    """Règles avec exactement les mêmes src/dst/service/action (doublons stricts)."""
    seen = {}
    duplicates = []
    for p in policies:
        key = (
            tuple(sorted(as_list(p.get("srcaddr")))),
            tuple(sorted(as_list(p.get("dstaddr")))),
            tuple(sorted(as_list(p.get("service")))),
            p.get("action"),
        )
        if key in seen:
            duplicates.append({
                "policy_a": seen[key],
                "policy_b": p.get("policyid"),
                "name_a": next((pp.get("name") for pp in policies if pp.get("policyid") == seen[key]), None),
                "name_b": p.get("name"),
            })
        else:
            seen[key] = p.get("policyid")
    return duplicates


def find_orphan_addresses(policies, addresses, addrgroups):
    """Objets adresses/groupes définis mais jamais référencés dans aucune policy."""
    referenced = set()
    for p in policies:
        referenced.update(as_list(p.get("srcaddr")))
        referenced.update(as_list(p.get("dstaddr")))

    # les groupes peuvent aussi référencer des adresses entre eux : on les inclut
    for g in addrgroups:
        referenced.update(as_list(g.get("member")))

    all_addr_names = {a.get("name") for a in addresses}
    all_group_names = {g.get("name") for g in addrgroups}

    orphan_addresses = sorted(all_addr_names - referenced)
    orphan_groups = sorted(all_group_names - referenced)
    return orphan_addresses, orphan_groups


def build_report(hostname, policies, addresses, addrgroups):
    unused = find_unused(policies)
    permissive = find_permissive(policies)
    disabled = find_disabled(policies)
    shadowed = find_shadowed(policies)
    duplicates = find_duplicates(policies)
    orphan_addr, orphan_grp = find_orphan_addresses(policies, addresses, addrgroups)

    report = {
        "hostname": hostname,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": {
            "policies": len(policies),
            "addresses": len(addresses),
            "addrgroups": len(addrgroups),
        },
        "findings": {
            "unused_policies": [
                {"policyid": p.get("policyid"), "name": p.get("name"), "hit_count": p.get("hit_count")}
                for p in unused
            ],
            "permissive_policies": [
                {"policyid": p.get("policyid"), "name": p.get("name"), "action": p.get("action")}
                for p in permissive
            ],
            "disabled_policies": [
                {"policyid": p.get("policyid"), "name": p.get("name")}
                for p in disabled
            ],
            "shadowed_policies": shadowed,
            "duplicate_policies": duplicates,
            "orphan_addresses": orphan_addr,
            "orphan_addrgroups": orphan_grp,
        },
    }
    return report


def write_json_report(report, report_dir, hostname):
    os.makedirs(report_dir, exist_ok=True)
    path = os.path.join(report_dir, f"{hostname}_report.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return path


def write_csv_report(report, report_dir, hostname):
    path = os.path.join(report_dir, f"{hostname}_report.csv")
    rows = []

    for f in report["findings"]["unused_policies"]:
        rows.append(["policy_non_utilisee", f["policyid"], f["name"], f"hit_count={f['hit_count']}"])
    for f in report["findings"]["permissive_policies"]:
        rows.append(["policy_permissive", f["policyid"], f["name"], "any/any/ALL en accept"])
    for f in report["findings"]["disabled_policies"]:
        rows.append(["policy_desactivee", f["policyid"], f["name"], "status=disable"])
    for f in report["findings"]["shadowed_policies"]:
        rows.append([
            "policy_potentiellement_shadowee",
            f["shadowed_policy"],
            f["shadowed_name"],
            f"masquee par policy {f['shadowed_by_policy']} ({f['shadowed_by_name']})",
        ])
    for f in report["findings"]["duplicate_policies"]:
        rows.append([
            "policy_doublon",
            f["policy_b"],
            f["name_b"],
            f"identique a policy {f['policy_a']} ({f['name_a']})",
        ])
    for name in report["findings"]["orphan_addresses"]:
        rows.append(["adresse_orpheline", "-", name, "non referencee dans aucune policy/groupe"])
    for name in report["findings"]["orphan_addrgroups"]:
        rows.append(["groupe_orphelin", "-", name, "non reference dans aucune policy/groupe"])

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["type_finding", "policyid", "nom", "detail"])
        writer.writerows(rows)
    return path


def build_cleanup_playbook(report, hostname):
    """
    Génère un playbook Ansible qui DÉSACTIVE (status: disable) les policies
    non utilisées et les policies trop permissives.
    Ne supprime jamais rien automatiquement, et ne s'exécute pas sans
    confirmation explicite (-e apply=true).
    """
    to_disable = report["findings"]["unused_policies"] + report["findings"]["permissive_policies"]
    # dédoublonnage par policyid
    seen_ids = set()
    unique_targets = []
    for item in to_disable:
        if item["policyid"] not in seen_ids:
            seen_ids.add(item["policyid"])
            unique_targets.append(item)

    lines = []
    lines.append("---")
    lines.append(f"# Playbook de nettoyage généré automatiquement pour {hostname}")
    lines.append(f"# Généré le {datetime.now(timezone.utc).isoformat()}")
    lines.append("#")
    lines.append("# CE PLAYBOOK NE FAIT RIEN PAR DÉFAUT.")
    lines.append("# Relisez chaque policy listée ci-dessous avant toute action.")
    lines.append("# Pour appliquer réellement les désactivations :")
    lines.append(f"#   ansible-playbook -i inventory.yml generated/{hostname}_cleanup.yml -e apply=true --ask-vault-pass")
    lines.append("#")
    lines.append(f"- name: Nettoyage des policies suspectes sur {hostname}")
    lines.append(f"  hosts: {hostname}")
    lines.append("  gather_facts: false")
    lines.append("  connection: local")
    lines.append("  vars:")
    lines.append("    apply: false   # passer à true (-e apply=true) pour exécuter réellement")
    lines.append("")
    lines.append("  tasks:")

    if not unique_targets:
        lines.append("    - name: Aucune policy suspecte détectée")
        lines.append("      ansible.builtin.debug:")
        lines.append(f'        msg: "Aucune action de nettoyage nécessaire pour {hostname}"')
    else:
        for item in unique_targets:
            pid = item["policyid"]
            name = (item.get("name") or "").replace('"', "'")
            lines.append(f"    - name: \"Désactiver policy {pid} ({name}) - à valider manuellement\"")
            lines.append("      ansible.builtin.uri:")
            lines.append(f"        url: \"https://{{{{ ansible_host }}}}/api/v2/cmdb/firewall/policy/{pid}\"")
            lines.append("        method: PUT")
            lines.append("        headers:")
            lines.append("          Authorization: \"Bearer {{ fortios_access_token }}\"")
            lines.append("        body_format: json")
            lines.append("        body:")
            lines.append("          status: disable")
            lines.append("        validate_certs: false")
            lines.append("        status_code: 200")
            lines.append("      delegate_to: localhost")
            lines.append("      no_log: true")
            lines.append("      when: apply | bool")
            lines.append("")

    return "\n".join(lines) + "\n"


def write_cleanup_playbook(report, cleanup_dir, hostname):
    os.makedirs(cleanup_dir, exist_ok=True)
    path = os.path.join(cleanup_dir, f"{hostname}_cleanup.yml")
    content = build_cleanup_playbook(report, hostname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def main():
    parser = argparse.ArgumentParser(description="Audit des policies FortiGate")
    parser.add_argument("--hostname", required=True)
    parser.add_argument("--policies", required=True)
    parser.add_argument("--policies-stats", required=True)
    parser.add_argument("--addresses", required=True)
    parser.add_argument("--addrgroups", required=True)
    parser.add_argument("--report-dir", default="./reports")
    parser.add_argument("--cleanup-dir", default="./generated")
    args = parser.parse_args()

    policies = load_json(args.policies)
    stats = load_json(args.policies_stats)
    addresses = load_json(args.addresses)
    addrgroups = load_json(args.addrgroups)

    policies = merge_stats(policies, stats)
    report = build_report(args.hostname, policies, addresses, addrgroups)

    json_path = write_json_report(report, args.report_dir, args.hostname)
    csv_path = write_csv_report(report, args.report_dir, args.hostname)
    cleanup_path = write_cleanup_playbook(report, args.cleanup_dir, args.hostname)

    f = report["findings"]
    print(f"=== Audit {args.hostname} ===")
    print(f"Policies analysées      : {report['totals']['policies']}")
    print(f"Policies non utilisées  : {len(f['unused_policies'])}")
    print(f"Policies permissives    : {len(f['permissive_policies'])}")
    print(f"Policies désactivées    : {len(f['disabled_policies'])}")
    print(f"Policies shadowées (?)  : {len(f['shadowed_policies'])}")
    print(f"Policies en doublon     : {len(f['duplicate_policies'])}")
    print(f"Adresses orphelines     : {len(f['orphan_addresses'])}")
    print(f"Groupes orphelins       : {len(f['orphan_addrgroups'])}")
    print(f"Rapport JSON  : {json_path}")
    print(f"Rapport CSV   : {csv_path}")
    print(f"Playbook nettoyage (à valider manuellement) : {cleanup_path}")


if __name__ == "__main__":
    main()