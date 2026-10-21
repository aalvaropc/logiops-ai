import argparse
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("/tmp/logiops-recovery-ssm.json"))
    args = parser.parse_args()
    rendered = subprocess.check_output(["terraform", f"-chdir={ROOT / 'infra/amazon'}", "output", "-raw", "recovery_setup"], text=True)
    args.output.write_text(json.dumps({"commands": [rendered]}, indent=2) + "\n")
    args.output.chmod(0o600)
    print(f"Prepared Systems Manager parameters: {args.output}")


if __name__ == "__main__":
    main()
