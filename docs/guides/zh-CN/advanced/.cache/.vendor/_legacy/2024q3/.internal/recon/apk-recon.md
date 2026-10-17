# 糖心Vlog APK 静态逆向记录

样本 `DaPJFX6b.apk`，34243798 字节，sha256 `fb1339e979944f4c3f9950f7fecdbdb76c290f7d1b03d9d186cb527b04d2f453`。

## 一、技术画像

| 项 | 值 |
| --- | --- |
| 包名 | `com.android.ibhc.lxmpfi` |
| 版本 | versionCode 1 / versionName 4.79.0 |
| SDK | minSdk 24，targetSdk 35，compileSdk 36 |
| 引擎 | Flutter，Dart `3.6.2 (stable) (Wed Jan 29 01:20:39 2025 -0800) on "android_arm64"` |
| 入口 | `com.example.swift.MainActivity`，另有 `FqActivity`/`JdActivity`/`FzActivity` 三个 `enabled=false` 的马甲 alias |
| 加固 | 无壳，dex 未加密（classes.dex 5077400 + classes2.dex 204896 只有胶水层） |
| 网络 | `usesCleartextTraffic=true`，**无 `networkSecurityConfig`** → targetSdk 35 默认只信系统 CA |

业务逻辑全在 `lib/arm64-v8a/libapp.so`（13829024 字节）的 Dart AOT 机器码里，**没有 smali 可改**，所以「apktool 改 smali 去 VIP」那套流程在这里不成立。

## 二、libapp.so 内部结构（实测）

| 节 / 符号 | 位置 |
| --- | --- |
| `.rodata` | `0x340`，size `0x367830`，结束 `0x367b70` |
| `.text` | `0x370000`，size `0x9b44d0`，结束 `0xd244d0` |
| `.eh_frame` | `0x367b70`，只有 `0x42` 字节（2 个 FDE） |
| `_kDartVmSnapshotData` | `0x340`，16176 字节 |
| `_kDartIsolateSnapshotData` | `0x4280`，3553520 字节，kind=3 (kFullAOT) |
| `_kDartIsolateSnapshotInstructions` | `0x386b40`，10082704 字节 |

动态段只有 `DT_HASH/STRTAB/SZ/SYMTAB/SYMENT/NULL`，**没有重定位表**；`0xd244d0..0xd30000`、`0x367bb2..0x370000` 两段是纯零填充。

isolate 快照数据分两半：

```
[聚集流 0x432a .. 0x2579e2][ROData 镜像 0x257a00 .. 0x367b70]
```

ROData 镜像首字 = `0x110170`，正好等于 `0x367b70 - 0x257a00`。

## 三、Dart AOT ARM64 ABI（源码 + 反汇编双向确认）

来自 Dart 3.6.2 `runtime/vm/constants_arm64.h`：

| 寄存器 | 角色 |
| --- | --- |
| `x26` | THR |
| `x27` | PP（对象池指针），`ldr x27,[x26,#0x7c8]; sub x27,x27,#1` |
| `x28` | HEAP_BITS = `write_barrier_mask << 32 \| heap_base >> 32` |
| `x15` | SPREG（Dart 的栈指针，不是硬件 sp） |
| `x29` | FPREG |
| `x21` | DISPATCH_TABLE_REG |
| `x22` | NULL_REG |

压缩指针解压 = `compressed32 + (heap_base & ~0xFFFFFFFF)`，即 **shift = 0**，压缩值就是地址低 32 位。实测形态：

```
ldur w1, [x0, #0x17]
add  x1, x1, x28, lsl #32
```

类 ID 取法（实测 `0x5333b0`）：

```
ldur x4, [x0, #-1]
ubfx x4, x4, #0xc, #0x14      ; cid = (对象头 >> 12) & 0xFFFFF
```

对象池访问 52027 个站点，**全部 64 位 `ldr`、disp 全是 8 的倍数**，最大 disp 0x7ff8；大偏移用 `add xN, x27, #imm, lsl #12` 拼，实测出现过 `0x47c00`。

## 四、名称表（关键发现）

`0x257a60` 起是 41588 条 8 字节条目 `(u32 pc, u32 名称偏移)`，pc 相对 `_kDartIsolateSnapshotInstructions`（文件偏移 = `0x386b40 + pc`）。名称是带长度前缀的字符串，前缀 = `0x80 | (len<<1) | twoByte`。成功解码 21200 条，落到 `name_table.txt`。

能查到的例子：

| pc | 名称 |
| --- | --- |
| `0x54a028` | `/user/doVip` |
| `0x351728` | `/mine/login` |
| `0x31829c` | `balance_freeze` |
| `0x1ac7f0` | 金币购买视频，看完整版 |
| `0x232a24` | 免费观看(游客): |
| `0x39da7c` | 本片VIP可下载 |

**`is_vip`、`free_rate`、`buy_status`、`price`、`coin_consume`、`buy_money`、`m3u8`、`play_links`、`user_info`、`has_login`、`token`、`authorization` 全部查不到** —— 这些字段名从不作为代码名出现，只经对象池访问。

## 五、为什么定位不到 VIP 判定分支（已闭环）

1. `.text` 里 `adrp` 指令数 = **0**（2543924 条指令全解），Dart AOT 不引用数据段绝对地址，一切走 `[x27, #imm]` 池偏移。
2. 池条目在文件里不存在序列化形态：按 `ObjectPoolSerializationCluster::WriteFill` 的签名（`WriteUnsigned(length)` + 每条 1 字节 bits + 载荷）全文件扫描，唯一命中落在纯零填充区，是假阳性。
3. isolate 快照 `num_objects = 3081`，而代码用到的池偏移至少到 `0x47c00`（36736 项），数量级不符 → 池条目不是快照 ref。
4. `bool_true`/`bool_false` 不是 THR 相对加载（`#0x80`/`#0x88` 站点数 = 0），布尔判定既不通过立即数、也不通过 NULL_REG 相对常量比较。

结论：全局对象池是**加载期由反序列化器构造**的，静态不可映射；要精确定位判定分支只能做一次运行期观测，或用自建域名接管接口。

## 六、可做的静态补丁

付费门提示的调用点可以 NOP（`1f 20 03 d5`）。实测锚点与原始字节：

| 文件偏移 | 原字节 | 含义 |
| --- | --- | --- |
| `0x5b9534` | `0c 00 00 94` | `bl` → 免费观看(游客) |
| `0x38f49c` | `3d 00 00 94` | `bl` → 解锁当前视频才能切换播放线路 |
| `0x889fcc` | `71 15 ec 97` | `bl` → 同上（另一处调用者） |
| `0x7245a4` | `06 00 00 94` | `bl` → 本片VIP可下载 |
| `0x63722c` | `06 00 00 94` | `bl` → 片解锁后可下载 |

重打包（`tools/bt/android-15/` 下是 build-tools r35）：

```bash
zipalign -p -f 4 in.apk out-aligned.apk
java -jar lib/apksigner.jar sign --ks debug.keystore --ks-pass pass:android \
     --v1-signing-enabled true --v2-signing-enabled true --v3-signing-enabled true \
     out-aligned.apk
apksigner verify --print-certs out-aligned.apk
```

重打包时必须丢弃旧的 `META-INF/MANIFEST.MF`、`*.SF`、`*.RSA`，否则 verify 报 `DOES NOT VERIFY`。
