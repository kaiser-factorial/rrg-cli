"""Q8: What proportion of movies are rated higher by social viewers?"""
import sys; sys.path.insert(0, '.')
from shared import *
from scipy.stats import mannwhitneyu

df = load_data()
rm = rating_matrix(df)
mc = movie_cols(df)
wp = watching_pref_col(df)

results = []
for movie in mc:
    ratings = rm[movie]
    social = ratings[(wp == 0) & ratings.notna()].values
    alone = ratings[(wp == 1) & ratings.notna()].values
    if len(social) >= 2 and len(alone) >= 2:
        # One-tailed: social > alone (same direction as Q7)
        stat, pv = mannwhitneyu(social, alone, alternative='greater')
        results.append({'movie': movie, 'n_social': len(social), 'n_alone': len(alone),
                        'statistic': stat, 'p_value': pv, 'significant': pv < 0.005,
                        'social_mean': social.mean(), 'alone_mean': alone.mean()})

out = pd.DataFrame(results)
save_raw_csv(out, 'Q8_raw.csv')

n_sig = out['significant'].sum()
n_total = len(out)
prop = n_sig / n_total

summary = {
    "question": "What proportion of the 400 movies are rated higher by social viewers than by viewers who prefer watching alone?",
    "n": int(n_total),
    "groups": {"social": "watching_pref==0", "alone": "watching_pref==1"},
    "test": "Mann-Whitney U (one-tailed, greater) per movie",
    "statistic": f"{n_sig}/{n_total} significant at raw p<0.005",
    "p_value": "Proportion-based (see count)",
    "effect_size": None,
    "multiplicity": "Raw p-values reported; no correction applied",
    "conclusion": f"{n_sig} of {n_total} movies ({prop:.2%}) show significantly higher ratings from social viewers at raw p<0.005.",
    "n_significant": int(n_sig),
    "n_tested": int(n_total),
    "proportion": round(float(prop), 4),
    "significant_titles": out[out['significant']]['movie'].tolist()
}
save_summary(summary, 'Q8_summary.json')
print(f"Q8: {n_sig}/{n_total} ({prop:.2%}) significant")
