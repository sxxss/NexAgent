import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");

const files = {
  globals: "src/app/globals.css",
  workbench: "src/components/wiki/WikiWorkbench.tsx",
  pagePanel: "src/components/wiki/WikiPagePanel.tsx",
};

const read = (key) => fs.readFileSync(path.join(root, files[key]), "utf8");

const checks = [
  [
    "workbench",
    'className="flex min-h-0 min-w-0 flex-col overflow-hidden',
    "Wiki workbench right panel must be a constrained flex column.",
  ],
  [
    "workbench",
    'className="min-h-0 flex-1 overflow-hidden',
    "Wiki workbench tab content must preserve height for nested scroll areas.",
  ],
  [
    "pagePanel",
    'className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden"',
    "Wiki page panel must preserve the height chain for nested scrolling.",
  ],
  [
    "pagePanel",
    'className="min-h-0 flex-1 overflow-auto bg-white px-5 py-5"',
    "Wiki page preview must expose its own scrollbar.",
  ],
  [
    "workbench",
    'className="flex min-h-0 flex-1 flex-col overflow-hidden"',
    "Wiki resource page directory wrapper must constrain its child height.",
  ],
  [
    "pagePanel",
    'className="flex h-full min-h-0 flex-1 flex-col overflow-hidden bg-white"',
    "Wiki page directory must preserve height for its scrollable list.",
  ],
  [
    "pagePanel",
    "wiki-scrollbar",
    "Wiki page directory list must use the visible wiki scrollbar style.",
  ],
  [
    "globals",
    ".wiki-scrollbar",
    "Wiki scrollbar style must be defined globally.",
  ],
];

const failures = checks
  .filter(([key, needle]) => !read(key).includes(needle))
  .map(([, , message]) => message);

if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}

console.log("wiki scroll checks passed");
