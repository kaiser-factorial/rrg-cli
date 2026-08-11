"""Q4: What proportion of 400 movies are rated differently by gender?"""
import sys; sys.path.insert(0, '.')
from shared import *
from scipy.stats import ks_2samp

df = load_data()
rm = rating_matrix(df)
mc = movie_cols(df)
gen = gender_col(df)

results = []
for movie in mc:
    ratings = rm[movie]
    fem = ratings[(gen == 1) & ratings.notna()].values
    mal = ratings[(gen == 2) & ratings.notna()].values
    if len(fem) >= 2 and len(mal) >= 2:
        stat, pv = ks_2samp(fem, mal)
        results.append({'movie': movie, 'n_female': len(fem), 'n_male': len(mal),
                        'statistic': stat, 'p_value': pv, 'significant': pv < 0.005})

out = pd.DataFrame(results)
save_raw_csv(out, 'Q4_raw.csv')

n_sig = out['significant'].sum()
n_total = len(out)
prop = n_sig / n_total

summary = {
    "question": "What proportion of the 400 movies are rated differently by male and female viewers?",
    "n": int(n_total),
    "groups": {"female": "gender==1", "male": "gender==2"},
    "test": "Two-sample Kolmogorov-Smirnov per movie",
    "statistic": f"{n_sig}/{n_total} significant at raw p<0.005",
    "p_value": "Proportion-based (see count)",
    "effect_size": None,
    "multiplicity": "Raw p-values reported; no correction applied",
    "conclusion": f"{n_sig} of {n_total} movies ({prop:.2%}) show significant gender differences at raw p<0.005.",
    "n_significant": int(n_sig),
    "n_tested": int(n_total),
    "proportion": round(float(prop), 4),
    "significant_titles": out[out['significant']]['movie'].tolist()
}
save_summary(summary, 'Q4_summary.json')
print(f"Q4: {n_sig}/{n_total} ({prop:.2%}) significant")
