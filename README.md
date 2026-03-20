# Folder Mover

这是一个带 GUI 的本地文件夹批量迁移工具。

## 用法

把 `folder_mover.py` 或打包后的 `folder_mover.exe` 放到目标文件夹根目录下，确保同级存在：

- `映射关系模板.csv`
- 需要迁移的子文件夹

程序启动后会显示一个简单窗口，点击“开始执行”即可运行。

窗口会显示：

- 当前执行状态
- 实时日志
- 成功、跳过、失败数量

程序会读取同级 CSV 里的映射关系，把匹配到的子文件夹移动到 `迁移结果/目标文件夹/源文件夹/`。

## 云端打包

GitHub Actions 工作流在 `.github/workflows/build-exe.yml`。

手动触发后会生成 Windows 版 exe，并输出 `folder_mover-win.zip`。
