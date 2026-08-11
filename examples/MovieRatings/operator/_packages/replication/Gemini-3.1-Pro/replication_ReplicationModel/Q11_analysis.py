"""Q11: Sensation-seeking score differences per movie."""
import sys; sys.path.insert(0, '.')
from shared import *
from scipy.stats import ks_2samp

df = load_data()
rm = rating_matrix(df)
mc = movie_cols(df)

# Sensation seeking: sum of columns 401-421 (indices 400-420)
ss_cols = sensation_cols(df)
ss_matrix = df[ss_cols].apply(pd.to_numeric, errors='coerce')
ss_score = ss_matrix.sum(axis=1)

# Median split, excluding exactly at median
median_ss = ss_score.median()
above_mask = ss_score > median_ss
below_mask = ss_score < median_ss

results = []
for movie in mc:
    ratings = rm[movie]
    above = ratings[above_mask & ratings.notna()].values
    below = ratings[below_mask & ratings.notna()].values
    if len(above) >= 2 and len(below) >= 2:
        stat, pv = ks_2samp(above, below)
        results.append({'movie': movie, 'n_above': len(above), 'n_below': len(below),
                        'statistic': stat, 'p_value': pv, 'significant': pv < 0.005})

out = pd.DataFrame(results)
save_raw_csv(out, 'Q11_raw.csv')

n_sig = out['significant'].sum()
n_total = len(out)
prop = n_sig / n_total

summary = {
    "question": "Which movies are rated differently by participants above versus below the median sensation-seeking score?",
    "n": int(n_total),
    "groups": {"above_median_ss": f"ss_score>{median_ss}", "below_median_ss": f"ss_score<{median_ss}"},
    "test": "Two-sample Kolmogorov-Smirnov per movie",
    "statistic": f"{n_sig}/{n_total} significant at raw p<0.005",
    "p_value": "Per-movie (see raw CSV)",
    "effect_size": None,
    "multiplicity": "Raw p-values reported; no correction applied",
    "conclusion": f"{n_sig} of {n_total} movies ({prop:.2%}) show significant differences between high and low sensation seekers at raw p<0.005.",
    "n_significant": int(n_sig),
    "n_tested": int(n_total),
    "proportion": round(float(prop), 4),
    "median_ss_score": float(median_ss),
    "significant_titles": out[out['significant']]['movie'].tolist()
}
save_summary(summary, 'Q11_summary.json')
print(f"Q11: {n_sig}/{n_total} ({prop:.2%}) significant, median SS={median_ss}")
