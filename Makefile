TASKS := setup dev test lint contracts phase0 secrets synth eval demo

.PHONY: $(TASKS)
$(TASKS):
	uv run python scripts/tasks.py $@
