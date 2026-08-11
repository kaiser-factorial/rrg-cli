"""Q7: Do social viewers rate The Wolf of Wall Street (2013) higher?"""
import sys; sys.path.insert(0, '.')
from shared import *
from scipy.stats import mannwhitneyu

df = load_data()
rm = rating_matrix(df)
wp = watching_pref_col(df)

wow_col = [c for c in rm.columns if 'The Wolf of Wall Street (2013)' in c][0]
ratings = rm[wow_col].copy()

# Watching preference: 0=social, 1=alone; exclude -1 and missing
social_mask = (wp == 0) & ratings.notna()
alone_mask = (wp == 1) & ratings.notna()

social_ratings = ratings[social_mask].values
alone_ratings = ratings[alone_mask].values

# One-tailed MW U: social viewers rate higher
stat, p_value = mannwhitneyu(social_ratings, alone_ratings, alternative='greater')

out = pd.DataFrame({
    'group': ['social', 'alone'],
    'n': [len(social_ratings), len(alone_ratings)],
    'mean_rating': [social_ratings.mean(), alone_ratings.mean()],
    'median_rating': [np.median(social_ratings), np.median(alone_ratings)],
    'std_rating': [social_ratings.std(), alone_ratings.std()]
})
save_raw_csv(out, 'Q7_raw.csv')

summary = {
    "question": "Do viewers who prefer watching movies socially rate The Wolf of Wall Street (2013) higher than viewers who prefer watching alone?",
    "n": int(len(social_ratings) + len(alone_ratings)),
    "groups": {"social": {"n": len(social_ratings), "mean": round(float(social_ratings.mean()), 4)}, "alone": {"n": len(alone_ratings), "mean": round(float(alone_ratings.mean()), 4)}},
    "test": "Mann-Whitney U (one-tailed, greater)",
    "statistic": float(stat),
    "p_value": float(p_value),
    "effect_size": None,
    "multiplicity": "No correction; single pre-specified comparison",
    "conclusion": f"{'Social viewers rate The Wolf of Wall Street (2013) significantly higher' if p_value < 0.005 else 'No significant difference in Wolf of Wall Street (2013) ratings between social and alone viewers'} at alpha=0.005 (U={stat:.1f}, p={p_value:.6e}).",
    "movie": wow_col
}
save_summary(summary, 'Q7_summary.json')
print(f"Q7: U={stat:.2f}, p={p_value:.6e}, social n={len(social_ratings)}, alone n={len(alone_ratings)}")
