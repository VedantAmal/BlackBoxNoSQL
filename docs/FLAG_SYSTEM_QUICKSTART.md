# Enhanced Flag System - Quick Start Guide

## 🎯 What's New

### 1. Regex Flag Matching
Accept multiple flag formats with a single regex pattern instead of creating multiple flag entries.

**Example Use Cases:**
- Flexible flag formats: `flag{[A-Za-z0-9_]+}`
- Variable content: `flag{user_\d+_[0-9a-f]{8}}`
- Multiple valid answers: `flag{(answer1|answer2|answer3)}`

### 2. Smart Flag Sharing Detection
Automatic detection of teams copying flags with temporal pattern analysis.

**Detection Logic (SAME TEAM PATTERN):**
The system tracks when Team A solves and Team B submits Team A's flag. Pattern detection focuses on **repeated copying between the same two teams**:

- **Critical**: Any dynamic flag submission from another team (immediate critical severity)
- **Pattern Detected**: When Team B copies from Team A **2+ times** across different challenges
- **Escalation**: Severity increases with repeated violations between the same teams

**Example:** If Team B submits Team A's flags on Challenge 1 and Challenge 5, that's a detected pattern (2+ times from same team).

**Note:** The 15-minute time window is used to determine if flag sharing was immediate or delayed, but **any dynamic flag abuse is critical** regardless of timing.

---

## 🚀 Quick Start

### Create a Regex Flag

1. Go to Admin → Challenge → Flags
2. Click "Add Flag"
3. Check "Is Regex"
4. Enter pattern: `flag\{[A-Za-z0-9]{8,16}\}`
5. Add label: "Alphanumeric 8-16 chars"
6. Save

**Accepts:** `flag{abc12345}`, `flag{TEST1234ABCD}`, etc.

### Monitor Flag Sharing

1. Go to Admin → Flag Abuse
2. Review statistics dashboard
3. Check "Repeat Offenders" widget (shows teams with 3+ attempts)
4. Look for "PATTERN DETECTED" notes (teams copying from same source 2+ times)
5. Investigate critical severity items

---

## 📋 Migration Steps

### 1. Run Database Migration
```bash
# Docker deployment
docker exec -i blackbox-db mysql -u ctf_user -pctf_password ctf_platform < migrations/add_enhanced_flag_features.sql

# Or use the reset script
./reset_and_init.sh
```

### 2. Restart Application
```bash
docker-compose restart blackbox
```

### 3. Verify Installation
1. Open Admin → Challenge → Add Flag
2. Confirm you see "Is Regex" and "Per-Team Dynamic" checkboxes
3. Go to Admin → Flag Abuse
4. Confirm you see severity breakdown and repeat offenders

---

## 💡 Common Patterns

### Regex Patterns

**UUID-like flags:**
```regex
flag\{[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\}
```

**Hex strings:**
```regex
flag\{[0-9a-fA-F]{32}\}
```

**Word-based flags:**
```regex
flag\{[a-zA-Z]{5,20}\}
```

**Format with underscores:**
```regex
flag\{[a-z]+_[a-z]+_\d{4}\}
```

---

## 🔍 Troubleshooting

### Regex flag not matching submissions

**Problem:** Pattern seems correct but submissions fail

**Solution:**
1. Test pattern at https://regex101.com/ (use Python flavor)
2. Remember to escape special characters: `\{`, `\}`, `\.`
3. Pattern must match the ENTIRE flag (uses `fullmatch`)
4. Check case sensitivity setting

**Example:**
```
❌ Wrong: flag{.*}     (. matches any char, not literal dot)
✅ Right: flag\{.*\}   (escaped braces)

❌ Wrong: flag\{test   (missing closing brace in pattern)
✅ Right: flag\{test\} (complete pattern)
```

### False positives in abuse detection

**Problem:** Legitimate behavior flagged as pattern

**Solution:**
1. Review the "targeted_attempts" count - pattern detection requires 2+ attempts from same source
2. Check actual timestamps in abuse log
3. Remember: Any dynamic flag abuse is critical, but patterns show systematic copying
4. Look for "PATTERN DETECTED" in notes field
5. One-off incidents won't show as patterns

**Understanding Detection:**
- **Not a pattern**: Team B submits Team A's flag once → Critical (single incident)
- **Pattern detected**: Team B submits Team A's flags on 2+ challenges → Critical with pattern note
- **Serial offender**: Team B has 5+ total abuse attempts across any teams → Additional note added

---

## 📊 Admin Dashboard Features

### Flag Abuse Dashboard (`/admin/flag-abuse`)

**Statistics Widget:**
- Total attempts (all time)
- Attempts today
- Unique users involved
- Unique teams involved

**Severity Breakdown:**
- Critical: X attempts (all dynamic flag abuse)

**Repeat Offenders (Top 10):**
Shows teams with 3+ total abuse attempts:
```
1. TeamName - 8 attempts (last: 2 hours ago)
2. AnotherTeam - 5 attempts (last: 30 minutes ago)
```

**Pattern Detection:**
Look for "PATTERN DETECTED" in notes - indicates team has copied from the same source 2+ times.

**Detailed Log with Filters:**
- Filter by challenge
- Filter by team
- Filter by user
- Filter by severity (all will be critical)
- Shows targeted_attempts count (copies from same team)
- Sortable columns
- Pagination

---

## 🎓 Best Practices

### When to Use Each Flag Type

**Static Flags:**
- Simple, single correct answer
- No variation needed
- Traditional CTF style

**Regex Flags:**
- Multiple valid formats accepted
- Flexible answer format
- Programming challenges with variable output
- Challenges where format matters but content varies

### Flag Sharing Detection

**Understanding Severity:**
- **All dynamic flag abuse is Critical** - any attempt to submit another team's dynamic flag
- **Pattern Detection** - when a team repeatedly copies from the SAME source (2+ times)
- **Serial Offenders** - teams with 5+ total attempts across any teams

**During CTF:**
1. Monitor dashboard every few hours
2. Check "Repeat Offenders" widget for teams with 3+ attempts
3. Look for "PATTERN DETECTED" notes showing systematic copying
4. Track teams targeting specific other teams
5. Document evidence before taking action

**After CTF:**
1. Review all critical attempts
2. Focus on teams with detected patterns (2+ copies from same source)
3. Check targeted_attempts count in logs
4. Consider disqualification for systematic abuse
5. Review temporal patterns (how quickly after solves)

### Security Tips

**For Regex Flags:**
- Don't make patterns too broad
- Test edge cases
- Consider what malicious input might match
- Document expected format for players

---

## 📚 Additional Resources

- **Full Documentation:** `docs/FLAG_SYSTEM_ENHANCED.md`
- **API Endpoints:** See full docs for API details
- **Database Schema:** See migration file for schema changes
- **Code Examples:** Check models/branching.py for implementation

---

## 🆘 Need Help?

**Common Issues:**
1. Regex not matching → Test at regex101.com
2. False positives → Check if it's a true pattern (2+ times from same source)
3. Migration errors → Check database connection and permissions

**Debug Steps:**
1. Check Docker logs: `docker logs blackbox-ctf`
2. Check database: `docker exec -it blackbox-db mysql -u ctf_user -pctf_password ctf_platform`
3. Test flag submission manually
4. Review admin flag abuse logs:
   - Check "targeted_attempts" field (how many times from same source)
   - Look for "PATTERN DETECTED" in notes
   - Review timestamps to understand timing

**Understanding the Logs:**
- **severity**: Always "critical" for dynamic flag abuse
- **targeted_attempts**: Number of times this team copied from the same source team
- **historical_attempts**: Total abuse attempts by this team (any source)
- **notes**: Detailed explanation including pattern detection
- **pattern_detected**: true if targeted_attempts >= 1 (same source 2+ times total)

---

**Version:** 1.0  
**Last Updated:** October 24, 2025  
**Compatibility:** BlackBox CTF Platform v2.0+
