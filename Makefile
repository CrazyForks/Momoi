# Full suite: make test
# Serial debugging: make test TEST_WORKERS=0 TEST_ARGS='tests/test_exec_tool.py -x'
TEST_WORKERS ?= 4
TEST_ARGS ?=

.PHONY: test
test:
	uv run --locked --group test pytest -q -n $(TEST_WORKERS) $(TEST_ARGS)
