"""
Single-command entrypoint for the normal auto_milp workflow.

Usage:
    python run.py --pdf problems/problem.pdf
    python run.py --problem outputs/problem_extracted.json --replay-dir replay/
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional

import agent
from prepare import (
    PDFExtractor,
    PROBLEM_EXTRACTED_FILE,
    TOY_EXAMPLES_FILE,
    extract_examples_from_problem,
    load_problem,
    save_examples,
    seed_toy_examples,
)


def extract_problem(pdf_path: Path, problem_file: Path, examples_file: Path) -> Dict[str, Any]:
    extractor = PDFExtractor(str(pdf_path))
    problem = extractor.extract_structure()
    extractor.save(problem_file)

    examples = extract_examples_from_problem(problem)
    if examples:
        save_examples(examples, examples_file)
    else:
        save_examples(seed_toy_examples(problem), examples_file)
    return problem


def run_pipeline(
    pdf_path: Optional[Path],
    problem_file: Path,
    examples_file: Path,
    max_iterations: int,
    quality_threshold: float,
    min_examples: int,
    model: Optional[str],
    temperature: float,
    replay_dir: Optional[Path],
) -> Dict[str, Any]:
    if pdf_path is not None:
        problem = extract_problem(pdf_path, problem_file, examples_file)
    else:
        problem = load_problem(problem_file)

    args = argparse.Namespace(
        model=model,
        temperature=temperature,
        replay_dir=replay_dir,
    )
    client = agent._resolve_client(args)
    result = agent.run_agent(
        problem_file=problem_file,
        examples_file=examples_file,
        max_iterations=max_iterations,
        quality_threshold=quality_threshold,
        min_examples=min_examples,
        llm_client=client,
    )
    result["problem"] = problem
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the full auto_milp pipeline in one command")
    parser.add_argument(
        "--pdf",
        type=Path,
        default=None,
        help="Path to a problem PDF. If omitted, use the existing extracted problem JSON.",
    )
    parser.add_argument(
        "--problem",
        type=Path,
        default=PROBLEM_EXTRACTED_FILE,
        help="Path to the extracted problem JSON file.",
    )
    parser.add_argument(
        "--examples",
        type=Path,
        default=TOY_EXAMPLES_FILE,
        help="Path to the toy examples JSON file.",
    )
    parser.add_argument("--max-iterations", type=int, default=4)
    parser.add_argument("--quality-threshold", type=float, default=0.9)
    parser.add_argument("--min-examples", type=int, default=3)
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--replay-dir", type=Path, default=None)
    args = parser.parse_args()

    result = run_pipeline(
        pdf_path=args.pdf,
        problem_file=args.problem,
        examples_file=args.examples,
        max_iterations=args.max_iterations,
        quality_threshold=args.quality_threshold,
        min_examples=args.min_examples,
        model=args.model,
        temperature=args.temperature,
        replay_dir=args.replay_dir,
    )

    best = result["best_evaluation"]
    print("=" * 70)
    print("AUTO_MILP")
    print("=" * 70)
    print(f"Problem:           {result['problem']['title']}")
    print(f"Toy examples:      {len(result['examples'])}")
    print(f"Best candidate:    {result['best_candidate_path']}")
    print(f"Overall quality:   {best['overall_quality']:.4f}")
    print(f"Example pass rate: {best['example_pass_rate']:.4f}")
    print(f"Output match rate: {best['output_match_rate']:.4f}")
    print(f"Metrics:           {Path('outputs') / 'metrics.json'}")
    print("=" * 70)


if __name__ == "__main__":
    main()
