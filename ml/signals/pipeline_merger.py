"""Pipeline merger for per-model best bets.

Session 443: Pools candidates from all model pipelines, applies
team cap, rescue cap, volume cap, and first-occurrence player dedup.
Sorts by composite_score (reuses aggregator's validated ranking).

The merge layer sits between per-model aggregator runs and the final
signal_best_bets_picks output. Each model's pipeline produces candidates
independently (with all negative filters and composite scoring applied),
and this module selects the final slate from the combined pool.
"""

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

MAX_MERGED_PICKS_PER_DAY = 15
MAX_PICKS_PER_TEAM = 2
MAX_PICKS_PER_GAME = 3  # Session 452: Mar 8 had 3 losses from SAS-HOU game
RESCUE_CAP_PCT = 0.40
# Session 452: Single source of truth for algorithm version.
# aggregator.py imports this constant — bump here for all changes.
ALGORITHM_VERSION = 'v453_slate_observations'

# Rescue signal priority weights — mirrors aggregator.RESCUE_SIGNAL_PRIORITY.
# When rescue cap trims, drop lowest-priority rescues first (ascending sort).
RESCUE_SIGNAL_PRIORITY: Dict[str, int] = {
    'high_scoring_environment_over': 3,
    'sharp_book_lean_over': 2,
    'home_under': 2,
    'combo_3way': 1,
    'combo_he_ms': 1,
}


# ------------------------------------------------------------------
# Pipeline agreement computation
# ------------------------------------------------------------------

def _compute_pipeline_agreement(
    pool: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Compute per-player agreement stats across model pipelines.

    For each player_lookup, counts how many distinct model pipelines
    nominated them and tracks direction agreement (OVER vs UNDER).

    Returns:
        Dict keyed by player_lookup with:
            - models: set of source_pipeline IDs
            - directions: dict of direction -> set of source_pipeline IDs
            - direction_conflict_count: number of models on minority direction
    """
    player_info: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {'models': set(), 'directions': defaultdict(set)}
    )

    for pick in pool:
        player = pick.get('player_lookup', '')
        model = pick.get('source_pipeline', 'unknown')
        direction = pick.get('recommendation', '')

        player_info[player]['models'].add(model)
        if direction:
            player_info[player]['directions'][direction].add(model)

    # Compute direction conflict count for each player
    result: Dict[str, Dict[str, Any]] = {}
    for player, info in player_info.items():
        direction_counts = {
            d: len(models) for d, models in info['directions'].items()
        }
        if len(direction_counts) <= 1:
            conflict_count = 0
        else:
            # Conflict = count of models on the minority direction
            sorted_counts = sorted(direction_counts.values(), reverse=True)
            conflict_count = sum(sorted_counts[1:])  # everything except majority

        result[player] = {
            'models': info['models'],
            'directions': dict(info['directions']),
            'direction_conflict_count': conflict_count,
        }

    return result


# ------------------------------------------------------------------
# Merge tagging
# ------------------------------------------------------------------

def _tag_candidate(
    pick: Dict[str, Any],
    agreement_info: Dict[str, Dict[str, Any]],
    was_selected: bool,
    selection_reason: str,
    merge_rank: Optional[int],
) -> None:
    """Tag a candidate pick with merge metadata (mutates in place).

    Every candidate — whether selected or rejected — gets tagged so
    that model_bb_candidates has full provenance.
    """
    player = pick.get('player_lookup', '')
    info = agreement_info.get(player, {
        'models': set(),
        'direction_conflict_count': 0,
    })

    pick['pipeline_agreement_count'] = len(info.get('models', set()))
    pick['pipeline_agreement_models'] = sorted(info.get('models', set()))
    pick['direction_conflict_count'] = info.get('direction_conflict_count', 0)
    pick['was_selected'] = was_selected
    pick['selection_reason'] = selection_reason
    pick['merge_rank'] = merge_rank
    pick['algorithm_version'] = ALGORITHM_VERSION


# ------------------------------------------------------------------
# Core merge logic
# ------------------------------------------------------------------

def merge_model_pipelines(
    model_candidates: Dict[str, List[Dict[str, Any]]],
    max_picks: int = MAX_MERGED_PICKS_PER_DAY,
    max_per_team: int = MAX_PICKS_PER_TEAM,
    max_per_game: int = MAX_PICKS_PER_GAME,
    rescue_cap_pct: float = RESCUE_CAP_PCT,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Pool all model candidates, rank, dedup, apply constraints.

    This is the merge layer for per-model best bets pipelines. Each
    model's aggregator produces an independent candidate list (with all
    negative filters and composite scoring already applied). This function
    unions them, deduplicates by player, and applies cross-model constraints
    (team cap, rescue cap, volume cap).

    Args:
        model_candidates: system_id -> list of candidate picks from
            that model's pipeline. Each pick must have at least:
            - player_lookup (str)
            - team_abbr (str)
            - composite_score (float)
            - recommendation (str): 'OVER' or 'UNDER'
            - source_pipeline (str): model system_id
            Optionally:
            - signal_rescued (bool)
            - rescue_signal (str)

        max_picks: Maximum picks in merged output (volume cap).
        max_per_team: Maximum picks per team (team cap).
        rescue_cap_pct: Maximum fraction of selected picks that can be
            rescued. Minimum 1 rescue always kept.

    Returns:
        Tuple of:
            - selected_picks: List of picks that survived merge, sorted
              by composite_score DESC, with merge_rank assigned 1-based.
            - merge_summary: Dict with merge statistics for logging and
              audit.
    """
    # ---- 1. Pool all candidates ----
    pool: List[Dict[str, Any]] = []
    per_model_counts: Dict[str, int] = {}

    for model_id, candidates in model_candidates.items():
        per_model_counts[model_id] = len(candidates)
        pool.extend(candidates)

    total_candidates = len(pool)
    models_contributing = len([
        m for m, c in per_model_counts.items() if c > 0
    ])

    if not pool:
        logger.info("Pipeline merger: no candidates from any model")
        return [], _build_summary(
            total_candidates=0,
            unique_players=0,
            models_contributing=0,
            per_model_counts=per_model_counts,
            selected=[],
            rejection_counts={},
            agreement_info={},
        )

    # ---- 2. Compute pipeline agreement ----
    agreement_info = _compute_pipeline_agreement(pool)
    unique_players = len(agreement_info)

    logger.info(
        f"Pipeline merger: {total_candidates} candidates from "
        f"{models_contributing} models, {unique_players} unique players"
    )

    # ---- 3. Sort by composite_score DESC ----
    pool.sort(key=lambda p: p.get('composite_score', 0), reverse=True)

    # ---- 4. Walk sorted list with constraints ----
    selected: List[Dict[str, Any]] = []
    seen_players: set = set()
    team_counts: Dict[str, int] = defaultdict(int)
    game_counts: Dict[str, int] = defaultdict(int)
    rescue_count = 0

    rejection_counts: Dict[str, int] = defaultdict(int)

    for pick in pool:
        player = pick.get('player_lookup', '')
        team = pick.get('team_abbr', '')
        game_id = pick.get('game_id', '')
        is_rescued = bool(pick.get('signal_rescued'))

        # --- Player dedup: first occurrence wins ---
        if player in seen_players:
            _tag_candidate(pick, agreement_info, False, 'player_dedup', None)
            rejection_counts['player_dedup'] += 1
            continue

        # --- Team cap ---
        if team and team_counts[team] >= max_per_team:
            _tag_candidate(pick, agreement_info, False, 'team_cap', None)
            rejection_counts['team_cap'] += 1
            logger.info(
                f"Merge team cap: dropping {player} ({team}, "
                f"#{team_counts[team] + 1} pick) "
                f"composite={pick.get('composite_score', 0):.2f}"
            )
            # Mark player as seen so duplicate entries don't get a second
            # chance via a different model's lower-composite candidate.
            seen_players.add(player)
            continue

        # --- Game cap (Session 452) ---
        # Mar 8: 3 picks from SAS-HOU game, all lost. Team cap (2/team)
        # didn't help because picks were on different teams in the same game.
        if game_id and game_counts[game_id] >= max_per_game:
            _tag_candidate(pick, agreement_info, False, 'game_cap', None)
            rejection_counts['game_cap'] += 1
            logger.info(
                f"Merge game cap: dropping {player} (game {game_id}, "
                f"#{game_counts[game_id] + 1} pick) "
                f"composite={pick.get('composite_score', 0):.2f}"
            )
            seen_players.add(player)
            continue

        # --- Volume cap ---
        if len(selected) >= max_picks:
            _tag_candidate(pick, agreement_info, False, 'volume_cap', None)
            rejection_counts['volume_cap'] += 1
            seen_players.add(player)
            continue

        # --- Rescue cap ---
        # Minimum 1 rescue always kept (matches aggregator behavior).
        if is_rescued:
            max_rescue = max(1, int(len(selected) * rescue_cap_pct)) if selected else 1
            if rescue_count >= max_rescue:
                _tag_candidate(pick, agreement_info, False, 'rescue_cap', None)
                rejection_counts['rescue_cap'] += 1
                logger.info(
                    f"Merge rescue cap: dropping {player} "
                    f"composite={pick.get('composite_score', 0):.2f} "
                    f"rescue={pick.get('rescue_signal', '?')} "
                    f"priority={RESCUE_SIGNAL_PRIORITY.get(pick.get('rescue_signal', ''), 0)}"
                )
                seen_players.add(player)
                continue

        # --- Select this pick ---
        rank = len(selected) + 1
        _tag_candidate(pick, agreement_info, True, 'selected', rank)

        selected.append(pick)
        seen_players.add(player)
        team_counts[team] += 1
        if game_id:
            game_counts[game_id] += 1
        if is_rescued:
            rescue_count += 1

    # Tag any remaining pool entries that weren't visited
    # (volume cap stops the loop early via continue, but these are
    # candidates from already-seen players that appear later in the pool)
    for pick in pool:
        if 'was_selected' not in pick:
            player = pick.get('player_lookup', '')
            if player in seen_players:
                _tag_candidate(pick, agreement_info, False, 'player_dedup', None)
                rejection_counts['player_dedup'] += 1
            else:
                # Player never reached in the walk (volume cap hit first)
                _tag_candidate(pick, agreement_info, False, 'volume_cap', None)
                rejection_counts['volume_cap'] += 1
                seen_players.add(player)

    # ---- 5. Tag slate-level observations ----
    slate_obs = _compute_slate_observations(selected, game_counts)
    for pick in selected:
        pick['slate_observation_tags'] = slate_obs['tags']

    # ---- 6. Build summary ----
    summary = _build_summary(
        total_candidates=total_candidates,
        unique_players=unique_players,
        models_contributing=models_contributing,
        per_model_counts=per_model_counts,
        selected=selected,
        rejection_counts=dict(rejection_counts),
        agreement_info=agreement_info,
        slate_observations=slate_obs,
    )

    logger.info(
        f"Pipeline merger: selected {len(selected)} picks "
        f"(OVER={summary['direction_over']}, UNDER={summary['direction_under']}), "
        f"rejected: {dict(rejection_counts)}"
    )

    return selected, summary


# ------------------------------------------------------------------
# Slate-level observations (Session 453)
# ------------------------------------------------------------------

# Thresholds for slate observations — all observation-only (no blocking).
DIRECTIONAL_LEAN_THRESHOLD = 0.80  # >80% same direction = observation
SAME_GAME_SAME_DIR_MIN = 2         # 2+ picks from same game in same direction
CONCENTRATED_GAME_THRESHOLD = 3    # 3+ picks from any single game


def _compute_slate_observations(
    selected: List[Dict[str, Any]],
    game_counts: Dict[str, int],
) -> Dict[str, Any]:
    """Compute slate-level structural observations on the merged slate.

    These are pure observation tags — they do NOT block picks. They flag
    slate-level risks that per-pick filters can't detect:
    - Directional lean (>80% OVER or UNDER)
    - Same-game same-direction concentration
    - Heavy concentration in a single game

    Returns:
        Dict with 'tags' (list of observation strings) and detail fields.
    """
    if not selected:
        return {'tags': [], 'detail': {}}

    tags: List[str] = []
    detail: Dict[str, Any] = {}

    total = len(selected)

    # --- Directional lean ---
    over_count = sum(1 for p in selected if p.get('recommendation') == 'OVER')
    under_count = total - over_count
    over_pct = over_count / total if total else 0
    under_pct = under_count / total if total else 0

    if over_pct >= DIRECTIONAL_LEAN_THRESHOLD and total >= 5:
        tags.append('slate_heavy_over_lean')
        detail['over_pct'] = round(over_pct * 100, 1)
        logger.info(
            f"Slate obs: heavy OVER lean — {over_count}/{total} "
            f"({detail['over_pct']}%) picks are OVER"
        )
    elif under_pct >= DIRECTIONAL_LEAN_THRESHOLD and total >= 5:
        tags.append('slate_heavy_under_lean')
        detail['under_pct'] = round(under_pct * 100, 1)
        logger.info(
            f"Slate obs: heavy UNDER lean — {under_count}/{total} "
            f"({detail['under_pct']}%) picks are UNDER"
        )

    # --- Same-game same-direction concentration ---
    game_direction: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for p in selected:
        gid = p.get('game_id', '')
        direction = p.get('recommendation', '')
        if gid and direction:
            game_direction[gid][direction] += 1

    for gid, dirs in game_direction.items():
        for direction, count in dirs.items():
            if count >= SAME_GAME_SAME_DIR_MIN:
                tags.append('slate_same_game_same_dir')
                detail.setdefault('same_game_same_dir', []).append({
                    'game_id': gid,
                    'direction': direction,
                    'count': count,
                })
                logger.info(
                    f"Slate obs: {count} {direction} picks from game {gid}"
                )

    # --- Heavy game concentration ---
    for gid, count in game_counts.items():
        if count >= CONCENTRATED_GAME_THRESHOLD:
            tags.append('slate_game_concentration')
            detail.setdefault('concentrated_games', []).append({
                'game_id': gid,
                'count': count,
            })
            logger.info(
                f"Slate obs: {count} picks from game {gid} (max={MAX_PICKS_PER_GAME})"
            )

    if tags:
        logger.info(f"Slate observations: {tags}")
    else:
        logger.info("Slate observations: none")

    return {'tags': tags, 'detail': detail}


# ------------------------------------------------------------------
# Summary builder
# ------------------------------------------------------------------

def _build_summary(
    total_candidates: int,
    unique_players: int,
    models_contributing: int,
    per_model_counts: Dict[str, int],
    selected: List[Dict[str, Any]],
    rejection_counts: Dict[str, int],
    agreement_info: Dict[str, Dict[str, Any]],
    slate_observations: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build merge_summary dict with statistics for logging and audit.

    Returns:
        Dict with keys: total_candidates, unique_players,
        models_contributing, per_model_counts, selected_count,
        rejection_counts, direction_over, direction_under,
        avg_agreement_selected, avg_agreement_rejected,
        algorithm_version, slate_observations.
    """
    direction_over = sum(
        1 for p in selected if p.get('recommendation') == 'OVER'
    )
    direction_under = sum(
        1 for p in selected if p.get('recommendation') == 'UNDER'
    )

    # Average pipeline agreement for selected vs rejected
    selected_players = {p.get('player_lookup') for p in selected}
    selected_agreements = [
        len(info.get('models', set()))
        for player, info in agreement_info.items()
        if player in selected_players
    ]
    rejected_agreements = [
        len(info.get('models', set()))
        for player, info in agreement_info.items()
        if player not in selected_players
    ]

    avg_agreement_selected = (
        sum(selected_agreements) / len(selected_agreements)
        if selected_agreements else 0.0
    )
    avg_agreement_rejected = (
        sum(rejected_agreements) / len(rejected_agreements)
        if rejected_agreements else 0.0
    )

    return {
        'total_candidates': total_candidates,
        'unique_players': unique_players,
        'models_contributing': models_contributing,
        'per_model_counts': per_model_counts,
        'selected_count': len(selected),
        'rejection_counts': rejection_counts,
        'direction_over': direction_over,
        'direction_under': direction_under,
        'avg_agreement_selected': round(avg_agreement_selected, 2),
        'avg_agreement_rejected': round(avg_agreement_rejected, 2),
        'algorithm_version': ALGORITHM_VERSION,
        'slate_observations': slate_observations or {'tags': [], 'detail': {}},
    }
