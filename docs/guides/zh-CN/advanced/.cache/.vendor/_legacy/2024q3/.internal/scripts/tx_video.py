"""糖心系站点视频源抓取器。

原理: 站点是 Nuxt SSR，每个内容页 /post/subscription/<id> 的 SSR payload 里直接内嵌
      videos[].m3u8_url，形如 /api/m3u8/p/<32位hash>.m3u8。该地址返回标准 HLS 播放列表，
      分片为 https://mmb.igftwg.cn/<bucket>/m3u8/<id>/<hash>/<seg>-mN.ts?sign=...，
      密钥 https://mmb.igftwg.cn/<bucket>/m3u8/enc.key?sign=... （AES-128）。
      分片与密钥都带 sign 且会过期，所以必须现取现用，不能缓存 URL。

用法:
  python scripts\\tx_video.py index [--out recon\\posts.json]
  python scripts\\tx_video.py list [--keyword 关键词] [--limit 50]
  python scripts\\tx_video.py resolve <post_id 或 完整URL> [--json]
  python scripts\\tx_video.py playlist <post_id> [--index 1] [--out FILE]
  python scripts\\tx_video.py play <post_id> [--index 1]
  python scripts\\tx_video.py grab <post_id> [--index 1] [--out DIR]
"""
import sys, io, os, re, json, subprocess, shutil, tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='backslashreplace')

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')
SITES = ['http://txfansmm.com', 'https://txfans520.com', 'https://txinweb1.com']
SITEMAPS = ['/sitemap/sitemap_post.xml', '/sitemap/sitemap_movie.xml']
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, 'recon', 'posts.json')


def curl(url, timeout=30, referer=None, binary=False):
    args = ['curl.exe', '-sS', '-m', str(timeout), '-k', '-L', '-A', UA,
            '-w', '\n@@HTTP:%{http_code}@@']
    if referer:
        args += ['-H', 'Referer: ' + referer]
    args.append(url)
    r = subprocess.run(args, capture_output=True)
    raw = r.stdout
    body = raw.decode('utf-8', 'replace')
    m = re.search(r'\n@@HTTP:(\d+)@@$', body)
    code = ''
    if m:
        code = m.group(1)
        body = body[:m.start()]
    return code, (raw if binary else body)


def pick_site():
    for s in SITES:
        code, body = curl(s + '/', timeout=15)
        if code == '200' and len(body) > 5000:
            return s, body
    return None, ''


def load_index():
    if os.path.exists(INDEX):
        with open(INDEX, encoding='utf-8') as f:
            return json.load(f)
    return {'posts': []}


POST_RE = re.compile(r'/post/(?:detail|subscription)/([0-9a-zA-Z]+)')


def sitemap_walk(url, seen, depth=0, limit=200000):
    if depth > 3 or len(seen) >= limit:
        return
    code, body = curl(url, timeout=40)
    if code != '200':
        print('  %-56s http=%s' % (url[-56:], code))
        return
    locs = re.findall(r'<loc>(.*?)</loc>', body)
    nested = [l for l in locs if l.endswith('.xml')]
    print('  %-56s http=200 locs=%d nested=%d' % (url[-56:], len(locs), len(nested)))
    for l in locs:
        if l.endswith('.xml'):
            continue
        m = POST_RE.search(l)
        if m:
            kind = 'post' if '/post/detail/' in l else 'creator'
            seen.setdefault(m.group(1), {'id': m.group(1), 'url': l, 'kind': kind})
    for l in nested:
        sitemap_walk(l, seen, depth + 1, limit)


def cmd_index(out):
    site, _ = pick_site()
    if not site:
        print('所有站点都不可达')
        return
    print('site =', site)
    seen = {}
    for sm in SITEMAPS:
        sitemap_walk(site + sm, seen)
    rows = sorted(seen.values(), key=lambda x: x['url'])
    data = {'site': site, 'posts': rows}
    os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print('indexed %d entries -> %s' % (len(rows), out))


def cmd_list(keyword, limit):
    data = load_index()
    rows = data.get('posts', [])
    if keyword:
        rows = [r for r in rows if keyword in r.get('title', '') or keyword in r['id']]
    print('site=%s  entries=%d' % (data.get('site'), len(rows)))
    for r in rows[:limit]:
        print('  %-8s %-6s %s' % (r['id'], r.get('kind', ''), r.get('title', '')))


def post_url(site, ref):
    if ref.startswith('http'):
        return ref
    if ref.isdigit():
        return '%s/post/subscription/%s' % (site, ref)
    return '%s/post/detail/%s' % (site, ref)


def cmd_resolve(ref, as_json):
    site, _ = pick_site()
    if not site:
        print('所有站点都不可达')
        return
    url = post_url(site, ref)
    code, body = curl(url, referer=site + '/')
    if code != '200':
        print('http=%s  %s' % (code, url))
        return
    title = re.search(r'<title>(.*?)</title>', body, re.S)
    title = title.group(1).strip() if title else ''
    found = sorted(set(re.findall(r'/api/m3u8/p/[0-9a-f]{32}\.m3u8', body)))
    out = {'url': url, 'title': title, 'site': site, 'playlists': [site + f for f in found]}
    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return out
    print('页面:', url)
    print('标题:', title)
    print('播放列表 %d 条:' % len(out['playlists']))
    for i, p in enumerate(out['playlists'], 1):
        print('  [%d] %s' % (i, p))
    return out


def fetch_playlist(site, pl_url, out_path=None):
    code, body = curl(pl_url, referer=site + '/')
    if code != '200':
        print('取播放列表失败 http=%s %s' % (code, pl_url))
        return None
    if out_path:
        with open(out_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(body)
        print('已写入 %s (%d 字节)' % (out_path, len(body)))
    segs = re.findall(r'^(https?://\S+\.ts\?\S+)$', body, re.M)
    print('分片数 %d' % len(segs))
    if segs:
        print('示例分片 %s' % segs[0])
    return body


def cmd_playlist(ref, idx, out):
    info = cmd_resolve(ref, True)
    if not info or not info['playlists']:
        return
    n = max(1, min(idx, len(info['playlists'])))
    pl = info['playlists'][n - 1]
    print('选中 [%d] %s' % (n, pl))
    if not out:
        out = os.path.join(ROOT, 'build', 'play_%s_%d.m3u8' % (re.sub(r'\W', '_', ref)[-12:], n))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fetch_playlist(info['site'], pl, out)
    print('本地播放列表: %s' % out)


def cmd_play(ref, idx):
    info = cmd_resolve(ref, True)
    if not info or not info['playlists']:
        return
    n = max(1, min(idx, len(info['playlists'])))
    pl = info['playlists'][n - 1]
    print('播放 [%d] %s' % (n, pl))
    for exe, args in (('mpv', ['--no-config']), ('vlc', []), ('PotPlayerMini64', [])):
        p = shutil.which(exe)
        if p:
            subprocess.Popen([p] + args + [pl])
            print('已交给播放器:', exe)
            return
    print('未找到 mpv/vlc/PotPlayer，直接把上面的地址粘进播放器即可。')


def cmd_grab(ref, idx, outdir):
    info = cmd_resolve(ref, True)
    if not info or not info['playlists']:
        return
    n = max(1, min(idx, len(info['playlists'])))
    pl = info['playlists'][n - 1]
    ff = shutil.which('ffmpeg')
    if not ff:
        print('未找到 ffmpeg，无法直接下载；可用播放列表地址交给下载器：')
        print('  ' + pl)
        return
    os.makedirs(outdir, exist_ok=True)
    name = re.sub(r'[\\/:*?"<>|]', '_', info['title'] or ref)[:60]
    target = os.path.join(outdir, '%s_%d.mp4' % (name, n))
    print('ffmpeg -> %s' % target)
    subprocess.run([ff, '-y', '-headers', 'Referer: %s/\r\n' % info['site'],
                    '-i', pl, '-c', 'copy', '-bsf:a', 'aac_adtstoasc', target])


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return
    mode = a[0]
    kw = {}
    i = 1
    while i < len(a):
        if a[i].startswith('--'):
            k = a[i][2:]
            if i + 1 < len(a) and not a[i + 1].startswith('--'):
                kw[k] = a[i + 1]
                i += 2
            else:
                kw[k] = '1'
                i += 1
        else:
            kw.setdefault('_', a[i])
            i += 1
    ref = kw.get('_', '')
    if mode == 'index':
        cmd_index(kw.get('out', INDEX))
    elif mode == 'list':
        cmd_list(kw.get('keyword', ''), int(kw.get('limit', 50)))
    elif mode == 'resolve':
        cmd_resolve(ref, kw.get('json'))
    elif mode == 'playlist':
        cmd_playlist(ref, int(kw.get('index', 1)), kw.get('out'))
    elif mode == 'play':
        cmd_play(ref, int(kw.get('index', 1)))
    elif mode == 'grab':
        cmd_grab(ref, int(kw.get('index', 1)), kw.get('out', os.path.join(ROOT, 'build', 'videos')))
    else:
        print(__doc__)


main()
