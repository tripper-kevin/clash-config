# clash-config

Clash Verge Rev 的 Merge（全局扩展）配置文件备份。

## Merge.yaml 变更记录

### 2026-11-03

| 项 | 旧值 | 新值 |
| --- | --- | --- |
| `dns.fake-ip-range6` | `fdfe:dcba:9876::1/64` | `2001:2::0/64` |
| `proxy-groups` 共用模板 `&auto.interval` | `1800` | `3600` |

- **`dns.fake-ip-range6`**：IPv6 fake-ip 网段改为 `2001:2::/64`。
- **`proxy-groups` 中 `&auto` 锚点的 `interval`**：`url-test` 健康检查间隔 30min → 60min。
  影响 🇭🇰 香港 / 🇨🇳 台湾 / 🇯🇵 日本 / 🇸🇬 新加坡 / 🇺🇸 美国 / ⚡ 自动选择 共 6 个组；
  `🔄 故障转移`（fallback，`interval: 600`）不受影响。
- 其余内容（`rules`、`nameserver-policy`、各业务策略组、`exclude-filter`）未改动。

> 本地文件由 Clash Verge Rev 以 CRLF 保存，仓库内统一为 LF。
