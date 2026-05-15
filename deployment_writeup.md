# Daily Pricing Pipeline — Deployment Plan

**Status:** Pre-deployment design memo
**Audience:** Management / non-technical stakeholders
**Author:** Allen
**Last updated:** 2026-05-14

---

## 1. Executive Summary

We are preparing to deploy our daily swap-pricing routine from local development to a scheduled, automated cloud workflow. This memo documents the architectural decisions made during planning, the rationale behind them, expected costs, and the sequence of work required to deploy.

**Headline decisions:**
- **Compute platform:** AWS Fargate (serverless containers), triggered daily by a cron-like scheduler.
- **Storage:** AWS S3 for pricing outputs (Parquet format, partitioned by date).
- **Monitoring:** CloudWatch Logs (automatic) + email alert on failure (CloudWatch Alarm → SNS).
- **Estimated cost:** ~$5–10/month at production scale; worst-case ceiling ~$20/month.
- **Deployment readiness:** ~2–3 calendar weeks of focused work after the pipeline is stable locally.

**Critical prerequisite:** outputs from the two in-flight pricers must be unified into a single agreed schema **before** any deployment work begins.

---

## 2. Current State

| Component | Status |
|---|---|
| Pricer A | In development (one team member) |
| Pricer B | In development (one team member) |
| Data fetcher | Working prototype in Jupyter notebook (`.ipynb`); not yet integrated |
| Unified output format | **Not yet defined** — top-priority gap |
| Orchestration script | Not yet written |
| Docker packaging | Not started |
| Cloud deployment | Not started |

---

## 3. Architectural Decisions

### 3.1 Compute: AWS Fargate (vs. EC2, Lambda, VPS, GitHub Actions)

| Option | Verdict | Rationale |
|---|---|---|
| **AWS Fargate** | ✅ **Chosen** | Pay-per-use; no idle server cost; supports our runtime; identical local-vs-cloud environment via Docker |
| AWS Lambda | ❌ Rejected | Hard 15-minute runtime cap; our job runs ~10 min today and will likely exceed the cap as data grows |
| AWS EC2 | ❌ Rejected | Always-on server costs ~$120/month for a job that runs 15 minutes/day; wasteful |
| Cheap VPS + cron | ❌ Rejected | Self-managed OS patching, security, and disk maintenance not appropriate for corporate use |
| GitHub Actions cron | ❌ Rejected | Schedule reliability and artifact retention not suitable for production data pipelines |

**Key driver:** runtime is ~10 min today and may grow. Lambda's 15-min cap leaves no margin. Fargate has effectively no runtime ceiling.

### 3.2 Storage: AWS S3 with Parquet outputs

| Decision | Rationale |
|---|---|
| **S3 over local disk** | Fargate's container disk is ephemeral — anything written there is destroyed when the task exits. S3 is the durable destination. |
| **S3 over RDS/Postgres** | Output is write-once, read-occasionally. A database adds cost (~$15/month minimum) and complexity not justified by the access pattern. |
| **Parquet over CSV** | 5–10× smaller, faster to read, preserves data types. Native pandas support. Industry standard for analytical data. |
| **Date-partitioned paths** (`s3://bucket/pricing/YYYY-MM-DD/results.parquet`) | Enables time-range queries, makes re-runs idempotent (overwrites cleanly), simple to reason about. |

### 3.3 Image registry: AWS ECR

Hosts the Docker image that Fargate runs. Required because Fargate needs a registry to pull from.

**Practice:** images tagged by git commit SHA (e.g., `swaps:abc123ef`), **never** `:latest`. This gives:
- Reproducible deployments — we know exactly what code ran on any given day.
- One-minute rollback by re-pointing the task definition at the previous tag.
- Auditability for compliance review.

### 3.4 Scheduling: EventBridge

EventBridge is AWS's native cron service. One rule (e.g., `cron(0 13 * * ? *)` = 9am ET daily) triggers the Fargate task. Free for scheduled rules.

### 3.5 Monitoring: CloudWatch Logs + SNS email alerts

- **CloudWatch Logs:** automatic. Every `print` and stack trace from the container is captured and queryable.
- **CloudWatch Alarm:** fires when the Fargate task exits non-zero (i.e., the script crashed).
- **SNS topic:** forwards alarm notifications to the team email.

**Optional enhancements** deferred until needed: Slack notifications, custom metrics (rows produced, runtime), runtime-exceeded alerts.

### 3.6 Idempotency

Date-partitioned output paths make re-runs safe by design — running today's job twice overwrites today's file, never duplicates. No additional system needed; this is a coding discipline rather than an architectural component.

---

## 4. Target Architecture (At a Glance)

```
                EventBridge (daily cron)
                         │
                         ▼
                ┌─────────────────┐         ┌──────────────┐
                │  Fargate task   │ ──pull──│     ECR      │
                │  (15 min/day)   │         │ (image repo) │
                └────────┬────────┘         └──────────────┘
                         │
              ┌──────────┼──────────┐
              │          │          │
              ▼          ▼          ▼
         fetch_data  price_A   price_B
              │          │          │
              └──────────┼──────────┘
                         ▼
                  unified results
                         │
                         ▼
              ┌────────────────────┐
              │       S3 bucket    │ ◄── notebooks, downstream consumers
              │  pricing/YYYY-MM-DD│
              └────────────────────┘
                         │
              ┌──────────┴──────────┐
              │ CloudWatch Logs     │ ◄── automatic capture
              │ CloudWatch Alarm    │ ──▶ SNS ──▶ team email on failure
              └─────────────────────┘
```

---

## 5. AWS Components Required

For introduction to the corporate cloud engineering team:

| # | Component | Purpose |
|---|---|---|
| 1 | AWS account access | Foundation for all services |
| 2 | S3 bucket | Stores daily pricing output (Parquet files) |
| 3 | ECR repository | Stores the Docker image of our pricing application |
| 4 | ECS cluster + Fargate task definition | Serverless runtime that executes the pricing script |
| 5 | IAM role | Grants the running task permission to write to S3 (and read secrets, if applicable) |
| 6 | EventBridge rule | Cron schedule that triggers the daily run |
| 7 | CloudWatch Logs | Automatic log capture for the running container |
| 8 | CloudWatch alarm + SNS topic | Email alert when the daily job fails |
| 9 | AWS Secrets Manager *(if data sources require API keys)* | Stores third-party API credentials securely |

---

## 6. Cost Estimate

### Realistic monthly cost (production scale)

| Component | Estimate |
|---|---|
| Fargate compute (4 vCPU × 8 GB × 15 min/day) | ~$1.50 |
| S3 storage (~1 GB/year) | ~$0.02 |
| S3 requests | ~$0.01 |
| ECR storage (~2 GB of images) | ~$0.20 |
| CloudWatch Logs (~300 MB ingestion + retention) | ~$0.20 |
| EventBridge schedule | Free |
| SNS email alerts (under 1,000/month) | Free |
| **Realistic total** | **~$2–3/month** |

### Worst-case ceiling (10× scale, daily image pushes, larger logs)

| Component | Worst-case |
|---|---|
| Fargate (30 min/day, 8 vCPU, 16 GB) | ~$6 |
| S3 (50 GB) | ~$1.20 |
| ECR (10 GB images) | ~$1.00 |
| CloudWatch Logs (1 GB/month) | ~$1.50 |
| Miscellaneous | ~$1.00 |
| **Worst-case total** | **~$10–15/month** |

### Hidden cost risks to flag with the cloud engineer

1. **NAT Gateway** — if corporate policy requires running the task in a private VPC without direct internet egress, a NAT Gateway costs ~$33/month flat. **Mitigation:** request a **VPC endpoint** for S3 access instead (near-zero cost). This is the single biggest potential cost surprise.
2. **ECR image accumulation** — without a lifecycle policy, old images accumulate. **Mitigation:** lifecycle rule to retain only the most recent N images.
3. **CloudWatch Logs retention** — defaults to indefinite. **Mitigation:** set a 30–90 day retention policy at creation.
4. **Cross-region data transfer** — keep all resources (S3, Fargate, ECR) in the same AWS region.

**Stakeholder summary:** infrastructure cost is effectively rounding-error. Real cost concerns are policy-driven configuration (e.g., NAT Gateway), not the services themselves.

---

## 7. Deployment Roadmap

### Phase 0 — Prerequisite: unify pricer outputs *(top priority, blocks everything else)*

- [ ] 30-minute meeting with both pricer authors
- [ ] Define and commit `OUTPUT_SCHEMA.md` — column names, dtypes, units, missing-value conventions
- [ ] Write a small `validate_output(df)` helper that both pricers call before returning
- [ ] Both pricers refactored to conform

**Why this is non-negotiable:** without a unified schema, every downstream piece (orchestrator, storage, validation, dashboards) has to handle two different shapes. The integration cost compounds. Fixing this *before* the pricers diverge further is the highest-leverage 30 minutes available.

### Phase 1 — Local end-to-end pipeline (target: 1 week)

- [ ] Extract data fetcher from notebook → `fetch.py` module (function returning a DataFrame)
- [ ] Wrap each pricer in a function returning the agreed schema
- [ ] Write `run_daily.py` orchestrator: fetch → price → concat → write Parquet
- [ ] Output destination configurable via environment variable (`OUTPUT_DIR`)
- [ ] Run end-to-end on a laptop, validate outputs
- [ ] Stable, reproducible local run

**Milestone:** `python run_daily.py` works on a laptop with production-equivalent data.

### Phase 2 — Packaging and cloud deployment (target: 1–2 weeks)

- [ ] Dockerfile: build image locally, run end-to-end inside Docker, verify identical output
- [ ] Confirm AWS access with cloud engineer; confirm component approvals
- [ ] Create S3 bucket; switch `OUTPUT_DIR` to `s3://...` in the Fargate environment
- [ ] Create ECR repository; push image tagged with git SHA
- [ ] Create ECS cluster, task definition, IAM role
- [ ] Manual test run from the AWS console; verify output lands in S3
- [ ] Create EventBridge rule with daily cron schedule
- [ ] Create CloudWatch alarm on task failure; subscribe team email via SNS
- [ ] Document one-off re-run procedure (single CLI command)

**Milestone:** first scheduled run succeeds end-to-end.

### Phase 3 — Hardening (target: ongoing)

- [ ] ECR lifecycle policy (retain last N images)
- [ ] CloudWatch Logs retention policy (30–90 days)
- [ ] Runbook for common failures (data-source down, schema validation failure, etc.)
- [ ] Optional: custom metrics for output volume and runtime
- [ ] Optional: Slack notifications

---

## 8. Questions for the Cloud Engineer

To be raised in the introduction call:

1. Are all listed AWS services approved under company cloud policy?
2. Are there mandated alternatives (internal registry instead of ECR, internal scheduler, etc.)?
3. Provisioning process — self-service, ticket-based, or fully managed by the cloud team?
4. Mandatory configurations: encryption at rest, VPC/network restrictions, tagging conventions, naming standards, log retention policies?
5. **NAT Gateway vs. VPC endpoint** — does our policy require the task to run in a private subnet? If so, can we use a VPC endpoint for S3 access instead of a NAT Gateway?
6. Secrets management — what is the corporate standard for third-party API keys (AWS Secrets Manager, internal vault, other)?
7. Access patterns — how are team members granted read access to S3 outputs?
8. Audit/compliance considerations — image SHA pinning, log retention, change-control records?

---

## 9. Open Questions and Future Considerations

- **Parallelization within the container:** pricing each deal is independent and CPU-bound. Once the pipeline is stable, we can parallelize via Python's `ProcessPoolExecutor` to cut runtime. Fargate vCPU allocation can be adjusted to match. Deferred until baseline is in place.
- **Multiple pricers running in parallel:** currently planning sequential execution inside one container. If both pricers grow heavy enough to dominate runtime, splitting them into separate containers (orchestrated with AWS Step Functions) is the upgrade path. Not needed for v1.
- **Output schema versioning:** when the schema must change, bump to `v2` rather than mutating in place. Old consumers continue reading old data; new consumers read the new schema.
- **Disaster recovery:** S3 is durable by design (11 nines). For additional safety, S3 versioning can be enabled (~no extra cost at our scale). Recommended for production data.
- **Access logging on the S3 bucket:** useful for audit but adds storage cost. Decide with cloud engineer.

---

## 10. Summary

**What we are building:** an automated daily pricing routine that runs in the cloud at a fixed time, writes results to a central durable store, and alerts the team if anything fails.

**Why this design:** it is the simplest architecture that meets corporate reliability standards, costs under $20/month, and stays operationally simple as the project grows.

**What unblocks the work:** unifying the two pricers' output schemas, and an introduction to the cloud engineering team to validate AWS component approvals.

**Timeline:** roughly 2–3 calendar weeks of focused work after the pipeline is stable locally.
