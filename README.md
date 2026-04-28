# autoformalizer

Generate MILP formulations from optimization problem PDFs.

This project extracts a problem statement, builds test examples, asks an LLM for a candidate OR-Tools formulation, and evaluates the result in a loop.

## Inspiration

This repository was inspired by Andrew Karpathy's `autoresearch` project and adapted toward automatic MILP formulation.

## Features

- Extracts problem text and sample I/O from PDFs.
- Builds toy examples when the PDF does not contain usable samples.
- Generates and iterates on candidate formulations with an LLM.
- Evaluates candidate modules against the extracted examples.
- Supports offline replay for testing without an API.

## Quick Start

Install dependencies:

```bash
uv sync
```

If you want to run the live agent against an OpenAI-compatible endpoint, set:

```bash
AUTOFORMALIZER_MODEL=<model-name>
AUTOFORMALIZER_API_KEY=<api-key>
AUTOFORMALIZER_BASE_URL=https://api.openai.com/v1
AUTOFORMALIZER_ENDPOINT=chat/completions
```

`AUTOFORMALIZER_BASE_URL` and `AUTOFORMALIZER_ENDPOINT` are optional. The defaults target an OpenAI-compatible chat-completions API.

## Usage

Extract a PDF and prepare example data:

```bash
python prepare.py --pdf problems/problem.pdf
```

Inspect the generated examples:

```bash
python prepare.py --dump-examples
```

Run the agent loop:

```bash
python agent.py --max-iterations 4 --min-examples 3
```

Re-evaluate a candidate manually:

```bash
python formulate.py --candidate outputs/best_formulation.py
```

Generate a starter candidate template:

```bash
python formulate.py --template --candidate outputs/candidate_template.py
```

Run offline with saved responses:

```bash
python agent.py --replay-dir path/to/replay
```

## Project Layout

- `agent.py` runs the iterative generation and repair loop.
- `prepare.py` extracts PDF text and builds example data.
- `formulate.py` evaluates a candidate formulation module.
- `program.md` contains the original agent notes.
- `evaluation.md` documents the scoring and evaluation approach.

## Candidate Contract

Generated formulation modules are plain Python files that should implement:

- `parse_instance(input_text) -> dict`
- `build_model(instance) -> (solver, context)`
- `extract_solution(solver, instance, context) -> dict`
- `format_output(solution) -> str`
- `describe_formulation(problem) -> dict`

They should use `from ortools.linear_solver import pywraplp`.

## Testing

```bash
python -m unittest discover -s tests -v
```
