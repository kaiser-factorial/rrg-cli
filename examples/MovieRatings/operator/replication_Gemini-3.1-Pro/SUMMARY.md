# Gemini 3.1 Pro MovieRatings Replication Report

**Date of Execution**: 2026-06-22  
**Platform**: macOS (mac)  
**Replication Engine**: Gemini 3.5 Flash (High) (executing inside target environment `Gemini-3.1-Pro`)  
**Significance Threshold ($\alpha$)**: 0.005 (per-test, raw p-value)

---

## 1. Executive Summary

This report documents the replication of the MovieRatings data analysis protocol using the dataset `movie_ratings.csv` (and its equivalent `movie_ratings.parquet`). The analysis was executed in accordance with the fixed protocol specified in `ANALYSIS_PROTOCOL_OG.md` and the constraints in `VALIDATION_INSTRUCTIONS.md`.

All input files were confirmed to load successfully prior to starting the analysis. No prior results or reports were searched for or consulted during the analysis.

### Summary of Key Findings

| Q# | Finding Description | Statistical Test | Usable N | Test Statistic | p-value | Replicated? (p < 0.005) |
|---|---|---|---|---|---|---|
| **1** | Popularity vs. Rating | One-tailed Mann-Whitney U | 112,214 ratings | $U = 1,242,808,144.5$ | $2.423454 \times 10^{-759}$ | **Yes** (ratings are higher for popular movies) |
| **2** | Release Year (New vs. Old) | Two-sample Kolmogorov-Smirnov | 112,214 ratings | $D = 0.01115798$ | $2.251936 \times 10^{-3}$ | **Yes** (newer and older ratings differ) |
| **3** | Shrek (2001) Gender Diff | Two-sample Kolmogorov-Smirnov | 984 ratings | $D = 0.09796552$ | $5.608204 \times 10^{-2}$ | **No** (no significant gender difference) |
| **4** | Proportion of Gender Diff Movies | 400 Movie-level Two-sample KS | 400 tests | N/A | N/A | 25/400 movies (6.25%) differ |
| **5** | Lion King (1994) Sibling Diff | One-tailed Mann-Whitney U | 927 ratings | $U = 52,929.0$ | $0.978419$ | **No** (only children do not rate it higher) |
| **6** | Proportion of Sibling Diff Movies | 400 Movie-level Two-sample KS | 400 tests | N/A | N/A | 3/400 movies (0.75%) differ |
| **7** | Wolf of Wall Street Social Diff | One-tailed Mann-Whitney U | 663 ratings | $U = 49,303.5$ | $0.943666$ | **No** (social preference does not rate it higher) |
| **8** | Proportion of Social Preference Diff | 400 Movie-level One-tailed MWU | 400 tests | N/A | N/A | 6/400 movies (1.50%) differ |
| **9** | Home Alone vs. Finding Nemo | Two-sample Kolmogorov-Smirnov | 1,871 ratings | $D = 0.15269080$ | $6.379397 \times 10^{-10}$ | **Yes** (distributions differ significantly) |
| **10**| Franchise Consistency (8 groups) | Kruskal-Wallis (across movies) | 8 tests | See Section 3.10 | See Section 3.10 | 7 out of 8 franchises are inconsistent |
| **11**| Sensation-Seeking Rating Diff | 400 Movie-level Two-sample KS | 400 tests | N/A | N/A | 7/400 movies differ (strict sum method) |

---

## 2. Data and Preprocessing Verification

### 2.1. File Characteristics
We verified that the files load successfully and have identical dimensions:
- **`movie_ratings.csv`**: 1,097 rows, 477 columns. MD5 / SHA-256 hashes match those listed in `_provenance.json`.
- **`movie_ratings.parquet`**: 1,097 rows, 477 columns. Evaluated to be structurally equivalent.
- **`movie_ratings.codebook.csv`**: 477 rows, 6 columns.

### 2.2. Missingness Handling
- **Missing Data Definition**: Blank cells and the literal text `N/A` are treated as missing (`NaN`).
- **No Imputation**: In compliance with the rules, missing movie ratings and grouping variables were strictly left as missing and excluded pairwise/listwise from tests as appropriate.
- **Usable N Reporting**: The exact number of non-missing observations used is reported for every test below.

### 2.3. Multiplicity Correction
- **Explicit Statement**: No multiplicity correction (e.g., Bonferroni, FDR) was applied to the 400 movie-level analyses in Questions 4, 6, 8, and 11. Individual tests were evaluated against the raw per-test threshold of $\alpha = 0.005$ as specified in the protocol.

---

## 3. Question-by-Question Replication Results

### 3.1. Question 1: Popularity vs. Rating
*Are movies with more observed ratings rated higher than movies with fewer observed ratings?*

- **Method**: The 400 movies were split at the median observed rating count. Ratings were pooled within groups, and a one-tailed Mann-Whitney U test (`alternative='greater'`) was run for higher ratings in the high-popularity group.
- **Median Count**: 197.5 ratings.
  - **Low-Popularity Group**: 200 movies (each $\le 197$ ratings, pooled N = 22,000 ratings).
  - **High-Popularity Group**: 200 movies (each $\ge 198$ ratings, pooled N = 90,214 ratings).
- **Usable N (Pooled)**: 112,214 ratings.
- **Mann-Whitney U Statistic**: 1,242,808,144.5
- **Exact p-value**: $2.423454 \times 10^{-759}$ (computed via normal approximation with tie-correction: $z = 59.021687$)
- **Conclusion**: **Significant difference**. The high-popularity group has significantly higher ratings than the low-popularity group ($p < 0.005$).

### 3.2. Question 2: Release Year (New vs. Old)
*Are newer movies rated differently from older movies?*

- **Method**: Release years were extracted from the movie titles (e.g., `(2003)`). The 400 movies were split at the median release year, with the median year included in the newer group. Ratings were pooled within groups, and a two-sample Kolmogorov-Smirnov test was performed.
- **Median Year**: 1999.0.
  - **Older Group**: 197 movies (released before 1999, pooled N = 46,524 ratings).
  - **Newer Group**: 203 movies (released in or after 1999, pooled N = 65,690 ratings).
- **Usable N (Pooled)**: 112,214 ratings.
- **Kolmogorov-Smirnov Statistic ($D$)**: 0.01115798
- **Exact p-value**: $2.251936 \times 10^{-3}$ ($0.002251936$)
- **Conclusion**: **Significant difference**. Rating distributions of older and newer movies differ significantly ($p = 0.00225 < 0.005$).

### 3.3. Question 3: Shrek (2001) Gender Difference
*Do male and female viewers rate `Shrek (2001)` differently?*

- **Method**: Two-sample Kolmogorov-Smirnov test comparing male and female ratings of the movie `Shrek (2001)`.
- **Usable N**: 984 ratings (Female N = 743, Male N = 241). Participants with self-described gender (value 3) or missing gender/ratings were excluded.
- **Kolmogorov-Smirnov Statistic ($D$)**: 0.09796552
- **Exact p-value**: $5.608204 \times 10^{-2}$ ($0.05608204$)
- **Conclusion**: **Not significant**. Male and female ratings for `Shrek (2001)` do not differ significantly at the $\alpha = 0.005$ level.

### 3.4. Question 4: Proportion of Movies with Gender Differences
*What proportion of the 400 movies are rated differently by male and female viewers?*

- **Method**: Run a separate two-sample Kolmogorov-Smirnov test for each of the 400 movies by gender (Female = 1 vs. Male = 2).
- **Usable N**: Varies per movie. Female N ranges from 32 to 746; Male N ranges from 15 to 251.
- **Number of Qualifying Movies (raw $p < 0.005$)**: 25 movies.
- **Proportion**: 0.0625 (6.25%).
- **Qualifying Movie Titles & Statistics (ordered by p-value)**:
  1. `The Proposal (2009)` (Female N = 519, Male N = 79, $p = 1.243258 \times 10^{-6}$)
  2. `Harry Potter and the Chamber of Secrets (2002)` (Female N = 633, Male N = 203, $p = 5.625336 \times 10^{-6}$)
  3. `Beauty and the Beauty (1991)` (Female N = 391, Male N = 100, $p = 2.568939 \times 10^{-5}$)
  4. `Harry Potter and the Goblet of Fire (2005)` (Female N = 610, Male N = 195, $p = 4.110781 \times 10^{-5}$)
  5. `Saving Private Ryan (1998)` (Female N = 272, Male N = 151, $p = 5.306185 \times 10^{-5}$)
  6. `Batman: The Dark Knight (2008)` (Female N = 494, Male N = 220, $p = 5.951690 \times 10^{-5}$)
  7. `Alien (1979)` (Female N = 164, Male N = 115, $p = 6.496200 \times 10^{-5}$)
  8. `Cheaper by the Dozen (2003)` (Female N = 540, Male N = 135, $p = 6.758832 \times 10^{-5}$)
  9. `Harry Potter and the Deathly Hallows: Part 2 (2011)` (Female N = 614, Male N = 202, $p = 1.019839 \times 10^{-4}$)
  10. `The Matrix (1999)` (Female N = 321, Male N = 170, $p = 2.129602 \times 10^{-4}$)
  11. `Harry Potter and the Sorcerer's Stone (2001)` (Female N = 640, Male N = 215, $p = 2.219361 \times 10^{-4}$)
  12. `Bend it Like Beckham (2002)` (Female N = 294, Male N = 78, $p = 2.423864 \times 10^{-4}$)
  13. `The Wolf of Wall Street (2013)` (Female N = 479, Male N = 183, $p = 2.575779 \times 10^{-4}$)
  14. `Grease (1978)` (Female N = 523, Male N = 119, $p = 3.365194 \times 10^{-4}$)
  15. `The Cabin in the Woods (2012)` (Female N = 285, Male N = 119, $p = 3.577293 \times 10^{-4}$)
  16. `Gladiator (2000)` (Female N = 174, Male N = 123, $p = 4.370666 \times 10^{-4}$)
  17. `Pirates of the Caribbean: Dead Man's Chest (2006)` (Female N = 587, Male N = 207, $p = 1.009455 \times 10^{-3}$)
  18. `13 Going on 30 (2004)` (Female N = 565, Male N = 79, $p = 1.016311 \times 10^{-3}$)
  19. `My Big Fat Greek Wedding (2002)` (Female N = 399, Male N = 99, $p = 1.410643 \times 10^{-3}$)
  20. `The Exorcist (1973)` (Female N = 303, Male N = 110, $p = 1.997904 \times 10^{-3}$)
  21. `Uptown Girls (2003)` (Female N = 217, Male N = 25, $p = 2.414715 \times 10^{-3}$)
  22. `10 Things I Hate About You (1999)` (Female N = 481, Male N = 57, $p = 2.673282 \times 10^{-3}$)
  23. `Chicago (2002)` (Female N = 196, Male N = 41, $p = 2.720318 \times 10^{-3}$)
  24. `Divine Secrets of the Ya-Ya Sisterhood (2002)` (Female N = 55, Male N = 26, $p = 4.219230 \times 10^{-3}$)
  25. `Aladdin (1992)` (Female N = 625, Male N = 176, $p = 4.330153 \times 10^{-3}$)

*(Note: "Beauty and the Beauty (1991)" is the literal column header in the dataset and has been preserved exactly.)*

### 3.5. Question 5: Sibling Difference for The Lion King (1994)
*Do only children rate `The Lion King (1994)` higher than viewers with siblings?*

- **Method**: One-tailed Mann-Whitney U test of whether only children (`sibling_col == 1`) rate `The Lion King (1994)` higher than viewers with siblings (`sibling_col == 0`).
- **Usable N**: 927 ratings (Only children N = 151, Sibling N = 776).
- **Mann-Whitney U Statistic**: 52,929.0
- **Exact p-value**: $0.97841909$
- **Conclusion**: **Not significant**. There is no evidence that only children rate `The Lion King (1994)` higher than viewers with siblings (in fact, only children rated it slightly lower on average).

### 3.6. Question 6: Proportion of Movies with Sibling Differences
*What proportion of the 400 movies are rated differently by only children and viewers with siblings?*

- **Method**: Run a separate two-sample Kolmogorov-Smirnov test for each of the 400 movies comparing only children (1) vs. viewers with siblings (0).
- **Usable N**: Varies per movie.
- **Number of Qualifying Movies (raw $p < 0.005$)**: 3 movies.
- **Proportion**: 0.0075 (0.75%).
- **Qualifying Movie Titles & Statistics (ordered by p-value)**:
  1. `Happy Gilmore (1996)` (Only N = 36, Sibling N = 266, $p = 1.158866 \times 10^{-3}$)
  2. `Toy Story (1995)` (Only N = 144, Sibling N = 772, $p = 2.495966 \times 10^{-3}$)
  3. `Billy Madison (1995)` (Only N = 43, Sibling N = 224, $p = 3.872372 \times 10^{-3}$)

### 3.7. Question 7: Social Preference Difference for The Wolf of Wall Street (2013)
*Do viewers who prefer watching movies socially rate `The Wolf of Wall Street (2013)` higher than viewers who prefer watching alone?*

- **Method**: One-tailed Mann-Whitney U test of whether social viewers (`alone_col == 0`) rate `The Wolf of Wall Street (2013)` higher than viewers who prefer watching alone (`alone_col == 1`).
- **Usable N**: 663 ratings (Social N = 270, Alone N = 393).
- **Mann-Whitney U Statistic**: 49,303.5
- **Exact p-value**: $0.94366580$
- **Conclusion**: **Not significant**. Social viewers do not rate `The Wolf of Wall Street (2013)` higher than alone viewers.

### 3.8. Question 8: Proportion of Movies Rated Higher by Social Viewers
*What proportion of the 400 movies are rated higher by social viewers than by viewers who prefer watching alone?*

- **Method**: Run a separate one-tailed Mann-Whitney U test for each movie comparing social (0) vs. alone (1) ratings, testing the hypothesis that social ratings are higher (`alternative='greater'`).
- **Usable N**: Varies per movie.
- **Number of Qualifying Movies (raw $p < 0.005$)**: 6 movies.
- **Proportion**: 0.0150 (1.50%).
- **Qualifying Movie Titles & Statistics (ordered by p-value)**:
  1. `Shrek 2 (2004)` (Social N = 410, Alone N = 535, $p = 1.398084 \times 10^{-4}$)
  2. `Captain America: Civil War (2016)` (Social N = 243, Alone N = 293, $p = 4.751160 \times 10^{-4}$)
  3. `The Avengers (2012)` (Social N = 340, Alone N = 412, $p = 9.989391 \times 10^{-4}$)
  4. `Spider-Man (2002)` (Social N = 367, Alone N = 459, $p = 1.179535 \times 10^{-3}$)
  5. `The Transporter (2002)` (Social N = 92, Alone N = 99, $p = 2.333190 \times 10^{-3}$)
  6. `North (1994)` (Social N = 39, Alone N = 35, $p = 2.347843 \times 10^{-3}$)

### 3.9. Question 9: Home Alone vs. Finding Nemo Rating Distributions
*Does the rating distribution of `Home Alone (1990)` differ from that of `Finding Nemo (2003)`?*

- **Method**: Two-sample Kolmogorov-Smirnov test comparing the observed ratings of `Home Alone (1990)` and `Finding Nemo (2003)`.
- **Usable N**: 1,871 ratings (Home Alone N = 857, Finding Nemo N = 1014).
- **Kolmogorov-Smirnov Statistic ($D$)**: 0.15269080
- **Exact p-value**: $6.379397 \times 10^{-10}$
- **Conclusion**: **Significant difference**. The rating distributions for `Home Alone (1990)` and `Finding Nemo (2003)` differ significantly ($p < 0.005$).

### 3.10. Question 10: Franchise Consistency
*How many of the eight named franchises exhibit inconsistent ratings among their constituent movies?*

- **Method**: Movies belonging to each of the eight franchises were identified by searching for the franchise keyword in their titles (case-insensitive). Within each franchise, a Kruskal-Wallis H test was conducted across the constituent movies' observed ratings.
- **Results Table**:

| Franchise | Keyword | Constituent Movies | KW Stat ($H$) | Usable N (Total) | p-value | Significant (p < 0.005)? |
|---|---|---|---|---|---|---|
| **Star Wars** | `Star Wars` | 6 movies | 230.58417537 | 2,959 | $8.016477 \times 10^{-48}$ | **Yes** (Inconsistent) |
| **Harry Potter** | `Harry Potter` | 4 movies | 3.33123073 | 3,360 | 0.34331951 | **No** (Consistent) |
| **The Matrix** | `The Matrix` | 3 movies | 48.37886652 | 1,207 | $3.123652 \times 10^{-11}$ | **Yes** (Inconsistent) |
| **Indiana Jones** | `Indiana Jones` | 4 movies | 45.79416340 | 1,747 | $6.272776 \times 10^{-10}$ | **Yes** (Inconsistent) |
| **Jurassic Park** | `Jurassic Park` | 3 movies | 46.59088064 | 1,697 | $7.636930 \times 10^{-11}$ | **Yes** (Inconsistent) |
| **Pirates of the Caribbean** | `Pirates of the Caribbean` | 3 movies | 20.64399756 | 2,142 | $3.290129 \times 10^{-5}$ | **Yes** (Inconsistent) |
| **Toy Story** | `Toy Story` | 3 movies | 24.38599494 | 2,711 | $5.065805 \times 10^{-6}$ | **Yes** (Inconsistent) |
| **Batman** | `Batman` | 3 movies | 190.53496873 | 1,449 | $4.225297 \times 10^{-42}$ | **Yes** (Inconsistent) |

- **Conclusion**: **7 of the 8 franchises** exhibit inconsistent ratings (only Harry Potter is consistent).

---

## 4. Question 11: Sensation-Seeking Score Split Comparison

*Which movies are rated differently by participants above versus below the median sensation-seeking score?*

Sensation seeking is defined as the row-wise sum of columns 401-421. Because some participants have missing values in these columns, we evaluated two distinct summation methods to compare their impact on the median split and the resulting list of qualifying movies.

### 4.1. Comparison of Summation Methods

| Metric | Method A: Strict Sum (Recommended) | Method B: Relaxed Sum |
|---|---|---|
| **Description** | Excludes rows with any missing values in columns 401-421 (Strict "no imputation" rule) | Sums available columns using `skipna=True` (excludes only if all 21 items are missing) |
| **Median Score** | 61.0 | 60.0 |
| **Above Median N** | 484 | 544 |
| **Below Median N** | 530 | 495 |
| **Exactly at Median N (Excluded)**| 52 | 55 |
| **Missing Sensation Score N** | 31 | 3 |
| **Number of Qualifying Movies** | 7 movies | 7 movies |

### 4.2. Qualifying Movies by Method

#### Method A: Strict Sum (Recommended - No Imputation)
Only participants with a fully completed sensation-seeking battery (N = 1,066) were included. The median was 61.0. Participants exactly at 61.0 were excluded.
The following 7 movies showed significant rating differences ($p < 0.005$) between above-median and below-median sensation seekers:
1. `The Wolf of Wall Street (2013)` (Above N = 328, Below N = 293, $p = 7.877642 \times 10^{-7}$)
2. `The Cabin in the Woods (2012)` (Above N = 232, Below N = 157, $p = 3.797054 \times 10^{-5}$)
3. `The Ring (2002)` (Above N = 201, Below N = 151, $p = 8.880693 \times 10^{-4}$)
4. `The Texas Chainsaw Massacre (1974)` (Above N = 186, Below N = 109, $p = 9.474255 \times 10^{-4}$)
5. `Saw (2004)` (Above N = 203, Below N = 137, $p = 1.295989 \times 10^{-3}$)
6. `Ice Age (2002)` (Above N = 397, Below N = 427, $p = 3.406446 \times 10^{-3}$)
7. `The Exorcist (1973)` (Above N = 241, Below N = 158, $p = 3.961939 \times 10^{-3}$)

#### Method B: Relaxed Sum (Sums Available Items)
Sensation seeking was computed as the sum of non-missing items using `skipna=True`. The median was 60.0. Participants exactly at 60.0 were excluded.
The following 7 movies qualified:
1. `The Wolf of Wall Street (2013)` (Above N = 365, Below N = 264, $p = 3.297491 \times 10^{-6}$)
2. `The Cabin in the Woods (2012)` (Above N = 253, Below N = 141, $p = 8.706173 \times 10^{-4}$)
3. `The Ring (2002)` (Above N = 221, Below N = 136, $p = 2.032649 \times 10^{-3}$)
4. `Scary Movie (2000)` (Above N = 191, Below N = 106, $p = 2.701831 \times 10^{-3}$)
5. `Scream (1996)` (Above N = 220, Below N = 119, $p = 2.938148 \times 10^{-3}$)
6. `Along Came a Spider (2002)` (Above N = 44, Below N = 20, $p = 2.970891 \times 10^{-3}$)
7. `Saw (2004)` (Above N = 223, Below N = 125, $p = 3.918987 \times 10^{-3}$)

*Methodological Note*: Method A (Strict Sum) is the recommended replication result because summing with `skipna=True` operates as a form of imputation (replacing missing values with zeros or shifting the score distribution downward), which contradicts the instruction: *"Do not impute missing movie ratings or grouping variables."*

---
*Report generated and validated for replication.*
