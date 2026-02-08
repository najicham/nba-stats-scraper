#!/usr/bin/env python3
"""
Run a Complete Walk-Forward Experiment

Combines training and evaluation in a single command. This is the primary
entry point for running experiments.

Usage:
    # Run experiment A1: Train on 2021-22, evaluate on 2022-23
    PYTHONPATH=. python ml/experiments/run_experiment.py \
        --experiment-id A1 \
        --train-start 2021-11-01 --train-end 2022-06-30 \
        --eval-start 2022-10-01 --eval-end 2023-06-30

    # Run with monthly breakdown
    PYTHONPATH=. python ml/experiments/run_experiment.py \
        --experiment-id A3 \
        --train-start 2021-11-01 --train-end 2024-06-01 \
        --eval-start 2024-10-01 --eval-end 2025-01-29 \
        --monthly-breakdown

Common Experiments:
    A1: Train 2021-22, eval 2022-23 (1 season training)
    A2: Train 2021-23, eval 2023-24 (2 seasons training)
    A3: Train 2021-24, eval 2024-25 (3 seasons training)
    B1: Train 2021-23, eval 2024-25 (older data, skip 2023-24)
    B2: Train 2023-24, eval 2024-25 (recent data only)
    B3: Train 2022-24, eval 2024-25 (2 recent seasons)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
import subprocess
import json
from datetime import datetime

RESULTS_DIR = Path(__file__).parent / "results"


def run_command(cmd: list[str], description: str) -> bool:
    """Run a command and return success status"""
    print(f"\n{'='*60}")
    print(f" {description}")
    print(f"{'='*60}")
    print(f"Command: {' '.join(cmd)}\n")

    result = subprocess.run(cmd, cwd=Path(__file__).parent.parent.parent)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(
        description="Run a complete walk-forward experiment (train + evaluate)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Series A: Training window size
  python run_experiment.py --experiment-id A1 --train-start 2021-11-01 --train-end 2022-06-30 --eval-start 2022-10-01 --eval-end 2023-06-30
  python run_experiment.py --experiment-id A2 --train-start 2021-11-01 --train-end 2023-06-30 --eval-start 2023-10-01 --eval-end 2024-06-30
  python run_experiment.py --experiment-id A3 --train-start 2021-11-01 --train-end 2024-06-01 --eval-start 2024-10-01 --eval-end 2025-01-29

  # Series B: Recency vs volume
  python run_experiment.py --experiment-id B1 --train-start 2021-11-01 --train-end 2023-06-30 --eval-start 2024-10-01 --eval-end 2025-01-29
  python run_experiment.py --experiment-id B2 --train-start 2023-10-01 --train-end 2024-06-01 --eval-start 2024-10-01 --eval-end 2025-01-29
  python run_experiment.py --experiment-id B3 --train-start 2022-10-01 --train-end 2024-06-01 --eval-start 2024-10-01 --eval-end 2025-01-29
        """
    )
    parser.add_argument("--experiment-id", required=True, help="Experiment identifier (e.g., A1, B2, retrain_v10)")
    parser.add_argument("--train-start", required=True, help="Training start date (YYYY-MM-DD)")
    parser.add_argument("--train-end", required=True, help="Training end date (YYYY-MM-DD)")
    parser.add_argument("--eval-start", required=True, help="Evaluation start date (YYYY-MM-DD)")
    parser.add_argument("--eval-end", required=True, help="Evaluation end date (YYYY-MM-DD)")
    parser.add_argument("--min-edge", type=float, default=1.0, help="Minimum edge for betting (default: 1.0)")
    parser.add_argument("--monthly-breakdown", action="store_true", help="Show monthly evaluation breakdown")
    parser.add_argument("--skip-training", action="store_true", help="Skip training, use existing model")
    parser.add_argument("--verbose", action="store_true", help="Show detailed training output")
    args = parser.parse_args()

    print("=" * 70)
    print(f" WALK-FORWARD EXPERIMENT: {args.experiment_id}")
    print("=" * 70)
    print(f"Training:   {args.train_start} to {args.train_end}")
    print(f"Evaluation: {args.eval_start} to {args.eval_end}")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Step 1: Training
    if not args.skip_training:
        train_cmd = [
            "python", "ml/experiments/train_walkforward.py",
            "--train-start", args.train_start,
            "--train-end", args.train_end,
            "--experiment-id", args.experiment_id,
        ]
        if args.verbose:
            train_cmd.append("--verbose")

        if not run_command(train_cmd, "STEP 1: TRAINING"):
            print("\nERROR: Training failed!")
            return 1

    # Find the model file
    model_pattern = f"catboost_v9_exp_{args.experiment_id}_*.cbm"
    model_files = list(RESULTS_DIR.glob(model_pattern))
    if not model_files:
        print(f"\nERROR: No model found matching pattern: {model_pattern}")
        return 1
    model_path = sorted(model_files)[-1]  # Most recent

    # Step 2: Evaluation
    eval_cmd = [
        "python", "ml/experiments/evaluate_model.py",
        "--model-path", str(model_path),
        "--eval-start", args.eval_start,
        "--eval-end", args.eval_end,
        "--experiment-id", args.experiment_id,
        "--min-edge", str(args.min_edge),
    ]
    if args.monthly_breakdown:
        eval_cmd.append("--monthly-breakdown")

    if not run_command(eval_cmd, "STEP 2: EVALUATION"):
        print("\nERROR: Evaluation failed!")
        return 1

    # Summary
    results_path = RESULTS_DIR / f"{args.experiment_id}_results.json"
    if results_path.exists():
        with open(results_path) as f:
            results = json.load(f)

        print("\n" + "=" * 70)
        print(" EXPERIMENT COMPLETE")
        print("=" * 70)

        betting = results.get('results', {}).get('betting', {})
        print(f"""
Experiment: {args.experiment_id}
Training:   {args.train_start} to {args.train_end}
Evaluation: {args.eval_start} to {args.eval_end}

Results:
  MAE:      {results['results']['mae']:.4f}
  Hit Rate: {betting.get('hit_rate_pct', 'N/A')}%
  ROI:      {betting.get('roi_pct', 'N/A')}%
  Bets:     {betting.get('bets_placed', 0)} placed, {betting.get('bets_graded', 0)} graded

Files:
  Model:   {model_path}
  Results: {results_path}

Next: Run 'python ml/experiments/compare_results.py' to see all experiments
""")

    return 0


if __name__ == "__main__":
    sys.exit(main())
