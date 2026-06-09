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
  graphPage: "src/app/knowledge/[id]/wiki/graph/page.tsx",
  lint: "src/components/wiki/WikiLintPanel.tsx",
  sidebar: "src/components/Sidebar.tsx",
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
  ["workbench", "loadWikiPages"],
  ["workbench", "loadWikiGraph"],
  ["workbench", "loadWikiLint"],
  ["workbench", "ensureTabData"],
  ["workbench", "renderResources"],
  ["workbench", "WikiResourceContext"],
  ["list", "ModelSettingsDialog"],
  ["list", "onSettings"],
  ["detail", "WikiKnowledgeCard"],
  ["detail", "WikiSourceToolbar"],
  ["detail", "WikiQuickUpload"],
  ["detail", "WikiFileList"],
  ["detail", "WikiTaskQueue"],
  ["detail", "showUpload"],
  ["detail", "uploadDialogDropzone"],
  ["detail", "wikiUploadDialogTrigger"],
  ["detail", "taskQueueTrigger"],
  ["detail", "taskQueuePopover"],
  ["detail", "wikiSidebar"],
  ["detail", "activeSourceFileId"],
  ["detail", "onToggleSourceFilter"],
  ["page", "wiki-link"],
  ["page", "urlTransform={preserveWikiUrl}"],
  ["page", "function preserveWikiUrl"],
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
  ["graph", "WikiGraphExplorerShell"],
  ["graph", "typeFilters"],
  ["graph", "communityFilters"],
  ["graph", "selectedNodeId"],
  ["graph", "focusNodeId"],
  ["graph", "onFitView"],
  ["graph", "页面类型"],
  ["graph", "社区"],
  ["graph", "关系列表"],
  ["graphPage", "图谱说明"],
  ["graphPage", "页面关系 / 主题结构 / 来源关联"],
  ["lint", "一键 AI 生成修复候选"],
  ["lint", "WikiRepairResultCard"],
  ["lint", "repairResult"],
  ["lint", "lastRepairItems"],
  ["lint", "force"],
  ["lint", "skipped_issues"],
  ["lint", "处理候选"],
  ["lint", "AI 修复已加入任务队列"],
  ["lint", "groupedIssues"],
  ["lint", "repairWikiKbIssues"],
  ["detail", "taskKindLabel"],
  ["detail", "wiki_repair"],
  ["detail", "Wiki 编译"],
  ["detail", "visibleJobs"],
  ["detail", "hiddenJobCount"],
  ["detail", "showAllJobs"],
  ["detail", "活跃"],
  ["detail", "历史任务"],
  ["sidebar", 'import Link from "next/link"'],
  ["sidebar", "<Link"],
  ["sidebar", "prefetch={false}"],
];

const absentChecks = [
  ["page", "page.excerpt"],
  ["detail", "xl:grid-cols-[340px_minmax(0,1fr)]"],
  ["page", "xl:grid-cols-[360px_minmax(0,1fr)]"],
  ["detail", "<WikiModelPanel"],
  ["detail", "Wiki LLM 配置"],
  ["detail", "任务{jobs.length"],
  ["workbench", "const [nextPages, nextGraph, nextLint] = await Promise.all"],
  ["page", "wiki-new:"],
  ["page", "createLinkedPage"],
  ["page", "crystallizeWikiKbPage"],
  ["page", "创建中..."],
  ["sidebar", "no-html-link-for-pages"],
  ["sidebar", "<a\n"],
  ["sidebar", "</a>"],
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
