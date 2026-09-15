# `trajectory_export_app` 模块

这是 SolidWorks 草图轨迹导出器的 Python 应用模块。项目根目录的
`README.md` 是完整使用说明，本文件只保留模块级说明。

## 模块职责

- `core.py`：导出核心逻辑和命令行入口。
- `config.py`：导出参数模型。
- `events.py`：进度事件、结果和取消令牌。
- `solidworks_adapter.py`：SolidWorks 会话访问接口。
- `worker.py`：独立进程中的检查和导出任务。
- `gui_fluent_workspace.py`：Fluent 风格图形界面。
- `gui.py`：兼容用的旧版 PySide6 图形界面。
- `vendor/`：SolidWorks COM 连接及环境预检辅助代码。
- `tests/`：不依赖真实 SolidWorks 会话的核心测试。

GUI 不应直接持有 SolidWorks COM 对象。需要访问 SolidWorks 时，应通过
Worker 和适配层完成，并通过 JSON Lines 进度事件将状态传回 GUI。
