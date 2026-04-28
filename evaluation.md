# Evaluation Metrics & Validation

This document explains how formulations are evaluated and scored.

## Overview

Each formulation iteration produces **composite metrics** that combine multiple dimensions of quality:

1. **Validity** — Does the code compile & model structure valid?
2. **Correctness** — Does the formulation represent the problem accurately?
3. **Constraint Strength** — How tight are the LP relaxation bounds?
4. **Code Clarity** — Is the code readable and well-documented?

These combine into an **Overall Quality Score** (0-1), which drives the keep/discard decision.

## Individual Metrics

### Validity Score (0-1)

**What:** Does the formulation code run without errors?

- **1.0** — Code compiles, model builds, solver accepts it
- **0.8** — Code compiles, but solver has warnings or model structure issues
- **0.5** — Code compiles but model is infeasible or has logical errors
- **0.0** — Syntax error or runtime crash

**How computed:**
1. Check Python syntax
2. Try to execute `build_model(problem)` 
3. Verify solver state (no uninitialized variables, etc.)

**Why it matters:** A formulation that doesn't run is useless.

---

### Correctness Score (0-1)

**What:** Does the formulation accurately capture the problem statement?

- **1.0** — All problem requirements correctly encoded
- **0.8** — Most requirements encoded, minor omissions  
- **0.6** — Partial encoding, some constraints/objectives missing
- **0.3** — Significant misrepresentation
- **0.0** — No resemblance to problem

**How computed:**
Manual assessment by agent based on:
- Problem description in `problem['description']`
- Problem constraints in `problem['constraints']`
- Problem objective in `problem['objective_hint']`
- Cross-check: do variables align with problem entities?
- Cross-check: do constraints match problem rules?

**Why it matters:** A valid model that doesn't match the problem is wrong.

---

### Constraint Strength (0-1)

**What:** How well does the LP relaxation bound the problem?

- **1.0** — LP relaxation is very tight (near integral in many cases)
- **0.7** — Moderate; typical for a standard formulation
- **0.4** — Weak; many fractional LP solutions
- **0.0** — Very loose formulation

**How computed (heuristic):**
```
strength = min(num_constraints / num_variables, 5) / 5
```

This is a rough proxy. True measure requires solving LP relaxation & comparing to integer optimum, which we skip for speed.

**Agent can improve by:**
- Adding valid cutting planes or valid inequalities
- Strengthening big-M constants
- Adding redundant constraints that tighten bounds
- Reformulating to reduce fractional variables

**Why it matters:** Strong formulations solve faster & use fewer branch-and-bound nodes.

---

### Code Clarity (0-1)

**What:** Is the code readable, well-structured, and documented?

- **1.0** — Clear variable names, detailed comments, logical structure
- **0.75** — Generally clear, some comments, mostly understandable
- **0.5** — Minimal comments, confusing variable names
- **0.25** — Poorly organized, hard to follow
- **0.0** — Incomprehensible

**How computed:**
```
clarity_score = 0.5 + 0.2 * (comment_density)
```
where `comment_density = num_comment_lines / total_lines`

**Agent can improve by:**
- Adding descriptive comments (e.g., "Big-M for constraint X")
- Using meaningful variable names (e.g., `x_flow[i,j]` not `x[i]`)
- Structuring code with clear sections
- Documenting variable bounds and interpretations

**Why it matters:** Others (and future you) need to understand the formulation.

---

## Overall Quality Score

**Weighted average:**
```
overall_quality = 0.4 * validity 
                + 0.3 * correctness 
                + 0.2 * constraint_strength 
                + 0.1 * code_clarity
```

**Interpretation:**
- **> 0.85** — Excellent formulation, keep it
- **0.7-0.85** — Good formulation, improvements possible
- **0.5-0.7** — Mediocre, likely needs work
- **< 0.5** — Poor, discard and try different approach

---

## Example Progression

### Round 1 (Baseline)
```
Validity:    1.0  (baseline model compiles)
Correctness: 0.7  (captures main problem structure)
Strength:    0.5  (basic formulation, weak LP bounds)
Clarity:     0.6  (minimal comments)
Overall:     0.71
```
**Decision:** Keep (baseline reference)

### Round 2 (Add constraints)
```
Validity:    1.0  (still valid)
Correctness: 0.9  (added 3 missing constraints)
Strength:    0.6  (constraints tighten bounds slightly)
Clarity:     0.65 (added comments for new constraints)
Overall:     0.78
```
**Decision:** Keep (0.78 > 0.71, improvement of 0.07)

### Round 3 (Big-M tuning)
```
Validity:    1.0
Correctness: 0.9
Strength:    0.65 (better big-M constants)
Clarity:     0.65
Overall:     0.787
```
**Decision:** Keep (marginal improvement, worth it)

### Round 4 (Ambitious reformulation)
```
Validity:    0.5  (model infeasible or has errors)
Correctness: 0.0  (reformulation broke semantics)
Strength:    0.0
Clarity:     0.6
Overall:     0.24
```
**Decision:** Discard (0.24 << 0.787; revert)

### Round 5 (Cleanup code)
```
Validity:    1.0
Correctness: 0.9
Strength:    0.65
Clarity:     0.85 (added comprehensive comments)
Overall:     0.797
```
**Decision:** Keep (small improvement; clarity matters)

---

## How to Interpret & Use Metrics

### As an agent:

1. **After each run**, read `outputs/metrics.json`
2. **Compare to previous best:** Is `overall_quality` higher?
3. **Check individual scores:**
   - If Validity < 1.0 → fix the code
   - If Correctness low → re-read problem
   - If Strength low → add constraints or reformulate
   - If Clarity low → add comments
4. **Decide:** If improved, keep & advance. If worse, revert.

### Example decision logic:
```
new_quality = 0.82
old_quality = 0.787

if new_quality > old_quality:
    git commit -m "Improved: ..."  # KEEP
    advance branch
else:
    git reset --hard HEAD~1  # DISCARD
    try next idea
```

---

## Limitations & Notes

1. **Constraint Strength is heuristic** — True LP gap requires solving, which we skip.
2. **Correctness is agent-assessed** — May require manual review by human.
3. **Metrics are not perfect** — Code clipboard may not capture "elegance" or "practical solvability."
4. **Improvement is sparse** — Early rounds may show jumps; later improvements marginal.

To improve metrics in future:
- Solve LP relaxation and compare to ground truth (if available)
- Use SMT solver for semantic validation
- Apply readability scoring tools (e.g., Pylint for code style)

---

## Validation Checklist

Before committing a formulation improvement, verify:

- [ ] Code compiles (`python formulate.py` runs to completion)
- [ ] `outputs/metrics.json` exists
- [ ] All five metrics are numerics (no NaN or inf)
- [ ] `overall_quality` is higher than your previous best
- [ ] Git commit is descriptive (what did you change?)
- [ ] `results.tsv` is updated with new row

---

## Further Reading

- **Chvátal (1983)** — On algorithmic approach to the TSP: branch-and-bound with tight LP relaxations
- **Nemhauser & Ullmann (1969)** — Discrete dynamic programming and capital allocation
- **Fisher & Kedia (1990)** — Optimal solution of set covering/partitioning problems using Lagrangian relaxation

For practical MILP strengthening techniques, see any modern MILP solver documentation (CPLEX, Gurobi, SCIP).
