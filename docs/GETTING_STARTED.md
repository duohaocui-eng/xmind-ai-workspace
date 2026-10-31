# 开始使用

1. 使用模板建立自己的仓库，私人内容选择 Private；已有工作区可继续使用。
2. 把自己的仓库克隆到电脑，再下载并打开 [XMindSync.exe](https://github.com/duohaocui-eng/xmind-ai-workspace/releases/latest/download/XMindSync.exe)，选择该工作区。
3. 让能操作仓库的 AI 读取 `AI_USAGE.md`，并给出导图路径和本次任务。
4. AI 保存到仓库后，点击“获取云端更新”，重新打开本地导图。
5. 你在 XMind 中编辑保存后，点击“上传本地修改”。

[完整同步说明](SYNC.md) · [AI 使用接口](../AI_USAGE.md) · [示例目录](../CATALOG.md)

## 需要云端自动编辑时

在自己的仓库启用 Actions；按需在 Settings → Actions → General 允许工作流写入仓库。AI 按 `AI_USAGE.md` 提交新请求后，检查工作流是否成功以及 `requests/results` 是否产生回执。提交请求本身不代表导图已修改完成。

## 可选：只体验本地工具

下载仓库 ZIP 并解压，有 Python 3.10+ 时运行 `run.cmd` 或 `bash run.sh`。选择 3 跑通示例修改，再用 XMind 客户端检查示例文件。

这个入口不要求 Git，但它不是云端同步程序。ZIP 文件夹不具有 Git 仓库信息，不能直接用于双按钮同步。
