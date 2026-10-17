"""把内容页的 HLS 流落盘成可播放的 .ts（可选再转 mp4）。

不依赖 ffmpeg：自己取 m3u8、取 AES-128 密钥、逐分片解密、按顺序拼接。

用法:
  python scripts\\tx_dl.py <post_id 或 URL> [--index N] [--all] [--out DIR] [--workers 8]
  python scripts\\tx_dl.py --m3u8 <播放列表URL> [--out DIR]

说明:
  - 分片与密钥的 URL 都带 sign，会过期；所以每次都现取现下，不要复用旧 m3u8。
  - 站点是 Nuxt SSR，内容页 HTML 直接内嵌 /api/m3u8/p/<hash>.m3u8，无需登录、无需签名头。
  - CDN 分片不校验 Referer。
"""
import sys, io, os, re, json, time, subprocess, argparse, shutil
from concurrent.futures import ThreadPoolExecutor

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='backslashreplace')

from Crypto.Cipher import AES

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')
SITES = ['http://txfansmm.com', 'https://txfans520.com', 'https://txinweb1.com']
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def curl_bytes(url, timeout=120, retries=3):
    last = b''
    for i in range(retries):
        r = subprocess.run(['curl.exe', '-sS', '-m', str(timeout), '-k', '-L', '-A', UA,
                            '-o', '-', url], capture_output=True)
        if r.returncode == 0 and r.stdout:
            return r.stdout
        last = r.stdout
        time.sleep(1 + i)
    return last


def curl_text(url, timeout=40):
    return curl_bytes(url, timeout, 2).decode('utf-8', 'replace')


def pick_site():
    for s in SITES:
        body = curl_text(s + '/', 15)
        if len(body) > 5000:
            return s
    return SITES[0]


def resolve(site, ref):
    url = ref if ref.startswith('http') else (
        '%s/post/subscription/%s' % (site, ref) if ref.isdigit()
        else '%s/post/detail/%s' % (site, ref))
    html = curl_text(url)
    title = re.search(r'<title>(.*?)</title>', html, re.S)
    title = title.group(1).strip() if title else ref
    title = re.sub(r'\s*-\s*糖心.*$', '', title)
    pls = sorted(set(re.findall(r'/api/m3u8/p/[0-9a-f]{32}\.m3u8', html)))
    return title, [site + p for p in pls]


def parse_m3u8(text, base):
    keys = {}
    seq = 0
    cur = None
    segs = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('#EXT-X-MEDIA-SEQUENCE:'):
            seq = int(line.split(':', 1)[1])
        elif line.startswith('#EXT-X-KEY:'):
            attrs = dict(re.findall(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)', line[7:]))
            method = attrs.get('METHOD', '').strip('"')
            if method == 'AES-128':
                uri = attrs['URI'].strip('"')
                if not uri.startswith('http'):
                    uri = base + uri if uri.startswith('/') else base + '/' + uri
                iv = attrs.get('IV', '').strip('"')
                cur = (uri, iv)
            else:
                cur = None
        elif line.startswith('#EXTINF:'):
            pass
        elif line and not line.startswith('#'):
            if not line.startswith('http'):
                line = base + line if line.startswith('/') else base + '/' + line
            segs.append((len(segs), line, cur))
    return segs


def iv_for(iv_str, index, seq):
    if iv_str:
        h = iv_str[2:] if iv_str.lower().startswith('0x') else iv_str
        return bytes.fromhex(h.rjust(32, '0'))
    return (seq + index).to_bytes(16, 'big')


def strip_pad(data):
    if not data:
        return data
    n = data[-1]
    if 1 <= n <= 16 and data[-n:] == bytes([n]) * n:
        return data[:-n]
    return data


def download(m3u8_url, out_path, workers=8):
    text = curl_text(m3u8_url)
    if not text.lstrip().startswith('#EXTM3U'):
        print('  播放列表无效:', text[:120])
        return False
    base = re.match(r'(https?://[^/]+)', m3u8_url).group(1)
    segs = parse_m3u8(text, base)
    durs = [float(x) for x in re.findall(r'#EXTINF:([\d.]+)', text)]
    if not segs:
        print('  没有分片')
        return False
    print('  分片 %d 个，总时长 %.1f 秒' % (len(segs), sum(durs)))

    keycache = {}

    def get_key(uri):
        if uri not in keycache:
            keycache[uri] = curl_bytes(uri, 60)
        return keycache[uri]

    def one(item):
        idx, url, keyinfo = item
        raw = curl_bytes(url, 300)
        if keyinfo:
            key = get_key(keyinfo[0])
            if len(key) not in (16, 24, 32):
                raise RuntimeError('密钥长度异常 %d' % len(key))
            iv = iv_for(keyinfo[1], idx, 0)
            raw = AES.new(key, AES.MODE_CBC, iv).decrypt(raw)
            raw = strip_pad(raw)
        return idx, raw

    parts = [None] * len(segs)
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for idx, data in ex.map(one, segs):
            parts[idx] = data
            done += 1
            if done % 10 == 0 or done == len(segs):
                print('    已取 %d/%d' % (done, len(segs)), end='\r')
    print()
    if any(p is None for p in parts):
        print('  有分片下载失败')
        return False
    blob = b''.join(parts)
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    with open(out_path, 'wb') as f:
        f.write(blob)
    print('  写出 %s  %.2f MB' % (out_path, len(blob) / 1048576.0))
    return True


def maybe_mp4(ts_path):
    ff = shutil.which('ffmpeg')
    if not ff:
        return None
    mp4 = os.path.splitext(ts_path)[0] + '.mp4'
    r = subprocess.run([ff, '-y', '-loglevel', 'error', '-i', ts_path,
                        '-c', 'copy', '-bsf:a', 'aac_adtstoasc', mp4],
                       capture_output=True)
    if r.returncode == 0 and os.path.exists(mp4):
        return mp4
    return None


def safe(name):
    return re.sub(r'[\\/:*?"<>|]', '_', name)[:70]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('ref', nargs='?')
    ap.add_argument('--m3u8')
    ap.add_argument('--index', type=int, default=0)
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--out', default=os.path.join(ROOT, 'build', 'videos'))
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--mp4', action='store_true')
    a = ap.parse_args()

    if a.m3u8:
        name = re.search(r'p/([0-9a-f]{32})', a.m3u8)
        out = os.path.join(a.out, (name.group(1) if name else 'stream') + '.ts')
        download(a.m3u8, out, a.workers)
        return

    if not a.ref:
        ap.error('需要 post id/URL 或 --m3u8')

    site = pick_site()
    print('站点:', site)
    title, pls = resolve(site, a.ref)
    print('标题:', title)
    print('播放列表 %d 条' % len(pls))
    if not pls:
        return

    picks = list(range(len(pls))) if a.all else [max(0, min(a.index - 1, len(pls) - 1)) if a.index else 0]
    for n in picks:
        out = os.path.join(a.out, '%s_%d.ts' % (safe(title), n + 1))
        print('[%d/%d] %s' % (n + 1, len(pls), pls[n]))
        if download(pls[n], out, a.workers) and a.mp4:
            mp4 = maybe_mp4(out)
            if mp4:
                print('  转 mp4:', mp4)


if __name__ == '__main__':
    main()
