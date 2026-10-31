# 1.1.0 · AI 不绑定，一键同步

- 新增 Windows 双按钮同步程序：获取云端更新、上传本地修改。
- 复用已有 Git 认证；Windows 打包版不需要安装 Python。
- 正常操作一键完成；冲突时保留双方副本，上传失败保留本地提交。
- 不绑定特定 AI 模型、模式或平台；接入条件是具备需要的仓库读写与执行能力。
- 工作区自身不设置导图同步张数配额，支持任意画布定位和批量编辑。
- 首页集中展示解决的问题和使用步骤，详细说明移至次级文档。

文件编辑与云端自动提交沿用 1.0.0 的工具。同步核心已通过 12 项真实 Git 仓库检查（含中文 / 空格文件名）；Windows 构建、打包后界面启动及 Git 访问检查已通过：[成功工作流](https://github.com/duohaocui-eng/xmind-ai-workspace/actions/runs/41186155421)。[下载 v1.1.0](https://github.com/duohaocui-eng/xmind-ai-workspace/releases/tag/v1.1.0)。未在使用者电脑上完成新的 XMind 客户端兼容性验证。
