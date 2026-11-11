"""Copy only public site assets and market data; never deploy local private positions."""
from pathlib import Path
import shutil
from core import BASE

def main():
    site=BASE/'site'
    if site.exists():shutil.rmtree(site)
    site.mkdir()
    for file in ['index.html','manifest.webmanifest','sw.js']:
        shutil.copy2(BASE/file,site/file)
    (site/'assets').mkdir()
    shutil.copy2(BASE/'assets'/'icon.svg',site/'assets'/'icon.svg')
    data=site/'data';data.mkdir()
    for file in ['quotes.json','screen.json','stocks.json','baostock_status.json']:
        shutil.copy2(BASE/'data'/file,data/file)
    src=BASE/'data'/'history';dest=data/'history';dest.mkdir()
    for file in src.glob('*.json'):
        shutil.copy2(file,dest/file.name)
    (site/'.nojekyll').touch()
    print('Public site files:',len(list(site.rglob('*'))))

if __name__=='__main__':main()
