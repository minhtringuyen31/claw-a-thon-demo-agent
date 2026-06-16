import json
import sys
from dotenv import load_dotenv
from agent.graph import build_graph

load_dotenv()


def run_cli(raw_input: str) -> dict:
    graph = build_graph()
    state = graph.invoke({
        "raw_input": raw_input,
        "requirement": {},
        "plan": {},
        "existing_config": {},
        "operation": "create",
        "json_draft": {},
        "validation_errors": [],
        "final_output": {},
        "retry_count": 0,
        "output_file": "",
    })
    if state["final_output"]:
        return {
            "final_output": state["final_output"],
            "output_file": state["output_file"],
        }
    return {
        "_error": "Validation failed after max retries",
        "_validation_errors": state["validation_errors"],
        "_draft": state["json_draft"],
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Config Agent V2 CLI")
    parser.add_argument("pattern", nargs="*", help="Fraud pattern description (plain text)")
    parser.add_argument("-o", "--output", help="Save result summary to file (e.g. result.json)")
    args = parser.parse_args()

    if args.pattern:
        raw = " ".join(args.pattern)
    else:
        print("Enter fraud pattern (end with Ctrl+D):")
        raw = sys.stdin.read().strip()

    result = run_cli(raw)
    output_str = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_str)
        print(f"Saved to {args.output}")
    else:
        print(output_str)
