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

## 自动同步（第三版：按用途直接替换）

唯一日常配置源是 `Merge.yaml`。提交到 `main` 后，GitHub Actions 自动生成并提交 `Merge.json`、`Shadowrocket.conf` 和 `conversion-report.json`。原来的 Clash YAML 不修改，JSON 是其完整解析结果。

小火箭版直接使用维护者发布的兼容规则集，以用途相近为准。AI、开发、社交、通信和学术采用多个规则集组合；个别没有独立现成集合的服务在映射文件里补充主要域名。**不再下载 MetaCubeX 数据库、不再转换 GeoSite 文本规则，也没有丢弃域名正则的流程。**

### 使用与更新

1. 将包内文件按原目录结构上传到仓库，尤其 `.github/workflows/yaml-to-json.yml`。
2. 在 Actions 中查看 `Sync client configurations`，也可用 `Run workflow` 手动运行。
3. 在小火箭单独导入节点订阅，再下载并启用下面的远程配置，使用配置模式：

`https://raw.githubusercontent.com/tripper-kevin/clash-config/main/Shadowrocket.conf`

GitHub 更新配置后，手机需更新远程配置。现成规则集使用维护者的实时链接；手机更新规则集后即可获取新版内容。生成时检查链接可下载、规则非空、规则类型可识别，并在报告中记录校验条数与摘要。

### 分流安排

- 保留原配置的业务分组与规则顺序；国内游戏资源仍先直连，随后匹配游戏平台。
- AI 使用 OpenAI、Anthropic、Claude、Gemini 与主要 AI 域名组合。
- 开发使用 Developer、GitHub、GitLab、Docker、Npmjs、Python、Jetbrains、Stackexchange、SourceForge、Atlassian。
- 国内学术用 CNKI、Wanfang、CAS、ShiJiChaoXing；国际学术用 GlobalScholar。
- 海外社交与通信使用对应平台规则组合。
- 中国域名用 ChinaMaxNoIP，随后保留 GEOIP,CN,DIRECT，最终出口仍按“其他”组。
- 同一规则和同一出口的重复项自动合并。

### 维护入口

`scripts/shadowrocket-rule-map.json` 的每项包含：

- `urls`：直接引用的远程 RULE-SET，可写多个。
- `rules`：补充的域名规则，不附出口；生成时沿用 YAML 对应策略。
- `note`：用途说明。

普通类别键对应 GEOSITE 名称，`geoip:private` 和 `geoip:telegram` 对应非国家 IP 分类。以后新增未映射的分类，构建会提示补充映射，不会静默丢掉。`scripts/**` 与测试、工作流变更同样触发生成。

### 平台处理

Windows 的 `PROCESS-NAME` 不写入 iPhone 配置，这是当前唯一按平台省略的规则类型。DNS 使用阿里/腾讯 DoH 基础配置，校园网内部解析可按需在小火箭另行适配。Clash 的 fake-ip、DNS 策略以及部分检测参数不移植；详细项在报告中。策略组保留 select/url-test/fallback 与名称筛选，超时从毫秒转为秒。节点需在小火箭单独导入。

脚本做了自动校验和转换测试，未做小火箭真机测试。固定节点需要在手动分组选择具体节点，并留意客户端“测试并选择最快服务器”选项。

### 工作流与本地运行

工作流需要仓库 contents: write 权限，使用 GitHub 自动令牌，无需个人访问令牌。分支保护若禁止机器人提交，则需改用 PR。推送冲突会从最新 main 重新生成后重试，避免把旧 YAML 的产物推到新版本上。

```sh
python -m pip install PyYAML==6.0.2
python -m unittest discover -s tests -v
python scripts/sync_configs.py
```

旧版 `shadowrocket-rules/*.list` 已停用，可以删除；工作流下次成功生成也会清理。目录里的 README 仅用于记录迁移。

### 规则来源

- [blackmatrix7/ios_rule_script 的 Shadowrocket 分类](https://github.com/blackmatrix7/ios_rule_script/tree/master/rule/Shadowrocket)
- [anti-ad 的 Surge 文本规则](https://anti-ad.net/surge.txt)
- 部分服务主要域名最初参照原配置所用的公开域名清单整理为静态补充；不会在构建时下载 GeoSite。

### 当前映射明细

| YAML 类别 | 小火箭规则或补充 |
| --- | --- |
| `private` | Lan |
| `steam` | Steam |
| `openai` | OpenAI |
| `anthropic` | Anthropic |
| `wikimedia` | Wikimedia |
| `netflix` | Netflix |
| `disney` | Disney |
| `hbo` | HBO |
| `primevideo` | PrimeVideo |
| `youtube` | YouTube |
| `tiktok` | TikTok |
| `bahamut` | Bahamut |
| `spotify` | Spotify |
| `google` | Google |
| `github` | GitHub |
| `onedrive` | OneDrive |
| `microsoft` | Microsoft |
| `apple` | Apple |
| `atlassian` | Atlassian |
| `sourceforge` | SourceForge |
| `reddit` | Reddit |
| `pinterest` | Pinterest |
| `snap` | Snap |
| `twitch` | Twitch |
| `cn` | ChinaMaxNoIP |
| `category-scholar-!cn` | GlobalScholar |
| `category-ads` | surge.txt |
| `category-games@cn` | SteamCN |
| `category-games-!cn` | Game |
| `category-ai-!cn` | OpenAI、Anthropic、Claude、Gemini、8 条域名补充 |
| `category-dev` | Developer、GitHub、GitLab、Docker、Npmjs、Python、Jetbrains、Stackexchange、SourceForge、Atlassian |
| `category-scholar-cn` | CNKI、Wanfang、CAS、ShiJiChaoXing |
| `category-social-media-!cn` | Twitter、Facebook、Instagram、Reddit、Pinterest、Snap、Threads |
| `category-communication` | Telegram、Whatsapp、Line、Discord、Slack、Teams、2 条域名补充 |
| `perplexity` | 5 条域名补充 |
| `cursor` | 5 条域名补充 |
| `huggingface` | 3 条域名补充 |
| `sci-hub` | 6 条域名补充 |
| `z-library` | 22 条域名补充 |
| `disney@cn` | 1 条域名补充 |
| `primevideo@cn` | 2 条域名补充 |
| `geoip:private` | Lan |
| `geoip:telegram` | Telegram |
