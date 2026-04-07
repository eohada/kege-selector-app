"""
Centralized MMR configuration.
All rating constants are stored here to avoid hardcoded numbers in logic.
"""

from __future__ import annotations


MMR_DEFAULTS: dict[str, object] = {
    # Scale / hidden task weights
    "initial_mmr": 1000.0,
    "min_mmr": 0.0,
    "max_mmr": 2500.0,
    "difficulty_weight": {
        "base": 800.0,
        "standard": 1500.0,
        "hard": 2200.0,
    },
    # Matchmaking window for auto trainer mode
    "match_window": {
        "min_delta": -100.0,
        "max_delta": 200.0,
    },
    # Calibration multipliers: first 5 x3, next 5 x2
    "calibration": {
        "first_stage_tasks": 5,
        "first_stage_multiplier": 3.0,
        "second_stage_tasks": 10,
        "second_stage_multiplier": 2.0,
    },
    # Correct answer modifiers
    "time_coeff_correct": {
        "fast": 1.2,
        "normal": 1.0,
        "slow": 0.7,
    },
    "attempt_coeff_correct": {
        "first_try": 1.0,
        "second_try": 0.5,
        "other_try": 0.5,
    },
    # Wrong answer modifiers (penalties)
    "penalty_coeff_wrong": {
        "blunder_fast": 1.5,   # fast wrong answer
        "long_effort": 0.7,    # long effort + wrong answer
        "default": 1.0,
    },
    # Thresholds used by modifiers
    "thresholds": {
        "blunder_fast_sec": 10,
        "long_effort_sec": 900,
    },
    # Rematch ("Реванш") logic
    "rematch": {
        "trigger_attempts_gte": 2,
        "trigger_time_ratio_gte": 1.5,
        "first_min_days": 3,
        "first_max_days": 4,
        "repeat_error_min_days": 10,
        "repeat_error_max_days": 14,
        "perfect_reward_multiplier": 0.5,
        "repeat_error_penalty_multiplier": 1.5,
    },
    # Telemetry batching
    "telemetry": {
        "batch_interval_sec": 60,
        "idle_timeout_sec": 120,
        "intersection_threshold": 0.6,
    },
}


def get_mmr_config() -> dict[str, object]:
    """
    Return active MMR config.
    A dedicated DB-backed settings table can be plugged in later.
    """
    return MMR_DEFAULTS
