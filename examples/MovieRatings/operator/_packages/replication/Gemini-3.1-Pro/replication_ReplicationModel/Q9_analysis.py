"""Q9: Does Home Alone (1990) differ from Finding Nemo (2003)?"""
import sys; sys.path.insert(0, '.')
from shared import *
from scipy.stats import ks_2samp

df = load_data()
rm = rating_matrix(df)

ha_col = [c for c in rm.columns if 'Home Alone (1990)' in c][0]
fn_col = [c for c in rm.columns if 'Finding Nemo (2003)' in c][0]

ha_ratings = rm[ha_col].dropna().values
fn_ratings = rm[fn_col].dropna().values

stat, p_value = ks_2samp(ha_ratings, fn_ratings)

out = pd.DataFrame({
    'group': ['Home Alone (1990)', 'Finding Nemo (2003)'],
    'n': [len(ha_ratings), len(fn_ratings)],
    'mean_rating': [ha_ratings.mean(), fn_ratings.mean()],
    'median_rating': [np.median(ha_ratings), np.median(fn_ratings)],
    'std_rating': [ha_ratings.std(), fn_ratings.std()]
})
save_raw_csv(out, 'Q9_raw.csv')

summary = {
    "question": "Does the rating distribution of Home Alone (1990) differ from that of Finding Nemo (2003)?",
    "n": int(len(ha_ratings) + len(fn_ratings)),
    "groups": {"home_alone": {"n": len(ha_ratings), "mean": round(float(ha_ratings.mean()), 4)}, "finding_nemo": {"n": len(fn_ratings), "mean": round(float(fn_ratings.mean()), 4)}},
    "test": "Two-sample Kolmogorov-Smirnov",
    "statistic": float(stat),
    "p_value": float(p_value),
    "effect_size": None,
    "multiplicity": "No correction; single pre-specified comparison",
    "conclusion": f"{'Rating distributions differ significantly between Home Alone (1990) and Finding Nemo (2003)' if p_value < 0.005 else 'No significant distributional difference between Home Alone (1990) and Finding Nemo (2003) ratings'} at alpha=0.005 (D={stat:.4f}, p={p_value:.6e})."
}
save_summary(summary, 'Q9_summary.json')
print(f"Q9: D={stat:.4f}, p={p_value:.6e}")
