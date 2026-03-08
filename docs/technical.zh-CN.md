# 技术文档

## 项目目标
`obsidian-knowledge-ingestor` 是一个本机优先的学习型项目，目标是把：
- 知乎内容
- 微信公众号内容

采集下来，统一规范化成 Markdown，写入 Obsidian Vault，然后只通过官方 Obsidian CLI 给 agent 使用。

这个项目的重点不是“炫技爬虫”，而是稳定边界、可验证结果和可持续迭代。

## 技术栈
- 运行时：Python 3
- 包管理：`pyproject.toml`
- 浏览器自动化：Playwright
- HTML 解析与清洗：BeautifulSoup + 仓库内 HTML 工具
- 存储形态：Obsidian Vault 中的 Markdown + YAML frontmatter
- 状态管理：`Sources/_state` 下的 JSON 状态文件

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
  - `qa_runner.py`：官方 Obsidian CLI 封装
  - `verification.py`：抓取后校验逻辑
- `docs/`：架构、计划、技术文档
- `samples/`：样例 target 配置
- `targets/`：本地真实目标配置
- `tests/`：单元测试

## 数据流
```text
知乎 / 微信公众号
  -> adapter.fetch_source()
  -> RawItem
  -> normalize()
  -> CanonicalNote
  -> write_note()
  -> Obsidian Vault
  -> query_vault()
```

## 核心接口
项目固定了四个核心逻辑接口：
- `fetch_source(target, auth_ctx, since) -> raw_items[]`
- `normalize(raw_item) -> canonical_note`
- `write_note(canonical_note, vault_path) -> note_path`
- `query_vault(prompt, scope) -> results`

这四个接口就是系统边界。底层实现以后可以继续换，但这层契约不应该乱变。

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
知乎页面经常会把推荐回答、互动内容、别人的 pin 暴露出来。现在系统已经加了作者归属校验，只有目标作者本人的内容才会真正入库。

### 抓取后校验
知乎校验不是只看“总共抓了多少”，而是分三层：
- `profile_counts`：主页头部显示的数字
- `accessible_counts`：当前登录态下实际可访问列表暴露出的数量
- `vault_counts`：真正落盘到 Obsidian 的数量

这样设计是为了把“源站展示统计”和“当前能抓到的内容”区分开。

对 `lin-lin-98-23` 这个真实样本，目前系统观测到：
- 主页头部：`27 回答 / 3 文章 / 60 想法`
- 可访问列表：`26 回答 / 3 文章 / 60 想法`
- Vault 落盘：`26 回答 / 3 文章 / 60 想法`

这说明：
- 系统对“可访问内容”的采集和落盘已经一致
- 但知乎主页头部统计和实际可访问回答列表之间，仍然存在 `1` 条差异

系统现在会把这种情况标成 `warn`，而不是错误地当成全量成功，或者错误地判定采集失败。

## 微信公众号实现
公众号当前支持：
- 以文章 URL 作为种子抓取
- 复用浏览器会话抓页面
- `discover wechat`：从可访问的 seed 文章反推出 `mp/profile_ext?action=getmsg`，再做分页历史发现
- 抓取过程中流式落盘，而不是整批抓完后再统一写 Markdown
- 基于 state 的验证后续跑

这里要明确两点：
- 本地微信缓存已经不再被当成“历史文章发现结果”
- 它现在只用于恢复带 `key`、`pass_ticket` 等参数的 seed URL，帮助系统打开 `profile_ext/getmsg`

也就是说，真正的历史列表来源是 `profile_ext/getmsg`，不是缓存里碰巧出现过的文章链接。

因此，当前版本已经可以对“能从 seed 文章打开可用历史接口”的公众号做程序化历史发现；但仍然不能声称“任意公众号都能自动全量回溯历史文章”。

### 公众号详细技术路线
当前可用路线被明确拆成两个阶段。

第一阶段：历史发现
1. 从一个或多个可访问的 seed 文章开始。
2. 尽量恢复完整文章 URL，包括 `__biz`、`uin`、`key`、`pass_ticket`。
3. 抓文章 HTML，从中提取 `appmsg_token`。
4. 用这些参数调用 `mp/profile_ext?action=getmsg`。
5. 解析 `general_msg_list`，把单图文和多图文都展开成统一 URL 队列。

第二阶段：正文入库
1. 把发现到的文章 URL 队列交给浏览器驱动的 WeChat adapter。
2. 对 query 形式的文章 URL，用 `mid + idx + sn` 生成稳定的 `content_id`。
3. 每抓到一篇就立刻 `normalize`。
4. 每 `normalize` 完一篇就立刻写 Markdown 和 state，不等整批结束。

为什么要这样拆：
- 历史发现和正文抓取的失败原因不同
- 历史发现是否成功，可以先看 URL 队列总数
- 正文抓取如果被打断，可以只依赖 `Sources/_state` 从剩余 URL 继续

### 验证后的续跑机制
当微信中途返回验证页时：
1. 当前这篇不会写入
2. 已经写入的篇目仍然留在 vault
3. state 里已经记录了完成的 `content_id`
4. CLI 会根据原始 target 和当前 state 重新计算剩余 URL
5. 然后只对剩余 URL 继续重试

这不是验证码破解，而是围绕人工验证边界做故障恢复。

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
当前 CLI：
- `oki auth <source>`
- `oki ingest <source> --target <file>`
- `oki discover wechat --target <file>`
- `oki verify zhihu --target <file> --vault <path>`
- `oki search <query>`
- `oki read <note-path>`
- `oki ask <prompt>`

## 测试覆盖
当前自动化测试主要覆盖：
- 正规化
- Vault 写入
- 增量跳过逻辑
- 微信验证墙识别
- 微信 query 文章 URL 的 `content_id` 稳定性
- 微信历史发现解析
- 知乎浏览器发现
- 知乎作者归属过滤
- 知乎校验状态分类

运行测试：
```bash
cd /Users/haoyuebai/Dev/ai/obsidian-knowledge-ingestor
source .venv/bin/activate
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## 当前限制
- 不做验证码自动破解
- 不保证完全无人值守的长期登录态刷新
- 对那些无法从 seed 文章打通 `profile_ext/getmsg` 的公众号，历史全量回补仍然没有通用解
- 知乎回答总数可能出现“主页头部统计”和“可访问列表”不一致
- 当前校验证明的是“Vault 与可访问内容一致”，不是证明“平台绝对全量可抓”

## 为什么这项目值得学
这个项目比较适合作为学习项目，因为它同时覆盖了：
- 浏览器驱动采集
- 抗脆弱的 adapter 设计
- 统一文档模型
- Markdown 知识库生成
- 面向 Vault 的 agent 检索
- 抓取后验证，而不是只会“爬完就算”
