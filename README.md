# auto_milp

`auto_milp` is a small prototype for turning optimization problem statements into executable MILP candidates.

For the normal path, you only need one command:

```bash
python run.py --pdf problems/problem.pdf
```

The current workflow is:

1. Extract text and simple structure from a PDF problem statement.
2. Detect sample I/O if the PDF contains examples.
3. Create toy examples when the statement does not provide enough usable examples.
4. Ask an LLM for a candidate OR-Tools formulation module.
5. Run the candidate on the examples and score the result.
6. Repeat with feedback from the failed cases.

The repository is aimed at contest-style and coursework-style optimization problems.

## Current scope

What is implemented:

- PDF text extraction with basic section detection
- parser hints derived from the extracted input/output specification
- sample detection from PDF example blocks
- heuristic or LLM-generated toy examples when samples are missing
- candidate generation through an OpenAI-compatible API
- evaluation of candidate modules by parsing input, building a solver model, solving, and comparing output
- replay mode for testing the agent loop without live API calls

To Be Done:

- robust PDF parsing for messy statements
- strong semantic validation beyond sample-based checking
- problem-specific repair strategies beyond general prompt feedback
- support for more complex input/output formats

## Repository layout

- `prepare.py`
  Extracts problem structure and manages examples.
- `agent.py`
  Runs the iterative generate-evaluate loop.
- `formulate.py`
  Evaluates one candidate formulation module.
- `outputs/`
  Stores extracted problems, examples, reports, and best candidates.
- `tests/`
  Replay-based tests for the current loop.
- `program.md`
  Notes on the original iteration idea.
- `evaluation.md`
  Scoring notes.

## Installation

With `pip`:

```bash
python -m pip install -e .
```

With `uv`:

```bash
uv sync
```

## Usage

### One-command path

```bash
python run.py --pdf problems/problem.pdf
```

This does the usual full flow:

1. extract the problem
2. create or recover examples
3. run the agent loop
4. write the best formulation to `outputs/best_formulation.py`

### 1. Extract a problem

```bash
python prepare.py --pdf problems/problem.pdf
```

This writes:

- `outputs/problem_extracted.json`
- `outputs/toy_examples.json`

### 2. Inspect examples

```bash
python prepare.py --dump-examples
```

### 3. Configure the model endpoint

The agent expects an OpenAI-compatible chat completions API.

```bash
AUTO_MILP_MODEL=<model-name>
AUTO_MILP_API_KEY=<api-key>
AUTO_MILP_BASE_URL=https://api.openai.com/v1
AUTO_MILP_ENDPOINT=chat/completions
```

`AUTO_MILP_BASE_URL` and `AUTO_MILP_ENDPOINT` are optional.

### 4. Run the agent loop

```bash
python agent.py --max-iterations 4 --min-examples 3
```

### 5. Re-evaluate a candidate

```bash
python formulate.py --candidate outputs/best_formulation.py
```

### 6. Write a candidate template

```bash
python formulate.py --template --candidate outputs/candidate_template.py
```

## Replay mode

To test the orchestration without a live API:

```bash
python agent.py --replay-dir path/to/replay
```

The replay directory should contain JSON responses in call order.

## Candidate module interface

Each generated formulation is a Python module that should define:

- `parse_instance(input_text) -> dict`
- `build_model(instance) -> (solver, context)`
- `extract_solution(solver, instance, context) -> dict`
- `format_output(solution) -> str`
- `describe_formulation(problem) -> dict`

Candidate modules are expected to use:

```python
from ortools.linear_solver import pywraplp
```

## Outputs

The main output files are:

- `outputs/best_formulation.py`
- `outputs/metrics.json`
- `outputs/formulation.md`
- `outputs/formulation.tex`
- `outputs/agent_report.md`
- `outputs/agent_runs/`

## Notes

- `run.py` is the simplest way to use the project.
- `prepare.py`, `agent.py`, and `formulate.py` still exist for debugging or manual control.

## Testing

```bash
python -m unittest discover -s tests -v
```
