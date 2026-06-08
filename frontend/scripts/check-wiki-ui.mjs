import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");

const files = {
  api: "src/lib/api.ts",
  workbench: "src/components/wiki/WikiWorkbench.tsx",
  page: "src/components/wiki/WikiPagePanel.tsx",
  graph: "src/components/wiki/WikiGraphPanel.tsx",
  lint: "src/components/wiki/WikiLintPanel.tsx",
};

const read = (key) => fs.readFileSync(path.join(root, files[key]), "utf8");
const checks = [
  ["api", "repairWikiKbIssues"],
  ["api", "acceptGeneratedWikiKbPage"],
  ["api", "discardGeneratedWikiKbPage"],
  ["api", "deleteWikiKbPage"],
  ["workbench", "graphOptions"],
  ["workbench", "pageFilters"],
  ["workbench", "handleGraphNodeSelect"],
  ["workbench", "handleIssueAction"],
  ["page", "wiki-link"],
  ["page", "acceptGeneratedWikiKbPage"],
  ["page", "discardGeneratedWikiKbPage"],
  ["page", "sourceFilter"],
  ["graph", "includeWeak"],
  ["graph", "maxEdges"],
  ["graph", "核心节点"],
  ["graph", "关系详情"],
  ["lint", "一键 AI 修复"],
  ["lint", "groupedIssues"],
  ["lint", "repairWikiKbIssues"],
];

const failures = [];
for (const [key, needle] of checks) {
  if (!read(key).includes(needle)) {
    failures.push(`${files[key]} is missing ${needle}`);
  }
}

if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}

console.log("wiki ui checks passed");
