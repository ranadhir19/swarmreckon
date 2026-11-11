"""swarmreckon — a parallel multi-agent runner that grades itself.

Takes a small development task, splits it into subtasks, runs
role-specialised worker agents in parallel against free-tier models,
and — the point of the tool — benchmarks every parallel run against
the same work done sequentially, with a per-agent evidence and cost
ledger and human approval gates for writes outside the sandbox.
"""

__version__ = "0.1.0"
