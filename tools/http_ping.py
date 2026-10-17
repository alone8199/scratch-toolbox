"""批量探测 URL 可达性。

用法:
    python http_ping.py urls.txt [--timeout 10] [--ua UA]
    python http_ping.py --inline https://a.com https://b.com
"""
import sys
import subprocess
import argparse


def probe(url, timeout=10, ua='curl/8'):
    r = subprocess.run(
        ['curl', '-sS', '-o', '/dev/null' if sys.platform != 'win32' else 'NUL',
         '-m', str(timeout), '-A', ua,
         '-w', '%{http_code}\t%{time_total}\t%{content_type}\t%{size_download}',
         url],
        capture_output=True, text=True)
    out = (r.stdout or '').strip()
    if not out:
        return '000', '-', '-', '-'
    parts = out.split('\t')
    while len(parts) < 4:
        parts.append('-')
    return tuple(parts[:4])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src', nargs='?', help='每行一个 URL 的文件')
    ap.add_argument('--inline', nargs='*', default=None)
    ap.add_argument('--timeout', type=int, default=10)
    ap.add_argument('--ua', default='curl/8')
    a = ap.parse_args()

    urls = a.inline or []
    if a.src:
        with open(a.src, encoding='utf-8') as f:
            urls += [l.strip() for l in f if l.strip() and not l.startswith('#')]
    if not urls:
        ap.error('没有输入')

    print('%-6s %-8s %-26s %-10s %s' % ('CODE', 'TIME', 'TYPE', 'BYTES', 'URL'))
    for u in urls:
        code, t, ct, size = probe(u, a.timeout, a.ua)
        print('%-6s %-8s %-26s %-10s %s' % (code, t, ct[:26], size, u))


if __name__ == '__main__':
    main()
