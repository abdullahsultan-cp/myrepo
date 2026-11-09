"""setup_check.py -- get a new laptop ready for page fixing, and prove it works.

    python setup_check.py                      # check everything
    python setup_check.py --token sb_pat_...   # first run: writes config/storyblok.json

Checks, in order: Python version, packages, the Storyblok token (and that it
opens space 289824742951963), the live component schemas (fetched if absent),
the work folders, and that aku.edu answers. Writes nothing to Storyblok.

config/storyblok.json is gitignored -- the token never goes into git.
"""
import argparse
import importlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CFG = os.path.join(ROOT, 'config', 'storyblok.json')
EXAMPLE = os.path.join(ROOT, 'config', 'storyblok.example.json')
SPACE = '289824742951963'
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, 'reconfigure'):
        _s.reconfigure(encoding='utf-8', errors='replace')


def ok(msg):
    print(f'  OK    {msg}')


def bad(msg, fix):
    print(f'  FAIL  {msg}\n        -> {fix}')
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--token', help='Storyblok personal access token (sb_pat_...)')
    a = ap.parse_args()
    good = True

    if sys.version_info < (3, 10):
        return bad(f'Python {sys.version.split()[0]}', 'install Python 3.10 or newer')
    ok(f'Python {sys.version.split()[0]}')

    for mod, pkg in (('bs4', 'beautifulsoup4'), ('requests', 'requests'), ('html5lib', 'html5lib')):
        try:
            importlib.import_module(mod)
            ok(f'package {pkg}')
        except ImportError:
            good = bad(f'package {pkg} missing', 'pip install -r requirements.txt  (from the repo root)')
    if not good:
        return False

    if a.token:
        cfg = json.load(open(CFG if os.path.exists(CFG) else EXAMPLE, encoding='utf-8'))
        cfg.update({'space_id': SPACE, 'management_token': a.token.strip()})
        json.dump(cfg, open(CFG, 'w', encoding='utf-8'), indent=2)
        ok(f'wrote {CFG} (gitignored)')
    if not os.path.exists(CFG):
        return bad('no config/storyblok.json',
                   'python setup_check.py --token <your sb_pat_ token>  '
                   '(Storyblok -> My account -> Personal access tokens)')
    cfg = json.load(open(CFG, encoding='utf-8'))
    if not str(cfg.get('management_token', '')).startswith('sb_pat_'):
        return bad('config/storyblok.json has no sb_pat_ token', 'python setup_check.py --token <token>')

    sys.path.insert(0, HERE)
    from create_pages import SB
    sb = SB()
    r = sb.call('GET', '')
    if r.status_code != 200:
        return bad(f'Storyblok answered HTTP {r.status_code}',
                   'the token is wrong, expired or rotated -- make a new one and rerun with --token')
    ok(f"Storyblok space {SPACE}: {r.json().get('space', {}).get('name')}")

    import fix_page as fp
    fp.ensure_components(sb, max_age_days=0 if a.token else 7)
    ok('live component schemas')
    for d in ('html', 'prepared'):
        os.makedirs(os.path.join(fp.FIX, d), exist_ok=True)
    os.makedirs(fp.BACKUP, exist_ok=True)
    ok(f'work folders ({fp.FIX})')

    try:
        import requests
        s = requests.get('https://www.aku.edu/Pages/home.aspx', timeout=30,
                         headers={'User-Agent': 'Mozilla/5.0'})
        ok(f'aku.edu answers (HTTP {s.status_code})') if s.status_code < 500 else \
            bad(f'aku.edu HTTP {s.status_code}', 'try again later; fix_page.py retries')
    except Exception as e:                       # noqa: BLE001 -- report, do not crash
        bad(f'aku.edu unreachable ({type(e).__name__})',
            'check the network/VPN; aku.edu drops connections, fix_page.py retries 8 times')

    print('\nReady. Give Claude an old aku.edu URL and the Storyblok editor URL.')
    return True


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
