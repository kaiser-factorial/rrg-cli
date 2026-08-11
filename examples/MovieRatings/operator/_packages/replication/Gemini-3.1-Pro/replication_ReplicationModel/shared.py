"""Shared utilities for MovieRatings replication analysis."""
import pandas as pd
import numpy as np
import json
from pathlib import Path

# Resolve data path: data is at ../../data/ relative to this dir
_BASE = Path(__file__).resolve().parent
DATA_PATH = Path('/Users/corinakaiser/Projects/RRG_real_root/RRG_root/rrg-cli/examples/MovieRatings/data/movie_ratings.csv')
RAW_DIR = Path(__file__).resolve().parent / 'raw'
RAW_DIR.mkdir(exist_ok=True)

def load_data():
    """Load dataset and return DataFrame (1097 x 477)."""
    df = pd.read_csv(DATA_PATH, na_values=['', 'N/A'])
    return df

def movie_cols(df):
    """Return list of the first 400 column names (movie ratings)."""
    return df.columns[:400].tolist()

def rating_matrix(df):
    """Return numeric 1097x400 DataFrame of movie ratings."""
    mc = movie_cols(df)
    rm = df[mc].copy()
    for c in mc:
        rm[c] = pd.to_numeric(rm[c], errors='coerce')
    return rm

def gender_col(df):
    """Column 475 (0-indexed 474): gender identity."""
    return pd.to_numeric(df.iloc[:, 474], errors='coerce')

def only_child_col(df):
    """Column 476 (0-indexed 475): only child status."""
    return pd.to_numeric(df.iloc[:, 475], errors='coerce')

def watching_pref_col(df):
    """Column 477 (0-indexed 476): watching preference."""
    return pd.to_numeric(df.iloc[:, 476], errors='coerce')

def sensation_cols(df):
    """Columns 401-421 (0-indexed 400-420): sensation seeking items."""
    cols = df.columns[400:421].tolist()
    return cols

def extract_year(title):
    """Extract release year from movie title string."""
    import re
    m = re.search(r'\((\d{4})\)', title)
    return int(m.group(1)) if m else None

def save_raw_csv(df_out, filename):
    """Save DataFrame to raw/ directory as CSV."""
    RAW_DIR.mkdir(exist_ok=True)
    path = RAW_DIR / filename
    df_out.to_csv(path, index=False)
    return path

def save_summary(d, filename):
    """Save dict as JSON to raw/ directory."""
    RAW_DIR.mkdir(exist_ok=True)
    path = RAW_DIR / filename
    with open(path, 'w') as f:
        json.dump(d, f, indent=2, default=str)
    return path
