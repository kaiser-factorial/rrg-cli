"""Q10: Franchise consistency — 8 Kruskal-Wallis tests."""
import sys; sys.path.insert(0, '.')
from shared import *
from scipy.stats import kruskal

df = load_data()
rm = rating_matrix(df)
mc = movie_cols(df)

franchises = {
    "Star Wars": ["Star Wars"],
    "Harry Potter": ["Harry Potter"],
    "The Matrix": ["The Matrix"],
    "Indiana Jones": ["Indiana Jones"],
    "Jurassic Park": ["Jurassic Park"],
    "Pirates of the Caribbean": ["Pirates of the Caribbean"],
    "Toy Story": ["Toy Story"],
    "Batman": ["Batman"]
}

results = []
for franchise, keywords in franchises.items():
    # Find matching movies
    matching = [m for m in mc if any(kw.lower() in m.lower() for kw in keywords)]
    # Collect ratings per movie (drop NaN per-movie)
    groups = []
    group_info = []
    for m in matching:
        vals = rm[m].dropna().values
        if len(vals) >= 1:
            groups.append(vals)
            group_info.append({'movie': m, 'n': len(vals), 'mean': float(vals.mean())})
    
    if len(groups) >= 2:
        stat, pv = kruskal(*groups)
        results.append({
            'franchise': franchise, 'n_movies': len(matching), 'n_tested': len(groups),
            'statistic': stat, 'p_value': pv, 'significant': pv < 0.005,
            'movies': matching
        })
    else:
        results.append({
            'franchise': franchise, 'n_movies': len(matching), 'n_tested': len(groups),
            'statistic': None, 'p_value': None, 'significant': False,
            'movies': matching
        })

out = pd.DataFrame(results)
save_raw_csv(out[['franchise', 'n_movies', 'n_tested', 'statistic', 'p_value', 'significant']], 'Q10_raw.csv')

n_sig = sum(1 for r in results if r['significant'])

summary = {
    "question": "How many of the eight named franchises exhibit inconsistent ratings among their constituent movies?",
    "n": int(sum(r['n_tested'] for r in results if r['statistic'] is not None)),
    "groups": {r['franchise']: {"n_movies": r['n_movies'], "movies": r['movies']} for r in results},
    "test": "Kruskal-Wallis per franchise",
    "statistic": f"{n_sig}/8 franchises significant at raw p<0.005",
    "p_value": "Per-franchise (see raw CSV)",
    "effect_size": None,
    "multiplicity": "Raw p-values reported; no correction applied",
    "conclusion": f"{n_sig} of 8 franchises show significant rating inconsistencies among constituent movies at raw p<0.005.",
    "n_significant_franchises": n_sig,
    "franchise_results": [{k: v for k, v in r.items() if k != 'movies'} | {"significant_titles": r['movies'] if r['significant'] else []} for r in results]
}
save_summary(summary, 'Q10_summary.json')
print(f"Q10: {n_sig}/8 franchises significant")
for r in results:
    sig_str = "SIG" if r['significant'] else "ns"
    p_str = f"{r['p_value']:.6e}" if r['p_value'] else "N/A"
    print(f"  {r['franchise']}: {r['n_movies']} movies, H={r['statistic']}, p={p_str} [{sig_str}]")
