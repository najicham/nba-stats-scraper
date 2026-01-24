# NBA Props Platform Documentation

**Start here:** [00-start-here/README.md](00-start-here/README.md)

---

## Directory Structure

| Directory | Purpose |
|-----------|---------|
| [00-start-here/](00-start-here/) | Navigation, status, getting started |
| [01-architecture/](01-architecture/) | System design & decisions |
| [02-operations/](02-operations/) | Daily ops, backfills, troubleshooting |
| [03-phases/](03-phases/) | Phase-specific documentation |
| [04-deployment/](04-deployment/) | Deployment status & guides |
| [05-development/](05-development/) | Guides, patterns, testing |
| [06-reference/](06-reference/) | Quick lookups, processor cards |
| [07-monitoring/](07-monitoring/) | Grafana, alerts, observability |
| [07-admin-dashboard/](07-admin-dashboard/) | Pipeline UI documentation |
| [07-security/](07-security/) | Security governance & compliance |
| [08-projects/](08-projects/) | Active work tracking |
| [09-handoff/](09-handoff/) | Session handoffs |
| [validation/](validation/) | Data validation framework & reports |
| [archive/](archive/) | Historical documentation |

### Note on 07-* Directories

Three directories share the "07-" prefix but serve different audiences:
- **07-monitoring/** - System observability (engineers, ops)
- **07-admin-dashboard/** - Pipeline UI documentation (UI users)
- **07-security/** - Security governance (security team, compliance)

---

## Where to Put New Documentation

| You're creating... | Put it in... |
|--------------------|--------------|
| **Active project/task tracking** (checklists, status, progress) | `08-projects/current/{project-name}/` |
| **Session handoff notes** | `09-handoff/` |
| **Backfill runbooks** | `02-operations/runbooks/backfill/` |
| **Operational procedures** | `02-operations/` |
| **Phase-specific docs** | `03-phases/phase{N}/` |
| **How-to guides** | `05-development/guides/` |
| **Pattern documentation** | `05-development/patterns/` |
| **Quick reference/lookups** | `06-reference/` |
| **Data source coverage/fallbacks** | `06-reference/data-sources/` |
| **Monitoring/alerting** | `07-monitoring/` |
| **Architecture decisions** | `01-architecture/decisions/` |
| **Deployment status/history** | `04-deployment/` |
| **Validation framework/reports** | `validation/` |
| **Security audits/compliance** | `07-security/` |

**Full guide:** [05-development/docs-organization.md](05-development/docs-organization.md)

---

**Last reorganized:** 2026-01-24
