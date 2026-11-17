# ExamProctor — Disaster Recovery & Business Continuity Plan

## 1. Disaster Recovery Objectives

The ExamProctor Disaster Recovery (DR) Plan ensures business continuity for institutions and high-stakes examination bodies during infrastructure failures, data corruption, or regional outages.

| Metric | Target | Description |
| :--- | :--- | :--- |
| **Recovery Point Objective (RPO)** | **< 15 minutes** | Maximum acceptable data loss period (achieved via WAL archiving + hourly snapshots). |
| **Recovery Time Objective (RTO)** | **< 30 minutes** | Total time required to restore database, run health checks, and resume exam delivery. |
| **Backup Integrity Verification** | **100% SHA-256** | Every backup artifact is validated with a cryptographic SHA-256 checksum prior to restore. |

---

## 2. Backup Architecture & Tooling

ExamProctor includes automated, battle-tested backup and restoration utilities:
- `scripts/backup_db.py`
- `scripts/restore_db.py`

### 2.1 Backup Mechanism
When `scripts/backup_db.py` runs:
1. Invokes PostgreSQL's native `pg_dump` with clean, transactional options (`--clean --if-exists --no-owner --no-privileges`).
2. Generates an immutable timestamped `.sql` file in the configured backup directory (default: `backups/`).
3. Computes the SHA-256 cryptographic digest and writes it alongside the backup as `<backup_file>.sha256`.
4. Prunes backups exceeding the retention threshold (default: 30 days / 100 backups).

### 2.2 Manual Backup Execution
```bash
# Create immediate backup
python scripts/backup_db.py --output backups/

# Custom tag or destination
python scripts/backup_db.py --prefix pre_upgrade_v12
```

### 2.3 Automated Backup Schedule (Cron / Systemd)
Add to system crontab (`crontab -e`):
```cron
# Hourly backup during exam windows (08:00 - 20:00)
0 8-20 * * * /opt/exam-proctor/venv/bin/python /opt/exam-proctor/scripts/backup_db.py >> /var/log/examproctor_backup.log 2>&1

# Nightly backup and cleanup at 02:00
0 2 * * * /opt/exam-proctor/venv/bin/python /opt/exam-proctor/scripts/backup_db.py --keep-days 30 >> /var/log/examproctor_backup.log 2>&1
```

---

## 3. Offsite Backup Replication

Local backups in `backups/` must be synchronized offsite to cloud object storage (e.g., AWS S3, Google Cloud Storage, or MinIO):

```bash
# S3 Sync Script (/usr/local/bin/sync_backups_s3.sh)
#!/bin/bash
aws s3 sync /opt/exam-proctor/backups/ s3://institution-examproctor-backups/database/ \
  --sse aws:kms \
  --exclude "*" \
  --include "*.sql" \
  --include "*.sha256"
```

---

## 4. Disaster Recovery & Restoration Procedure

### 4.1 Step 1: Assess Incident & Isolate System
If active exams are occurring:
1. Put the platform into maintenance mode:
   ```bash
   curl -X POST https://exams.yourdomain.com/api/v1/admin/platform-config \
     -H "Authorization: Bearer <SUPER_ADMIN_TOKEN>" \
     -d '{"maintenance_mode": true}'
   ```
2. Stop background workers to prevent race conditions:
   ```bash
   docker compose stop worker
   ```

### 4.2 Step 2: Select and Verify Target Backup
Locate the most recent verified backup file and verify checksum:
```bash
python scripts/restore_db.py backups/exam_proctor_backup_20261117_195147.sql --verify-only
```
Output must show:
```
[INTEGRITY] SHA-256 verification SUCCESSFUL.
Expected: a1b2c3...
Computed: a1b2c3...
```

### 4.3 Step 3: Execute Database Restoration

> [!CAUTION]
> To prevent accidental disaster on production instances, `restore_db.py` contains a built-in production safety barrier. It will refuse to run against a production database without the `--confirm-production` flag.

```bash
# In Non-Production / Staging:
python scripts/restore_db.py backups/exam_proctor_staging_backup.sql

# In Production (Emergency Recovery):
python scripts/restore_db.py backups/exam_proctor_backup_20261117_195147.sql --confirm-production
```

### 4.4 Step 4: Run Post-Recovery Migrations & Verification
Ensure schema matches current application code:
```bash
python migrations/run_migrations.py status
python migrations/run_migrations.py upgrade --confirm
```

### 4.5 Step 5: Validate System Health & Resume Traffic
```bash
curl -f http://127.0.0.1:8000/health/ready
```
Once `/health/ready` returns HTTP 200:
1. Start worker: `docker compose start worker`
2. Disable maintenance mode: `maintenance_mode = false`
3. Notify exam coordinators and candidates.

---

## 5. Annual Disaster Recovery Drill Runbook

Execute this drill once per semester on staging:
1. Spin up a clean staging server without database data.
2. Download latest S3 backup and `.sha256` checksum.
3. Execute `python scripts/restore_db.py <backup>`.
4. Run test suite: `python -m unittest testing/test_phase12_e2e_acceptance.py`.
5. Log drill completion time, verify RTO < 30m, and sign off.
