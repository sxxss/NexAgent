export const dynamic = "force-dynamic";

export function GET() {
  const html = `<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>NexAgent Cache Reset</title>
  </head>
  <body>
    <script>
      location.replace("/knowledge?cacheReset=" + Date.now());
    </script>
    <p>正在清理本地缓存...</p>
  </body>
</html>`;

  return new Response(html, {
    headers: {
      "Cache-Control": "no-store, must-revalidate",
      "Clear-Site-Data": "\"cache\"",
      "Content-Type": "text/html; charset=utf-8",
    },
  });
}
