# 测试

在仓库根目录运行 Python 测试。优先使用 Makefile 入口；它通过 uv 使用锁定的 `test` 依赖组（pytest、pytest-xdist）。

```bash
# 全量回归，默认 4 个独立进程并行
make test

# 指定文件或筛选测试
make test TEST_ARGS='tests/test_exec_tool.py'
make test TEST_ARGS='-k recall'

# 串行调试；单个测试或少量测试优先串行，避免进程启动开销
make test TEST_WORKERS=0 TEST_ARGS='tests/test_exec_tool.py -x'

# 查看最慢的测试
make test TEST_ARGS='--durations=20'
```

没有 make 时，等价命令为：

```bash
uv run --locked --group test pytest -q -n 4
```

不要再以 `uv run --with pytest pytest -q` 作为默认全量入口：它默认串行，也没有使用锁定的测试依赖组。需要串行运行时，显式设置 `TEST_WORKERS=0`（或 `-n 0`）。

测试必须支持进程隔离：文件和数据库使用各测试自己的临时目录，测试 HTTP 服务使用动态端口，避免共享固定路径或端口。不要为了加速跳过断言或缩减覆盖。

前端改动另运行 `npm run build` 验证构建；Python 测试不替代前端构建检查。
