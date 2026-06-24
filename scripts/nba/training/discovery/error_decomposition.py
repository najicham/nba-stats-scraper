"""Error-decomposition — find where the model is systematically wrong (2026-06-23).

A discovery method we've never used: instead of hypothesis-testing hand-built signals,
let the MODEL'S OWN ERRORS name the missing features. residual = actual - predicted on
47K walk-forward CatBoost V12_NOVEG predictions. Any pre-game feature that robustly
predicts the residual is signal the model is leaving on the table = a feature to add.

Two reads:
  (1) Per-feature: Spearman corr with residual + cross-season sign-consistency + BH-FDR.
      MARKET/line-derived features are a POSITIVE CONTROL (V12_NOVEG doesn't see the line,
      so they SHOULD predict residual = "vegas helps", a known result). The interesting
      finds are NON-market PLAYER/CONTEXT features that robustly predict residual.
  (2) Held-out meta-model: LightGBM (features -> residual), trained on 4 seasons and
      scored on the held-out 5th. Held-out R^2 ~ 0 => model well-specified, feature work
      is DONE. R^2 > 0 on NON-market features => exploitable structure remains.

Run: PYTHONPATH=. .venv/bin/python3 scripts/nba/training/discovery/error_decomposition.py
"""

import logging
import numpy as np
import pandas as pd
from scipy import stats

from scripts.nba.training.discovery.data_loader import DiscoveryDataset
from scripts.nba.training.discovery.stats_utils import benjamini_hochberg

logging.basicConfig(level=logging.WARNING, format='%(message)s')

# Features derived from the betting line/market — positive control (V12_NOVEG can't see them).
MARKET_FEATURES = {
    'line_vs_season_avg', 'margin_vs_line_avg_last5', 'line_std', 'line_min', 'line_max',
    'over_odds_median', 'book_count', 'line_movement', 'over_rate_last_10',
    'prop_under_streak', 'prop_over_streak',
}


def main():
    df = DiscoveryDataset(min_edge=0.0).df.copy()
    df['residual'] = df['actual_points'] - df['predicted_points']

    block = {'predicted_points', 'actual_points', 'edge', 'abs_edge', 'correct', 'line',
             'vegas_points_line', 'residual', 'feature_25_value'}
    feats = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])
             and c not in block and df[c].notna().mean() > 0.6]

    print("=" * 90)
    print(f"ERROR DECOMPOSITION — residual = actual - predicted  (N={len(df)}, {len(feats)} features)")
    print("=" * 90)
    print("Model bias (mean residual) by season — confirms calibration:")
    for s, g in df.groupby('season'):
        print(f"  {s}: mean_resid={g['residual'].mean():+.3f}  MAE={g['residual'].abs().mean():.3f}")

    # ---- (1) Per-feature Spearman corr with residual + cross-season consistency ----
    rows = []
    for c in feats:
        sub = df[[c, 'residual', 'season']].dropna()
        if len(sub) < 500:
            continue
        rho, p = stats.spearmanr(sub[c], sub['residual'])
        # cross-season sign consistency
        signs = []
        for s, g in sub.groupby('season'):
            if len(g) >= 200:
                r, _ = stats.spearmanr(g[c], g['residual'])
                signs.append(np.sign(r))
        consistent = max(signs.count(1), signs.count(-1)) if signs else 0
        rows.append({'feature': c, 'rho': rho, 'p': p, 'n': len(sub),
                     'xseason_consistent': consistent, 'n_seasons': len(signs),
                     'market': c in MARKET_FEATURES})
    res = pd.DataFrame(rows)
    _, res['p_adj'] = benjamini_hochberg(res['p'].values, alpha=0.05)
    res['abs_rho'] = res['rho'].abs()
    res = res.sort_values('abs_rho', ascending=False)

    def block_print(title, sub):
        print(f"\n{title}")
        print(f"  {'feature':<26} {'rho':>7} {'p_adj':>9} {'xseason':>8} {'N':>6}")
        for _, r in sub.head(15).iterrows():
            flag = '***' if (r['p_adj'] < 0.05 and r['xseason_consistent'] >= 4) else ''
            print(f"  {r['feature']:<26} {r['rho']:>+7.3f} {r['p_adj']:>9.4f} "
                  f"{int(r['xseason_consistent'])}/{int(r['n_seasons'])}      {int(r['n']):>6} {flag}")

    print("\n" + "-" * 90)
    print("PER-FEATURE residual correlation (*** = FDR-sig AND >=4/5 seasons same sign)")
    print("-" * 90)
    block_print("MARKET features (POSITIVE CONTROL — should predict residual):", res[res['market']])
    block_print("PLAYER/CONTEXT features (THE INTERESTING ONES — missing-feature candidates):",
                res[~res['market']])

    # ---- (2) Held-out meta-model: how much residual structure is learnable? ----
    print("\n" + "=" * 90)
    print("HELD-OUT META-MODEL — LightGBM (features -> residual), leave-one-season-out R^2")
    print("=" * 90)
    try:
        import lightgbm as lgb
    except Exception as e:  # noqa: BLE001
        print(f"  lightgbm unavailable ({e}); skipping meta-model.")
        return

    player_feats = [c for c in feats if c not in MARKET_FEATURES]
    market_feats = [c for c in feats if c in MARKET_FEATURES]
    seasons = sorted(df['season'].unique())

    def loso_r2(use_feats, label):
        r2s, imp_sum = [], pd.Series(0.0, index=use_feats)
        for test_s in seasons:
            tr = df[df['season'] != test_s]
            te = df[df['season'] == test_s]
            Xtr, ytr = tr[use_feats].fillna(0), tr['residual']
            Xte, yte = te[use_feats].fillna(0), te['residual']
            if len(te) < 300:
                continue
            m = lgb.LGBMRegressor(n_estimators=200, max_depth=4, learning_rate=0.05,
                                  num_leaves=15, min_child_samples=50, verbose=-1)
            m.fit(Xtr, ytr)
            pred = m.predict(Xte)
            ss_res = ((yte - pred) ** 2).sum()
            ss_tot = ((yte - yte.mean()) ** 2).sum()
            r2s.append(1 - ss_res / ss_tot)
            imp_sum += pd.Series(m.feature_importances_, index=use_feats)
        r2 = np.mean(r2s) if r2s else float('nan')
        print(f"\n  [{label}] held-out R^2 = {r2:+.4f}  (per-season: {[round(x,3) for x in r2s]})")
        top = imp_sum.sort_values(ascending=False).head(8)
        print(f"    top drivers: {', '.join(f'{k}({int(v)})' for k,v in top.items())}")
        return r2

    r2_all = loso_r2(feats, 'ALL features (incl. market control)')
    r2_player = loso_r2(player_feats, 'PLAYER/CONTEXT only (the real question)')
    r2_market = loso_r2(market_feats, 'MARKET only (positive control)')

    print("\n" + "=" * 90)
    print("VERDICT")
    print("=" * 90)
    print(f"  Market-only R^2={r2_market:+.4f} (control — should be >0: vegas helps, known).")
    print(f"  Player/context-only R^2={r2_player:+.4f}.")
    if r2_player > 0.01:
        print("  ⇒ NON-market structure remains: the model under-exploits player/context features.")
        print("    The top drivers above are the missing-feature candidates worth engineering.")
    else:
        print("  ⇒ ~No learnable non-market residual structure. The 60-feature set is well-specified;")
        print("    feature work is effectively DONE — remaining edge is in SELECTION/signals, not features.")


if __name__ == '__main__':
    main()
