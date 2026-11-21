"""Copy only public site assets and market data; never deploy local private positions."""
from pathlib import Path
import shutil
import subprocess
from core import BASE
from slice_signal_tracker import split_tracker

def main():
    site=BASE/'site'
    if site.exists():shutil.rmtree(site)
    site.mkdir()
    for file in ['index.html','manifest.webmanifest','sw.js']:
        shutil.copy2(BASE/file,site/file)
    # Publish the approved mobile landing at / while preserving the original
    # fully functional app at /app.html, same origin and localStorage keys.
    # Keep source index.html frozen: the strategy JS is extracted from it by
    # historical comparison scripts and tested against source SHA baselines.
    shutil.copy2(BASE/'index.html', site/'app.html')
    shutil.copy2(BASE/'mobile.html', site/'index.html')
    (site/'assets').mkdir()
    shutil.copy2(BASE/'assets'/'icon.svg',site/'assets'/'icon.svg')
    shutil.copy2(BASE/'assets'/'backtest-v2.js',site/'assets'/'backtest-v2.js')
    data=site/'data';data.mkdir()
    for file in ['quotes.json','screen.json','stocks.json','baostock_status.json']:
        source = BASE/'data'/file
        if source.exists():
            shutil.copy2(source, data/file)
    src=BASE/'data'/'history';dest=data/'history';dest.mkdir()
    for file in src.glob('*.json'):
        shutil.copy2(file,dest/file.name)
    # Mobile first: publish a small tracker index + last 30 calendar days;
    # leave data/signal_tracker.json unchanged, and fetch old months only on demand.
    tracker_source = BASE/'data'/'signal_tracker.json'
    if tracker_source.exists():
        split_tracker(tracker_source, data/'tracker')
    # Build a frozen, auditable comparison from committed source histories.
    # No API calls, no changes to data/ or quote-feed, and no trading signals published.
    subprocess.run(['node', str(BASE/'scripts'/'build_v2_study.js'), str(data/'backtest_v2.json')],
                   cwd=BASE, check=True, timeout=140)
    # A second, bounded research-only build using the exact same public history.
    # Does not affect production entry signals or user positions.
    subprocess.run(['node', str(BASE/'scripts'/'build_entry_quality_v22.js'), str(data/'entry_quality_v22.json')],
                   cwd=BASE, check=True, timeout=140)
    # Research-only, identical execution rules with seeded non-signal dates.
    subprocess.run(['node', str(BASE/'scripts'/'build_matched_control.js'), str(data/'evidence_control.json')],
                   cwd=BASE, check=True, timeout=140)
    (site/'.nojekyll').touch()
    print('Public site files:',len(list(site.rglob('*'))))

if __name__=='__main__':main()
