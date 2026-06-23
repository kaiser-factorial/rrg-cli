import pandas as pd
import numpy as np
import scipy.stats as stats
import re
import os

# Set paths
pkg_dir = "/Users/corinakaiser/Projects/LS_Lab/RRG_root/demo_projects/MovieRatings/RRG_demo/operator/_packages/replication/Gemini-3.1-Pro"
out_dir = "/Users/corinakaiser/Projects/LS_Lab/RRG_root/demo_projects/MovieRatings/RRG_demo/operator/replication_Gemini-3.1-Pro"

csv_path = os.path.join(pkg_dir, "movie_ratings.csv")

# Load data
df = pd.read_csv(csv_path)
print(f"Loaded movie_ratings.csv, shape: {df.shape}")

# Define column groups
movie_cols = list(df.columns[:400])
sensation_cols = list(df.columns[400:421])
gender_col = 'Gender identity (1 = female; 2 = male; 3 = self-described)'
sibling_col = 'Are you an only child? (1: Yes; 0: No; -1: Did not respond)'
alone_col = 'Movies are best enjoyed alone (1: Yes; 0: No; -1: Did not respond)'

# ----------------- QUESTION 1 -----------------
print("\n--- Question 1 ---")
# Count observed ratings per movie
observed_counts = df[movie_cols].notna().sum()
median_count = observed_counts.median()

low_pop_movies = observed_counts[observed_counts < median_count].index
high_pop_movies = observed_counts[observed_counts > median_count].index

print(f"Median popularity rating count: {median_count}")
print(f"Low popularity group size: {len(low_pop_movies)} movies")
print(f"High popularity group size: {len(high_pop_movies)} movies")

# Pool ratings within groups
low_pop_pooled = df[low_pop_movies].values.flatten()
low_pop_pooled = low_pop_pooled[~np.isnan(low_pop_pooled)]

high_pop_pooled = df[high_pop_movies].values.flatten()
high_pop_pooled = high_pop_pooled[~np.isnan(high_pop_pooled)]

# Run MWU test (one-tailed for higher ratings in high popularity)
# alternative='greater' means x > y is the alternative hypothesis
stat_q1, p_val_q1 = stats.mannwhitneyu(high_pop_pooled, low_pop_pooled, alternative='greater')
print(f"Pooled low popularity ratings N: {len(low_pop_pooled)}")
print(f"Pooled high popularity ratings N: {len(high_pop_pooled)}")
print(f"MWU Statistic: {stat_q1}, p-value: {p_val_q1}")


# ----------------- QUESTION 2 -----------------
print("\n--- Question 2 ---")
# Extract release years
years = []
for title in movie_cols:
    m = re.search(r'\((\d{4})\)', title)
    years.append(int(m.group(1)) if m else np.nan)

years_series = pd.Series(years, index=movie_cols)
median_year = years_series.median()
print(f"Median release year: {median_year}")

# Split movies (median year included in newer group)
older_movies = years_series[years_series < median_year].index
newer_movies = years_series[years_series >= median_year].index
print(f"Older movies (< {median_year}): {len(older_movies)}")
print(f"Newer movies (>= {median_year}): {len(newer_movies)}")

# Pool ratings
older_pooled = df[older_movies].values.flatten()
older_pooled = older_pooled[~np.isnan(older_pooled)]

newer_pooled = df[newer_movies].values.flatten()
newer_pooled = newer_pooled[~np.isnan(newer_pooled)]

# Run two-sample KS test (two-sided)
stat_q2, p_val_q2 = stats.ks_2samp(newer_pooled, older_pooled)
print(f"Older group pooled N: {len(older_pooled)}")
print(f"Newer group pooled N: {len(newer_pooled)}")
print(f"KS Statistic: {stat_q2}, p-value: {p_val_q2}")


# ----------------- QUESTION 3 -----------------
print("\n--- Question 3 ---")
# Shrek (2001) ratings by gender (1 = female, 2 = male)
shrek_df = df[['Shrek (2001)', gender_col]].dropna()
shrek_female = shrek_df[shrek_df[gender_col] == 1]['Shrek (2001)'].values
shrek_male = shrek_df[shrek_df[gender_col] == 2]['Shrek (2001)'].values

stat_q3, p_val_q3 = stats.ks_2samp(shrek_female, shrek_male)
print(f"Female N: {len(shrek_female)}, Male N: {len(shrek_male)}")
print(f"KS Statistic: {stat_q3}, p-value: {p_val_q3}")


# ----------------- QUESTION 4 -----------------
print("\n--- Question 4 ---")
# Separate two-sample KS test for each of 400 movies by gender (1 vs 2)
sig_count_q4 = 0
results_q4 = []

for m in movie_cols:
    sub = df[[m, gender_col]].dropna()
    f_ratings = sub[sub[gender_col] == 1][m].values
    m_ratings = sub[sub[gender_col] == 2][m].values
    
    if len(f_ratings) > 0 and len(m_ratings) > 0:
        stat, pval = stats.ks_2samp(f_ratings, m_ratings)
        if pval < 0.005:
            sig_count_q4 += 1
            results_q4.append((m, len(f_ratings), len(m_ratings), pval))
    else:
        print(f"Warning: {m} has empty ratings for a group. Female N: {len(f_ratings)}, Male N: {len(m_ratings)}")

proportion_q4 = sig_count_q4 / len(movie_cols)
print(f"Count of movies with p < 0.005: {sig_count_q4}")
print(f"Proportion: {proportion_q4:.4f} ({sig_count_q4}/400)")


# ----------------- QUESTION 5 -----------------
print("\n--- Question 5 ---")
# Only children (1) vs Siblings (0) rating of The Lion King (1994)
lk_df = df[['The Lion King (1994)', sibling_col]].dropna()
lk_only = lk_df[lk_df[sibling_col] == 1]['The Lion King (1994)'].values
lk_siblings = lk_df[lk_df[sibling_col] == 0]['The Lion King (1994)'].values

stat_q5, p_val_q5 = stats.mannwhitneyu(lk_only, lk_siblings, alternative='greater')
print(f"Only child N: {len(lk_only)}, Sibling N: {len(lk_siblings)}")
print(f"MWU Statistic: {stat_q5}, p-value: {p_val_q5}")


# ----------------- QUESTION 6 -----------------
print("\n--- Question 6 ---")
# Separate two-sample KS test for each movie by only-child status (1 vs 0)
sig_count_q6 = 0
qualifying_q6 = []

for m in movie_cols:
    sub = df[[m, sibling_col]].dropna()
    only_ratings = sub[sub[sibling_col] == 1][m].values
    sib_ratings = sub[sub[sibling_col] == 0][m].values
    
    if len(only_ratings) > 0 and len(sib_ratings) > 0:
        stat, pval = stats.ks_2samp(only_ratings, sib_ratings)
        if pval < 0.005:
            sig_count_q6 += 1
            qualifying_q6.append((m, len(only_ratings), len(sib_ratings), pval))

proportion_q6 = sig_count_q6 / len(movie_cols)
print(f"Count of movies with p < 0.005: {sig_count_q6}")
print(f"Proportion: {proportion_q6:.4f} ({sig_count_q6}/400)")
print("Qualifying titles:")
for m, n1, n2, pval in qualifying_q6:
    print(f"  - {m} (Only N: {n1}, Sibling N: {n2}, p: {pval:.6f})")


# ----------------- QUESTION 7 -----------------
print("\n--- Question 7 ---")
# Social (0) vs Alone (1) rating of The Wolf of Wall Street (2013)
wolf_df = df[['The Wolf of Wall Street (2013)', alone_col]].dropna()
wolf_social = wolf_df[wolf_df[alone_col] == 0]['The Wolf of Wall Street (2013)'].values
wolf_alone = wolf_df[wolf_df[alone_col] == 1]['The Wolf of Wall Street (2013)'].values

stat_q7, p_val_q7 = stats.mannwhitneyu(wolf_social, wolf_alone, alternative='greater')
print(f"Social N: {len(wolf_social)}, Alone N: {len(wolf_alone)}")
print(f"MWU Statistic: {stat_q7}, p-value: {p_val_q7}")


# ----------------- QUESTION 8 -----------------
print("\n--- Question 8 ---")
# Separate MWU test (one-tailed greater) for each movie (social > alone)
sig_count_q8 = 0
qualifying_q8 = []

for m in movie_cols:
    sub = df[[m, alone_col]].dropna()
    social_ratings = sub[sub[alone_col] == 0][m].values
    alone_ratings = sub[sub[alone_col] == 1][m].values
    
    if len(social_ratings) > 0 and len(alone_ratings) > 0:
        stat, pval = stats.mannwhitneyu(social_ratings, alone_ratings, alternative='greater')
        if pval < 0.005:
            sig_count_q8 += 1
            qualifying_q8.append((m, len(social_ratings), len(alone_ratings), pval))

proportion_q8 = sig_count_q8 / len(movie_cols)
print(f"Count of movies with p < 0.005: {sig_count_q8}")
print(f"Proportion: {proportion_q8:.4f} ({sig_count_q8}/400)")
print("Qualifying titles:")
for m, n1, n2, pval in qualifying_q8:
    print(f"  - {m} (Social N: {n1}, Alone N: {n2}, p: {pval:.6f})")


# ----------------- QUESTION 9 -----------------
print("\n--- Question 9 ---")
# KS test comparing Home Alone (1990) and Finding Nemo (2003)
ha_ratings = df['Home Alone (1990)'].dropna().values
fn_ratings = df['Finding Nemo (2003)'].dropna().values

stat_q9, p_val_q9 = stats.ks_2samp(ha_ratings, fn_ratings)
print(f"Home Alone N: {len(ha_ratings)}, Finding Nemo N: {len(fn_ratings)}")
print(f"KS Statistic: {stat_q9}, p-value: {p_val_q9}")


# ----------------- QUESTION 10 -----------------
print("\n--- Question 10 ---")
# Kruskal-Wallis across constituent movies of 8 franchises
franchises = [
    'Star Wars', 'Harry Potter', 'The Matrix', 'Indiana Jones',
    'Jurassic Park', 'Pirates of the Caribbean', 'Toy Story', 'Batman'
]

kw_sig_count = 0
for f in franchises:
    matches = [m for m in movie_cols if f.lower() in m.lower()]
    movie_data = [df[m].dropna().values for m in matches]
    
    # Kruskal-Wallis
    stat, pval = stats.kruskal(*movie_data)
    is_sig = pval < 0.005
    if is_sig:
        kw_sig_count += 1
    print(f"{f} ({len(matches)} movies): KW Statistic: {stat}, p-value: {pval} (Significant: {is_sig})")

print(f"Number of inconsistent franchises (p < 0.005): {kw_sig_count}")


# ----------------- QUESTION 11 -----------------
print("\n--- Question 11 ---")

def run_q11(method_name, sensation_scores):
    median_score = sensation_scores.median()
    print(f"Method: {method_name}")
    print(f"  Median sensation score: {median_score}")
    
    # Split participants above/below, excluding those at median
    df_temp = df.copy()
    df_temp['sens_score'] = sensation_scores
    
    above_df = df_temp[df_temp['sens_score'] > median_score]
    below_df = df_temp[df_temp['sens_score'] < median_score]
    exact_df = df_temp[df_temp['sens_score'] == median_score]
    missing_df = df_temp[df_temp['sens_score'].isna()]
    
    print(f"  Above Median N: {len(above_df)}")
    print(f"  Below Median N: {len(below_df)}")
    print(f"  Exactly at Median N: {len(exact_df)}")
    print(f"  Missing Sensation N: {len(missing_df)}")
    
    qualifying = []
    for m in movie_cols:
        above_ratings = above_df[m].dropna().values
        below_ratings = below_df[m].dropna().values
        
        if len(above_ratings) > 0 and len(below_ratings) > 0:
            stat, pval = stats.ks_2samp(above_ratings, below_ratings)
            if pval < 0.005:
                qualifying.append((m, len(above_ratings), len(below_ratings), pval))
                
    print(f"  Number of qualifying movies (p < 0.005): {len(qualifying)}")
    print("  Qualifying titles:")
    for m, n1, n2, pval in qualifying:
        print(f"    - {m} (Above N: {n1}, Below N: {n2}, p: {pval:.6f})")

# Sum strict (exclude rows with any missing)
score_strict = df[sensation_cols].sum(axis=1, skipna=False)
run_q11("Strict Sum (exclude if any item missing)", score_strict)

# Sum relaxed (skipna=True, but exclude if all missing)
score_relaxed = df[sensation_cols].sum(axis=1, skipna=True)
score_relaxed[df[sensation_cols].isna().all(axis=1)] = np.nan
run_q11("Relaxed Sum (skipna=True)", score_relaxed)

