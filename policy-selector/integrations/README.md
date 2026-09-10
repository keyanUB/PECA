# 跨 Agent 接入

`policy-selector` 是独立的 MCP 服务。策略来源、选择模型和验证规则都位于
`src/policy_selector`；客户端配置、命令桥接和已知兼容性问题放在本目录。

所有客户端使用同一套 `tools/list` / `tools/call` 接口：

- `select_for_task(task)`
- `select_for_repository(task, repository_path?, file_paths?, files?)`
- `refine_selection(task, generated_code, previous_selection)`
- `policy_catalog()`

工具参数使用平铺 JSON，例如 `{"task":"实现一个用户查询函数"}`。
客户端内部的 `data`、`arguments` 等封装不属于这些工具的业务参数。
客户端负责选择何时调用工具；MCP 服务不会强制生成模型落实建议。

## 接入与验证状态

| 客户端 | 接入方式 | 当前验证范围 |
| --- | --- | --- |
| Codex | 原生 stdio / Streamable HTTP MCP | 已生成并解析配置；尚未进行 Codex 模型端到端调用 |
| Claude Code | 原生 stdio / Streamable HTTP MCP | 已生成并解析配置；尚未进行 Claude 模型端到端调用 |
| SWE-agent | 自定义工具 → 通用 MCP CLI → MCP 服务 | 桥接代码已提供，底层 stdio/HTTP 已测；本机未安装 SWE-agent，尚未完整运行 |
| OpenHands | 原生 MCP；PECA 启动器加载独立兼容层 | 1.13.0 原生 Responses schema 缺陷已定位；见专用兼容入口与重测记录 |

“配置已提供”“协议已通过”“实际 Agent 端到端已通过”是不同的验证阶段。
OpenHands 的缺陷应修复在客户端适配层，不能通过改变所有客户端的工具参数来规避。

PECA 启动器现已加载 [OpenHands 兼容入口](openhands/README.md)。直接运行裸
`openhands` 命令不会加载这个修复；其他客户端仍直接使用标准 MCP 服务。

官方接入依据：
[Codex MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)、
[Claude Code MCP](https://code.claude.com/docs/en/mcp)、
[SWE-agent 工具扩展](https://swe-agent.com/latest/config/tools/)。
SWE-agent 的桥接采用其自定义命令机制，不假定某个版本具有原生 MCP 支持。

## 生成配置示例

在 PECA 目录运行：

```bash
python3 policy-selector/integrations/render_configs.py \
  --repo-root /absolute/path/to/your/project \
  --output /tmp/peca-client-configs
```

输出 `codex.toml`、`claude.mcp.json` 和 `openhands.mcp.json`，仅创建示例文件，
不会修改客户端配置。已有同名文件不会被覆盖。默认使用 PECA 的 `.venv/bin/python`；
其他部署方式可通过 `--python` 指定安装了本包的解释器。

Codex：将 TOML 中的表合并到目标项目的 `.codex/config.toml`，或用户配置。
`env_vars` 转发 `OPENAI_API_KEY`，工具超时设为 300 秒，以容纳 selector 的校正尝试。

Claude Code：将 JSON 中的 server 条目合并到项目 `.mcp.json`。
其中 `${OPENAI_API_KEY}` 由 Claude Code 展开；不要替换为写入文件的实际密钥。
客户端可能需要信任项目配置，之后可用 `/mcp` 检查连接。

这些 stdio 配置由客户端启动和关闭服务。启动客户端前，确保环境中有
`OPENAI_API_KEY`。无论生成模型属于哪家厂商，selector 仍使用自己的
`gpt-5.6-luna` 和 OpenAI API 凭据。

## 通用命令桥接

安装或更新本包后可使用 `policy-selector-client`。也可以直接使用模块入口：

```bash
# 自动启动本地 stdio MCP；只发现工具，不调用选择模型
.venv/bin/python -m policy_selector.client list

# request.json 为平铺工具参数，例如 {"task":"实现一个 SQLite 查询函数"}
.venv/bin/python -m policy_selector.client call select_for_task --input request.json

# 连接已启动的 HTTP MCP 服务
.venv/bin/python -m policy_selector.client --url http://127.0.0.1:8765/mcp \
  call select_for_task --input request.json
```

桥接实际执行 MCP 初始化、工具发现和调用，不绕过 MCP 直接请求选择模型。
它先根据服务端公布的 schema 校验参数，再发起调用。结果输出到 stdout，
错误输出到 stderr；工具失败返回非零退出码。`--input -` 可从 stdin 读取 JSON。

## SWE-agent

`swe_agent/` 是工具 bundle：`bin/policy_selector` 调用上述通用客户端，
`config.yaml` 描述工具的两个参数。将该 bundle 作为一个额外条目加入
SWE-agent 的 `agent.tools.bundles`，同时保留其原有工具配置。

```yaml
agent:
  tools:
    bundles:
      - path: /absolute/path/to/PECA/policy-selector/integrations/swe_agent
```

执行环境内必须先安装本包，使 bundle 的 `python3` 可以导入 `policy_selector`。
例如，将本包挂载到容器后执行：

```bash
python3 -m pip install /mounted/PECA/policy-selector
```

Agent 可调用：

```bash
policy_selector select_for_task request.json
policy_selector refine_selection refinement.json
```

默认启动同一环境内的 stdio 服务。设置 `POLICY_SELECTOR_MCP_URL` 后改为连接指定
HTTP MCP 服务，不需要将 selector 的 API 密钥提供给远程客户端。
同样的命令桥接也适用于能够运行 shell 命令的其他 Agent。

## 容器与远程仓库

客户端的 `/workspace/repo` 不一定存在于服务端。此时使用文件快照：

```json
{
  "task": "补全用户查询函数",
  "files": [
    {"path": "src/users.py", "content": "def find_user(connection, username):\n    pass\n"},
    {"path": "README.md", "content": "项目使用 SQLite。"}
  ]
}
```

将它传给 `select_for_repository`。`files` 与 `repository_path` 必须二选一，
`file_paths` 仅用于服务端本地路径模式。快照沿用 40 个文件、200,000 字节的限制，
并明确返回部分覆盖标记。它不会读取客户端提供的路径，也不会声称已检查整个仓库。

HTTP 服务目前只监听本机回环地址，没有内建多用户认证。跨容器可在客户端容器内
运行 stdio 服务，或使用受控隧道/代理访问服务；容器中的 `127.0.0.1` 指向容器自身。
公开远程部署及其认证不属于当前实现。

## 回归验证

```bash
cd policy-selector
../.venv/bin/python -m pytest -q
```

测试覆盖标准 stdio 和 HTTP 的实际客户端调用、工具 schema、文件快照输入与
互斥参数校验。后续每个 Agent 的验收还应记录：客户端版本、实际调用事件、
selector 响应 ID、成功/失败状态，以及代码安全测试结果。
