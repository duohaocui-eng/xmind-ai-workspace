# 从第一次使用到持续协作

## 方式一：本地 / Codex（推荐先体验）

1. 下载解压，运行 `run.cmd` 或 `bash run.sh`。
2. 选择 3，查看新增的修改后示例文件。多次运行会覆盖演示输出，但保留示例原图。
3. 用 XMind 客户端打开两份文件，对比中心主题。确认当前客户端兼容后，把自己的图复制到 `10_进行中`。
4. 让 AI 读取你的文件并提出修改。确认后，在可以执行 Python 的环境完成修改。
5. 文件修改后用 XMind 重新打开。需要跨设备保存时，上传回自己的云仓库，或 commit + push。

不必先学习 JSON 才能体验：菜单可运行完整示例；日常精确编辑的请求由 AI 按 `AI_USAGE.md` 生成。

## 方式二：个人 GitHub 云目录

1. 在本项目点击 Use this template，新建自己的仓库。私人内容选择 Private。
2. 用 Add file → Upload files，将自己的导图放进对应目录。不要放到本项目作者的公共仓库。
3. 本地运行 `python workspace.py list` 并上传 `CATALOG.md` 可刷新入口；即使没刷新目录，文件仍能从文件夹访问。
4. 连接有权访问该仓库的 GitHub 工具；让 AI 读取文件并继续工作。

使用 Git 时：先保存并关闭 XMind 目标文件 → `git pull --ff-only` → 重新打开 → 编辑保存 → 关闭 → commit + push。遇到冲突先保留两份文件再人工判断，不强制覆盖。

## 方式三：让云端自动应用修改

1. 在自己的仓库打开 Actions，按页面提示启用工作流；模板复制后通常需要启用。
2. 如果工作流不能提交结果，到 Settings → Actions → General → Workflow permissions，允许 Read and write permissions。组织策略可能禁止这一选项。
3. 让有二进制读取和仓库写入能力的 AI 读取目标导图，生成新 `request_id`、当前文件哈希和操作内容。
4. 保存到 `requests/request.json` 并提交。工作流会自动执行；也可 Actions → Update my XMind workspace → Run workflow。
5. 查看绿色成功状态和 `requests/results` 的结果文件。下载或同步更新后的 `.xmind`，重新打开。

GitHub 工作流可读写你自己的仓库。涉及敏感文件时使用私人仓库，遵循你所在组织的云端使用要求。工作流没有第三方 AI API 密钥需求。

## 在新对话接续

> 仓库是【链接】，导图是【路径】。读取 README 和 AI_USAGE，先读取最新文件，然后继续处理【这次要做的事】。

云目录提供持续入口；新对话是否能直接读写，取决于当前工具连接和运行环境权限。
