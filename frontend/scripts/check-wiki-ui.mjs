import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");

const files = {
  api: "src/lib/api.ts",
  list: "src/app/knowledge/page.tsx",
  detail: "src/app/knowledge/[id]/page.tsx",
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
  ["workbench", "sidebar"],
  ["workbench", "WikiPageDirectory"],
  ["workbench", "resources"],
  ["workbench", "WikiResourcePane"],
  ["workbench", "wikiWorkbenchTab"],
  ["list", "ModelSettingsDialog"],
  ["list", "onSettings"],
  ["detail", "WikiKnowledgeCard"],
  ["detail", "WikiQuickUpload"],
  ["detail", "WikiFileList"],
  ["detail", "WikiTaskQueue"],
  ["detail", "showUpload"],
  ["detail", "uploadDialogDropzone"],
  ["detail", "taskQueuePopover"],
  ["detail", "wikiSidebar"],
  ["page", "wiki-link"],
  ["page", "wiki-new:"],
  ["page", "crystallizeWikiKbPage"],
  ["page", "export function WikiPageDirectory"],
  ["page", "compactFilterBar"],
  ["page", "text-blue-700"],
  ["page", "acceptGeneratedWikiKbPage"],
  ["page", "discardGeneratedWikiKbPage"],
  ["page", "sourceFilter"],
  ["graph", "includeWeak"],
  ["graph", "maxEdges"],
  ["graph", "nodesDraggable"],
  ["graph", "showInteractive"],
  ["graph", "核心节点"],
  ["graph", "关系详情"],
  ["lint", "一键 AI 修复"],
  ["lint", "groupedIssues"],
  ["lint", "repairWikiKbIssues"],
];

const absentChecks = [
  ["page", "page.excerpt"],
  ["detail", "xl:grid-cols-[340px_minmax(0,1fr)]"],
  ["page", "xl:grid-cols-[360px_minmax(0,1fr)]"],
  ["detail", "<WikiModelPanel"],
  ["detail", "Wiki LLM 配置"],
];

const failures = [];
for (const [key, needle] of checks) {
  if (!read(key).includes(needle)) {
    failures.push(`${files[key]} is missing ${needle}`);
  }
}
for (const [key, needle] of absentChecks) {
  if (read(key).includes(needle)) {
    failures.push(`${files[key]} still contains ${needle}`);
  }
}

if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}

console.log("wiki ui checks passed");
