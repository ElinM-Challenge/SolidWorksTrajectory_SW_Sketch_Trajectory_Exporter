# SolidWorks 草图轨迹导出器

这是一个 Windows 下的 SolidWorks 草图轨迹导出工具。它通过 SolidWorks
COM 会话读取当前打开的模型和指定草图，将草图中的曲线采样后导出为 CSV，
并提供 PySide6 图形界面用于选择草图、设置导出参数、查看进度和预览轨迹。

## 主要功能

- 连接当前运行中的 SolidWorks 会话。
- 显示当前模型及可用草图。
- 将选定草图导出为 CSV。
- 支持采样步长、曲面偏移、输出文件名和覆盖策略配置。
- 在导出过程中显示阶段、进度、警告和错误信息。
- 提供 XY、XZ、YZ 三个方向的轨迹预览。
- 保留兼容命令行入口，便于脚本调用和问题诊断。

## 运行环境

- Windows。
- 已安装并完成 COM 注册的 SolidWorks。
- Python 3.11 或更高版本，开发环境当前使用 Python 3.14。
- PySide6。

目标计算机如果只运行打包后的程序，不需要安装 Python，但仍需要安装
SolidWorks，并且 SolidWorks COM 接口必须可用。

## 本地开发

在仓库根目录创建虚拟环境并安装依赖：

```powershell
py -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r .\trajectory_export_app\requirements.txt
```

启动图形界面：

```powershell
& .\.venv\Scripts\python.exe .\launch_gui.py
```

运行核心测试：

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s .\trajectory_export_app\tests -v
```

兼容命令行入口：

```powershell
& .\.venv\Scripts\python.exe .\export_solidworks_trajectory.py --help
& .\.venv\Scripts\python.exe .\export_solidworks_trajectory.py --gui
```

## 构建 EXE

推荐先使用目录模式构建，便于定位 DLL 和 COM 依赖问题：

```powershell
& .\build_trajectory_gui.ps1
```

确认目录模式正常后，再构建单文件版本：

```powershell
& .\build_trajectory_gui_onefile.ps1
```

单文件程序输出为：

```text
dist-onefile\SolidWorksTrajectory.exe
```

当前 PyInstaller 脚本会尝试把 Qt 依赖的 Windows ICU DLL 一起打包，以降低
目标计算机出现 `QtCore` 或 `loadlibrary` 加载错误的概率。发布前仍应在一台
没有 Python 开发环境的 Windows 计算机上进行实际启动测试。

`build_trajectory_gui_nuitka.ps1` 和 `pysidedeploy.spec` 暂时保留为实验性
部署路线。Windows 下 Nuitka 可能需要额外的依赖分析工具，因此当前正式构建
路线仍然是 PyInstaller。

## 项目结构

```text
launch_gui.py                         图形界面入口
export_solidworks_trajectory.py      兼容命令行入口
trajectory_export_app/
  app.py                              应用入口
  gui.py                              PySide6 界面
  worker.py                           独立导出进程
  core.py                             导出核心逻辑
  config.py                           导出参数
  events.py                           进度事件与取消令牌
  solidworks_adapter.py               SolidWorks 适配层
  vendor/                             COM 连接和预检辅助模块
  tests/                              核心逻辑测试
```

GUI 不直接持有 SolidWorks COM 对象。导出和会话访问由 Worker 进程负责，
进度通过 JSON Lines 事件传回 GUI。这样可以降低 COM 阻塞对界面的影响，
也便于将来扩展批量导出和更细的进度统计。

## 使用注意

- 导出前请确认选中了真正包含目标曲线的草图，而不是模型包围盒或其他辅助对象。
- SolidWorks 必须处于运行状态，并且当前文档已经打开。
- 生成的 CSV、元数据和本地构建目录默认不会提交到 Git。
- 单文件 EXE 更适合作为 GitHub Release 附件，而不是提交到源码仓库。

## 版本控制建议

源码仓库只保存源代码、测试、构建脚本和文档。归档目录、虚拟环境、构建
目录和测试导出文件保留在仓库之外；每次发布的 EXE 单独放入 Release，并在
README 或变更记录中注明对应版本。
