"""Build the existing detective UI and prompts for Cloudflare Workers."""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "scripts" / "lib"
OUT = ROOT / "dist"


def main():
    public = OUT / "detective-public"
    public.mkdir(parents=True, exist_ok=True)
    for source, target in (("detective_page.html", "index.html"), ("detective_page.js", "app.js")):
        (public / target).write_bytes((LIB / source).read_bytes())
    prompts = {}
    for node in ast.parse((LIB / "detective.py").read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ("_DECOMPOSE_SYSTEM", "_VERDICT_SYSTEM"):
                    prompts[target.id] = ast.literal_eval(node.value)
    if len(prompts) != 2:
        raise ValueError("Missing detective prompts")
    (OUT / "cloudflare-prompts.mjs").write_text(
        "export default " + json.dumps(prompts, ensure_ascii=False) + ";\n", encoding="utf-8"
    )
    print("Cloudflare assets built in dist/detective-public")


if __name__ == "__main__":
    main()
