"""
Iterative agent loop for parser-aware MILP formulation generation.

The agent:
1. Loads the extracted problem statement.
2. Detects existing examples, or generates toy examples when the PDF has none.
3. Prompts an LLM for a candidate OR-Tools formulation module.
4. Evaluates the candidate on the toy examples.
5. Feeds the evaluation back into the next iteration until it finds a strong candidate.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from formulate import BEST_CANDIDATE_FILE, CANDIDATE_TEMPLATE, evaluate_candidate
from prepare import (
    OUTPUTS_DIR,
    PROBLEM_EXTRACTED_FILE,
    TOY_EXAMPLES_FILE,
    load_examples,
    load_problem,
    save_examples,
    seed_toy_examples,
)


RUNS_DIR = OUTPUTS_DIR / "agent_runs"
BEST_METADATA_FILE = OUTPUTS_DIR / "best_attempt.json"
AGENT_REPORT_FILE = OUTPUTS_DIR / "agent_report.md"


class JSONLLMClient(Protocol):
    def complete_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        ...


def _strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


class OpenAICompatibleClient:
    """Uses an OpenAI-compatible chat-completions endpoint that returns JSON."""

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        endpoint: str = "chat/completions",
        temperature: float = 0.2,
        timeout: int = 180,
    ):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.endpoint = endpoint.lstrip("/")
        self.temperature = temperature
        self.timeout = timeout

    def complete_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        url = f"{self.base_url}/{self.endpoint}"
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM request failed: HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LLM request failed: {exc.reason}") from exc

        try:
            content = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise RuntimeError(f"Unexpected LLM response shape: {json.dumps(raw, indent=2)}") from exc

        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        if not isinstance(content, str):
            raise RuntimeError("LLM response content was not text")

        return json.loads(_strip_code_fences(content))


class ReplayClient:
    """Deterministic offline client for testing and local prompt iteration."""

    def __init__(self, replay_dir: Path):
        self.files = sorted(Path(replay_dir).glob("*.json"))
        if not self.files:
            raise FileNotFoundError(f"No replay JSON files found in {replay_dir}")
        self.index = 0

    def complete_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        if self.index >= len(self.files):
            raise RuntimeError("Replay responses exhausted")
        payload = json.loads(self.files[self.index].read_text(encoding="utf-8"))
        self.index += 1
        return payload


def _example_signature(example: Dict[str, Any]) -> str:
    return (
        example.get("input_text", "").strip()
        + "\n---\n"
        + example.get("expected_output_text", "").strip()
    )


def _merge_examples(existing: List[Dict[str, Any]], new_examples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    merged: List[Dict[str, Any]] = []
    for example in existing + new_examples:
        signature = _example_signature(example)
        if signature in seen:
            continue
        seen.add(signature)
        merged.append(example)
    return merged


def _normalize_examples(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    examples = payload.get("examples", [])
    normalized: List[Dict[str, Any]] = []
    for idx, example in enumerate(examples, start=1):
        if not isinstance(example, dict):
            continue
        input_text = str(example.get("input_text", "")).strip()
        output_text = str(example.get("expected_output_text", "")).strip()
        if not input_text:
            continue
        normalized.append(
            {
                "name": example.get("name") or f"toy_example_{idx}",
                "source": example.get("source", "llm"),
                "input_text": input_text,
                "expected_output_text": output_text,
                "expected_objective": example.get("expected_objective"),
                "explanation": str(example.get("explanation", "")).strip(),
            }
        )
    return normalized


def _build_examples_prompt(problem: Dict[str, Any], desired: int) -> str:
    parser_hints = json.dumps(problem.get("parser_hints", {}), indent=2)
    return f"""Generate {desired} small toy examples for this optimization problem.

Return JSON with this shape:
{{
  "examples": [
    {{
      "name": "short_name",
      "input_text": "exact input text",
      "expected_output_text": "exact output text",
      "expected_objective": 123,
      "explanation": "why this case is useful"
    }}
  ]
}}

Use tiny integer values and make the examples self-consistent with the parser hints.
Only emit JSON.

Problem title:
{problem.get("title", "")}

Description:
{problem.get("description", "")}

Input spec:
{problem.get("input_spec", "")}

Output spec:
{problem.get("output_spec", "")}

Constraints:
{problem.get("constraints", "")}

Objective hint:
{problem.get("objective_hint", "")}

Parser hints:
{parser_hints}
"""


def ensure_examples(
    problem: Dict[str, Any],
    examples_file: Path,
    llm_client: Optional[JSONLLMClient],
    min_examples: int,
) -> List[Dict[str, Any]]:
    existing = load_examples(
        examples_file,
        problem=problem,
        desired=min_examples,
        allow_seed=False,
    )
    good_existing = [example for example in existing if example.get("input_text", "").strip()]

    if len(good_existing) >= min_examples and any(
        example.get("expected_output_text", "").strip() for example in good_existing
    ):
        save_examples(good_existing, examples_file)
        return good_existing

    generated: List[Dict[str, Any]] = []
    if llm_client is not None:
        system_prompt = (
            "You create tiny, exact toy examples for competitive-programming style optimization "
            "problems. Output strictly valid JSON."
        )
        response = llm_client.complete_json(system_prompt, _build_examples_prompt(problem, min_examples))
        generated = _normalize_examples(response)

    if not generated:
        generated = seed_toy_examples(problem, desired=min_examples)

    merged = _merge_examples(good_existing, generated)
    save_examples(merged, examples_file)
    return merged


def _build_formulation_prompt(
    problem: Dict[str, Any],
    examples: List[Dict[str, Any]],
    history: List[Dict[str, Any]],
    best_evaluation: Optional[Dict[str, Any]],
) -> str:
    recent_history = history[-2:]
    history_json = json.dumps(recent_history, indent=2) if recent_history else "[]"
    examples_json = json.dumps(examples, indent=2)
    best_summary = json.dumps(best_evaluation, indent=2) if best_evaluation else "null"

    return f"""Write a candidate Python module for this repository.

Return JSON with exactly these keys:
{{
  "formulation_name": "short_name",
  "analysis": "brief reasoning",
  "assumptions": ["list", "of", "assumptions"],
  "latex": "latex formulation",
  "python_code": "full python module text"
}}

Requirements for python_code:
- Use OR-Tools linear solver via `from ortools.linear_solver import pywraplp`
- Target Python 3.10+
- Implement `parse_instance(input_text) -> dict`
- Implement `build_model(instance) -> (solver, context)`
- Implement `extract_solution(solver, instance, context) -> dict`
- Implement `format_output(solution) -> str`
- Implement `describe_formulation(problem) -> dict`
- Solve the toy examples exactly when the output is provided
- Keep the code deterministic and self-contained
- Do not wrap the module in markdown fences

Repository candidate template:
{CANDIDATE_TEMPLATE}

Problem:
{json.dumps(problem, indent=2)}

Toy examples:
{examples_json}

Previous attempts:
{history_json}

Current best evaluation:
{best_summary}
"""


def _feedback_from_evaluation(evaluation: Dict[str, Any]) -> Dict[str, Any]:
    failures = []
    for example in evaluation.get("example_results", []):
        if example.get("passed"):
            continue
        failures.append(
            {
                "name": example.get("name"),
                "solver_status": example.get("solver_status_name", "ERROR"),
                "actual_output": example.get("actual_output"),
                "expected_output": example.get("expected_output"),
                "error": example.get("error"),
            }
        )
    return {
        "overall_quality": evaluation.get("overall_quality"),
        "validity_score": evaluation.get("validity_score"),
        "correctness_score": evaluation.get("correctness_score"),
        "constraint_strength": evaluation.get("constraint_strength"),
        "failures": failures,
    }


def _write_agent_report(
    problem: Dict[str, Any],
    examples: List[Dict[str, Any]],
    history: List[Dict[str, Any]],
    best_evaluation: Optional[Dict[str, Any]],
) -> None:
    lines = [
        f"# Agent Report: {problem.get('title', 'Unknown problem')}",
        "",
        f"Toy examples available: {len(examples)}",
        "",
    ]

    if best_evaluation is not None:
        lines.extend(
            [
                "## Best Evaluation",
                "",
                f"- Formulation: {best_evaluation.get('formulation_name', 'unknown')}",
                f"- Overall quality: {best_evaluation.get('overall_quality', 0.0):.4f}",
                f"- Example pass rate: {best_evaluation.get('example_pass_rate', 0.0):.4f}",
                f"- Output match rate: {best_evaluation.get('output_match_rate', 0.0):.4f}",
                "",
            ]
        )

    lines.append("## Attempts")
    lines.append("")
    for record in history:
        lines.append(
            f"- Round {record['round']}: quality={record['evaluation']['overall_quality']:.4f} "
            f"name={record['proposal'].get('formulation_name', 'unknown')}"
        )
    lines.append("")
    AGENT_REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")


def run_agent(
    problem_file: Path,
    examples_file: Path,
    max_iterations: int,
    quality_threshold: float,
    min_examples: int,
    llm_client: JSONLLMClient,
) -> Dict[str, Any]:
    problem = load_problem(problem_file)
    examples = ensure_examples(problem, examples_file, llm_client, min_examples=min_examples)

    run_root = RUNS_DIR / time.strftime("%Y%m%d-%H%M%S")
    candidates_dir = run_root / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)

    history: List[Dict[str, Any]] = []
    best_evaluation: Optional[Dict[str, Any]] = None
    best_candidate_path: Optional[Path] = None
    best_quality = float("-inf")

    for round_index in range(1, max_iterations + 1):
        system_prompt = (
            "You are an expert optimization modeler. You write small, exact, executable "
            "OR-Tools MILP modules and improve them from evaluation feedback. Output JSON only."
        )
        user_prompt = _build_formulation_prompt(problem, examples, history, best_evaluation)
        proposal = llm_client.complete_json(system_prompt, user_prompt)

        candidate_code = _strip_code_fences(str(proposal.get("python_code", "")))
        if not candidate_code.strip():
            raise RuntimeError("LLM response did not include python_code")

        candidate_path = candidates_dir / f"attempt_{round_index:03d}.py"
        candidate_path.write_text(candidate_code, encoding="utf-8")
        (candidate_path.with_suffix(".json")).write_text(
            json.dumps(proposal, indent=2),
            encoding="utf-8",
        )

        evaluation_dir = run_root / f"attempt_{round_index:03d}"
        evaluation = evaluate_candidate(
            candidate_path,
            problem=problem,
            examples=examples,
            output_dir=evaluation_dir,
            persist=True,
        )

        record = {
            "round": round_index,
            "proposal": {
                "formulation_name": proposal.get("formulation_name"),
                "analysis": proposal.get("analysis"),
                "assumptions": proposal.get("assumptions", []),
            },
            "evaluation": _feedback_from_evaluation(evaluation),
            "candidate_path": str(candidate_path),
        }
        history.append(record)

        quality = float(evaluation.get("overall_quality", 0.0))
        if quality > best_quality:
            best_quality = quality
            best_evaluation = evaluation
            best_candidate_path = candidate_path
            shutil.copy2(candidate_path, BEST_CANDIDATE_FILE)
            BEST_METADATA_FILE.write_text(json.dumps(record, indent=2), encoding="utf-8")

        solved_everything = (
            evaluation.get("validity_score", 0.0) >= 1.0
            and evaluation.get("example_pass_rate", 0.0) >= 1.0
        )
        if quality >= quality_threshold and solved_everything:
            break

    if best_candidate_path is None or best_evaluation is None:
        raise RuntimeError("Agent did not produce any evaluable candidate")

    final_evaluation = evaluate_candidate(
        BEST_CANDIDATE_FILE,
        problem=problem,
        examples=examples,
        output_dir=OUTPUTS_DIR,
        persist=True,
    )
    _write_agent_report(problem, examples, history, final_evaluation)

    return {
        "problem": problem,
        "examples": examples,
        "history": history,
        "best_evaluation": final_evaluation,
        "best_candidate_path": str(BEST_CANDIDATE_FILE),
    }


def _resolve_client(args: argparse.Namespace) -> JSONLLMClient:
    if args.replay_dir:
        return ReplayClient(args.replay_dir)

    model = args.model or os.getenv("AUTOFORMALIZER_MODEL") or os.getenv("OPENAI_MODEL")
    api_key = os.getenv("AUTOFORMALIZER_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("AUTOFORMALIZER_BASE_URL") or "https://api.openai.com/v1"
    endpoint = os.getenv("AUTOFORMALIZER_ENDPOINT") or "chat/completions"

    if not model:
        raise RuntimeError(
            "No model configured. Set AUTOFORMALIZER_MODEL or pass --model."
        )
    if not api_key:
        raise RuntimeError(
            "No API key configured. Set AUTOFORMALIZER_API_KEY or OPENAI_API_KEY."
        )

    return OpenAICompatibleClient(
        model=model,
        api_key=api_key,
        base_url=base_url,
        endpoint=endpoint,
        temperature=args.temperature,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the iterative MILP formulation agent")
    parser.add_argument("--problem", type=Path, default=PROBLEM_EXTRACTED_FILE)
    parser.add_argument("--examples", type=Path, default=TOY_EXAMPLES_FILE)
    parser.add_argument("--max-iterations", type=int, default=4)
    parser.add_argument("--quality-threshold", type=float, default=0.9)
    parser.add_argument("--min-examples", type=int, default=3)
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--replay-dir", type=Path, default=None)
    args = parser.parse_args()

    client = _resolve_client(args)
    result = run_agent(
        problem_file=args.problem,
        examples_file=args.examples,
        max_iterations=args.max_iterations,
        quality_threshold=args.quality_threshold,
        min_examples=args.min_examples,
        llm_client=client,
    )

    best = result["best_evaluation"]
    print("=" * 70)
    print("AUTOFORMALIZER AGENT")
    print("=" * 70)
    print(f"Problem:           {result['problem']['title']}")
    print(f"Toy examples:      {len(result['examples'])}")
    print(f"Best candidate:    {result['best_candidate_path']}")
    print(f"Overall quality:   {best['overall_quality']:.4f}")
    print(f"Example pass rate: {best['example_pass_rate']:.4f}")
    print(f"Output match rate: {best['output_match_rate']:.4f}")
    print("=" * 70)


if __name__ == "__main__":
    main()
