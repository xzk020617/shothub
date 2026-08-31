# 截图中转站 ShotHub

**当前版本：ver0.1**

Windows 自用的截图临时中转工具：启动后自动捕获截图工具（Win+Shift+S 等）产生的截图，以缩略图墙展示；随时复制回剪贴板或直接拖出使用；退出时自动清理未保留的截图，不占用磁盘。

## 功能进度

- [x] 第 1 步：存储层（manifest 持久化）+ 缩略图网格 + 手动添加 / 单张删除 / 一键清空 / 退出清理
- [x] 第 2 步：剪贴板闭环——截图自动捕获入库（序号+内容指纹双重去重）、双击/按钮复制出去（CF_DIB + PNG 双格式、自我写入过滤）
- [x] 第 3 步：拖拽双向（拖入文件/位图 + 全窗口高亮遮罩，卡片拖出为文件）+ Ctrl+V 粘贴
- [x] 第 4 步：托盘常驻（关窗口最小化到托盘、首次气泡提示）+ 单实例（QLocalServer 唤起已有窗口）+ 退出清理/崩溃残留清理
- [x] 第 5 步：编辑合并（截图工具连续编辑只保留最终版，同尺寸高相似原位替换）+ 窗口置顶按钮

完整技术方案见 [Plan.md](Plan.md)。

## 运行

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

要求：Windows + Python 3.12。数据存放在 `%LOCALAPPDATA%\ShotHub\`。

## 打包与安装（Windows）

```bash
.venv\Scripts\pip install pyinstaller
.venv\Scripts\python -m PyInstaller --noconfirm --noconsole --onefile \
  --name ShotHub --icon assets/icon.ico --add-data "assets/icon.ico;assets" main.py
# 产物：dist\ShotHub.exe（单文件，约 52MB）
```

安装到系统（复制 exe 到 `%LOCALAPPDATA%\ShotHub\bin\` 并创建开始菜单快捷方式）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

开机自启（写入当前用户注册表 Run 键）：

```powershell
reg add "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Run" /v ShotHub /t REG_SZ /d "\"%LOCALAPPDATA%\ShotHub\bin\ShotHub.exe\"" /f
```

图标由 `scripts/make_icon.py` 程序化生成（渐变圆角方块 + 相框 + 环绕箭头）。

## 测试

```bash
.venv\Scripts\python tests\smoke_step1.py   # 存储 + 列表（20 项）
.venv\Scripts\python tests\smoke_step2.py   # 剪贴板闭环 + 去重（17 项）
.venv\Scripts\python tests\smoke_step3.py   # 拖拽双向 + 粘贴（23 项）
.venv\Scripts\python tests\smoke_step4.py   # 托盘 + 单实例 + 退出清理（17 项）
.venv\Scripts\python tests\smoke_step5.py   # 编辑合并 + 窗口置顶（23 项）
```

## 技术栈

Python 3.12 · PySide6（Qt 6）· pywin32 · Pillow

## 目录结构

```
main.py               # 入口（单实例）
app/
  storage.py          # StorageManager：落盘 / manifest / 缩略图 / 清理
  clipboard_hub.py    # 剪贴板监听 + 去重 + 自我过滤 + 双格式写回
  widgets.py          # FlowLayout / ThumbnailCard / EmptyState / 托盘图标
  mainwindow.py       # 主窗口 + 托盘
scripts/
  make_icon.py        # 程序化生成应用图标（icon.ico）
  install.ps1         # 安装 exe + 开始菜单快捷方式
ShotHub.spec          # PyInstaller 打包配置
tests/                # 离屏冒烟测试（100 项）
```
