import json
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

import agent
import formulate
from prepare import seed_toy_examples

try:
    from ortools.linear_solver import pywraplp
except ImportError:
    pywraplp = None


class PrepareTests(unittest.TestCase):
    def test_seed_toy_examples_from_specs(self) -> None:
        problem = {
            "input_spec": "N M\nA_i B_i",
            "output_spec": "best_score",
        }
        examples = seed_toy_examples(problem, desired=2)
        self.assertEqual(len(examples), 2)
        self.assertTrue(all(example["input_text"] for example in examples))
        self.assertTrue(all(example["expected_output_text"] for example in examples))


@unittest.skipIf(pywraplp is None, "ortools is not installed")
class ReplayAgentTests(unittest.TestCase):
    def test_run_agent_with_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outputs_dir = root / "outputs"
            replay_dir = root / "replay"
            outputs_dir.mkdir(parents=True, exist_ok=True)
            replay_dir.mkdir(parents=True, exist_ok=True)

            problem = {
                "title": "Tiny Knapsack",
                "description": "Choose a subset of items with maximum value and bounded weight.",
                "input_spec": "n capacity\nweight_i value_i",
                "output_spec": "best_value",
                "constraints": "All weights and values are non-negative integers.",
                "objective_hint": "maximize total value",
                "detected_examples": [],
                "parser_hints": {
                    "input_lines": ["n capacity", "weight_i value_i"],
                    "output_lines": ["best_value"],
                    "named_tokens": ["n", "capacity", "weight_i", "value_i"],
                },
                "raw_text": "",
            }
            problem_file = outputs_dir / "problem_extracted.json"
            examples_file = outputs_dir / "toy_examples.json"
            problem_file.write_text(json.dumps(problem, indent=2), encoding="utf-8")

            example_payload = {
                "examples": [
                    {
                        "name": "single_pick",
                        "input_text": "2 3\n1 2\n2 4\n",
                        "expected_output_text": "6",
                        "expected_objective": 6,
                        "explanation": "Both items fit.",
                    },
                    {
                        "name": "capacity_tradeoff",
                        "input_text": "3 4\n2 3\n1 2\n3 4\n",
                        "expected_output_text": "6",
                        "expected_objective": 6,
                        "explanation": "Pick items 0 and 1.",
                    },
                ]
            }

            candidate_code = textwrap.dedent(
                '''
                from typing import Any, Dict, Tuple

                from ortools.linear_solver import pywraplp

                FORMULATION_NAME = "tiny_knapsack"


                def parse_instance(input_text: str) -> Dict[str, Any]:
                    rows = [list(map(int, line.split())) for line in input_text.strip().splitlines() if line.strip()]
                    n, capacity = rows[0]
                    items = [{"weight": row[0], "value": row[1]} for row in rows[1:1 + n]]
                    return {"n": n, "capacity": capacity, "items": items}


                def build_model(instance: Dict[str, Any]) -> Tuple[pywraplp.Solver, Dict[str, Any]]:
                    solver = pywraplp.Solver.CreateSolver("SCIP")
                    if solver is None:
                        raise RuntimeError("Could not create SCIP solver")

                    # Binary choice per item.
                    picks = [solver.IntVar(0, 1, f"x_{i}") for i in range(instance["n"])]

                    # Capacity and redundant bounds for a tighter scored model.
                    solver.Add(
                        solver.Sum(instance["items"][i]["weight"] * picks[i] for i in range(instance["n"]))
                        <= instance["capacity"]
                    )
                    for pick in picks:
                        solver.Add(pick <= 1)
                        solver.Add(pick >= 0)

                    solver.Maximize(
                        solver.Sum(instance["items"][i]["value"] * picks[i] for i in range(instance["n"]))
                    )
                    return solver, {"picks": picks}


                def extract_solution(
                    solver: pywraplp.Solver,
                    instance: Dict[str, Any],
                    context: Dict[str, Any],
                ) -> Dict[str, Any]:
                    chosen = [
                        index
                        for index, pick in enumerate(context["picks"])
                        if pick.solution_value() > 0.5
                    ]
                    objective = int(round(solver.Objective().Value()))
                    return {"selected_items": chosen, "objective_value": objective}


                def format_output(solution: Dict[str, Any]) -> str:
                    return str(solution["objective_value"])


                def describe_formulation(problem: Dict[str, Any]) -> Dict[str, Any]:
                    return {
                        "summary": "Simple 0/1 knapsack with one binary variable per item.",
                        "latex": "\\\\max \\\\sum_i v_i x_i",
                        "assumptions": ["The parsed problem is standard 0/1 knapsack."],
                    }
                '''
            ).strip()

            proposal_payload = {
                "formulation_name": "tiny_knapsack",
                "analysis": "Model the problem as a 0/1 knapsack.",
                "assumptions": ["The problem is standard knapsack."],
                "latex": "\\max \\sum_i v_i x_i",
                "python_code": candidate_code,
            }

            (replay_dir / "01_examples.json").write_text(
                json.dumps(example_payload, indent=2),
                encoding="utf-8",
            )
            (replay_dir / "02_formulation.json").write_text(
                json.dumps(proposal_payload, indent=2),
                encoding="utf-8",
            )

            client = agent.ReplayClient(replay_dir)
            best_candidate = outputs_dir / "best_formulation.py"

            with mock.patch.object(agent, "OUTPUTS_DIR", outputs_dir), \
                mock.patch.object(agent, "RUNS_DIR", outputs_dir / "agent_runs"), \
                mock.patch.object(agent, "BEST_METADATA_FILE", outputs_dir / "best_attempt.json"), \
                mock.patch.object(agent, "AGENT_REPORT_FILE", outputs_dir / "agent_report.md"), \
                mock.patch.object(agent, "BEST_CANDIDATE_FILE", best_candidate), \
                mock.patch.object(formulate, "BEST_CANDIDATE_FILE", best_candidate):
                result = agent.run_agent(
                    problem_file=problem_file,
                    examples_file=examples_file,
                    max_iterations=1,
                    quality_threshold=0.7,
                    min_examples=2,
                    llm_client=client,
                )

            self.assertTrue(examples_file.exists())
            self.assertTrue(best_candidate.exists())
            self.assertEqual(len(result["examples"]), 2)
            self.assertEqual(result["best_evaluation"]["example_pass_rate"], 1.0)
            self.assertEqual(result["best_evaluation"]["output_match_rate"], 1.0)
            self.assertGreater(result["best_evaluation"]["overall_quality"], 0.8)


if __name__ == "__main__":
    unittest.main()
