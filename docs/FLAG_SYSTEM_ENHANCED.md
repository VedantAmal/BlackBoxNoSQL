# Enhanced Flag System Documentation

This document describes the enhanced flag features in the BlackBox CTF Platform, including regex flag matching, per-team static flag generation, and improved flag sharing detection.

## Table of Contents
1. [Regex Flag Matching](#regex-flag-matching)
2. [Per-Team Static Flags](#per-team-static-flags)
3. [Enhanced Flag Sharing Detection](#enhanced-flag-sharing-detection)
4. [Admin Interface](#admin-interface)
5. [Database Schema](#database-schema)

---

## Regex Flag Matching

### Overview
Regex flags allow you to accept multiple valid flag formats without creating separate flag entries. This is useful for:
- Flags with flexible formatting (e.g., `flag{[A-Za-z0-9_]+}`)
- Flags with variable content (e.g., `flag{user_\d+_[0-9a-f]{8}}`)
- Challenges where multiple correct answers exist

### Usage

#### Creating a Regex Flag
When adding a flag in the admin panel:
1. Check the "Is Regex" option
2. Enter a valid regex pattern in the flag value field
3. Optionally disable case sensitivity

#### Examples

**Example 1: Accept any alphanumeric content**
```regex
flag\{[A-Za-z0-9_]+\}
```
Matches: `flag{hello123}`, `flag{test_flag}`, `flag{ABC}`, etc.

**Example 2: Accept specific format with variable ID**
```regex
flag\{user_\d+_[0-9a-f]{8}\}
```
Matches: `flag{user_42_a1b2c3d4}`, `flag{user_123_deadbeef}`, etc.

**Example 3: Multiple word flags**
```regex
flag\{(secret|password|key)_\d{4}\}
```
Matches: `flag{secret_1234}`, `flag{password_5678}`, `flag{key_9999}`, etc.

### Important Notes
- Use `\{` and `\}` to match literal braces
- The regex must match the **entire** submitted flag (uses `fullmatch`)
- Case sensitivity can be toggled independently of the regex pattern
- Invalid regex patterns will be rejected when creating the flag

---

## Per-Team Static Flags

### Overview
Per-team flags generate unique static flags for each team using a template system. This is ideal for:
- Static file-based challenges (downloadable files)
- Challenges where you want each team to have a unique flag
- Preventing flag sharing between teams
- Non-container challenges that need team-specific flags

**Note:** This is different from Docker container flags, which are dynamically generated at runtime. Per-team static flags are pre-generated based on a template.

### Template Variables

The following variables can be used in flag templates:

| Variable | Description | Example |
|----------|-------------|---------|
| `{team_id}` | Numeric team ID | `42` |
| `{team_name}` | Sanitized team name | `RedTeam` → `RedTeam`, `Team #1` → `Team__1` |
| `{team_hash}` | 8-char hash of team+challenge | `a1b2c3d4` |
| `{user_id}` | Numeric user ID (for solo players) | `123` |
| `{user_name}` | Sanitized username | `alice` |
| `{user_hash}` | 8-char hash of user+challenge | `e5f6g7h8` |

**Sanitization:** Team/user names are sanitized to replace special characters with underscores, keeping only `[a-zA-Z0-9_-]`.

### Usage

#### Creating a Per-Team Flag
1. Check the "Per-Team Dynamic" option when adding a flag
2. Enter a template in the "Flag Template" field
3. The template will be rendered for each team

#### Template Examples

**Example 1: Simple team ID flag**
```
flag{team_{team_id}_solved_challenge}
```
Generates:
- Team 1: `flag{team_1_solved_challenge}`
- Team 5: `flag{team_5_solved_challenge}`
- Team 42: `flag{team_42_solved_challenge}`

**Example 2: Team name in flag**
```
flag{{team_name}_{team_hash}}
```
Generates:
- RedTeam: `flag{RedTeam_a1b2c3d4}`
- BlueTeam: `flag{BlueTeam_e5f6g7h8}`

**Example 3: Cryptographic-style flag**
```
CTF{SHA256_{team_hash}_VERIFY}
```
Generates unique hashes per team for the same challenge.

**Example 4: Mixed variables**
```
flag{t{team_id}_h{team_hash}_secret}
```
Generates: `flag{t42_ha1b2c3d4_secret}`

### Viewing Generated Flags

Admins can view all generated flags for a per-team flag:
1. Go to the challenge flags page in admin
2. Click "View Team Flags" for any per-team flag
3. See a table with each team's generated flag

This helps when:
- Embedding flags in challenge files
- Verifying flag generation
- Troubleshooting team-specific issues

---

## Enhanced Flag Sharing Detection

### Overview
The enhanced system detects temporal patterns in flag submissions to identify systematic flag sharing between teams.

### Detection Features

#### 1. Temporal Analysis
The system tracks when Team A solves a challenge and when Team B submits the same flag:
- **Warning:** Flag submitted >15 minutes after original solve
- **Suspicious:** Flag submitted 5-15 minutes after original solve
- **Critical:** Flag submitted <5 minutes after original solve

#### 2. Pattern Recognition
The system analyzes historical behavior:
- **Targeted copying:** Team repeatedly copying from the same source team
- **Serial offenders:** Teams with multiple flag sharing attempts
- **Escalation:** Severity increases with repeated violations

#### 3. Severity Levels

| Severity | Criteria | Admin Action |
|----------|----------|--------------|
| **Warning** | Single incident, >15 min delay | Monitor |
| **Suspicious** | 2+ attempts or <15 min delay | Investigate |
| **Critical** | 3+ attempts from same source or <5 min delay | Review and potentially disqualify |

### How It Works

When a team submits a wrong flag, the system:
1. Checks if it's a valid dynamic flag format
2. Identifies the actual owner (team/user)
3. Queries when the owner solved the challenge
4. Calculates time since solve
5. Checks historical abuse attempts
6. Assigns severity based on patterns
7. Logs with detailed notes

### Admin Dashboard

The Flag Abuse page (`/admin/flag-abuse`) shows:
- **Statistics:** Total attempts, today's attempts, unique offenders
- **Severity breakdown:** Warning/Suspicious/Critical counts
- **Repeat offenders:** Top 10 teams with most attempts
- **Detailed log:** Each attempt with timestamp, challenge, severity, notes
- **Filters:** By challenge, team, user, severity

### Repeat Offenders Widget

Shows teams with 3+ flag sharing attempts:
```
Top Offenders:
1. HackerTeam - 8 attempts (last: 2h ago)
2. CodeBreakers - 5 attempts (last: 30m ago)
3. CTFWarriors - 4 attempts (last: 1d ago)
```

### Example Detection Flow

**Scenario:** Team B submits Team A's flag 8 minutes after Team A solves it

1. Team A solves Challenge X at 10:00 AM
2. Team B submits Team A's flag at 10:08 AM
3. System detects:
   - Valid dynamic flag format ✓
   - Belongs to different team ✓
   - Solved 8 minutes ago ✓
4. Temporal analysis:
   - Time since solve: 8 minutes → **Suspicious**
   - Team B history: First offense → Keep at Suspicious
   - Team B → Team A history: First time → Add note
5. Result logged:
   - Severity: **Suspicious**
   - Notes: "Flag submitted within 8 minutes of solve"

**Scenario 2:** Team B does it again 2 days later

1. Team A solves Challenge Y at 2:00 PM
2. Team B submits Team A's flag at 2:03 PM
3. System detects pattern:
   - Time since solve: 3 minutes → **Suspicious**
   - Team B history: 2nd offense → Escalate
   - Team B → Team A: 2nd time copying from same team → **Critical**
4. Result:
   - Severity: **Critical**
   - Notes: "Flag submitted within 3 minutes of solve; Team has copied from same team 2 times"
   - Admin receives critical log

---

## Admin Interface

### Flag Management

#### Adding a Flag
1. Navigate to Challenge → Flags section
2. Click "Add Flag"
3. Fill in the form:
   - **Flag Type:** Choose Static, Regex, or Per-Team
   - **Flag Value/Pattern/Template:** Depends on type
   - **Label:** Human-readable description
   - **Case Sensitive:** Toggle
   - **Unlocks Challenge:** Optional branching
   - **Points Override:** Optional custom points

#### Flag Types Form

**Static Flag:**
```
[ ] Is Regex
[ ] Per-Team Dynamic
Flag Value: [flag{static_flag_here}]
```

**Regex Flag:**
```
[x] Is Regex
[ ] Per-Team Dynamic
Flag Pattern: [flag\{[A-Za-z0-9]+\}]
```

**Per-Team Flag:**
```
[ ] Is Regex
[x] Per-Team Dynamic
Flag Template: [flag{team_{team_id}_{team_hash}}]
```

### Viewing Per-Team Flags

For per-team flags, a "View Team Flags" button appears:
- Shows template used
- Lists all teams and their generated flags
- Useful for distributing challenge files with embedded flags

---

## Database Schema

### New Columns in `challenge_flags`

```sql
-- Flag type flags
is_regex BOOLEAN DEFAULT FALSE
is_dynamic_per_team BOOLEAN DEFAULT FALSE

-- Template storage
flag_template VARCHAR(500) DEFAULT NULL

-- Extended pattern length
flag_value VARCHAR(500)  -- Increased from 255
```

### New Indexes in `flag_abuse_attempts`

```sql
-- For temporal analysis queries
CREATE INDEX idx_flag_abuse_timestamp ON flag_abuse_attempts(timestamp);

-- For pattern analysis queries  
CREATE INDEX idx_flag_abuse_team ON flag_abuse_attempts(team_id);
```

---

## Migration

Run the migration script:

```bash
# Docker environment
docker exec -i blackbox-db mysql -u ctf_user -pctf_password ctf_platform < migrations/add_enhanced_flag_features.sql

# Or via reset script
./reset_and_init.sh
```

---

## API Endpoints

### Get Challenge Flags
```
GET /admin/branching/challenges/<challenge_id>/flags
```
Returns all flags for a challenge with full details.

### Get Per-Team Generated Flags
```
GET /admin/branching/challenges/<challenge_id>/flags/<flag_id>/team-flags
```
Returns generated flags for all teams (only works for per-team flags).

### Add Flag
```
POST /admin/branching/flags
Form Data:
  - challenge_id
  - flag_value (or flag_template for per-team)
  - flag_label
  - is_regex (0 or 1)
  - is_dynamic_per_team (0 or 1)
  - is_case_sensitive (0 or 1)
  - unlocks_challenge_id (optional)
  - points_override (optional)
```

---

## Best Practices

### Regex Flags
- **Test your patterns:** Use a regex tester before deploying
- **Be specific:** Avoid overly broad patterns that might accept unintended inputs
- **Document format:** Use the label to describe what format is expected
- **Use anchors:** The system uses `fullmatch`, but be explicit in your pattern

### Per-Team Flags
- **Use hashes for security:** `{team_hash}` is more secure than just `{team_id}`
- **Keep templates readable:** Future you will thank you
- **Test with sample teams:** View generated flags before going live
- **Embed in files:** Perfect for challenges with downloadable content
- **Version control:** Keep track of which template was used for each challenge

### Flag Sharing Detection
- **Review regularly:** Check the abuse dashboard daily during CTF
- **Investigate suspicious:** Don't auto-disqualify, investigate first
- **Track patterns:** Look for systematic abuse vs. one-off mistakes
- **Adjust thresholds:** Default 15 minutes can be configured in code
- **Communicate policy:** Make clear that flag sharing will be detected

---

## Troubleshooting

### Regex Not Matching
- Check if pattern uses `fullmatch` semantics (must match entire string)
- Verify special characters are properly escaped
- Test pattern at https://regex101.com/ with "Python" flavor
- Ensure case sensitivity setting matches expected input

### Per-Team Flags Not Generating
- Verify template has valid placeholders
- Check if team/user exists in database
- Look for missing `{` or `}` in template
- Confirm `is_dynamic_per_team` flag is set

### False Positives in Abuse Detection
- May occur if teams solve very quickly
- Review actual timestamps in abuse log
- Consider that legitimate solves can be fast
- Check if it's a shared hint or public writeup causing pattern

---

## Future Enhancements

Potential improvements:
- Admin UI for editing existing flags (currently must delete/recreate)
- Bulk flag generation tools for per-team flags
- Export team flags as CSV for distribution
- Configurable time windows for abuse detection
- Automated notifications for critical abuse patterns
- Regex pattern library/examples in admin UI
- Flag validation testing tool
