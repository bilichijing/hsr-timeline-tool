"""Web 前端的后端服务（标准库 HTTP，**不依赖 PySide6**）。

启动方式：

    python web_main.py            # 默认 http://127.0.0.1:8765
    python web_main.py --port 9000 --open

设计要点：

- 后端持有唯一会话（单用户本地工具）：队伍配置 + 交互模拟器 + 快照栈；
- 所有写操作返回**完整状态**，前端只负责渲染；
- 面板 / 战斗数值复用 `src/core`，与桌面端同口径；
- 静态资源为无构建的原生 ES Module（`static/`），零 Node 依赖。
"""
