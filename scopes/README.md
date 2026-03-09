# scopes

Each file in this directory defines one person-level scope for the QA layer.

Example shape:

```json
{
  "scope_id": "linlin",
  "display_name": "林琳",
  "description": "Single-person scope that can aggregate multiple vault source roots.",
  "sources": [
    {
      "path": "Sources/Zhihu/lin-lin-98-23",
      "source": "zhihu",
      "author_id": "lin-lin-98-23",
      "author_name": "lin-lin-98-23"
    },
    {
      "path": "Sources/WeChat/大魔王的后花园",
      "source": "wechat",
      "account_name": "大魔王的后花园"
    }
  ]
}
```
