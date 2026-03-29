"""
Production Deployment Checklist and Operations Guide for TheCouncil

This document outlines the production-readiness requirements, deployment steps,
and operational procedures for TheCouncil.
"""

# PRODUCTION DEPLOYMENT CHECKLIST

## Pre-Deployment Verification (Security)

### Environment Configuration
- [ ] API_SECRET_KEY set to secure random value (min 32 chars)
- [ ] OPENROUTER_API_KEY or XAI_API_KEY configured
- [ ] POSTGRES_PASSWORD changed from default "council"
- [ ] DATABASE_URL points to production database
- [ ] REDIS_URL points to production Redis (with AUTH)
- [ ] CORS_ORIGINS restricted to known domains only
- [ ] STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET configured
- [ ] LOG_LEVEL set to INFO (not DEBUG)

### Database Readiness
- [ ] PostgreSQL instance running with SSL enabled
- [ ] Database migrations applied: `alembic upgrade head`
- [ ] Automated daily backups configured
- [ ] Database user has minimal required permissions
- [ ] Connection pooling configured (pool_size=5, max_overflow=10)
- [ ] All indexes created for foreign keys

### Infrastructure Readiness
- [ ] Redis instance configured with persistence (AOF)
- [ ] Redis AUTH password set
- [ ] Docker images built and pushed to registry
- [ ] Kubernetes secrets configured for all sensitive vars
- [ ] Health check endpoints responding correctly
- [ ] Rate limiting configured (100 req/min default)
- [ ] Request size limits enforced (100MB)
- [ ] HTTPS/TLS certificate installed
- [ ] Security headers validated on sample requests

### Celery Worker Setup
- [ ] Separate Celery worker process running
- [ ] COUNCIL_DISABLE_WORKER=0 on API instances
- [ ] COUNCIL_DISABLE_WORKER=1 (explicitly) or omitted on workers
- [ ] Celery broker/backend pointing to production Redis
- [ ] Worker processes configured with proper concurrency
- [ ] Task timeouts configured (soft=600s, hard=720s)

### Monitoring & Observability
- [ ] Structured logging configured (JSON format)
- [ ] Log aggregation tool connected (ELK, Cloud Logging, etc.)
- [ ] Metrics collection configured (Prometheus/CloudWatch)
- [ ] Tracing configured (correlation IDs on logs)
- [ ] Alerting rules defined for:
  - [ ] High error rate (>5% req failure)
  - [ ] Queue lag (>30s)
  - [ ] Database connection issues
  - [ ] Task timeout/failure rate
  - [ ] Memory usage (>80% of container limit)
  - [ ] Disk usage (>90% of volume)

### Authentication & Authorization
- [ ] Per-user API keys implemented (not single token)
- [ ] API key hash verification working
- [ ] Session authentication mechanism in place
- [ ] Webhook signature verification tested with Stripe
- [ ] Rate limiting per user/API key configured

### Security Validation
- [ ] No hardcoded secrets in code or config files
- [ ] All API endpoints require authentication
- [ ] SQL injection tests passed (ORM safe)
- [ ] XSS protection headers present
- [ ] CSRF token validation enabled on state-changing requests
- [ ] Security scan tools configured (e.g., Snyk, Dependabot)
- [ ] Dependency vulnerabilities addressed

### Data Protection
- [ ] Encryption at rest enabled for sensitive data
- [ ] Encryption in transit (TLS 1.2+) enforced
- [ ] User data retention policy enforced
- [ ] PII logged securely (no bearer tokens in logs)
- [ ] GDPR/privacy compliance validated

### Testing & QA
- [ ] All critical paths tested end-to-end
- [ ] Load test passed (target throughput sustained)
- [ ] Failure injection tests completed
- [ ] Rollback procedure tested successfully
- [ ] Database restore from backup tested
- [ ] Security audit passed

---

## Deployment Steps

### 1. Pre-Deployment Validation
```bash
# Run all checks
./scripts/pre-deploy-check.sh

# Verify environment
python -m council.api.app  # Should start and validate env

# Run test suite
pytest tests/ -v

# Run security checks
bandit -r council/
snyk test
```

### 2. Database Migration
```bash
# Apply all pending migrations
alembic upgrade head

# Verify schema
psql -d council -c "\dt"

# Backup before major change
pg_dump council > backup_$(date +%s).sql
```

### 3. Deploy API Service
```bash
# Build image
docker build -t council-api:$VERSION .

# Push to registry
docker push council-api:$VERSION

# Deploy (e.g., with kubectl)
kubectl set image deployment/council-api council-api=council-api:$VERSION

# Wait for rollout
kubectl rollout status deployment/council-api --timeout=5m

# Verify health
curl -s https://api.council.example.com/health | jq
curl -s https://api.council.example.com/readiness | jq
```

### 4. Deploy Celery Worker
```bash
# Deploy worker (separate from API)
kubectl set image deployment/council-worker council-worker=council-api:$VERSION

# Verify workers are picking up tasks
kubectl logs -f deployment/council-worker
```

### 5. Deploy Frontend
```bash
# Build next.js
cd web
npm run build

# Deploy static assets or Node.js app
# (push to CDN or deploy as Node.js app)
```

### 6. Smoke Tests
```bash
./scripts/smoke-test.sh

# Should test:
# - Health endpoint
# - Create run with valid auth
# - Get run status
# - List runs
# - Entitlements endpoint
```

---

## Operational Procedures

### Health Monitoring

**Health Endpoint** (`/health`):
- Returns immediately with "ok" or error
- Used by load balancers for traffic decisions
- Should respond in <200ms

**Readiness Endpoint** (`/readiness`):
- Validates database, Redis, external dependencies
- Returns 200 if ready, 503 if degraded
- Used by orchestration for deployment decisions

### Incident Response

#### High Error Rate
1. Check logs for common error patterns
2. Check database connectivity
3. Check API rate limits
4. Rollback if recent deployment
5. Increase worker count if queue lag high

#### Queue Backlog
1. Check worker health: `kubectl get pods -l app=worker`
2. Check Redis connectivity: `redis-cli ping`
3. Scale workers: `kubectl scale deployment/council-worker --replicas=5`
4. Check task logs for stuck jobs

#### Database Issues
1. Check connection pool: `SELECT usename, count(*) FROM pg_stat_activity GROUP BY usename;`
2. Kill long-running queries: `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE duration > interval '5 mins';`
3. Trigger backup: `pg_dump council > emergency_backup.sql`

### Scaling

**Horizontal Scaling (Add More Workers)**:
```bash
kubectl scale deployment/council-worker --replicas=10
```

**Vertical Scaling (More Resources)**:
```yaml
# Update resource limits in deployment
resources:
  requests:
    memory: "2Gi"
    cpu: "1000m"
```

**Database Scaling**:
- Read replicas for reporting queries
- Connection pooling (pgBouncer recommended)
- Partition large tables (by user_id or date)

### Rollback Procedure

```bash
# If deployment fails health checks
kubectl rollout undo deployment/council-api

# If rollback needed after production issue
kubectl rollout history deployment/council-api
kubectl rollout undo deployment/council-api --to-revision=3
```

### Log Analysis

```bash
# Find errors in structured logs
gcloud logging read 'severity=ERROR' --limit=100

# Track specific run
gcloud logging read 'jsonPayload.run_id="abc123"'

# Monitor queue lag
gcloud logging read 'jsonPayload.event="queue_dequeued"' --limit=100
```

---

## Metrics & Alerts

### Key Metrics to Monitor

| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| API Response Time (p50) | <500ms | >1000ms |
| API Response Time (p99) | <2s | >5s |
| Error Rate | <1% | >5% |
| Queue Lag | <5s | >30s |
| Worker Throughput | >10 runs/min | <5 runs/min |
| Database Pool Usage | <70% | >85% |
| Redis Memory | <500MB | >1GB |
| Pod Memory | <1GB | >1.5GB |
| Pod CPU | <500m | >800m |

### Prometheus Queries

```promql
# API request rate
rate(http_requests_total[5m])

# API error rate
rate(http_requests_total{status=~"5.."}[5m])

# Queue lag
queue_length

# Worker throughput
rate(runs_completed_total[5m])
```

---

## Runbook Examples

### High API Latency
1. Check metrics for correlated spike in database queries
2. Review slow query log: `PGSLOW > 1s`
3. Check for blocked queries: `SELECT * FROM pg_locks WHERE waiting = true;`
4. If query optimization needed, apply index
5. Monitor for next 30 mins post-fix

### Worker Task Failures
1. Check Celery task logs for error pattern
2. Identify failed task type
3. If transient, tasks auto-retry (max_retries=3)
4. If persistent, may need code fix + redeploy
5. Move failed tasks to DLQ for investigation

### Database Connection Pool Exhaustion
1. Check active connections: `SELECT count(*) FROM pg_stat_activity;`
2. Identify long-running transactions
3. Kill if safe: `SELECT pg_terminate_backend(pid) ...`
4. Scale read replicas if query load high
5. Review connection pool settings

---

## Disaster Recovery

### Backup & Restore

```bash
# Daily automated backup (configured in infrastructure)
# Manual backup before major change
pg_dump council -Fc > backup_$(date -I).custom

# Restore from backup
pg_restore -d council -Fc backup_TIMESTAMP.custom

# Verify restore
psql -d council -c "SELECT COUNT(*) FROM deliberations;"
```

### Point-in-Time Recovery

PostgreSQL PITR can restore to specific timestamp:
```bash
# Enable WAL archiving in production (already recommended)
# Restore to specific point in time:
pg_basebackup -D /tmp/restored_db
# Then restore WAL files and recover to target timeline
```

---

## Compliance & Security

### Regular Security Checks
- Weekly: Dependency vulnerability scan (Snyk)
- Monthly: OWASP top 10 review + penetration testing
- Quarterly: Full security audit
- Annually: SOC 2 Type II audit (if required)

### Data Privacy
- PII removed from logs
- API keys never logged
- Database backups encrypted
- User data retention policy enforced
- GDPR deletion requests honored within 30 days

### Performance SLOs

| Service | Target SLO |
|---------|-----------|
| API availability | 99.9% |
| API latency (p99) | <2s |
| Run completion time | <5 min (p95) |
| Queue processing lag | <30s (p95) |

---

## Post-Deployment Verification

After deployment, verify:
1. All health checks passing
2. Sample runs completing successfully
3. No unusual error patterns in logs
4. Billing events processing correctly
5. WebSocket connections succeeding
6. Frontend app loading and making API calls
7. Stripe webhook deliveries succeeding

If any verification fails, execute rollback immediately.

---

Generated: March 2026
Last Updated: Production Readiness Audit
