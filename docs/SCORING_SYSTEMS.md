# Scoring Systems

This platform supports multiple scoring systems for challenges. You can configure the scoring behavior globally or per-challenge.

## Scoring Types

### 1. Static Scoring
**When to use:** Simple CTFs, educational challenges, or when you want consistent point values.

- Challenge always awards the same points
- Points never change regardless of how many teams solve it
- Set `is_dynamic = False` on the challenge

**Example:**
- Challenge worth 500 points
- First solver gets 500 points
- 100th solver still gets 500 points

---

### 2. Dynamic Scoring - Logarithmic Decay (Default)
**When to use:** Competitive CTFs where you want to reward early solvers significantly but maintain smooth progression.

**Formula:**
```
points = initial - (initial - minimum) × (ln(solves + 1) / ln(decay + 1))
```

**Characteristics:**
- Smooth, gradual decrease in points
- Early solvers get substantial rewards
- Points decrease slowly at first, then stabilize
- Natural logarithm provides continuous decay

**Example with initial=500, minimum=100, decay=30:**
- Solve #1: 500 points
- Solve #5: ~368 points
- Solve #10: ~305 points
- Solve #20: ~218 points
- Solve #30+: 100 points (minimum)

**Visual pattern:**
```
500 |█████████████████████████████
400 |█████████████████████▒▒▒▒▒▒▒▒
300 |████████████▒▒▒▒▒▒▒▒░░░░░░░░
200 |██████░░░░░░░░░░░░░░░░░░░░░░
100 |░░░░░░░░░░░░░░░░░░░░░░░░░░░░
    +-----------------------------
     1  5  10  15  20  25  30  35
           Number of solves
```

---

### 3. Dynamic Scoring - Parabolic Decay (CTFd-style)
**When to use:** Highly competitive environments where you want to strongly incentivize being first, with rapid point loss initially.

**Formula:**
```
points = (((minimum - initial) / decay²) × solves²) + initial
points = ceil(points)
```

**Characteristics:**
- Steeper decrease early on
- Quadratic (x²) decay curve
- Levels out near minimum more quickly
- Same formula as CTFd platform

**Example with initial=500, minimum=100, decay=30:**
- Solve #1: 500 points
- Solve #5: ~456 points
- Solve #10: ~456 points
- Solve #20: ~322 points
- Solve #30+: 100 points (minimum)

**Visual pattern:**
```
500 |███████████████████████▒▒▒▒▒
400 |█████████████████▒▒▒▒▒░░░░░░
300 |██████████▒▒▒▒░░░░░░░░░░░░░░
200 |███▒▒░░░░░░░░░░░░░░░░░░░░░░░
100 |░░░░░░░░░░░░░░░░░░░░░░░░░░░░
    +-----------------------------
     1  5  10  15  20  25  30  35
           Number of solves
```

---

## Configuration

### Global Settings

**1. During Initial Setup:**
- Choose decay function when creating your admin account
- Options: Logarithmic (default) or Parabolic

**2. In Admin Settings:**
- Navigate to: Admin → Settings → Event Configuration
- Find "Dynamic Scoring Decay Function" dropdown
- Choose between:
  - **Logarithmic** (Smooth, gradual decay)
  - **Parabolic** (CTFd-style, steeper early decay)
- Click "Save Event Configuration"

**3. Via Environment Variables:**
Add to your `.env` file:
```bash
# Choose decay function: 'logarithmic' or 'parabolic'
DECAY_FUNCTION=logarithmic
```

### Per-Challenge Settings

When creating or editing a challenge in the admin panel:

**Scoring Configuration Section:**
- **Initial Points:** Starting point value (e.g., 500)
- **Minimum Points:** Lowest point value after full decay (e.g., 100)
- **Decay Solves:** Number of solves to reach minimum (e.g., 30)
- **Dynamic Scoring Toggle:** Enable/disable dynamic scoring for this challenge

**To disable dynamic scoring for a specific challenge:**
1. Edit the challenge
2. Uncheck "Dynamic Scoring"
3. The challenge will award Initial Points to all solvers

---

## Comparison Table

| Feature | Static | Logarithmic | Parabolic |
|---------|--------|-------------|-----------|
| **Point variation** | None | Smooth decrease | Steep early decrease |
| **Early solver advantage** | None | High | Very high |
| **Predictability** | Perfect | Moderate | Low early, high late |
| **Best for** | Education | Standard CTFs | Competitive CTFs |
| **Complexity** | Very simple | Simple | Moderate |

---

## Choosing the Right System

### Use **Static Scoring** when:
- Running a training/educational CTF
- All challenges should have equal weight
- Participants are beginners
- You want predictable scoring

### Use **Logarithmic Decay** when:
- Running a standard CTF competition
- Want to reward early solvers moderately
- Prefer smooth, predictable point curves
- Most CTF platforms (default behavior)

### Use **Parabolic Decay** when:
- Running highly competitive CTFs
- Want to strongly incentivize speed
- Emulating CTFd platform behavior
- Have experienced participants
- First solves should be highly rewarded

---

## Technical Details

### Implementation

Both decay functions are implemented in:
- `services/scoring.py` - `ScoringService.calculate_dynamic_points()`
- `models/challenge.py` - `Challenge.get_current_points()`

### Calculation Example

For a challenge with:
- Initial Points: 500
- Minimum Points: 100
- Decay Solves: 30

**At 10 solves:**

**Logarithmic:**
```python
points = 500 - (500 - 100) × (ln(11) / ln(31))
points = 500 - 400 × (2.398 / 3.434)
points = 500 - 400 × 0.698
points = 500 - 279.2
points = 220  # (rounded)
```

**Parabolic:**
```python
points = (((100 - 500) / 30²) × 10²) + 500
points = ((-400 / 900) × 100) + 500
points = (-0.444 × 100) + 500
points = -44.4 + 500
points = 456  # (rounded up)
```

---

## Migration Notes

If you're migrating from another CTF platform:

- **From CTFd:** Use **Parabolic** decay for identical behavior
- **From rCTF:** Use **Logarithmic** decay (similar)
- **From PicoCTF:** Use **Static** scoring (no decay)
- **From HackTheBox:** Use **Static** scoring (fixed points)

---

## FAQ

**Q: Can I change the decay function mid-competition?**  
A: Yes, but it will recalculate all challenge points immediately. This may affect the scoreboard significantly. Best to set before the CTF starts.

**Q: Does the decay function affect already-earned points?**  
A: No. Points are recorded at the time of solve. Changing the function only affects future solves.

**Q: Can I have different decay functions for different challenges?**  
A: No, the decay function is global. However, you can disable dynamic scoring per-challenge to have some static and some dynamic challenges.

**Q: What happens if decay_solves is reached?**  
A: The challenge awards minimum points to all subsequent solvers, regardless of the decay function.

**Q: Which decay function is more "fair"?**  
A: Logarithmic is generally considered more balanced. Parabolic heavily favors speed, which can be discouraging for slower teams.

---

## Additional Resources

- [CTFd Dynamic Scoring Documentation](https://docs.ctfd.io/docs/scoring/dynamic)
- Challenge configuration in this platform: Admin → Challenges → Edit Challenge
- Global settings: Admin → Settings → Event Configuration
