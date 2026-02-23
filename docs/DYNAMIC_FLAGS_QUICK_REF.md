# Dynamic Flags Quick Reference

## TL;DR - How It Works

**Each team gets a unique flag when starting a Docker container:**
```
Team A starts container → CYS{base64(1:team_5:743)}
Team B starts container → CYS{base64(1:team_8:129)}
```

**Key Features:**
- ✅ Unique per team (cannot be shared)
- ✅ Unique per instance (random component prevents collisions)
- ✅ Time-bound (expires when container stops)
- ✅ Verified in real-time (admin monitoring interface)

## Quick Access

- **Admin Page:** `/admin/dynamic-flags`
- **API Verify:** `POST /admin/dynamic-flags/verify`
- **API Check:** `POST /admin/dynamic-flags/check-uniqueness`

## Flag Format

```
PREFIX{base64_payload}

Payload: "challenge_id:identifier:random_number"
Identifier: "team_{id}" or "user_{id}"
Random: 1-1000000 (ensures uniqueness)
Encoding: URL-safe base64 without padding
```

## Storage Locations

| Location | Key | TTL | Purpose |
|----------|-----|-----|---------|
| **Database** | `container_instances.dynamic_flag` | Permanent | Historical record |
| **Cache Mapping** | `dynamic_flag_mapping:{chal_id}:{identifier}` | 24 hours | Validation lookup |
| **Session Cache** | `dynamic_flag:{session_id}` | Container lifetime | Quick access |

## Admin Interface Actions

### View All Flags
1. Go to **Admin → Dynamic Flags**
2. See all active containers and their flags
3. Color codes: 🟢 Running | 🟡 Starting | 🔴 Stopped | ⚠️ Expired

### Test a Flag
1. Click **"Test"** button next to container
2. Enter flag to verify
3. Get instant validation result

### Check Uniqueness
1. Click **"Check Uniqueness"** button
2. System scans all active containers
3. Reports:
   - Total containers
   - Unique flags count
   - Any duplicates or collisions
   - Robustness status (✅ or ❌)

### Copy Flag
1. Click clipboard icon next to flag
2. Flag copied to clipboard
3. Use for testing or verification

## Verification Example

```bash
# Via curl
curl -X POST http://localhost:5000/admin/dynamic-flags/verify \
  -H "Content-Type: application/json" \
  -d '{
    "container_id": 123,
    "submitted_flag": "CYS{Y2hhbDp0ZWFtXzU6NzQz}"
  }'

# Response if valid:
{
  "success": true,
  "verification": {
    "valid": true,
    "expected": "CYS{Y2hhbDp0ZWFtXzU6NzQz}"
  }
}

# Response if invalid:
{
  "success": true,
  "verification": {
    "valid": false,
    "expected": "CYS{Y2hhbDp0ZWFtXzU6NzQz}",
    "submitted": "CYS{WRONGflag}",
    "reason": "Flag mismatch"
  }
}
```

## Troubleshooting Checklist

| Issue | Check | Fix |
|-------|-------|-----|
| No flag generated | Challenge has `docker_flag_path` set? | Edit challenge, set path (e.g., `/flag.txt`) |
| Flag mismatch | All 3 storage locations consistent? | Restart container |
| Duplicates found | Same team or different teams? | Different teams = critical, stop all containers |
| Flag not accepted | Container expired? | Check expiration time, restart if needed |

## Fairness Guarantees Summary

| Guarantee | How Achieved |
|-----------|-------------|
| **Unique per team** | team_id in payload |
| **No collisions** | Random 1-1000000 component |
| **No sharing** | Abuse detection logs cross-team submissions |
| **Time-bound** | Expires with container |
| **Verifiable** | Admin monitoring interface |

## Code Snippets

### Check Flag in Python
```python
from models.container import ContainerInstance

container = ContainerInstance.query.get(container_id)
expected_flag = container.get_expected_flag()
result = container.verify_flag(submitted_flag)

if result['valid']:
    print(f"✅ Valid flag: {result['expected']}")
else:
    print(f"❌ Invalid. Expected: {result['expected']}")
```

### Generate Flag Manually
```python
from services.container_manager import ContainerOrchestrator

orchestrator = ContainerOrchestrator()
flag = orchestrator._generate_dynamic_flag(
    challenge=challenge,
    team_id=5,
    user_id=123
)
# Returns: CYS{Y2hhbGxlbmdlXzE6dGVhbV81OjE0Mg}
```

### Parse Flag
```python
from services.container_manager import ContainerOrchestrator

metadata = ContainerOrchestrator.parse_dynamic_flag(
    "CYS{Y2hhbGxlbmdlXzE6dGVhbV81OjE0Mg}"
)
# Returns:
# {
#   'challenge_id': 1,
#   'team_id': 5,
#   'is_valid': True,
#   'is_team_flag': True
# }
```

## Database Queries

### Find All Active Flags
```sql
SELECT 
    ci.id,
    c.name AS challenge,
    t.name AS team,
    u.username,
    ci.dynamic_flag,
    ci.status,
    ci.expires_at
FROM container_instances ci
JOIN challenges c ON ci.challenge_id = c.id
JOIN users u ON ci.user_id = u.id
LEFT JOIN teams t ON ci.team_id = t.id
WHERE ci.status IN ('starting', 'running')
  AND ci.dynamic_flag IS NOT NULL
ORDER BY ci.created_at DESC;
```

### Find Duplicate Flags
```sql
SELECT 
    dynamic_flag,
    COUNT(*) as count,
    GROUP_CONCAT(id) as container_ids
FROM container_instances
WHERE status IN ('starting', 'running')
  AND dynamic_flag IS NOT NULL
GROUP BY dynamic_flag
HAVING count > 1;
```

### Find Team Collisions
```sql
SELECT 
    dynamic_flag,
    challenge_id,
    COUNT(DISTINCT team_id) as team_count,
    GROUP_CONCAT(DISTINCT team_id) as teams
FROM container_instances
WHERE status IN ('starting', 'running')
  AND dynamic_flag IS NOT NULL
  AND team_id IS NOT NULL
GROUP BY dynamic_flag, challenge_id
HAVING team_count > 1;
```

## Testing Commands

### Test Uniqueness with Multiple Teams
```python
# Start containers for 10 teams simultaneously
import threading
from services.container_manager import container_orchestrator

def start_container(team_id):
    container_orchestrator.start_container(
        challenge_id=1,
        user_id=team_id,
        team_id=team_id
    )

threads = []
for team_id in range(1, 11):
    t = threading.Thread(target=start_container, args=(team_id,))
    threads.append(t)
    t.start()

for t in threads:
    t.join()

# Check uniqueness via admin interface or API
```

### Verify All Active Flags
```python
from models.container import ContainerInstance

containers = ContainerInstance.query.filter(
    ContainerInstance.status.in_(['starting', 'running'])
).all()

for container in containers:
    expected = container.get_expected_flag()
    result = container.verify_flag(expected)
    print(f"Container {container.id}: {result['valid']}")
```

## Configuration

### Enable Dynamic Flags for Challenge
1. Edit challenge in admin
2. Enable "Docker Container"
3. Set "Flag File Path" (e.g., `/flag.txt`)
4. Save challenge

### Configure Container Lifetime
```python
from models.settings import DockerSettings

settings = DockerSettings.query.first()
settings.container_lifetime_minutes = 15  # Default
db.session.commit()
```

### Clear All Flag Caches
```python
from services.cache import cache_service

# Clear mapping cache
cache_service.delete_pattern("dynamic_flag_mapping:*")

# Clear session cache
cache_service.delete_pattern("dynamic_flag:*")
```

## Monitoring

### Real-Time Metrics
- Active containers: `ContainerInstance.query.filter_by(status='running').count()`
- Unique flags: `ContainerInstance.query.filter(dynamic_flag.isnot(None)).distinct(dynamic_flag).count()`
- Expired containers: Check `expires_at < datetime.utcnow()`

### Auto-Refresh
The admin page auto-refreshes every 30 seconds to show current status.

## Best Practices

1. **Always check uniqueness** after system restart
2. **Monitor expiration times** to avoid expired flag submissions
3. **Review flag sources** badges - all 3 should be present
4. **Test flags manually** before CTF starts
5. **Document abuse attempts** from flag sharing logs

## Emergency Procedures

### If Duplicates Detected
```bash
# 1. Stop all affected containers
docker stop $(docker ps -q --filter "name=challenge-*")

# 2. Clear caches
redis-cli KEYS "dynamic_flag*" | xargs redis-cli DEL

# 3. Restart platform
docker-compose restart blackbox

# 4. Verify uniqueness via admin interface
```

### If Flags Not Generating
```bash
# 1. Check Docker settings exist
# Via admin or database

# 2. Verify challenge has docker_flag_path
# Edit challenge, check "Flag File Path"

# 3. Check schema
python -c "from scripts.db_schema import ensure_docker_schema; ensure_docker_schema()"

# 4. Restart
docker-compose restart blackbox
```

## Support

- **Full Documentation:** See `DYNAMIC_FLAGS_VERIFICATION.md`
- **Admin Interface:** `/admin/dynamic-flags`
- **Logs:** `docker-compose logs -f blackbox | grep -i "flag"`
