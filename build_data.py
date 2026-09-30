import argparse
import pandas as pd
import json
import os

parser = argparse.ArgumentParser(description='Build IPEDS JSON dataset for the web tool.')
parser.add_argument('--year', type=int, default=2024,
                    help='IPEDS data year, e.g. 2024 for the 2023-24 release')
args = parser.parse_args()

YEAR = args.year
LABEL = f'IPEDS {YEAR - 1}-{str(YEAR)[2:]}'
COMP_FILE = f'c{YEAR}_a/c{YEAR}_a.csv'
HD_FILE   = f'hd{YEAR}/hd{YEAR}.csv'
COST_FILE = f'cost1_{YEAR}/cost1_{YEAR}.csv'

def fmt_cip(v):
    try:
        return f"{float(v):07.4f}"
    except (ValueError, TypeError):
        return str(v)

def safe_int(v):
    try:
        f = float(v)
        return int(f) if f >= 0 else None
    except (ValueError, TypeError):
        return None

def safe_cbsa(code, ctype):
    try:
        ct = int(float(ctype))
        if ct in (1, 2):
            c = int(float(code))
            return str(c) if c > 0 else None
    except (ValueError, TypeError):
        pass
    return None

def safe_coord(v, lo, hi):
    try:
        f = float(v)
        return round(f, 5) if lo <= f <= hi else None
    except (ValueError, TypeError):
        return None

print(f"Building {LABEL} dataset (year={YEAR})")
print(f"Loading {COMP_FILE}...")
comp_df = pd.read_csv(
    COMP_FILE,
    usecols=['UNITID', 'CIPCODE', 'AWLEVEL', 'MAJORNUM', 'CTOTALT']
)
for col in ['UNITID', 'AWLEVEL', 'MAJORNUM', 'CTOTALT']:
    comp_df[col] = pd.to_numeric(comp_df[col], errors='coerce')
comp_df['CIPCODE'] = comp_df['CIPCODE'].apply(fmt_cip)

comp_df = comp_df[
    (comp_df['MAJORNUM'] == 1) &
    (comp_df['CTOTALT'] > 0) &
    (~comp_df['CIPCODE'].str.startswith('99'))
].dropna(subset=['UNITID', 'AWLEVEL', 'CTOTALT'])
print(f"  {len(comp_df):,} qualifying records")

print(f"Loading {HD_FILE}...")
hd_df = pd.read_csv(
    HD_FILE,
    usecols=['UNITID', 'INSTNM', 'CITY', 'STABBR', 'CONTROL', 'CBSA', 'CBSATYPE',
             'LATITUDE', 'LONGITUD']
)
for col in ['UNITID', 'CONTROL', 'CBSA', 'CBSATYPE', 'LATITUDE', 'LONGITUD']:
    hd_df[col] = pd.to_numeric(hd_df[col], errors='coerce')

print(f"Loading {COST_FILE}...")
cost_df = pd.read_csv(
    COST_FILE,
    usecols=['UNITID', 'TUITION1', 'TUITION2', 'TUITION5', 'TUITION6']
)
cost_df['UNITID'] = pd.to_numeric(cost_df['UNITID'], errors='coerce')
for col in ['TUITION1', 'TUITION2', 'TUITION5', 'TUITION6']:
    cost_df[col] = pd.to_numeric(cost_df[col], errors='coerce')
    cost_df.loc[cost_df[col] < 0, col] = float('nan')

print("Merging institution + tuition...")
inst_df = hd_df.merge(cost_df, on='UNITID', how='left')

print("Building CBSA name lookup...")
cbsa_names = {}
valid_cbsa = hd_df[hd_df['CBSATYPE'].isin([1, 2]) & hd_df['CBSA'].notna() & (hd_df['CBSA'] > 0)]
for cbsa_code, group in valid_cbsa.groupby('CBSA'):
    type_val = int(group['CBSATYPE'].iloc[0])
    type_label = 'Metro' if type_val == 1 else 'Micro'
    top = group[['CITY', 'STABBR']].value_counts()
    if top.empty:
        continue
    top_city, top_state = top.index[0]
    cbsa_names[str(int(cbsa_code))] = f"{top_city}, {top_state} {type_label}"
print(f"  {len(cbsa_names):,} CBSA areas")

institutions = {}
for _, row in inst_df.iterrows():
    if pd.isna(row['UNITID']):
        continue
    uid = str(int(row['UNITID']))
    institutions[uid] = [
        str(row.get('INSTNM', '')),
        str(row.get('CITY', '')),
        str(row.get('STABBR', '')),
        safe_int(row.get('CONTROL')),
        safe_int(row.get('TUITION1')),
        safe_int(row.get('TUITION2')),
        safe_int(row.get('TUITION5')),
        safe_int(row.get('TUITION6')),
        safe_cbsa(row.get('CBSA'), row.get('CBSATYPE')),
        safe_coord(row.get('LATITUDE'), -90, 90),
        safe_coord(row.get('LONGITUD'), -180, 180),
    ]
print(f"  {len(institutions):,} institutions")

print("Building completions index...")
completions = {}
for _, row in comp_df.iterrows():
    cip = str(row['CIPCODE'])
    entry = [int(row['UNITID']), int(row['AWLEVEL']), int(row['CTOTALT'])]
    completions.setdefault(cip, []).append(entry)

cips = sorted(completions.keys())
total_records = sum(len(v) for v in completions.values())
print(f"  {len(cips):,} unique CIP codes")
print(f"  {total_records:,} completion records")

os.makedirs('data', exist_ok=True)
output = {
    'year': YEAR,
    'label': LABEL,
    'inst': institutions,
    'comp': completions,
    'cips': cips,
    'cbsas': cbsa_names,
}

print("Writing data/ipeds_data.json...")
with open('data/ipeds_data.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, separators=(',', ':'), ensure_ascii=False)

size_mb = os.path.getsize('data/ipeds_data.json') / (1024 * 1024)
print(f"Done! data/ipeds_data.json — {size_mb:.1f} MB")
