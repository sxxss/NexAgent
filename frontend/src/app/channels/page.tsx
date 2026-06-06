"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle, Copy, Loader2, RefreshCw, Send } from "lucide-react";
import { useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { fetchChannels, sendChannelMessage } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function ChannelsPage() {
  const channelsQuery = useQuery({ queryKey: ["channels"], queryFn: fetchChannels });
  const channels = channelsQuery.data ?? [];
  const [selected, setSelected] = useState("generic");
  const [text, setText] = useState("你好，介绍一下 NexAgent");
  const [userId, setUserId] = useState("console-user");
  const [response, setResponse] = useState("");
  const [sending, setSending] = useState(false);
  const current = channels.find((item) => item.id === selected) ?? channels[0];

  const send = async () => {
    if (!text.trim() || !current) return;
    setSending(true);
    setResponse("");
    try {
      const result = await sendChannelMessage(current.id, { text, user_id: userId || "console-user", agent: "chatbot" });
      setResponse(result.response);
    } catch (error) {
      setResponse(error instanceof Error ? error.message : "发送失败");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="flex h-full min-w-0 flex-col bg-slate-100">
      <PageHeader
        eyebrow="Channels"
        title="渠道接入"
        description="通过统一 webhook 适配 IM、自动化平台和自定义入口，并在控制台里模拟入站消息。"
        actions={<button type="button" onClick={() => void channelsQuery.refetch()} className={outlineButton}><RefreshCw size={14} className={channelsQuery.isFetching ? "animate-spin" : ""} />刷新</button>}
      />
      <main className="grid min-h-0 flex-1 gap-5 overflow-y-auto p-6 xl:grid-cols-[420px_minmax(0,1fr)]">
        <section className="space-y-3">
          {channels.map((channel) => (
            <button key={channel.id} type="button" onClick={() => setSelected(channel.id)} className={cn("w-full rounded-xl border bg-white p-4 text-left shadow-sm transition hover:border-slate-300", current?.id === channel.id ? "border-sky-300 ring-2 ring-sky-100" : "border-slate-200")}>
              <div className="mb-2 flex items-center justify-between gap-3">
                <div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-xl bg-sky-50 text-sky-700"><Send size={15} /></div><div><p className="text-sm font-semibold text-slate-950">{channel.name}</p><p className="font-mono text-xs text-slate-400">{channel.id}</p></div></div>
                <Badge variant={channel.enabled ? "success" : "secondary"}>{channel.enabled ? "启用" : "关闭"}</Badge>
              </div>
              <p className="text-xs leading-5 text-slate-500">{channel.description}</p>
              <div className="mt-3 flex items-center gap-2 rounded-lg bg-slate-50 px-2 py-1.5"><code className="min-w-0 flex-1 truncate text-xs text-slate-500">{channel.webhook_path}</code><Copy size={12} className="text-slate-400" /></div>
            </button>
          ))}
        </section>

        <Card>
          <CardContent className="p-5">
            <div className="mb-5 flex items-center justify-between">
              <div><h2 className="text-sm font-semibold text-slate-950">{current?.name ?? "渠道控制台"}</h2><p className="mt-1 text-xs text-slate-500">用标准 payload 模拟入站消息</p></div>
              {current?.enabled ? <CheckCircle size={18} className="text-sky-600" /> : null}
            </div>
            <div className="space-y-4">
              <Field label="用户 ID"><input className={inputClass} value={userId} onChange={(event) => setUserId(event.target.value)} /></Field>
              <Field label="入站消息"><textarea className={`${inputClass} min-h-32 resize-none`} value={text} onChange={(event) => setText(event.target.value)} /></Field>
              <button type="button" onClick={() => void send()} disabled={sending || !text.trim()} className="inline-flex h-10 items-center gap-2 rounded-lg bg-slate-950 px-4 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50">{sending ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />}发送测试消息</button>
              {response ? <div className="rounded-xl border border-slate-200 bg-slate-50 p-4"><p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">Agent Response</p><p className="text-sm leading-6 text-slate-700">{response}</p></div> : null}
            </div>
          </CardContent>
        </Card>
      </main>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block text-xs font-medium text-slate-600"><span>{label}</span><div className="mt-1">{children}</div></label>;
}

const inputClass = "w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-sky-300 focus:ring-2 focus:ring-sky-100";
const outlineButton = "inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 hover:bg-slate-50";
