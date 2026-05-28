# 文件共享小助手 🌸

> 零配置、开箱即用的局域网文件共享工具

![Python](https://img.shields.io/badge/Python-3.8+-FF69B4?style=flat&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-2.3-FF8FAB?style=flat&logo=flask&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows-E8607D?style=flat&logo=windows&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-7BC8A4?style=flat)

## ✨ 简介

**文件共享小助手** 是一款轻量级的局域网文件共享工具。只需双击运行，就能在局域网内通过浏览器访问和共享指定文件夹。无需安装任何客户端，无需复杂的配置。

## 🎯 主要功能

| 功能 | 说明 |
|------|------|
| 📁 **文件浏览** | Web 界面浏览共享目录，支持进入子目录 |
| 📤 **文件上传** | 支持单/多文件上传，显示实时进度 |
| 📥 **文件下载** | 单文件下载、批量勾选 ZIP 下载、文件夹打包下载 |
| 🔄 **断点重传** | 上传失败或取消后可一键重传 |
| 📋 **上传记录** | 完整记录每次上传的时间、状态、错误信息 |
| 🔒 **密码保护** | 可选设置访问密码，保障共享安全 |
| 🎛 **桌面 GUI** | 可视化配置端口、目录、密码，一键启停服务 |

## 🚀 快速开始

### 方式一：直接使用打包好的 exe

1. 从 [Releases](https://github.com/your-username/file-share-assistant/releases) 下载 `文件共享小助手.exe`
2. 双击运行
3. 配置共享文件夹和端口
4. 点击「启动服务」
5. 局域网内其他设备访问 `http://你的IP:端口`

### 方式二：从源码运行

```bash
# 克隆仓库
git clone https://github.com/your-username/file-share-assistant.git
cd file-share-assistant

# 安装依赖
pip install -r requirements.txt

# 运行
python main.py
```

## 🖥 界面预览

```
┌─────────────────────────────────────┐
│  🌸 文件共享小助手 🌸                │
│  ✨ 轻轻松松分享你的文件 ✨          │
├─────────────────────────────────────┤
│  🎈 服务设置                        │
│  🎀 服务端口: [8080    ]            │
│  📂 共享文件夹: [________] 📂 浏览  │
│  🔒 访问密码: [________]            │
├─────────────────────────────────────┤
│  📦 上传限制                        │
│  📤 单文件大小上限: [1024] [MB▼]   │
├─────────────────────────────────────┤
│  [🚀 启动服务]  [⏹ 停止服务]  [💾 保存] │
├─────────────────────────────────────┤
│  😊 服务正在努力工作中！             │
│  端口: 8080 | http://localhost:8080  │
│                                 ●   │
└─────────────────────────────────────┘
```

## 🛠 技术栈

- **桌面 GUI**：Python tkinter
- **Web 框架**：Flask + Werkzeug
- **打包工具**：PyInstaller（单文件 exe）
- **前端**：原生 HTML/CSS/JavaScript（XHR 上传进度）

## 📚 文档

完整的技术文档请参阅 [TECHNICAL_DOCUMENT.md](./TECHNICAL_DOCUMENT.md)，包含：

- 系统架构设计与模块划分
- 全部 API 接口定义
- 数据流程与关键实现细节
- 环境配置与部署指南
- 测试策略与质量保障
- 未来迭代计划

## 📄 许可证

本项目基于 MIT 许可证开源。详见 [LICENSE](./LICENSE) 文件。
