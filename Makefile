PY_MODULE := shaq

ALL_PY_SRCS := $(shell find $(PY_MODULE) -name '*.py')

# Optionally overridden by the user in the `test` target.
TESTS :=

# Optionally overridden by the user/CI, to limit the installation to a specific
# subset of development dependencies.
INSTALL_EXTRA := dev

# If the user selects a specific test pattern to run, set `pytest` to fail fast
# and only run tests that match the pattern.
# Otherwise, run all tests and enable coverage assertions, since we expect
# complete test coverage.
ifneq ($(TESTS),)
	TEST_ARGS := -x -k $(TESTS)
	COV_ARGS :=
else
	TEST_ARGS :=
	COV_ARGS := --fail-under 100
endif

.PHONY: all
all:
	@echo "Run my targets individually!"

.PHONY: dev
dev: env/pyvenv.cfg

env/pyvenv.cfg: pyproject.toml
	# Create our Python 3 virtual environment
	python -m venv env
	./env/bin/python -m pip install --upgrade pip
	./env/bin/python -m pip install -e .[$(INSTALL_EXTRA)]

.PHONY: lint
lint: env/pyvenv.cfg
	. env/bin/activate && \
		black --check $(ALL_PY_SRCS) && \
		ruff $(ALL_PY_SRCS) && \
		mypy $(PY_MODULE)

.PHONY: reformat
reformat: env/pyvenv.cfg
	. env/bin/activate && \
		ruff --fix $(ALL_PY_SRCS) && \
		black $(ALL_PY_SRCS)

.PHONY: test tests
test tests: env/pyvenv.cfg
	. env/bin/activate && \
		pytest --cov=$(PY_MODULE) $(T) $(TEST_ARGS) && \
		python -m coverage report -m $(COV_ARGS)

.PHONY: package
package: env/pyvenv.cfg
	. env/bin/activate && \
		python -m build

.PHONY: edit
edit:
	$(EDITOR) $(ALL_PY_SRCS)
