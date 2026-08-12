# Open XiaoAI MCP

一个独立的 MCP（Model Context Protocol）服务器，把 MCP Agent 的工具调用转发到现有的 Open XiaoAI Bridge HTTP API。支持 stdio 与 Streamable HTTP；默认仍为 stdio，不向 stdout 输出日志或其他非协议内容。

## 工具

| 工具 | 作用 |
| --- | --- |
| `xiaoai_send_text(text, blocking=false, timeout_ms=60000)` | 调用 `POST /api/play/text` 播报文字 |
| `xiaoai_health()` | 调用 `GET /api/health` |
| `xiaoai_status()` | 调用 `GET /api/status` |
| `xiaoai_interrupt()` | 调用 `POST /api/interrupt` 打断播放 |

### 服务端静默时段

每天北京时间（`Asia/Shanghai`）**22:00（含）至次日 09:00（不含）**，`xiaoai_send_text`
会在服务端直接拒绝请求，且完全不会调用 Bridge。该策略固定在服务端，调用方不能通过工具参数关闭或绕过。
`xiaoai_health`、`xiaoai_status` 以及出于安全考虑保留的 `xiaoai_interrupt` 不受影响。

静默时段的拒绝结果会明确包含原因、服务器所见本地时间、时区和窗口，例如：

```json
{
  "success": false,
  "error": {
    "code": "quiet_hours",
    "message": "静默时段禁止发送播报请求",
    "reason": "quiet_hours_policy",
    "local_time": "2026-08-06T07:59:00+08:00",
    "timezone": "Asia/Shanghai",
    "window": "22:00-09:00"
  }
}
```

工具返回桥接服务的 JSON 对象。网络、超时、HTTP 状态和响应格式错误会统一返回：

```json
{
  "success": false,
  "error": {
    "code": "bridge_unreachable",
    "message": "无法连接小爱音箱桥接服务"
  }
}
```

## 安装与运行

需要 Python 3.10+ 和 [uv](https://docs.astral.sh/uv/)。在项目目录执行：

```bash
uv sync
uv run open-xiaoai-mcp
```

也可以安装为独立命令：

```bash
uv tool install /path/to/open-xiaoai-bridge/mcp
open-xiaoai-mcp
```

服务默认连接 `http://127.0.0.1:9092`。桥接服务位于其他地址时设置：

```bash
export XIAOAI_BRIDGE_URL="http://192.168.3.27:9092"
```

URL 中不需要添加 `/api`，末尾 `/` 可有可无。

## MCP Agent 配置

Claude Desktop、Claude Code、Cursor 等使用标准 `mcpServers` 配置的 Agent 可采用下面任一方式。配置文件的具体位置取决于 Agent。

直接用 uv 在源码目录运行：

```json
{
  "mcpServers": {
    "open-xiaoai": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/open-xiaoai-bridge/mcp",
        "run",
        "open-xiaoai-mcp"
      ],
      "env": {
        "XIAOAI_BRIDGE_URL": "http://127.0.0.1:9092"
      }
    }
  }
}
```

使用已经安装的命令：

```json
{
  "mcpServers": {
    "open-xiaoai": {
      "command": "open-xiaoai-mcp",
      "args": [],
      "env": {
        "XIAOAI_BRIDGE_URL": "http://127.0.0.1:9092"
      }
    }
  }
}
```

如果 Agent 不继承 shell 的 `PATH`，请把 `uv` 或 `open-xiaoai-mcp` 替换成 `which` 查询到的绝对路径。修改配置后重启 Agent。

## Streamable HTTP（Hermes / 独立部署）

HTTP 模式不启用应用层鉴权，默认只监听 `127.0.0.1:8765`，仅供同一台机器上的 Agent 使用。

启动服务：

```bash
XIAOAI_MCP_TRANSPORT=streamable-http \
uv run open-xiaoai-mcp
```

MCP 地址为 `http://127.0.0.1:8765/mcp`。Hermes 配置示例：

```yaml
mcp_servers:
  open-xiaoai:
    url: http://127.0.0.1:8765/mcp
    timeout: 610
    connect_timeout: 60
    enabled: true
```

可用环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `XIAOAI_MCP_TRANSPORT` | `stdio` | `stdio` 或 `streamable-http` |
| `XIAOAI_MCP_HOST` | `127.0.0.1` | HTTP 监听地址 |
| `XIAOAI_MCP_PORT` | `8765` | HTTP 监听端口 |
| `XIAOAI_MCP_PATH` | `/mcp` | Streamable HTTP 路径 |
| `XIAOAI_MCP_ALLOW_REMOTE` | `false` | 非 loopback 监听时必须显式设为 `true` |

当前服务没有应用层鉴权。若改为局域网部署，必须同时启用 `XIAOAI_MCP_ALLOW_REMOTE=true` 并通过主机防火墙限制来源 IP；不要把 MCP 或 Bridge 直接暴露到公网。

## 开发与质量检查

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

测试全部使用模拟 HTTP 响应，不需要启动或操作真实音箱。

## 健康检查

连接已运行的 loopback Streamable HTTP MCP、完成 initialize、核对工具清单并只调用 `xiaoai_health`：

```bash
cd /path/to/open-xiaoai-bridge/mcp && uv run python scripts/healthcheck.py
```

健康检查默认连接 `http://127.0.0.1:8765/mcp`，不会另行启动 MCP 进程；可用 `--url`
探测其他 loopback 实例。

脚本输出单行 JSON；健康时退出码为 0，MCP、Bridge 或音箱未就绪时退出码非 0。
健康检查不会调用 `xiaoai_send_text`、中断或任何播放工具，因此不会产生音频。

## 行为与限制

- `blocking=false` 时桥接服务在后台播放，工具成功仅表示桥接服务已接受请求。
- 每天北京时间 22:00（含）至次日 09:00（不含）禁止发送播报；此限制不可由 MCP 调用方覆盖。
- `blocking=true` 时 HTTP 读取超时为 `timeout_ms` 加 5 秒缓冲；最大 `timeout_ms` 为 600000（10 分钟）。
- stdio 依赖本机进程权限；Streamable HTTP 无应用层鉴权，默认只监听 loopback。
- 桥接服务当前接口没有请求 ID，因此无法对“已发送但响应丢失”的请求进行幂等重试；本服务不会自动重试播报，避免重复播放。

## License

MIT
