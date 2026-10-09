// Configure UPLOAD_TOKEN_SHA256 com o hash de um token aleatório de 256 bits.
// O token original fica exclusivamente no backend, nunca no navegador.
const EXPECTED_HASH = Deno.env.get("UPLOAD_TOKEN_SHA256") ?? "CONFIGURE_SHA256_BEFORE_DEPLOY";
const BUCKET = "commerce-photos";
const MAX_BYTES = 8 * 1024 * 1024;

function reply(status: number, value: object) {
  return new Response(JSON.stringify(value), { status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
}
async function authorized(req: Request) {
  const header = req.headers.get("authorization") ?? "";
  if (!header.startsWith("Bearer ") || header.length > 256) return false;
  const token = header.slice(7);
  if (token.length < 32 || !/^[a-f0-9]{64}$/.test(EXPECTED_HASH)) return false;
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(token)));
  const hash = Array.from(digest, b => b.toString(16).padStart(2, "0")).join("");
  let difference = 0;
  for (let i = 0; i < hash.length; i++) difference |= hash.charCodeAt(i) ^ EXPECTED_HASH.charCodeAt(i);
  return difference === 0;
}

export async function handler(req: Request) {
  if (req.method !== "POST") return reply(405, { error: "Method not allowed" });
  if (!await authorized(req)) return reply(401, { error: "Unauthorized" });
  const path = req.headers.get("x-object-path") ?? "";
  if (!/^[1-9][0-9]*\/[a-f0-9]{32}\.webp$/.test(path)) return reply(400, { error: "Invalid path" });
  if (req.headers.get("content-type") !== "image/webp") return reply(415, { error: "WebP required" });
  const declared = Number(req.headers.get("content-length") ?? 0);
  if (declared > MAX_BYTES) return reply(413, { error: "Photo too large" });
  const reader = req.body?.getReader();
  if (!reader) return reply(400, { error: "Empty photo" });
  const chunks: Uint8Array[] = [];
  let size = 0;
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > MAX_BYTES) { await reader.cancel(); return reply(413, { error: "Photo too large" }); }
    chunks.push(value);
  }
  const photo = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { photo.set(chunk, offset); offset += chunk.length; }
  const label = new TextDecoder();
  if (size < 12 || label.decode(photo.slice(0, 4)) !== "RIFF" || label.decode(photo.slice(8, 12)) !== "WEBP") {
    return reply(415, { error: "Invalid WebP" });
  }
  const base = Deno.env.get("SUPABASE_URL")!;
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ??
    JSON.parse(Deno.env.get("SUPABASE_SECRET_KEYS") ?? "{}").default;
  if (!key) return reply(503, { error: "Storage unavailable" });
  try {
    const uploaded = await fetch(base + "/storage/v1/object/" + BUCKET + "/" + path, {
      method: "POST", headers: { Authorization: "Bearer " + key, apikey: key,
        "Content-Type": "image/webp", "Cache-Control": "31536000", "x-upsert": "false" }, body: photo });
    if (!uploaded.ok) return reply(503, { error: "Could not save photo" });
    return reply(201, { url: base + "/storage/v1/object/public/" + BUCKET + "/" + path });
  } catch {
    return reply(503, { error: "Storage unavailable" });
  }
}
