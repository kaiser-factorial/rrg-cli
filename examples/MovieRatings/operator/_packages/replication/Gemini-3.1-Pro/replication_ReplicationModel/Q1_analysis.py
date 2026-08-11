"""Q1: Are movies with more observed ratings rated higher?"""
import sys; sys.path.insert(0, '.')
from shared import *
from scipy.stats import mannwhitneyu

df = load_data()
rm = rating_matrix(df)
mc = movie_cols(df)

# Count observed (non-NaN) ratings per movie
counts = rm.notna().sum()
counts_df = pd.DataFrame({'movie': mc, 'n_ratings': counts.values})
median_count = counts_df['n_ratings'].median()

# Split: low = below or at median, high = above median
low_mask = counts_df['n_ratings'] <= median_count
high_mask = counts_df['n_ratings'] > median_count
low_movies = counts_df[low_mask]['movie'].tolist()
high_movies = counts_df[high_mask]['movie'].tolist()

# Pool ratings within each group
low_ratings = rm[low_movies].values.flatten()
low_ratings = low_ratings[~np.isnan(low_ratings)]
high_ratings = rm[high_movies].values.flatten()
high_ratings = high_ratings[~np.isnan(high_ratings)]

# One-tailed MW U: higher ratings in high-popularity group
stat, p_value = mannwhitneyu(high_ratings, low_ratings, alternative='greater')

out = pd.DataFrame({
    'group': ['high_popularity', 'low_popularity'],
    'n_movies': [len(high_movies), len(low_movies)],
    'n_ratings': [len(high_ratings), len(low_ratings)],
    'mean_rating': [high_ratings.mean(), low_ratings.mean()],
    'median_rating': [np.median(high_ratings), np.median(low_ratings)],
    'std_rating': [high_ratings.std(), low_ratings.std()]
})
save_raw_csv(out, 'Q1_raw.csv')

summary = {
    "question": "Are movies with more observed ratings rated higher than movies with fewer observed ratings?",
    "n": int(len(high_ratings) + len(low_ratings)),
    "groups": {"high_popularity": {"n_movies": len(high_movies), "n_ratings": len(high_ratings), "mean": round(float(high_ratings.mean()), 4)}, "low_popularity": {"n_movies": len(low_movies), "n_ratings": len(low_ratings), "mean": round(float(low_ratings.mean()), 4)}},
    "test": "Mann-Whitney U (one-tailed, greater)",
    "statistic": float(stat),
    "p_value": float(p_value),
    "effect_size": None,
    "multiplicity": "No correction; single pre-specified comparison",
    "conclusion": f"{'High-popularity movies have significantly higher ratings' if p_value < 0.005 else 'No significant difference in ratings between high- and low-popularity movies'} at alpha=0.005 (U={stat:.1f}, p={p_value:.6e}).",
    "median_count_threshold": float(median_count),
    "low_n_movies": len(low_movies),
    "high_n_movies": len(high_movies)
}
save_summary(summary, 'Q1_summary.json')
print(f"Q1: U={stat:.2f}, p={p_value:.6e}")
