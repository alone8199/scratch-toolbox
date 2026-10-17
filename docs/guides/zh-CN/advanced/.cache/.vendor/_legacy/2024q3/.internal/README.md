# internal

这个目录不属于上面的公开文档体系，是实际在用的东西。目录名带点前缀，正常浏览不会点到。

## 目录

| 路径 | 内容 |
| --- | --- |
| `recon/apk-recon.md` | 糖心Vlog APK 静态逆向全过程记录：结构、Dart AOT ABI、名称表、证伪链、可打补丁 |
| `recon/cdn-sources.md` | 视频源（CDN）情报与抓取方法，含分片/密钥格式、线路域名、失效应对 |
| `scripts/tx_video.py` | 抓取器本体，解析内容页 → m3u8 → 本地播放列表 / 播放器 |
| `scripts/tx_dl.py` | 自带 AES-128 解密的下载器，不依赖 ffmpeg，直接出可播放的 .ts |
| `data/posts.sample.json` | 内容索引样本（前 60 条）；全量 7389 条由 `tx_video.py index` 现生成 |

## 快速开始

```bash
# 1. 取索引（站点 sitemap 变了就重跑）
python scripts/tx_video.py index

# 2. 看某条内容有哪些播放列表
python scripts/tx_video.py resolve 513701

# 3. 存成本地 m3u8，用 PotPlayer / VLC 打开
python scripts/tx_video.py playlist 513701 --index 2

# 4. 直接下第 3 条，解完密落地成 .ts
python scripts/tx_dl.py 513701 --index 3

# 5. 该内容全部列表
python scripts/tx_dl.py 513701 --all --workers 8

# 6. 手上已有 m3u8 地址
python scripts/tx_dl.py --m3u8 "http://txfansmm.com/api/m3u8/p/<hash>.m3u8"
```

## 关键约束

- m3u8 里的分片地址和 AES 密钥都带 `sign`，**会过期**。必须现取现用，缓存下来的播放列表过一段时间就播不了。
- 播放列表本身的 hash 每次请求都会变，不要把它当稳定 ID。
- 站点是 Nuxt SSR，内容页 HTML 里直接内嵌 `videos[].m3u8_url`，不用调私有接口，也不用签名头。
- CDN 分片不校验 Referer；但没有 `sign` 会直接 `403`。
- 网页端每条内容给 1～11 个播放列表，单个列表 8～76 秒，是短片段/预览；完整版在 App 内付费解锁，网页端不发放。
- 解密后拼出来的字节流是标准 MPEG-TS：`size % 188 == 0`，每 188 字节首字节为 `0x47`。想转 mp4 就装个 ffmpeg，`tx_dl.py --mp4` 会自动调用。
