# scratch-toolbox

零散小工具集合。平时写脚本时反复用到的几个函数抽出来放一起，免得每次翻旧项目。

## 内容

- `tools/http_ping.py` —— 批量探测 URL 可达性，输出状态码 / 响应时间 / content-type。
- `tools/url_normalize.py` —— URL 规整：补协议、去重复斜杠、统一大小写、去追踪参数。

## 用法

```bash
python tools/http_ping.py urls.txt
python tools/url_normalize.py "Example.COM//a//b?utm_source=x"
```

## 环境

Python 3.10+，无第三方依赖。网络请求走系统 `curl`，省得装 requests。

## 说明

代码风格不统一，属于随手记性质，能用就行。
