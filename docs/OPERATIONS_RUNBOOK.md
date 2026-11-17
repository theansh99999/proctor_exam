# ExamProctor — Operations Runbook



## 1. System Overview & Routine Operations



This operations runbook provides actionable procedures for Site Reliability Engineers (SREs), system administrators, and technical operations teams managing ExamProctor in production.



---



## 2. Service Management Procedures



### 2.1 Starting, Stopping, and Restarting (Docker Compose)

```bash

# Start all platform components

docker compose up -d



# Restart web application with zero-downtime rolling reload

docker compose restart web



# View live aggregate logs

docker compose logs -f --tail=100



# Stop entire platform gracefully

docker compose stop

```



### 2.2 Starting, Stopping, and Restarting (Systemd / Bare-Metal)

```bash

# Web application service

sudo systemctl restart examproctor-web.service

sudo systemctl status examproctor-web.service



# Background async worker service

sudo systemctl restart examproctor-worker.service

sudo systemctl status examproctor-worker.service

```



---



## 3. Background Worker Operations



The background worker (`worker.py` / `modules/background/worker.py`) performs periodic maintenance every 30 seconds:

1. **Auto-Finalize Expired Sessions**: Closes exam sessions exceeding end-time + grace period without student manual submission.

2. **Scheduled Notifications**: Dispatches exam reminders 24h and 1h prior to scheduled start times.

3. **Integration Sync Retries**: Retries queued outbound sync payloads (e.g. ServiceNow gradebook push).

4. **Cache & Temp File Pruning**: Cleans expired temporary evaluation artifacts.



### Checking Worker Heartbeat

```bash

# Inspect worker output

docker compose logs --tail=50 worker



# Expected periodic log entry:

# [WORKER] Cycle completed: 0 sessions finalized, 0 reminders sent, 0 syncs retried.

```



If the worker encounters unhandled exceptions, it catches them, logs the traceback, and continues execution to avoid terminating the process.



---



## 4. Log Inspection & Request Tracing



### 4.1 Structured Observability

ExamProctor emits structured access logs formatted with request metadata:

```

INFO: 192.168.1.10 - "POST /api/v1/auth/token HTTP/1.1" 200 OK | req_id=f47ac10b-58cc-4372-a567-0e02b2c3d479 | time=0.038s

```



### 4.2 Tracing a Specific Candidate Issue

If a candidate reports an issue during an examination:

1. Request their `X-Request-ID` or timestamp and student email.

2. Search application logs:

   ```bash

   grep "req_id=f47ac10b" /var/log/examproctor/access.log

   ```

3. Check the candidate's `ExamSession` in database:

   ```sql

   SELECT id, status, current_question_index, score, integrity_score, started_at, submitted_at

   FROM exam_sessions

   WHERE student_id = 42 AND exam_id = 10;

   ```



---



## 5. Schema Migration & Rollback Procedures



### 5.1 Checking Migration State

```bash

python migrations/run_migrations.py status

```



### 5.2 Safe Upgrades

```bash

python migrations/run_migrations.py upgrade --confirm

```



### 5.3 Downgrading / Rolling Back a Migration

If a migration needs to be rolled back to a previous state:

```bash

python migrations/run_migrations.py downgrade --target phase10_admin --confirm

```



---



## 6. Incident Response Playbooks



### Playbook A: Candidate Internet Disconnection Mid-Exam

- **Symptom**: Candidate's network drops during an active exam.

- **System Behavior**: Exam session remains `in_progress`. Autosave records answers in local storage and commits answered questions to backend upon reconnect. Server-side timer persists.

- **Resolution**:

  1. Candidate reconnects within the scheduled exam window.

  2. The candidate resumes directly where they left off; state and shuffled option order are restored from database.

  3. If candidate's deadline expired due to prolonged outage, an examiner can grant an extra attempt via `/api/v1/admin/users/{id}/reset-attempt`.



### Playbook B: Database Connection Pool Exhaustion

- **Symptom**: Requests return HTTP 500 with `TimeoutError: QueuePool limit of size 20 overflow 10 reached`.

- **Immediate Mitigation**:

  1. Inspect active PostgreSQL queries:

     ```sql

     SELECT pid, age(clock_timestamp(), query_start), usename, query

     FROM pg_stat_activity

     WHERE state != 'idle' AND query NOT ILIKE '%pg_stat_activity%'

     ORDER BY query_start ASC;

     ```

  2. Terminate long-running locking queries:

     ```sql

     SELECT pg_terminate_backend(<pid>);

     ```

  3. Temporarily increase pool size via environment variables:

     ```

     DB_POOL_SIZE=40

     DB_MAX_OVERFLOW=20

     ```

     Restart web service.



### Playbook C: Sudden Influx of Proctoring Violation Alerts

- **Symptom**: Examiner dashboard alerts spiking with `tab_switch` or `multiple_faces`.

- **Verification**:

  1. Check examiner live dashboard for video streams.

  2. Remember: **Academic marks are NEVER automatically docked by proctoring events**.

  3. Examiner can open flagged student's session and review timestamped audit frames.

  4. Examiner can mark flags as `legitimate` (false positive) or `confirmed_cheat`.



---



## 7. Performance Tuning & Capacity Planning



| Metric | Warning Threshold | Critical Threshold | Action |

| :--- | :--- | :--- | :--- |

| **API Response Time (p95)** | > 200 ms | > 500 ms | Scale web workers (`docker compose up --scale web=3`) |

| **Database CPU Usage** | > 70% | > 85% | Check slow query log; verify query indexes |

| **Database Pool Utilization**| > 80% (24/30) | > 95% (28/30) | Increase `DB_POOL_SIZE` or optimize connection leaks |

| **Redis Memory Utilization** | > 75% | > 90% | Adjust TTL on cached exam sessions or add Redis RAM |

| **Worker Execution Latency** | > 15 s | > 28 s | Scale worker frequency or shard by organization ID |
