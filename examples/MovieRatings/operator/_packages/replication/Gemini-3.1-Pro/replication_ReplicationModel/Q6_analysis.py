"""Q6: What proportion of movies are rated differently by only-child status?"""
import sys; sys.path.insert(0, '.')
from shared import *
from scipy.stats import ks_2samp

df = load_data()
rm = rating_matrix(df)
mc = movie_cols(df)
oc = only_child_col(df)

results = []
for movie in mc:
    ratings = rm[movie]
    only = ratings[(oc == 1) & ratings.notna()].values
    sibs = ratings[(oc == 0) & ratings.notna()].values
    if len(only) >= 2 and len(sibs) >= 2:
        stat, pv = ks_2samp(only, sibs)
        results.append({'movie': movie, 'n_only': len(only), 'n_siblings': len(sibs),
                        'statistic': stat, 'p_value': pv, 'significant': pv < 0.005})

out = pd.DataFrame(results)
save_raw_csv(out, 'Q6_raw.csv')

n_sig = out['significant'].sum()
n_total = len(out)
prop = n_sig / n_total

summary = {
    "question": "What proportion of the 400 movies are rated differently by only children and viewers with siblings?",
    "n": int(n_total),
    "groups": {"only_child": "only_child==1", "has_siblings": "only_child==0"},
    "test": "Two-sample Kolmogorov-Smirnov per movie",
    "statistic": f"{n_sig}/{n_total} significant at raw p<0.005",
    "p_value": "Proportion-based (see count)",
    "effect_size": None,
    "multiplicity": "Raw p-values reported; no correction applied",
    "conclusion": f"{n_sig} of {n_total} movies ({prop:.2%}) show significant only-child differences at raw p<0.005.",
    "n_significant": int(n_sig),
    "n_tested": int(n_total),
    "proportion": round(float(prop), 4),
    "significant_titles": out[out['significant']]['movie'].tolist()
}
save_summary(summary, 'Q6_summary.json')
print(f"Q6: {n_sig}/{n_total} ({prop:.2%}) significant")
