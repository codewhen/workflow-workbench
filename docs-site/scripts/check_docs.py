"""Check content coverage and repository-readable links without writing source files."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from release_workbench.domain.cards import REGISTRY  # noqa: E402 — standalone script resolves the checkout before imports.
from release_workbench.infrastructure.documents import SCHEMA  # noqa: E402 — standalone script resolves the checkout before imports.

DOCS = ROOT / "docs"


def main() -> None:
    manifest = json.loads((ROOT / "docs-site/coverage.json").read_text(encoding="utf-8"))
    errors: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    require(set(manifest["cards"]) == set(REGISTRY), "Registered card/page inventory differs.")
    for kind, spec in REGISTRY.items():
        item = manifest["cards"].get(kind, {})
        require(
            set(item.get("fields", [])) == {f["key"] for f in spec.fields},
            f"{kind}: undocumented field inventory",
        )
        modes = {f["key"]: f["options"] for f in spec.fields if f.get("options")}
        require(item.get("modes") == modes, f"{kind}: undocumented mode/options")
        navigation = (ROOT / "docs-site/.vitepress/config.mts").read_text(encoding="utf-8")
        require(
            bool(re.search(r"['\"]" + re.escape(kind) + r"['\"]", navigation)),
            f"{kind}: missing card navigation",
        )
        page = DOCS / item.get("page", "missing")
        if not page.is_file():
            errors.append(f"{kind}: missing guide")
            continue
        text = page.read_text(encoding="utf-8")
        for section in (
            "Before you start",
            "Behavior and ports",
            "Fields and defaults",
            "Configure it in the browser",
            "Configured example",
            "Common mistakes and recovery",
            "Next example",
        ):
            require("## " + section in text, f"{kind}: missing {section}")
        for field in spec.fields:
            require(
                "`" + field["key"] + "`" in text,
                f"{kind}: field absent from prose/table: {field['key']}",
            )
        for key in ("example", "screenshot"):
            require((DOCS / item.get(key, "missing")).is_file(), f"{kind}: missing {key}")
    require(
        set(manifest["layout"]) == set(SCHEMA["$defs"]["area"]["properties"]["kind"]["enum"]),
        "Layout guide inventory differs.",
    )
    for kind, item in manifest["layout"].items():
        for key in ("page", "example", "screenshot"):
            require((DOCS / item[key]).is_file(), f"{kind}: missing {key}")
    settings = SCHEMA["$defs"]["card"]["properties"]["settings"]["properties"]
    require(
        set(manifest["settings"]) == set(settings),
        "Execution settings coverage differs from schema.",
    )
    require(
        set(manifest["workflow_fields"]) == set(SCHEMA["properties"]),
        "Workflow field coverage differs from schema.",
    )
    discovery_fields = SCHEMA["properties"]["input_detection"]["properties"]
    require(
        set(manifest["discovery_fields"]) == set(discovery_fields),
        "Input discovery setting coverage differs from schema.",
    )
    retry_fields = settings["retry"]["properties"]
    require(
        set(manifest["retry_fields"]) == set(retry_fields),
        "Retry setting coverage differs from schema.",
    )
    for category in ("settings", "retry_fields", "workflow_fields", "discovery_fields", "features"):
        for key, item in manifest[category].items():
            page = DOCS / item["page"]
            require(page.is_file(), f"{key}: missing feature page")
            text = page.read_text(encoding="utf-8") if page.is_file() else ""
            for term in item.get("terms", [key]):
                require(term.lower() in text.lower(), f"{key}: missing explanation term {term}")
    for source, digest in manifest.get("reviewed_ui_sources", {}).items():
        file = ROOT / source
        require(
            file.is_file() and hashlib.sha256(file.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == digest,
            f"UI changed: review coverage/screenshots and update reviewed_ui_sources for {source}",
        )
    pages = [
        p for p in DOCS.rglob("*.md") if "reviews" not in p.parts and p.name != "acceptance.md"
    ]
    for page in pages:
        text = re.sub(r"```.*?```", "", page.read_text(encoding="utf-8"), flags=re.S)
        for match in re.finditer(r"(!?)\[([^\]]*)\]\(([^)]+)\)", text):
            image, label, raw = match.groups()
            url = raw.strip().split(' "')[0].strip("<>")
            parsed = urlsplit(url)
            if parsed.scheme or parsed.netloc:
                continue
            target = (page.parent / unquote(parsed.path)).resolve() if parsed.path else page
            require(
                target.is_relative_to(ROOT), f"{page.relative_to(DOCS)}: link escapes repository"
            )
            require(target.is_file(), f"{page.relative_to(DOCS)}: missing link {url}")
            if image:
                require(bool(label.strip()), f"{page}: screenshot needs alt text")
            if parsed.fragment and target.is_file() and target.suffix == ".md":
                headings = re.findall(r"^#{1,6}\s+(.+)$", target.read_text(encoding="utf-8"), re.M)
                anchors = {
                    re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
                    for heading in headings
                }
                require(unquote(parsed.fragment) in anchors, f"{page}: unknown anchor {url}")
    if errors:
        raise SystemExit("\n".join(errors))
    print(
        f"Documentation check passed: {len(pages)} pages, {len(REGISTRY)} cards, 3 layout tools, schema settings, modes, examples, screenshots and links."
    )


if __name__ == "__main__":
    main()
