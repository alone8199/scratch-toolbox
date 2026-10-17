# 视频源（CDN）情报与抓取链路

## 结论先说

网页端是通的，不需要登录、不需要签名头、不需要 Referer，拿到 m3u8 就能播能下。
整条链路已实测跑通：内容页 → m3u8 → 签名分片 → AES-128 解密 → 合法 MPEG-TS。

## 链路

```
内容页 (Nuxt SSR)
  http://txfansmm.com/post/detail/<24位hex>        单条内容
  http://txfansmm.com/post/subscription/<数字id>   创作者页，含多条
      ↓ HTML 内嵌 SSR payload，videos[].m3u8_url
  /api/m3u8/p/<32位hash>.m3u8                      HLS 播放列表（每次请求 hash 都变）
      ↓
  #EXT-X-KEY:METHOD=AES-128,URI="https://mmb.igftwg.cn/<bucket>/m3u8/enc.key?sign=..." ,IV=0x...
  分片 https://mmb.igftwg.cn/<bucket>/m3u8/<xx>/<32位hash>/<seg>-mN.ts?sign=...
```

## CDN 与签名

- 分片与密钥主机：`mmb.igftwg.cn`
- 路径结构：`/<bucket>/m3u8/<2位前缀>/<32位hash>/<6位段名>-mN.ts`
- 密钥：`/<bucket>/m3u8/enc.key`，返回**正好 16 字节**（AES-128 原始密钥）
- `sign` 格式：`<10位unix时间戳>-<32位hex>-0-<32位hex>`，按 URL 逐个签发，**会过期**
- 无 `sign` 直接请求分片 → `403`（14 字节响应体）
- 分片实测：单个 `.ts` 可达 11.9 MB，`content-type: video/mp2t`
- **不校验 Referer**：带不带 `Referer: http://txfansmm.com/` 都返回 200

## 站点与线路

| 用途 | 主机 | 备注 |
| --- | --- | --- |
| 主站（fans） | `txfansmm.com` / `txfans520.com` | `txfans520.com` 提供完整 sitemap |
| 主站（vlog） | `txinweb1.com` | 首页标题「糖心官网」 |
| 线路分发页 | `tx050.tv` | HTML 用 `hex2bin()` 编码，解码后是 10 条线路列表 |
| 线路落地页 | `txv01.f8dg2b.com` … `txv10.mjjvv8hckz.com` | 同一份下载落地页，非视频源 |
| 广告联盟 | `official.3fqmp0-t1t1.cyou` | 与视频无关 |

`tx050.tv` 解码后给出的 10 条线路（2026-10 实测）：

```
txv01.f8dg2b.com   txv02.spdsg8.com   txv03.v70381jx.com  txv04.8c8uz3oz.com
txv05.00uwdyc.com  txv06.xeg8hwi.com  txv07.up9h4fqb.com  txv08.rt0bxk.com
txv09.mmvjy0b.com  txv10.mjjvv8hckz.com
```

## 索引来源

`https://txfans520.com/sitemap/sitemap.xml` 是 sitemapindex，指向
`sitemap/sitemap_post.xml` → 再指向 `sitemap/sitemap_post-0.xml`，后者含 **7389** 条
`/post/detail/<24位hex>` 链接。`sitemap_movie.xml` 当前为空。

## 内容形态（重要）

网页端每条内容给出 1～11 个播放列表，**单个列表时长 8～76 秒**，属于短片段/预览，
不是完整长片。实测样本：

```
兔酱是个甜妹   11 条：15.7s / 75.9s / 7.9s / 36.4s / 41.3s / 29.1s / 10.6s / 26.2s / 66.2s / 16.4s / 33.9s
秋元            7 条：49.7s / 70.9s / 22.2s / 50.3s / 35.9s / 33.9s / 60.2s
```

完整版在 App 内走付费/金币解锁，网页端不发放。

## 工具

`scripts/tx_video.py`

```bash
python scripts/tx_video.py index                                    # 建索引 → recon/posts.json
python scripts/tx_video.py resolve 6aa7c3b91b62fbaf2402d414         # 列播放列表
python scripts/tx_video.py playlist 6aa7c3b91b62fbaf2402d414 -index 2   # 存本地 m3u8
```

`scripts/tx_dl.py`（自带解密，不依赖 ffmpeg）

```bash
python scripts/tx_dl.py 513701 --index 3                  # 下第 3 条 → build/videos/*.ts
python scripts/tx_dl.py 513701 --all --workers 8          # 该内容全部
python scripts/tx_dl.py --m3u8 "http://txfansmm.com/api/m3u8/p/<hash>.m3u8"
python scripts/tx_dl.py 513701 --index 3 --mp4            # 有 ffmpeg 时顺带转 mp4
```

## 验证记录

`python scripts/tx_dl.py 513701 --index 3` →
`build/videos/兔酱是个甜妹_3.ts`，31499588 字节，`size % 188 == 0`，
167551/167551 个 TS 包同步字节 `0x47` 全部命中，偏移 0 为 PAT、376 为 PMT。
即解密与拼接字节级正确，任意播放器可直接打开。

## 失效应对

- 播放列表 hash 每次都变，别当稳定 ID 存。
- 分片 `sign` 过期后整条列表作废，重新 `resolve` 一次即可。
- 主站换域名时，按 `SITES` 列表顺序回退；`tx050.tv` 是线路总入口。
