# SolidWorksTrajectory 开发约定

## 修改边界

- 核心导出行为优先修改 `trajectory_export_app/core.py`、`config.py` 和
  `solidworks_adapter.py`。
- GUI 行为修改集中在 `trajectory_export_app/gui.py`。
- SolidWorks COM 对象只应由 Worker 或适配层创建和使用，不要在 GUI 线程中
  直接访问 COM。
- 保持 `launch_gui.py` 和 `export_solidworks_trajectory.py` 作为稳定入口。

## 验证要求

- 纯核心逻辑修改至少运行 `trajectory_export_app/tests` 中的测试。
- 涉及 GUI 或进度事件时，增加对应的离线测试或进行无界面启动检查。
- 涉及 SolidWorks COM 的修改，需要在已打开 SolidWorks 的 Windows 环境中
  手动验证连接、草图选择、导出和取消流程。
- 构建脚本修改后，至少验证 `--worker --help` 和 GUI 启动。

## 文件管理

- 不要提交 `.venv`、`__pycache__`、`build`、`dist`、测试 CSV 或本地归档。
- EXE 属于发布物，优先通过 GitHub Release 分发。
- 不要覆盖或删除用户已有的归档和测试结果；需要清理时先确认文件属于
  当前工作树。

## 提交信息

提交信息使用简短、明确的动词开头，例如：

```text
修复草图轨迹采样顺序
增加导出取消状态
完善 PyInstaller ICU DLL 打包
```
