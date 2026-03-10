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
- 问答执行：本机 `codex` + 官方 Obsidian CLI + scope 派生包

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
  - `qa_builder.py`：scope 派生包生成
  - `scope_loader.py`：人物 scope 配置加载
  - `verification.py`：抓取后校验逻辑
- `docs/`：架构、计划、技术文档
- `scopes/`：人物级 scope 配置
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
  -> build-qa(scope)
  -> Derived/Scopes/<scope_id>/*.md
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
- `Derived/Scopes/<scope_id>/*.md`
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
- `oki build-qa --scope <scope_id>`
- `oki qa-search --scope <scope_id> --query <text>`
- `oki qa-read --path <note-path>`
- `oki qa-open-derived --scope <scope_id> --kind <kind>`
- `oki ask <prompt> --scope <scope_id>`

## 问答层实现
当前问答层仍然是 agentic 的，但 live 检索执行已经不再完全放给 Codex 自己乱跑：
1. `oki build-qa` 先为人物级 `scope` 生成派生包。
2. 程序负责生成确定性文件：
   - `manifest.md`
   - `corpus_index.md`
   - `full_context.md`
3. 本机 `codex` 负责生成高阶归纳文件：
   - `overview.md`
   - `themes.md`
4. `oki ask` 会先预加载该 `scope` 的派生地图。
5. 本机 `codex` 先生成结构化检索计划：
   - `question_reframing`
   - `query_plan[]`
6. 程序自己执行检索计划：
   - 多轮 `search_scope(...)`
   - 通过官方 Obsidian CLI 读取原始 note
   - 聚合并排序证据包
7. 本机 `codex` 再基于原始证据包生成最终长答。
8. 最终回答必须给：
   - 完整分析过程
   - 最终回答
   - 原始 note 引用

这里有一个边界要特别明确：
- 派生包只用于导航、全局理解和检索辅助
- 最终证据必须回到 `Sources/**` 下的原始 note
- scope 边界由 `scopes/*.json` 显式维护，不靠自动猜测

### 为什么 ask 主链路改了
更早版本的设计，是让 `codex exec` 自己决定什么时候调用 `qa-search`、`qa-read`、`qa-open-derived`。

这个思路理论上很优雅，但 live 跑下来不够稳：
- `codex exec` 里的多轮工具调用稳定性不够
- 官方 Obsidian CLI 由程序直接执行时更稳
- 最终回答深度会受“Codex 当次到底有没有搜够”影响

所以现在的设计是保留 agentic 的强项，把脆弱部分收回程序：
- Codex 负责理解问题
- Codex 负责重述问题、设计检索角度
- Codex 负责最终严肃长答
- Python 程序负责稳定执行 Vault 检索

### 当前 ask 执行模型
`oki ask --scope <scope_id>` 当前执行顺序是：
1. 检查 `Derived/Scopes/<scope_id>/` 是否存在
2. 预加载 `overview.md` 和 `themes.md`
3. 再按模式预加载：
   - `map` 模式只在 fallback 时再带上一份紧凑版 `corpus_index.md`
   - `fulltext` 模式加载 `full_context.md`
4. 让 Codex 先产出 JSON 检索计划
5. 程序对计划做规范化，并补上从用户问题派生出的 fallback queries
6. 程序做 scope 限定的原始 note 检索
7. 读取最有价值的原始 note
8. 组装有上限的 evidence bundle
9. 再让 Codex 只基于这个 evidence bundle 输出最终 Markdown 回答

### 流式输出行为
问答层用 `OKI_CODEX_STREAM` 控制 Codex 子进程是否流式输出。

当前行为是：
- `build-qa` 默认流式输出 Codex 过程
- `oki ask` 的“检索计划生成阶段”是流式的
- `oki ask` 还会输出确定性的进度日志，例如：
  - `[oki ask] planning retrieval`
  - `[oki ask] searching <query>`
  - `[oki ask] synthesizing final answer`
- 最终回答阶段被故意收口成只打印一次，避免整段答案重复输出

### Context mode
`oki ask` 当前支持两种上下文模式。

`map` 模式：
- 预加载 `overview`、`themes`
- 先建立作者地图
- 再派生多组 query 去检索原始 note
- 如果首轮检索拿到的原始 note 太少，再用紧凑版 `corpus_index` 做 fallback planning
- 最终证据仍然来自原始 note

`fulltext` 模式：
- 预加载 `overview`、`themes`，再加一份截断过的 `full_context`
- 让 Codex 先拥有更强的整库感
- prompt 更大，token 成本明显更高

默认仍然是 `map`，因为它更便宜，而且已经足以支撑第一批成功的严肃长答 smoke test。

### 运行时参数
当前问答层会读取：
- `OKI_CODEX_MODEL`
- `OKI_CODEX_REASONING_EFFORT`
- `OKI_CODEX_STREAM`

严肃使用场景推荐：
- `OKI_CODEX_MODEL=gpt-5.4`
- `OKI_CODEX_REASONING_EFFORT=medium`
- `OKI_CODEX_STREAM=1`

### 一次真实 smoke test 的用量
真实 Vault 上有一次成功 smoke test，问题是：
- `感到无聊老想出去玩social是对的吗`

当时的运行方式：
- scope: `linlin`
- context mode: `map`
- model: `gpt-5.4`
- reasoning effort: `high`

可确认的 token 用量：
- 一次成功 run 明确测到总共 `35,623` tokens
- 后续稳定化后的 rerun，planning 阶段明确看到 `28,930` tokens
- 但 final synthesis 因为是 non-stream capture，CLI 没额外暴露那一段的 token 数
- 上面的数字来自旧版 `map` 路径；当前实现已经去掉默认 `corpus_index` 预加载，并把 `build-qa` 生成的 `corpus_index` 收紧成轻量索引

目前项目拿不到 Codex 5 小时滚动额度的总 denominator，所以不能把这次 run 的 token 数可靠地换算成“用了额度的百分之多少”。

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
