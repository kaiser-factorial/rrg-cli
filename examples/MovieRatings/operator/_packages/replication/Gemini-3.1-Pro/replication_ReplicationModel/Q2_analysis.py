"""Q2: Are newer movies rated differently from older movies?"""
import sys; sys.path.insert(0, '.')
from shared import *
from scipy.stats import ks_2samp

df = load_data()
rm = rating_matrix(df)
mc = movie_cols(df)

# Extract years
years = [extract_year(c) for c in mc]
year_df = pd.DataFrame({'movie': mc, 'year': years})
median_year = year_df['year'].median()

# Split: older = below median, newer = at or above median
older_movies = year_df[year_df['year'] < median_year]['movie'].tolist()
newer_movies = year_df[year_df['year'] >= median_year]['movie'].tolist()

# Pool ratings
older_ratings = rm[older_movies].values.flatten()
older_ratings = older_ratings[~np.isnan(older_ratings)]
newer_ratings = rm[newer_movies].values.flatten()
newer_ratings = newer_ratings[~np.isnan(newer_ratings)]

# Two-sample KS test
stat, p_value = ks_2samp(older_ratings, newer_ratings)

out = pd.DataFrame({
    'group': ['older', 'newer'],
    'n_movies': [len(older_movies), len(newer_movies)],
    'n_ratings': [len(older_ratings), len(newer_ratings)],
    'mean_rating': [older_ratings.mean(), newer_ratings.mean()],
    'median_rating': [np.median(older_ratings), np.median(newer_ratings)],
    'std_rating': [older_ratings.std(), newer_ratings.std()]
})
save_raw_csv(out, 'Q2_raw.csv')

summary = {
    "question": "Are newer movies rated differently from older movies?",
    "n": int(len(older_ratings) + len(newer_ratings)),
    "groups": {"older": {"n_movies": len(older_movies), "n_ratings": len(older_ratings), "mean": round(float(older_ratings.mean()), 4), "year_range": f"{int(year_df[year_df['year']<median_year]['year'].min())}-{int(median_year-1)}"}, "newer": {"n_movies": len(newer_movies), "n_ratings": len(newer_ratings), "mean": round(float(newer_ratings.mean()), 4), "year_range": f"{int(median_year)}-{int(year_df['year'].max())}"}},
    "test": "Two-sample Kolmogorov-Smirnov",
    "statistic": float(stat),
    "p_value": float(p_value),
    "effect_size": None,
    "multiplicity": "No correction; single pre-specified comparison",
    "conclusion": f"{'Rating distributions differ significantly between older and newer movies' if p_value < 0.005 else 'No significant distributional difference between older and newer movie ratings'} at alpha=0.005 (D={stat:.4f}, p={p_value:.6e}).",
    "median_year_threshold": int(median_year)
}
save_summary(summary, 'Q2_summary.json')
print(f"Q2: D={stat:.4f}, p={p_value:.6e}")
