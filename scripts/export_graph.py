"""Export the compiled LangGraph as a Mermaid diagram (docs/workflow_graph.mmd) and PNG if possible.
Usage: python scripts/export_graph.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hr360.agents.base import AgentContext  # noqa: E402
from hr360.config import Settings  # noqa: E402
from hr360.graph.builder import build_graph  # noqa: E402


def main() -> None:
    graph = build_graph(AgentContext.build(Settings(embeddings_backend="hash", llm_backend="none"))).get_graph()
    out = ROOT / "docs"
    out.mkdir(exist_ok=True)
    mermaid = graph.draw_mermaid()
    (out / "workflow_graph.mmd").write_text(mermaid, encoding="utf-8")
    print(f"Wrote {out / 'workflow_graph.mmd'}")
    try:  # PNG rendering uses the mermaid.ink web service -> needs internet
        (out / "workflow_graph.png").write_bytes(graph.draw_mermaid_png())
        print(f"Wrote {out / 'workflow_graph.png'}")
    except Exception as exc:
        print(f"PNG skipped ({type(exc).__name__}); paste the .mmd into https://mermaid.live")


if __name__ == "__main__":
    main()
