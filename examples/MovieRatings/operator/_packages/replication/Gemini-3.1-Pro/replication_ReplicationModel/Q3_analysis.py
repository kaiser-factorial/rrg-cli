"""Q3: Do male and female viewers rate Shrek (2001) differently?"""
import sys; sys.path.insert(0, '.')
from shared import *
from scipy.stats import ks_2samp

df = load_data()
rm = rating_matrix(df)
gen = gender_col(df)

shrek_col = [c for c in rm.columns if 'Shrek (2001)' in c][0]
ratings = rm[shrek_col].copy()

# Gender: 1=female, 2=male; exclude 3 and missing
female_mask = (gen == 1) & ratings.notna()
male_mask = (gen == 2) & ratings.notna()

female_ratings = ratings[female_mask].values
male_ratings = ratings[male_mask].values

# KS test
stat, p_value = ks_2samp(female_ratings, male_ratings)

out = pd.DataFrame({
    'group': ['female', 'male'],
    'n': [len(female_ratings), len(male_ratings)],
    'mean_rating': [female_ratings.mean(), male_ratings.mean()],
    'median_rating': [np.median(female_ratings), np.median(male_ratings)],
    'std_rating': [female_ratings.std(), male_ratings.std()]
})
save_raw_csv(out, 'Q3_raw.csv')

summary = {
    "question": "Do male and female viewers rate Shrek (2001) differently?",
    "n": int(len(female_ratings) + len(male_ratings)),
    "groups": {"female": {"n": len(female_ratings), "mean": round(float(female_ratings.mean()), 4)}, "male": {"n": len(male_ratings), "mean": round(float(male_ratings.mean()), 4)}},
    "test": "Two-sample Kolmogorov-Smirnov",
    "statistic": float(stat),
    "p_value": float(p_value),
    "effect_size": None,
    "multiplicity": "No correction; single pre-specified comparison",
    "conclusion": f"{'Male and female viewers rate Shrek (2001) significantly differently' if p_value < 0.005 else 'No significant difference in Shrek (2001) ratings between male and female viewers'} at alpha=0.005 (D={stat:.4f}, p={p_value:.6e}).",
    "movie": shrek_col
}
save_summary(summary, 'Q3_summary.json')
print(f"Q3: D={stat:.4f}, p={p_value:.6e}, female n={len(female_ratings)}, male n={len(male_ratings)}")
