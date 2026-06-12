import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");

const files = {
  page: "src/app/page.tsx",
  input: "src/components/chat/ChatInput.tsx",
  bubble: "src/components/chat/MessageBubble.tsx",
  thinking: "src/components/chat/ThinkingToggle.tsx",
  globals: "src/app/globals.css",
};

const read = (key) => fs.readFileSync(path.join(root, files[key]), "utf8");

const checks = [
  [
    "page",
    '"grid h-full min-w-0 grid-cols-1 gap-2 overflow-hidden p-2 md:gap-3 md:p-3"',
    "Main chat grid must use compact outer spacing.",
  ],
  [
    "page",
    'lg:grid-cols-[220px_minmax(0,1fr)]',
    "Expanded conversation panel must be narrowed to 220px.",
  ],
  [
    "page",
    'xl:grid-cols-[220px_minmax(0,1fr)_300px]',
    "Inspector column must be narrowed to 300px.",
  ],
  [
    "page",
    'className="chat-compact mx-auto w-full max-w-[1120px] px-3 pt-3 pb-32 sm:px-4 lg:px-5"',
    "Message rail must be wider and denser.",
  ],
  [
    "page",
    'className="border-b border-slate-200/70 px-3 py-2 sm:px-4"',
    "Chat header must use tight vertical padding.",
  ],
  [
    "page",
    'className="no-scrollbar flex min-w-0 items-center gap-1.5 overflow-x-auto"',
    "Chat header controls must stay on one row with internal overflow instead of wrapping.",
  ],
  [
    "page",
    "h-8 w-8 items-center justify-center",
    "Header action buttons must be icon-sized.",
  ],
  [
    "page",
    "max-w-[170px]",
    "Header picker buttons must truncate long labels to keep the command bar compact.",
  ],
  [
    "thinking",
    '"flex h-8 items-center gap-1.5 rounded-xl border px-2.5',
    "Thinking mode toggle must match the compact header height.",
  ],
  [
    "page",
    'className="mx-auto flex h-full max-w-[1120px] flex-col gap-3 px-3 py-4 sm:px-4"',
    "Empty state must use compact full-height spacing.",
  ],
  [
    "input",
    "Math.min(el.scrollHeight, 104)",
    "Composer textarea height must be capped at 104px.",
  ],
  [
    "input",
    '"max-h-24 min-h-8 w-full resize-none bg-transparent px-3.5 pt-2 pb-0"',
    "Composer textarea must use compact padding.",
  ],
  [
    "bubble",
    "max-w-[min(84%,760px)]",
    "User messages must use a stable, wider max width.",
  ],
  [
    "bubble",
    "max-w-[min(92%,920px)]",
    "Assistant messages must use a stable, wider max width.",
  ],
  [
    "bubble",
    "bg-white/74 px-4 py-3 text-sm leading-7",
    "Assistant final card must be flatter and denser.",
  ],
  [
    "globals",
    ".chat-compact > div",
    "Shared chat compact rhythm must remain defined.",
  ],
];

const failures = checks
  .filter(([key, needle]) => !read(key).includes(needle))
  .map(([, , message]) => message);

const absentChecks = [
  [
    "page",
    "flex-wrap items-center",
    "Chat header must not wrap controls into a second row.",
  ],
  [
    "page",
    '<span className="hidden 2xl:inline">通话</span>',
    "Voice action must not show a text label in the header.",
  ],
  [
    "page",
    '<span className="hidden 2xl:inline">沉淀 Wiki</span>',
    "Wiki action must not show a text label in the header.",
  ],
  [
    "page",
    '<span className="hidden 2xl:inline">新对话</span>',
    "New conversation action must not show a text label in the header.",
  ],
];

failures.push(
  ...absentChecks
    .filter(([key, needle]) => read(key).includes(needle))
    .map(([, , message]) => message),
);

if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}

console.log("chat density checks passed");
