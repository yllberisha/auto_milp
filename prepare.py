"""
PDF parsing and problem extraction for auto_milp.

Usage:
    python prepare.py --pdf <path_to_pdf>   # Extract problem structure
    python prepare.py --dump-examples       # Show detected or seeded examples
"""

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import pdfplumber
except ImportError:
    pdfplumber = None


CACHE_DIR = Path.home() / ".cache" / "auto_milp"
PROBLEMS_DIR = Path(__file__).parent / "problems"
OUTPUTS_DIR = Path(__file__).parent / "outputs"
PROBLEM_EXTRACTED_FILE = OUTPUTS_DIR / "problem_extracted.json"
TOY_EXAMPLES_FILE = OUTPUTS_DIR / "toy_examples.json"

CACHE_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
PROBLEMS_DIR.mkdir(parents=True, exist_ok=True)

SECTION_HEADERS = [
    (re.compile(r"^\s*(problem|statement|description)\s*:?\s*$", re.IGNORECASE), "description"),
    (re.compile(r"^\s*(input|input format|input file)\s*:?\s*$", re.IGNORECASE), "input_spec"),
    (re.compile(r"^\s*(output|output format|output file)\s*:?\s*$", re.IGNORECASE), "output_spec"),
    (re.compile(r"^\s*(constraint|constraints|limits?)\s*:?\s*$", re.IGNORECASE), "constraints"),
    (re.compile(r"^\s*(objective|goal|score)\s*:?\s*$", re.IGNORECASE), "objective_hint"),
    (re.compile(r"^\s*(example|examples|sample|samples)\s*:?\s*$", re.IGNORECASE), "example"),
]
EXAMPLE_MARKER = re.compile(r"^\s*(example|sample)(?:\s+\d+)?\s*:?\s*$", re.IGNORECASE)
EXAMPLE_PART_HEADER = re.compile(r"^\s*(input|output|explanation)\s*:?\s*$", re.IGNORECASE)
TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _clean_text(text: Optional[str]) -> str:
    if text is None:
        return ""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _non_empty_lines(text: str) -> List[str]:
    return [line.strip() for line in _clean_text(text).splitlines() if line.strip()]


def _match_section_header(line: str) -> Optional[str]:
    for pattern, section_name in SECTION_HEADERS:
        if pattern.fullmatch(line.strip()):
            return section_name
    return None


def _split_sections(text: str) -> Dict[str, List[str]]:
    lines = _clean_text(text).splitlines()
    if not lines:
        return {}

    sections: Dict[str, List[str]] = {"description": []}
    current_section = "description"
    for raw_line in lines[1:]:
        section_name = _match_section_header(raw_line)
        if section_name is not None:
            current_section = section_name
            sections.setdefault(current_section, [])
            continue
        sections.setdefault(current_section, []).append(raw_line.rstrip())
    return sections


def _split_example_blocks(text: str) -> List[str]:
    lines = _clean_text(text).splitlines()
    if not lines:
        return []

    blocks: List[str] = []
    current: List[str] = []
    seen_marker = False
    for line in lines:
        if EXAMPLE_MARKER.fullmatch(line.strip()):
            if current:
                blocks.append("\n".join(current).strip())
                current = []
            seen_marker = True
            continue
        if seen_marker:
            current.append(line.rstrip())

    if current:
        blocks.append("\n".join(current).strip())

    if blocks:
        return [block for block in blocks if block]

    stripped = "\n".join(line.rstrip() for line in lines).strip()
    return [stripped] if stripped else []


def _contains_example_marker(text: str) -> bool:
    return any(EXAMPLE_MARKER.fullmatch(line.strip()) for line in _clean_text(text).splitlines())


def _parse_example_block(block: str, index: int) -> Optional[Dict[str, Any]]:
    current_section: Optional[str] = None
    parts: Dict[str, List[str]] = {"input": [], "output": [], "explanation": []}

    for line in _clean_text(block).splitlines():
        match = EXAMPLE_PART_HEADER.fullmatch(line.strip())
        if match:
            current_section = match.group(1).lower()
            continue
        if current_section is not None:
            parts[current_section].append(line.rstrip())

    if not parts["input"] and not parts["output"]:
        chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n", block) if chunk.strip()]
        if len(chunks) >= 2:
            parts["input"] = chunks[0].splitlines()
            parts["output"] = chunks[1].splitlines()

    input_text = "\n".join(parts["input"]).strip()
    output_text = "\n".join(parts["output"]).strip()
    if not input_text and not output_text:
        return None

    return {
        "name": f"detected_example_{index}",
        "source": "pdf",
        "input_text": input_text,
        "expected_output_text": output_text,
        "explanation": "\n".join(parts["explanation"]).strip(),
    }


def extract_examples_from_problem(problem: Dict[str, Any]) -> List[Dict[str, Any]]:
    examples = problem.get("toy_examples") or problem.get("detected_examples") or []
    normalized: List[Dict[str, Any]] = []
    for idx, example in enumerate(examples, start=1):
        if not isinstance(example, dict):
            continue
        input_text = _clean_text(example.get("input_text")).strip()
        output_text = _clean_text(example.get("expected_output_text")).strip()
        if not input_text and not output_text:
            continue
        normalized.append(
            {
                "name": example.get("name") or f"example_{idx}",
                "source": example.get("source", "unknown"),
                "input_text": input_text,
                "expected_output_text": output_text,
                "expected_objective": example.get("expected_objective"),
                "explanation": _clean_text(example.get("explanation")).strip(),
            }
        )
    return normalized


def _placeholder_line_from_spec(line: str, seed: int) -> str:
    tokens = TOKEN_PATTERN.findall(line)
    if not tokens:
        digits = re.findall(r"\d+", line)
        return " ".join(digits[:6]) if digits else str(max(1, seed))

    values: List[str] = []
    next_value = max(1, seed)
    for _token in tokens[:6]:
        values.append(str(next_value))
        next_value += 1
    return " ".join(values) if values else str(max(1, seed))


def seed_toy_examples(problem: Dict[str, Any], desired: int = 3) -> List[Dict[str, Any]]:
    existing = extract_examples_from_problem(problem)
    if existing:
        return existing[:desired]

    input_lines = _non_empty_lines(problem.get("input_spec", ""))[:3]
    output_lines = _non_empty_lines(problem.get("output_spec", ""))[:2]
    if not input_lines:
        input_lines = ["N", "values"]
    if not output_lines:
        output_lines = ["best_answer"]

    examples: List[Dict[str, Any]] = []
    for idx in range(1, desired + 1):
        input_text = "\n".join(_placeholder_line_from_spec(line, idx) for line in input_lines)
        output_text = "\n".join(_placeholder_line_from_spec(line, idx) for line in output_lines[:1])
        examples.append(
            {
                "name": f"seed_example_{idx}",
                "source": "heuristic",
                "input_text": input_text,
                "expected_output_text": output_text,
                "expected_objective": None,
                "explanation": (
                    "Heuristic seed example derived from the input/output specification. "
                    "Replace or refine it with an LLM-generated toy case when possible."
                ),
            }
        )
    return examples


def save_examples(examples: List[Dict[str, Any]], output_file: Path = TOY_EXAMPLES_FILE) -> Path:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as handle:
        json.dump(examples, handle, indent=2)
    return output_file


def load_examples(
    examples_file: Path = TOY_EXAMPLES_FILE,
    problem: Optional[Dict[str, Any]] = None,
    desired: int = 3,
    allow_seed: bool = True,
) -> List[Dict[str, Any]]:
    if examples_file.exists():
        with open(examples_file, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, list):
            normalized = extract_examples_from_problem({"toy_examples": data})
            if normalized:
                return normalized

    if problem is None:
        problem = load_problem()

    examples = extract_examples_from_problem(problem)
    if examples:
        return examples
    return seed_toy_examples(problem, desired=desired) if allow_seed else []


def _build_parser_hints(input_spec: str, output_spec: str) -> Dict[str, Any]:
    input_lines = _non_empty_lines(input_spec)
    output_lines = _non_empty_lines(output_spec)
    tokens = sorted(
        {
            token
            for token in TOKEN_PATTERN.findall("\n".join(input_lines + output_lines))
            if len(token) > 1
        }
    )
    return {
        "input_lines": input_lines[:8],
        "output_lines": output_lines[:8],
        "named_tokens": tokens[:30],
    }


class PDFExtractor:
    """Extract problem structure from optimization problem PDFs."""

    def __init__(self, pdf_path: str):
        if pdfplumber is None:
            raise ImportError("pdfplumber is required. Install the project dependencies first.")

        self.pdf_path = Path(pdf_path)
        if not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        self.problem_text = self._extract_text()
        self.problem_dict: Dict[str, Any] = {}

    def _extract_text(self) -> str:
        pages: List[str] = []
        with pdfplumber.open(self.pdf_path) as pdf:
            for page in pdf.pages:
                pages.append(page.extract_text() or "")
        return "\n".join(pages)

    def extract_structure(self) -> Dict[str, Any]:
        sections = _split_sections(self.problem_text)
        lines = [line.strip() for line in _clean_text(self.problem_text).splitlines() if line.strip()]
        title = lines[0] if lines else self.pdf_path.stem

        example_blocks = _split_example_blocks("\n".join(sections.get("example", [])))
        if not example_blocks and _contains_example_marker(self.problem_text):
            example_blocks = _split_example_blocks(self.problem_text)
        detected_examples = [
            parsed
            for idx, block in enumerate(example_blocks, start=1)
            if (parsed := _parse_example_block(block, idx)) is not None
        ]

        self.problem_dict = {
            "title": title,
            "description": "\n".join(sections.get("description", [])).strip(),
            "input_spec": "\n".join(sections.get("input_spec", [])).strip(),
            "output_spec": "\n".join(sections.get("output_spec", [])).strip(),
            "constraints": "\n".join(sections.get("constraints", [])).strip(),
            "objective_hint": "\n".join(sections.get("objective_hint", [])).strip(),
            "example": "\n".join(sections.get("example", [])).strip(),
            "detected_examples": detected_examples,
            "parser_hints": _build_parser_hints(
                "\n".join(sections.get("input_spec", [])),
                "\n".join(sections.get("output_spec", [])),
            ),
            "raw_text": self.problem_text,
        }
        return self.problem_dict

    def save(self, output_file: Path = PROBLEM_EXTRACTED_FILE) -> Path:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as handle:
            json.dump(self.problem_dict, handle, indent=2)
        return output_file


def load_problem(problem_file: Path = PROBLEM_EXTRACTED_FILE) -> Dict[str, Any]:
    with open(problem_file, "r", encoding="utf-8") as handle:
        return json.load(handle)


class ModelValidator:
    """Validation helpers shared by the formulation harness and the agent."""

    @staticmethod
    def check_syntax(model_code: str) -> Tuple[bool, str]:
        try:
            compile(model_code, "<candidate>", "exec")
            return True, ""
        except SyntaxError as exc:
            return False, f"{exc.msg} (line {exc.lineno})"

    @staticmethod
    def estimate_constraint_strength(num_vars: int, num_constraints: int) -> float:
        if num_vars <= 0:
            return 0.0
        ratio = min(num_constraints / max(1, num_vars), 5.0) / 5.0
        return float(ratio)

    @staticmethod
    def normalize_output(text: Optional[str]) -> str:
        lines = [line.rstrip() for line in _clean_text(text).splitlines()]
        return "\n".join(line for line in lines if line or len(lines) == 1).strip()


class EvaluationMetrics:
    """Composite scoring helpers for formulation candidates."""

    @staticmethod
    def compute_code_clarity(model_code: str) -> float:
        non_empty_lines = [line for line in model_code.splitlines() if line.strip()]
        if not non_empty_lines:
            return 0.0
        comment_lines = sum(1 for line in non_empty_lines if line.strip().startswith("#"))
        docstring_hits = model_code.count('"""') // 2 + model_code.count("'''") // 2
        density = (comment_lines + docstring_hits) / max(1, len(non_empty_lines))
        return min(1.0, 0.45 + 0.8 * density)

    @staticmethod
    def combine_scores(
        validity_score: float,
        correctness_score: float,
        constraint_strength: float,
        code_clarity: float,
        formulation_time: float,
    ) -> Dict[str, float]:
        overall = (
            0.35 * validity_score
            + 0.35 * correctness_score
            + 0.2 * constraint_strength
            + 0.1 * code_clarity
        )
        return {
            "validity_score": float(validity_score),
            "correctness_score": float(correctness_score),
            "constraint_strength": float(constraint_strength),
            "code_clarity": float(code_clarity),
            "overall_quality": float(overall),
            "formulation_time": float(formulation_time),
        }


def generate_latex_skeleton(problem_title: str, problem_desc: str) -> str:
    return f"""\\documentclass{{article}}
\\usepackage{{amsmath}}
\\usepackage{{amssymb}}

\\title{{{problem_title}}}
\\author{{auto\\_milp}}
\\date{{\\today}}

\\begin{{document}}
\\maketitle

\\section{{Problem Description}}
{problem_desc}

\\section{{Mathematical Formulation}}

\\subsection{{Variables}}
% Candidate should define variables here.

\\subsection{{Objective Function}}
\\begin{{equation}}
\\min \\text{{(objective)}}
\\end{{equation}}

\\subsection{{Constraints}}
\\begin{{align}}
% Candidate should add constraints here.
\\end{{align}}

\\end{{document}}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="auto_milp problem extraction")
    parser.add_argument("--pdf", type=str, help="Path to the PDF problem statement")
    parser.add_argument("--dump-examples", action="store_true", help="Print detected or seeded examples")
    parser.add_argument("--list-metrics", action="store_true", help="Show evaluation metrics")
    args = parser.parse_args()

    if args.list_metrics:
        print("Available evaluation metrics:")
        print("  - validity_score")
        print("  - correctness_score")
        print("  - constraint_strength")
        print("  - code_clarity")
        print("  - overall_quality")
        return

    if args.pdf:
        extractor = PDFExtractor(args.pdf)
        problem = extractor.extract_structure()
        extractor.save()
        examples = extract_examples_from_problem(problem)
        if examples:
            save_examples(examples)
        print(f"Problem extracted to {PROBLEM_EXTRACTED_FILE}")
        print(f"Title: {problem['title']}")
        print(f"Detected examples: {len(examples)}")
        if not examples:
            seeded = seed_toy_examples(problem)
            save_examples(seeded)
            print(f"Seeded toy examples: {len(seeded)}")
        return

    if args.dump_examples:
        problem = load_problem()
        examples = load_examples(problem=problem)
        print(json.dumps(examples, indent=2))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
