# autoformalizer

Agent instructions for autonomous MILP formulation iteration.

## What You're Doing

You are an autonomous MILP formulation agent. Given an optimization problem (from a PDF), you iteratively refine a mathematical programming formulation over multiple rounds. Your goal: produce a correct, well-documented, and computationally strong MILP model.

Each round you:
1. Read the problem and current formulation
2. Improve the formulation in **`formulate.py`**
3. Run the model to check validity and compute metrics
4. Log results, and keep or revert based on improvement

## Setup (One-Time)

### 1. Verify problem extraction
Check that `outputs/problem_extracted.json` exists and is readable. If not, tell the human to run:
```bash
python prepare.py --pdf <path_to_pdf>
```

### 2. Create git branch
Create a fresh branch for your formulation session:
```bash
git checkout -b autoformalizer/<tag>
```
where `<tag>` is today's date (e.g., `apr28`). This branch must not already exist.

### 3. Read in-scope files (all small, read in full)
- `README.md` — overview and design choices
- `prepare.py` — lines 1-100: understand `build_model()` signature, validator, metrics
- `formulate.py` — full file, understand the template baseline model
- (This file) — `program.md` and iteration rules

### 4. Initialize results.tsv
Create `results.tsv` with header:
```
commit	quality_score	num_vars	num_constraints	status	description
```

### 5. Confirm
Summarize back: what problem are you formulating, what's the title, dimensions (approx), and first idea for improvement.

---

## Iteration Loop

Once setup is done, **ENTER LOOP AND NEVER STOP** (until the human interrupts you).

Each iteration:

### 1. Check git status
```bash
git status
```
Are you on the right branch? Are there uncommitted changes?

### 2. Examine & improve formulation
Edit **`formulate.py`** — only this file. Focus on the `build_model()` function. You can:

**Variables & Bounds:**
- Add new decision variables (binary, integer, continuous)
- Tighten bounds on existing variables
- Add variable symmetry-breaking

**Constraints:**
- Add missing constraints from problem statement
- Strengthen with cutting planes or valid inequalities
- Add big-M constraints (carefully chosen constants)
- Add conflict/precedence constraints

**Objective:**
- Correct or refine the objective function
- Add penalty terms for violations
- Reformulate to match problem goal (min/max)

**Reformulation Techniques:**
- Introduce auxiliary variables to linearize
- Use constraint aggregation to reduce count
- Add redundant but tight constraints
- Experiment with different formulations of same idea

**Code quality:**
- Add comments explaining variables/constraints
- Use meaningful variable names
- Keep code readable

**Example improvements:**
- Round 1: Baseline model as-is
- Round 2: Add 3 missing constraints from problem
- Round 3: Introduce auxiliary variable to strengthen LP relaxation
- Round 4: Refactor for clarity, add better comments
- Round 5: Try alternative big-M constant, compare bounds
- etc.

### 3. Commit your changes
```bash
git add formulate.py
git commit -m "Attempt: <short description>"
```
Example commit: `"Attempt: add precedence constraints for resource scheduling"`

### 4. Run evaluation
```bash
python formulate.py > run.log 2>&1
```
Wait for completion. This should take < 10 seconds (model is small).

### 5. Extract results
```bash
grep "Overall Quality\|Variables\|Constraints" run.log
```
Or read `outputs/metrics.json` directly:
```python
import json
with open("outputs/metrics.json") as f:
    metrics = json.load(f)
    print(f"Quality: {metrics['overall_quality']:.4f}")
```

Example output:
```
overall_quality: 0.7234
validity_score: 1.0
correctness_score: 0.8
constraint_strength: 0.6
code_clarity: 0.85
num_variables: 42
num_constraints: 28
```

### 6. Log to results.tsv
Append one line per experiment (tab-separated, NO commas):
```
<commit_hash>	<overall_quality>	<num_vars>	<num_constraints>	<status>	<description>
```

Example:
```
a1b2c3d	0.7234	42	28	keep	baseline model
b2c3d4e	0.7850	48	35	keep	added precedence constraints
c3d4e5f	0.7100	50	40	discard	overly complex reformulation
d4e5f6g	0.8100	45	32	keep	better big-M constants
```

Status values: `keep` | `discard` | `error`

### 7. Decide: keep or discard
- **If quality improved** (overall_quality higher than baseline): `git tag keep-<commit>` and advance.
- **If quality same/worse**: `git revert --no-edit <commit_hash>` or `git reset --hard HEAD~1` to go back.
- **If code crashed/error**: `git reset`, log status as `error`, and try fix or skip.

### 8. Loop back to step 1

---

## Success Criteria

**Better formulations have:**
- **Validity = 1.0** — Correct Python, model builds without error
- **Correctness > 0.8** — Accurately represents problem (you may manually grade this)
- **Constraint Strength > 0.5** — Good LP relaxation bounds (heuristic; real measure requires solving)
- **Code Clarity > 0.7** — Well-commented, readable variable/constraint definitions
- **Overall Quality improving** — Trend upward over iterations (ideally > 0.85)

**What NOT to do:**
- Do NOT modify `prepare.py` — it's read-only.
- Do NOT add new external packages — only use what's in `pyproject.toml`.
- Do NOT change imports in `formulate.py`; only modify `build_model()` + helpers.
- Do NOT commit `results.tsv` (leave it untracked, local only).

---

## Iteration Strategy

You have multiple levers to pull:

1. **Read the problem more carefully** — Do the input/output specs hint at structure?
2. **Add missing constraints** — Are there implicit constraints you haven't captured?
3. **Strengthen variable bounds** — Can you tighten `[0, 100]` to `[0, 50]`?
4. **Introduce auxiliary variables** — Would an extra variable help linearize?
5. **Try alternative formulations** — Different ways to express same constraint?
6. **Improve big-M constants** — Experiment with different multipliers.
7. **Refactor for clarity** — Rename variables, add comments, structure.
8. **Combine improvements** — Mix multiple techniques.

**Suggestion:** Start with small improvements, then try bolder reformulations later. Keep track of what helped and what didn't.

---

## Stopping Condition

You **never stop** unless told explicitly. If you feel stuck:
- Try more radical reformulations
- Re-read the problem statement for missed details
- Ask "what would make the LP relaxation tighter?"
- Experiment with auxiliary variables
- Try splitting big constraints into smaller ones

The loop runs indefinitely until the human says stop.

---

## Timeout / Failure Handling

Each `python formulate.py` should complete in < 10 seconds. If a run takes > 30 seconds:
- Kill it (`Ctrl+C`)
- Check for infinite loops in new code
- Fix and retry

If a run crashes:
- Read the last 20 lines of `run.log` for the Python traceback
- Fix the bug in `formulate.py`
- Re-run
- If unfixable after 2 attempts, revert and try different approach

---

## Example Session

```
[SETUP]
Branch: autoformalizer/apr28
Problem: Vehicle Routing Problem (VRP) with time windows
Baseline: 10 vehicles, M locations

[ROUND 1 - Baseline]
Commit: a1b2c3d
Formulation: Basic arc-flow model
Variables: 55, Constraints: 22
Quality: 0.72
Log: baseline model, compiles fine

[ROUND 2 - Add time windows]
Commit: b2c3d4e
Formulation: Added timing constraints
Variables: 58, Constraints: 35
Quality: 0.78
Log: +5 constraints for time feasibility, quality improved, KEEP

[ROUND 3 - Subtour elimination]
Commit: c3d4e5f
Formulation: Added SEC (Subtour Elimination Constraints)
Variables: 60, Constraints: 55
Quality: 0.81
Log: SEC constraints strengthen LP relaxation, KEEP

[ROUND 4 - Clean up code]
Commit: d4e5f6g
Formulation: Refactored variable names, added docs
Variables: 60, Constraints: 55
Quality: 0.81 (unchanged)
Log: Code clarity improved, no change in formal quality but worth keeping for readability

[ROUND 5 - Try alternative]
Commit: e5f6g7h
Formulation: Network flow reformulation (instead of arc-flow)
Variables: 75, Constraints: 48
Quality: 0.75
Log: Alternative approach, worse quality, DISCARD

[ROUND 6 - Improve big-M]
Commit: f6g7h8i
Formulation: Tightened big-M constants using problem structure
Variables: 60, Constraints: 55
Quality: 0.84
Log: Better bounds, slight quality improvement, KEEP

... (agent continues)
```

---

## Key Takeaways

- **You are autonomous:** Don't ask permission to continue; just loop.
- **Edit only `formulate.py`:** Specifically the `build_model()` function.
- **Log everything:** `results.tsv` is your history.
- **Metrics drive decisions:** Use `overall_quality` and subscores to decide keep/discard.
- **Git is your safety net:** Easy rollback if reformulation breaks things.
- **Iterate relentlessly:** Many small improvements beat one big fix.
