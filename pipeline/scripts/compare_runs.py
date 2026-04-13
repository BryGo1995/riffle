# pipeline/scripts/compare_runs.py
"""Compare evaluation metrics between two MLflow training runs.

Usage:
  python pipeline/scripts/compare_runs.py <run_id_A> <run_id_B>

Prints a side-by-side metrics table with deltas and a recommendation.
Works with any two runs that have eval_ metrics logged (i.e., runs
trained with holdout_days > 0).
"""

import argparse
import os
import sys

sys.path.insert(0, "pipeline")
os.environ.setdefault("MLFLOW_TRACKING_URI", "http://localhost:5000")

from plugins.ml.evaluate import compare_runs


def main():
    parser = argparse.ArgumentParser(
        description="Compare evaluation metrics between two MLflow runs"
    )
    parser.add_argument("run_id_a", help="MLflow run ID for the baseline (Run A)")
    parser.add_argument("run_id_b", help="MLflow run ID for the candidate (Run B)")
    args = parser.parse_args()

    print(compare_runs(args.run_id_a, args.run_id_b))


if __name__ == "__main__":
    main()
