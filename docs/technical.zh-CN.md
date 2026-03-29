# 技术文档

## 项目目标
`source-notes-ingestor` 是一个本机优先的 ingestion 项目，目标是把：
- 知乎内容
- 微信公众号内容

采集下来，统一规范化成 Markdown，并写入一个本地 notes library。

仓库刻意不再内建问答运行时。检索层改成一个很薄的 repo-local skill/plugin，直接使用 `rg` 和原始文件读取。

## 技术栈
- 运行时：Python 3
- 包管理：`pyproject.toml`
- 浏览器自动化：Playwright
- HTML 解析与清洗：BeautifulSoup + 仓库内 HTML 工具
- 存储形态：本地 notes library 中的 Markdown + YAML frontmatter
- 状态管理：`Sources/_state` 下的 JSON 状态文件
- 问答路径：repo-local plugin/skill + `rg`

## 仓库结构
- `src/source_notes_ingestor/`
  - `adapters/`：知乎和公众号采集逻辑
  - `browser_automation.py`：浏览器登录态保存、页面发现与抓取
  - `normalizer.py`：统一文档模型转换
  - `library_writer.py`：Markdown 落盘、资源下载、状态写入
  - `pipeline.py`：端到端采集流程编排
  - `verification.py`：抓取后校验逻辑
- `plugins/notes-rg-qa/`：模型无关的检索 skill/plugin
- `docs/`：架构、计划、技术文档
- `tests/`：以 ingestion 为主的单元测试

## 数据流
```text
知乎 / 微信公众号
  -> adapter.fetch_source()
  -> RawItem
  -> normalize()
  -> CanonicalNote
  -> write_note()
  -> 本地 notes library
  -> notes-rg-qa skill/plugin
  -> rg + 原始文件读取
  -> agent 基于证据回答
```

## 核心接口
- `fetch_source(target, auth_ctx, since) -> raw_items[]`
- `normalize(raw_item) -> canonical_note`
- `write_note(canonical_note, library_path) -> note_path`

Python 包内部不再定义问答接口。

## 知乎实现
知乎当前支持三种采集路径：
- 浏览器发现页面后抓取
- 登录态 API 驱动抓取
- 手工 seed URL / HTML 导入

稳定路径是：
1. 通过 `sni auth zhihu` 保存真实浏览器登录态
2. 采集时复用这份登录态
3. 优先走 API 抓结构化内容
4. 必要时再走页面发现和页面抓取

## 微信公众号实现
公众号当前支持：
- 以文章 URL 作为种子抓取
- 复用浏览器会话抓页面
- `discover wechat`：从可访问的 seed 文章反推出 `mp/profile_ext?action=getmsg`，再做分页历史发现
- 抓取过程中流式落盘
- 基于 state 的验证后续跑

历史列表来源仍然是 `profile_ext/getmsg`，不是缓存里碰巧出现过的文章链接。

## Library 存储约定
目录结构固定为：
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
当前 `sni` 只保留 ingestion 命令：
- `sni auth <source>`
- `sni ingest <source> --target <file>`
- `sni discover wechat --target <file>`
- `sni verify zhihu --target <file> --library <path>`

## notes-rg-qa
检索层故意做得很薄：
- 不维护平行索引
- 不维护 session
- 不做模型专用 CLI 包装
- 不依赖特定编辑器 CLI

agent 直接用 `rg` 搜笔记、打开原始 Markdown、基于证据回答。
