"""URL 规整小工具。"""
import sys
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

TRACKING = ('utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
            'spm', 'from', 'share_token', 'ref')


def normalize(url, strip_tracking=True, lower_host=True):
    if '://' not in url:
        url = 'https://' + url
    s = urlsplit(url)
    scheme = s.scheme.lower()
    netloc = s.netloc
    if lower_host:
        userinfo, _, host = netloc.rpartition('@')
        host = host.lower()
        netloc = (userinfo + '@' + host) if userinfo else host
    path = '/'.join(p for p in s.path.split('/') if p) or '/'
    if s.path.startswith('/'):
        path = '/' + path.lstrip('/')
    q = parse_qsl(s.query, keep_blank_values=True)
    if strip_tracking:
        q = [(k, v) for k, v in q if k not in TRACKING]
    q.sort()
    return urlunsplit((scheme, netloc, path, urlencode(q), ''))


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        print('example: python url_normalize.py "Example.COM//a//b?utm_source=x"')
        return
    for a in args:
        print(normalize(a))


if __name__ == '__main__':
    main()
