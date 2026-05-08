# CS2 Config Manager

> **适用平台：Windows**  
> 一款用于在不同 Steam 账号之间同步 CS2（Counter-Strike 2）配置文件的 GUI 工具，打包后为**单文件 EXE**，无需安装任何运行时。

---

## 功能

| 功能 | 说明 |
|------|------|
| 🔍 自动检测 Steam | 通过 Windows 注册表或常用路径自动定位 Steam 安装目录 |
| 👤 账号列表 | 自动列出所有拥有 CS2 数据的 Steam 账号（含昵称） |
| 📋 文件预览 | 实时预览源账号与目标账号中各配置文件的存在状态 |
| 📂 选择性同步 | 可勾选只同步特定类型的配置文件 |
| 💾 配置存储 | 可将某个账号配置保存为本地配置档，后续直接应用到其他账号 |
| 🔒 自动备份 | 同步前自动将目标文件备份为 `.bak_YYYYMMDD_HHMMSS` |
| 📝 操作日志 | 实时显示每一步的操作结果 |

### 支持同步的文件

| 文件 | 说明 |
|------|------|
| `autoexec.cfg` | 自定义启动配置 |
| `config.cfg` | 游戏主配置（按键绑定、设置） |
| `cs2_video.txt` | 视频/画面设置 |
| `cs2_user_keys_0_slot0.vcfg` | 按键绑定数据 |
| `cs2_user_convars_0_slot0.vcfg` | 用户控制台变量 |
| `cs2_machine_convars.vcfg` | 机器级控制台变量 |
| `practiceserver.cfg` | 练习服务器配置 |

---

## 快速开始

### 方式一：下载发布版 EXE（推荐）

从 [Releases](../../releases) 页面下载最新的 `CS2ConfigManager.exe`，双击运行即可，无需安装 Python。

### 方式二：从源码运行

```bash
# 克隆仓库
git clone https://github.com/Mercerry/cs2-config-manager.git
cd cs2-config-manager

# 运行（需 Python 3.10+）
python src/main.py
```

### 方式三：自行打包为 EXE

```bat
# 在 Windows 命令行或 PowerShell 中执行：
build.bat
```

打包完成后，可执行文件位于 `dist\CS2ConfigManager.exe`。

> **要求：** Python 3.10 或更高版本（用于打包），运行打包后的 EXE 无需 Python。

---

## 使用方式

1. 启动程序后，软件会**自动检测 Steam 安装路径**并列出账号列表。  
   若检测失败，可点击「浏览…」手动选择 Steam 目录。
2. 在「**源账号**」下拉框中选择配置来源账号。
3. 在「**目标账号**」下拉框中选择要写入配置的账号。
4. 勾选需要同步的**文件类型**。
5. 确认右侧**文件预览**中各文件的存在状态。
6. 点击「**▶ 开始同步**」，确认弹框后开始同步。
7. 查看底部「**操作日志**」了解同步结果。

---

## 项目结构

```
cs2-config-manager/
├── src/
│   ├── main.py           # GUI 主程序（tkinter）
│   ├── steam_manager.py  # Steam 检测、账号列表、VDF 解析
│   └── config_syncer.py  # 配置文件同步逻辑（含备份）
├── tests/
│   ├── test_steam_manager.py
│   └── test_config_syncer.py
├── build.spec            # PyInstaller 打包配置
├── build.bat             # Windows 一键打包脚本
├── requirements.txt      # Python 依赖（仅 PyInstaller）
└── README.md
```

---

## 开发

```bash
# 运行测试
python -m pytest tests/ -v
```

---

## 许可证

[MIT License](LICENSE) © 2026 Mercerry
