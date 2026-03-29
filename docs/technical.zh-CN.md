# 技术文档

## 项目目标
`obsidian-knowledge-ingestor` 是一个本机优先的 ingestion 项目，目标是把：
- 知乎内容
- 微信公众号内容

采集下来，统一规范化成 Markdown，并写入 Obsidian Vault。

仓库不再内建问答运行时。Vault 问答改由仓库内的 Obsidian QA plugin/skill 完成，底层要求仍然是官方 Obsidian CLI。

## 技术栈
- 运行时：Python 3
- 包管理：`pyproject.toml`
- 浏览器自动化：Playwright
- HTML 解析与清洗：BeautifulSoup + 仓库内 HTML 工具
- 存储形态：Obsidian Vault 中的 Markdown + YAML frontmatter
- 状态管理：`Sources/_state` 下的 JSON 状态文件
- 问答路径：仓库内 plugin/skill + 官方 Obsidian CLI

## 仓库结构
- `src/obsidian_knowledge_ingestor/`
  - `adapters/`
    - `zhihu.py`：知乎采集逻辑
    - `wechat.py`：公众号采集逻辑
    - `feed.py`：通用 feed / seed 辅助逻辑
  - `browser_automation.py`：浏览器登录态保存、页面发现与抓取
  - `normalizer.py`：统一文档模型转换
  - `vault_writer.py`：Markdown 落盘、资源下载、状态写入
  - `pipeline.py`：端到端采集流程编排
  - `verification.py`：抓取后校验逻辑
- `plugins/obsidian-qa/`：模型无关的 Obsidian QA plugin 和 skill
- `docs/`：架构、计划、技术文档
- `samples/`：样例 target 配置
- `targets/`：本地真实目标配置
- `tests/`：以 ingestion 为主的单元测试

## 数据流
```text
知乎 / 微信公众号
  -> adapter.fetch_source()
  -> RawItem
  -> normalize()
  -> CanonicalNote
  -> write_note()
  -> Obsidian Vault
  -> Obsidian QA plugin/skill
  -> 官方 Obsidian CLI
  -> agent 基于原始笔记回答
```

## 核心接口
当前仓库固定的 ingestion 接口只有：
- `fetch_source(target, auth_ctx, since) -> raw_items[]`
- `normalize(raw_item) -> canonical_note`
- `write_note(canonical_note, vault_path) -> note_path`

Python 包内部不再定义问答接口。问答逻辑被移到 plugin/skill 层。

## 知乎实现
知乎当前支持三种采集路径：
- 浏览器发现页面后抓取
- 登录态 API 驱动抓取
- 手工 seed URL / HTML 导入

### 为什么是浏览器 + API 混合
知乎对纯 HTTP 请求很不稳定，所以当前稳定做法是：
1. 通过 `oki auth zhihu` 保存真实浏览器登录态
2. 采集时复用这份登录态
3. 优先走 API 抓结构化内容
4. 必要时再走页面发现和页面抓取

### 作者归属过滤
知乎页面经常会暴露推荐回答或别人的 pin。现在系统会先做作者归属校验，只有目标作者本人的内容才会真正入库。

### 抓取后校验
知乎校验分三层：
- `profile_counts`：主页头部显示的数字
- `accessible_counts`：当前登录态下实际可访问列表暴露出的数量
- `vault_counts`：真正写入 vault 的数量

这样可以把“源站展示差异”和“采集是否正确”区分开。

## 微信公众号实现
公众号当前支持：
- 以文章 URL 作为种子抓取
- 复用浏览器会话抓页面
- `discover wechat`：从可访问的 seed 文章反推出 `mp/profile_ext?action=getmsg`，再做分页历史发现
- 抓取过程中流式落盘
- 基于 state 的验证后续跑

需要明确：
- 本地微信缓存不再被当成历史文章发现结果
- 它只用于恢复带 `key`、`pass_ticket` 等参数的 seed URL
- 真正的历史列表来源仍然是 `profile_ext/getmsg`

### 公众号详细技术路线
第一阶段：历史发现
1. 从一个或多个可访问的 seed 文章开始。
2. 尽量恢复完整文章 URL，包括 `__biz`、`uin`、`key`、`pass_ticket`。
3. 抓文章 HTML，从中提取 `appmsg_token`。
4. 用这些参数调用 `mp/profile_ext?action=getmsg`。
5. 解析 `general_msg_list`，把单图文和多图文展开成统一 URL 队列。

第二阶段：正文入库
1. 把发现到的文章 URL 队列交给浏览器驱动的 WeChat adapter。
2. 对 query 形式的文章 URL，用 `mid + idx + sn` 生成稳定的 `content_id`。
3. 每抓到一篇就立刻 `normalize`。
4. 每 `normalize` 完一篇就立刻写 Markdown 和 state。

### 验证后的续跑机制
当微信中途返回验证页时：
1. 当前这篇不会写入
2. 已经写入的篇目仍然留在 vault
3. state 里已经记录了完成的 `content_id`
4. CLI 会根据原始 target 和当前 state 重新计算剩余 URL
5. 然后只对剩余 URL 继续重试

## Obsidian 存储约定
Vault 目录结构固定为：
- `Sources/Zhihu/<author>/answers/*.md`
- `Sources/Zhihu/<author>/thoughts/*.md`
- `Sources/Zhihu/<author>/articles/*.md`
- `Sources/WeChat/<account>/*.md`
- `Sources/_assets/...`
- `Sources/_state/...`

每篇笔记包含：
- YAML frontmatter 元数据
- 清洗后的 Markdown 正文
- 原始 HTML 路径（如果有）
- 基于 checksum 的更新语义

## CLI 能力
当前 `oki` 只保留 ingestion 命令：
- `oki auth <source>`
- `oki ingest <source> --target <file>`
- `oki discover wechat --target <file>`
- `oki verify zhihu --target <file> --vault <path>`

任何 vault 问答都应改走仓库内的 Obsidian QA plugin/skill。

## Obsidian QA Plugin
这个 plugin 故意做得很薄：
- 不维护平行索引
- 不生成派生 scope 包
- 不维护 ask session 或 token usage 日志

它只给 agent 一个严格的工作流：
1. 明确问题和检索意图
2. 用多轮短查询执行 `obsidian search`
3. 用 `obsidian read` 打开命中的原始笔记
4. 只基于原始笔记证据输出回答

这样 vault 仍然是唯一真相来源，同时 `oki` 不再重复造一层问答产品。
