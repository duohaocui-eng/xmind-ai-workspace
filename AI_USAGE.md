# AI 使用说明

这是使用接口说明。不绑定特定 AI 模型、模式或平台；当前环境需要能访问工作区，并能本地执行工具或提交云端请求。先读取目标文件最新版本，再处理用户要求的内容。

1. `.xmind` 是导图真源。文本大纲不是已经完成的文件修改。
2. 用户仅要求分析时只读；明确要求修改文件后再执行写入。
3. 有本地执行能力时优先使用现有工具，不重新研究文件格式。
4. 编辑前从摘要读取 `file_sha256`，写入时传 `expect_sha256`。使用节点 ID；标题不唯一时请用户指定。
5. 完成后读取结果验证，告知实际文件路径和保存 / 提交状态。失败不宣称完成；不自动退回旧版本覆盖新文件。
6. 外部编辑前提醒保存并关闭 XMind 文档，更新后重新打开。

## 本地读取和编辑

```bash
python tools/xmind_read.py "00_临时/入门示例.xmind"
python tools/xmind_read.py "00_临时/入门示例.xmind" --format tree
python tools/xmind_read.py "00_临时/入门示例.xmind" --find "保存"
python tools/xmind_edit.py --request requests/request.json --dry-run
python tools/xmind_edit.py --request requests/request.json
python workspace.py list
```

Windows 可将 `python` 换成 `py -3`，macOS/Linux 可换成 `python3`。直接执行的文件路径相对于当前工作目录；请在仓库根目录运行。

## 云端调用

仅在已连接的 GitHub 工具能**实际读取二进制 `.xmind` 并写入仓库**时使用。只有网页文本读取能力不够；读不到二进制时请用户上传目标文件，或改在能运行工具的 Codex 环境执行。不要猜测节点 ID 或文件哈希。

先从最新文件获取 SHA-256 和节点 ID，再把请求保存到使用者自己仓库的 `requests/request.json`：

```json
{
  "version": 1,
  "request_id": "edit-001",
  "file": "00_临时/入门示例.xmind",
  "expect_sha256": "替换为最新文件的64位SHA256",
  "operations": [
    {"op": "rename", "target": {"id": "welcome-root"}, "title": "我的第一张协作导图"}
  ]
}
```

每次新请求使用新 `request_id`。云端只接受五个导图目录内的 `.xmind`，忽略自定义 output / report 路径。重复提交相同已完成请求不再执行；同 ID 改内容会拒绝。过期哈希会拒绝。

请求提交后，检查 Actions **Update my XMind workspace** 是否成功，并读取 `requests/results/请求ID.json`。需要确认目标文件已有结果提交，不能把“已提交请求”当作“导图修改完成”。

## 编辑操作速查

| 操作 | 必要参数 |
| --- | --- |
| rename | target: {id}, title |
| add | parent: {id}, title |
| delete | target: {id} |
| move | target: {id}, new_parent: {id} |
| add_detached | sheet: {id}, title, position: {x,y} |
| set_position | target: {id}, position: {x,y} |
| add_sheet | title, 可选 root_title |
| rename_sheet | sheet: {id}, title |
| delete_sheet | sheet: {id} |

不要主动编辑本版未声明支持的关系线、概要、边界、Notes、链接、marker、图片和复杂样式。不要删除 / 移动画布根节点，不删除最后一个画布，不把节点移动到自己的子树。
