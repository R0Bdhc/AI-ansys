# 真实主机悬臂梁验证流程

本流程用于把“模板预览成功”和“真实 MAPDL 求解成功”分开验证。只有最后一步生成
`validation.json` 且退出码为 `0`，才能声明悬臂梁模板已经在真实主机上通过。

## 1. 环境门禁

1. 在 ≥3.11 的解释器中执行 `python -c "import main"`，确认 API 依赖可导入（`main.py` 启动时会强制校验 Python 3.11+，低版本直接 `RuntimeError`）。
2. 执行 `python -c "from ansys_runner import AnsysRunner; print(AnsysRunner().get_environment_status())"`。
3. 必须同时满足 `pymapdl_importable=true` 与 `detected_mapdl_exec` 非空；否则不得执行真实求解。
4. 将实际安装的 MAPDL 路径配置为 `MAPDL_EXECUTABLE`。`ANSYS_DIR` 和 `AWP_ROOT` 只作为备用目录配置。

当前工作区原有 `.venv` 由 Python 3.13 创建，但其中的 NumPy 和 Pydantic Core 是 CPython 3.10
二进制扩展。它不能通过第 1 步，不能作为测试环境使用。

## 2. 重建兼容环境

本机 ANSYS 252 自带 CPython 3.10，可用于创建与现有 CPython 3.10 wheels 兼容的虚拟环境：

> 注意：该 3.10 环境只用于跑 `scripts/validate_cantilever.py`（它直接导入 `ansys_runner`，不经过 `main.py` 的 3.11+ 门禁）。要启动 API / 仪表盘，必须另建 3.11+ 环境——两者不可混用。

```powershell
$python = 'D:\Program Files (x86)\ANSYS Inc25\v252\commonfiles\CPython\3_10\winx64\Release\python\python.exe'
& $python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install --upgrade --force-reinstall -r requirements.txt
```

在 `.env` 中设置：

```dotenv
MAPDL_EXECUTABLE=D:\Program Files (x86)\ANSYS Inc25\v252\ANSYS\bin\winx64\MAPDL.exe
ANSYS_DIR=D:\Program Files (x86)\ANSYS Inc25\v252\ANSYS
AWP_ROOT=D:\Program Files (x86)\ANSYS Inc25\v252
```

## 3. 真实求解验收

```powershell
.\.venv\Scripts\python.exe scripts\validate_cantilever.py
```

验证脚本会在 `runtime_data/cantilever_validation` 中保留 MAPDL 输出与 `validation.json`，并检查：

- MAPDL 实际启动并返回 `mapdl_executed`；
- 悬臂梁 `TIP_UY` 为负值；
- 数值解与 Euler-Bernoulli 理论挠度的相对误差不超过 25%。

失败时脚本返回非零退出码，并将诊断信息写入同一份 `validation.json`。不要以
`launch_mapdl=false` 的预览结果替代真实主机验证。
