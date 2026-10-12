"""Moved: the probes now live in drill/probes.py. Kept so the commands in
research/06 still work:  python3 eval/quality_probe.py <model> [...]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from drill.cli import main  # noqa: E402

for model in sys.argv[1:]:
    main(["probe", "--model", model, "--dialect", "es-ES", "--verbose"])
