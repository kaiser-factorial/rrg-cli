"""Q5: Do only children rate The Lion King (1994) higher?"""
import sys; sys.path.insert(0, '.')
from shared import *
from scipy.stats import mannwhitneyu

df = load_data()
rm = rating_matrix(df)
oc = only_child_col(df)

lk_col = [c for c in rm.columns if 'The Lion King (1994)' in c][0]
ratings = rm[lk_col].copy()

# Only child: 1=yes, 0=no; exclude -1 and missing
only_mask = (oc == 1) & ratings.notna()
sibling_mask = (oc == 0) & ratings.notna()

only_ratings = ratings[only_mask].values
sibling_ratings = ratings[sibling_mask].values

# One-tailed MW U: only children rate higher
stat, p_value = mannwhitneyu(only_ratings, sibling_ratings, alternative='greater')

out = pd.DataFrame({
    'group': ['only_child', 'has_siblings'],
    'n': [len(only_ratings), len(sibling_ratings)],
    'mean_rating': [only_ratings.mean(), sibling_ratings.mean()],
    'median_rating': [np.median(only_ratings), np.median(sibling_ratings)],
    'std_rating': [only_ratings.std(), sibling_ratings.std()]
})
save_raw_csv(out, 'Q5_raw.csv')

summary = {
    "question": "Do only children rate The Lion King (1994) higher than viewers with siblings?",
    "n": int(len(only_ratings) + len(sibling_ratings)),
    "groups": {"only_child": {"n": len(only_ratings), "mean": round(float(only_ratings.mean()), 4)}, "has_siblings": {"n": len(sibling_ratings), "mean": round(float(sibling_ratings.mean()), 4)}},
    "test": "Mann-Whitney U (one-tailed, greater)",
    "statistic": float(stat),
    "p_value": float(p_value),
    "effect_size": None,
    "multiplicity": "No correction; single pre-specified comparison",
    "conclusion": f"{'Only children rate The Lion King (1994) significantly higher' if p_value < 0.005 else 'No significant difference in The Lion King (1994) ratings between only children and viewers with siblings'} at alpha=0.005 (U={stat:.1f}, p={p_value:.6e}).",
    "movie": lk_col
}
save_summary(summary, 'Q5_summary.json')
print(f"Q5: U={stat:.2f}, p={p_value:.6e}, only n={len(only_ratings)}, sibling n={len(sibling_ratings)}")
