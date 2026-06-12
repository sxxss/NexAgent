# Chat Page Density Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Optimize the NexAgent chat page layout and visual density while preserving all existing chat behavior.

**Architecture:** Keep the existing Next.js component structure and make focused styling/layout changes in the chat page, message bubble, and input components. Avoid extracting new abstractions unless repeated class patterns become hard to maintain.

**Tech Stack:** Next.js 16, React 19, Tailwind CSS 4 utility classes, lucide-react icons, React Query.

---

## File Structure

- Modify `frontend/src/app/page.tsx` for the page grid, chat command bar, empty state, conversation panel, inspector spacing, and composer placement.
- Modify `frontend/src/components/chat/MessageBubble.tsx` for assistant/user message density and visual treatment.
- Modify `frontend/src/components/chat/ChatInput.tsx` for compact composer layout.
- Modify `frontend/src/app/globals.css` only for shared density and markdown rhythm utilities that cannot be expressed cleanly with existing classes.

### Task 1: Tighten Main Chat Layout

**Files:**
- Modify: `frontend/src/app/page.tsx`

- [ ] **Step 1: Reduce grid chrome and rebalance columns**

Change `layoutClass` so the left panel is slightly narrower, gaps are smaller, and the center chat gets the remaining space:

```tsx
const layoutClass = cn(
  "grid h-full min-w-0 grid-cols-1 gap-2 overflow-hidden p-2 md:gap-3 md:p-3",
  conversationCollapsed && inspectorCollapsed && "lg:grid-cols-[48px_minmax(0,1fr)]",
  conversationCollapsed && !inspectorCollapsed && "lg:grid-cols-[48px_minmax(0,1fr)] xl:grid-cols-[48px_minmax(0,1fr)_300px]",
  !conversationCollapsed && inspectorCollapsed && "lg:grid-cols-[220px_minmax(0,1fr)]",
  !conversationCollapsed && !inspectorCollapsed && "lg:grid-cols-[220px_minmax(0,1fr)] xl:grid-cols-[220px_minmax(0,1fr)_300px]",
);
```

- [ ] **Step 2: Flatten the chat shell**

Update the center `<section>` class to use less radius, lighter border, and less shadow:

```tsx
<section className="relative flex min-h-0 min-w-0 flex-col overflow-hidden rounded-[22px] border border-white/75 bg-white/58 shadow-[0_14px_34px_rgba(83,101,132,0.09)] backdrop-blur">
```

- [ ] **Step 3: Reduce message rail padding**

Update the message list wrapper from `max-w-5xl px-5 pt-5 pb-40` to a wider, denser rail:

```tsx
<div className="chat-compact mx-auto w-full max-w-[1120px] px-3 pt-3 pb-32 sm:px-4 lg:px-5">
```

Expected result: more visible message content both vertically and horizontally.

### Task 2: Compact Header Command Bar

**Files:**
- Modify: `frontend/src/app/page.tsx`

- [ ] **Step 1: Shrink header padding**

Change header class:

```tsx
<header className="border-b border-slate-200/70 px-3 py-2.5 sm:px-4">
```

- [ ] **Step 2: Split controls into left and right groups**

Keep existing controls and behavior, but adjust wrapper classes:

```tsx
<div className="flex min-w-0 flex-wrap items-center gap-1.5">
```

For the action group:

```tsx
<div className="ml-auto flex min-w-0 items-center gap-1.5">
```

- [ ] **Step 3: Make action buttons icon-first**

Keep text on larger screens and hide labels on cramped widths using `hidden sm:inline`. Example:

```tsx
<Phone size={14} />
<span className="hidden sm:inline">通话</span>
```

Apply the same pattern to `沉淀 Wiki`, `新对话`, and `配置`.

Expected result: the header remains one compact command row on typical desktop widths and wraps gracefully when narrow.

### Task 3: Replace Oversized Empty State With Dense Start Surface

**Files:**
- Modify: `frontend/src/app/page.tsx`

- [ ] **Step 1: Reduce empty state container spacing**

Change the root class in `EmptyState`:

```tsx
<div className="mx-auto flex h-full max-w-[1120px] flex-col gap-3 px-3 py-4 sm:px-4">
```

- [ ] **Step 2: Replace the hero card layout with a compact intro strip**

Keep the same links, stats, and quick starters, but change large `p-6`, `text-2xl`, and `mt-5` spacing to compact values: `p-4`, `text-xl`, `mt-3`. Use `lg:grid-cols-[minmax(0,1fr)_280px]`.

- [ ] **Step 3: Make quick-start cards lower**

Change quick-start button classes to:

```tsx
className="group rounded-2xl border border-white/80 bg-white/72 p-4 text-left shadow-[0_8px_22px_rgba(83,101,132,0.08)] transition hover:-translate-y-0.5 hover:bg-white hover:shadow-[0_14px_32px_rgba(83,101,132,0.12)]"
```

Expected result: empty page still feels polished but does not consume the whole viewport like a landing page.

### Task 4: Improve Message Density And Readability

**Files:**
- Modify: `frontend/src/components/chat/MessageBubble.tsx`

- [ ] **Step 1: Reduce avatar size and row padding**

For user and assistant wrappers, change row padding from `py-2` to `py-1.5`, avatar size from `h-8 w-8` to `h-7 w-7`, and icon size from `13/14` to `12/13`.

- [ ] **Step 2: Widen useful message area**

Change user bubble wrapper from `max-w-[78%]` to:

```tsx
className="flex max-w-[min(84%,760px)] min-w-0 items-end gap-2"
```

Change assistant content wrapper from `max-w-[86%]` to:

```tsx
className="min-w-0 max-w-[min(92%,920px)] flex-1 overflow-hidden"
```

- [ ] **Step 3: Make assistant final card flatter**

Change the assistant final card to:

```tsx
<div className="min-w-0 overflow-hidden rounded-2xl rounded-tl-md border border-slate-200/70 bg-white/74 px-4 py-3 text-sm leading-7 text-slate-800 shadow-[0_8px_20px_rgba(83,101,132,0.06)]">
```

Expected result: long assistant answers read more like a document, while user turns remain easy to scan.

### Task 5: Compact Composer

**Files:**
- Modify: `frontend/src/components/chat/ChatInput.tsx`
- Modify: `frontend/src/app/page.tsx`

- [ ] **Step 1: Reduce composer shadow and radius**

In `ChatInput`, change the root wrapper:

```tsx
<div className="input-glow overflow-hidden rounded-[18px] border border-white/70 bg-white/72 shadow-[0_12px_32px_rgba(83,101,132,0.13)] backdrop-blur-2xl">
```

- [ ] **Step 2: Reduce textarea max height and padding**

Change the auto-height cap from `120` to `104`, and textarea class from `max-h-28 ... px-4 pt-2 pb-0.5` to:

```tsx
"max-h-24 min-h-8 w-full resize-none bg-transparent px-3.5 pt-2 pb-0"
```

- [ ] **Step 3: Move composer closer to bottom and reduce max width**

In `page.tsx`, change the floating composer wrapper:

```tsx
<div className="pointer-events-none absolute inset-x-0 bottom-2 z-20 px-3 sm:px-4">
  <div className="pointer-events-auto mx-auto w-full max-w-[1120px]">
```

Expected result: the composer still feels prominent but blocks less of the transcript.

### Task 6: Verify And Inspect

**Files:**
- No source edits unless verification reveals layout defects.

- [ ] **Step 1: Run lint**

Run:

```bash
npm run lint
```

from `frontend`.

Expected: command exits successfully.

- [ ] **Step 2: Start dev server**

Run:

```bash
npm run dev
```

from `frontend`.

Expected: Next.js serves the app on a local port.

- [ ] **Step 3: Inspect desktop and narrow layouts**

Open the chat page in the browser. Check:

- Header controls do not overlap.
- Empty state does not look like a landing page.
- Message list and composer are visible and aligned.
- The right inspector opens without crushing the center column.
- Narrow viewport keeps controls usable.

- [ ] **Step 4: Fix only defects found in inspection**

If inspection shows overlap, clipped text, or broken alignment, adjust the smallest relevant class in the touched component and repeat lint/inspection.
