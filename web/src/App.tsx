import { useEffect, useRef, useState } from "react";

type Tool = { ferramenta: string; argumentos: Record<string, unknown> };
type Message = { role: "user" | "assistant"; text: string; tools?: Tool[] };

const GREETING: Message = {
  role: "assistant",
  text: "Olá! Eu sou o Tom, assistente virtual da Empório da Música. Posso ajudar com instrumentos, preços, pedidos e as regras da loja. Como posso te ajudar?",
};

// Customer messages stay in Portuguese: that is the language the store's customers speak.
const SUGGESTIONS = [
  "Quais violões vocês têm até R$1.000?",
  "Quanto custa o Takamine GD20?",
  "Qual o status do pedido 8?",
  "Me arrependi da compra, posso devolver?",
  "Vocês vendem cordas de guitarra?",
];

/** Inline formatting: **bold** (markdown) and *bold* (WhatsApp style). Built as React nodes, never raw HTML. */
function Inline({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*\n]+\*)/g);
  return (
    <>
      {parts.map((part, i) =>
        /^\*\*[^*]+\*\*$/.test(part) ? (
          <strong key={i}>{part.slice(2, -2)}</strong>
        ) : /^\*[^*\n]+\*$/.test(part) ? (
          <strong key={i}>{part.slice(1, -1)}</strong>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}

/** Minimal block formatting for chat replies: paragraphs and "- " / "• " bullet lists. */
function RichText({ text }: { text: string }) {
  const blocks: ({ type: "p"; text: string } | { type: "ul"; items: string[] })[] = [];
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const bullet = line.match(/^\s*[-•]\s+(.*)$/);
    if (bullet) {
      const last = blocks[blocks.length - 1];
      if (last && last.type === "ul") last.items.push(bullet[1]!);
      else blocks.push({ type: "ul", items: [bullet[1]!] });
    } else if (line.trim()) {
      blocks.push({ type: "p", text: line });
    }
  }
  return (
    <div className="space-y-2">
      {blocks.map((block, i) =>
        block.type === "ul" ? (
          <ul key={i} className="list-disc space-y-1 pl-5">
            {block.items.map((item, j) => (
              <li key={j}>
                <Inline text={item} />
              </li>
            ))}
          </ul>
        ) : (
          <p key={i}>
            <Inline text={block.text} />
          </p>
        ),
      )}
    </div>
  );
}

export default function App() {
  const [apiUrl, setApiUrl] = useState("http://localhost:8000");
  const [messages, setMessages] = useState<Message[]>([GREETING]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sessionId = useRef<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try {
      const saved = localStorage.getItem("emporio_api_url");
      if (saved) setApiUrl(saved);
    } catch {
      /* storage unavailable: keep the default */
    }
  }, []);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [messages, loading]);

  const base = () => apiUrl.replace(/\/$/, "");

  async function send(text: string) {
    if (!text.trim() || loading) return;
    setMessages((prev) => [...prev, { role: "user", text }]);
    setInput("");
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${base()}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, session_id: sessionId.current }),
      });
      if (!res.ok) throw new Error(`Error ${res.status}: ${await res.text()}`);
      const data = await res.json();
      sessionId.current = data.session_id;
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: data.reply, tools: data.tools_used },
      ]);
    } catch (err) {
      setError(
        `Could not reach the agent at ${apiUrl}. Start the Python backend ` +
          `(python -m emporio_agent.api --port 8000) and check the URL. Detail: ${
            err instanceof Error ? err.message : String(err)
          }`,
      );
    } finally {
      setLoading(false);
    }
  }

  async function newConversation() {
    const id = sessionId.current;
    sessionId.current = null;
    setMessages([GREETING]);
    setError(null);
    if (id) {
      try {
        await fetch(`${base()}/chat/${id}`, { method: "DELETE" });
      } catch {
        /* the server drops idle sessions on restart anyway */
      }
    }
  }

  return (
    <main className="mx-auto flex h-screen w-full max-w-3xl flex-col gap-4 overflow-hidden px-4 py-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.28em] text-primary">Empório da Música</p>
          <h1 className="text-4xl leading-tight">Tom, the virtual assistant</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Catalog, orders and store policies — always checking the system.
          </p>
        </div>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Python backend
          <input
            value={apiUrl}
            onChange={(e) => {
              setApiUrl(e.target.value);
              try {
                localStorage.setItem("emporio_api_url", e.target.value);
              } catch {
                /* ignore */
              }
            }}
            className="w-56 rounded-md border border-border bg-input px-2 py-1 font-mono text-xs text-foreground outline-none focus:border-primary"
          />
        </label>
      </header>

      <section className="surface flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl">
        <div ref={scroller} className="no-scrollbar min-h-0 flex-1 space-y-4 overflow-y-auto p-5">
          {messages.map((message, index) => (
            <div
              key={index}
              className={`animate-rise flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div className="max-w-[85%] space-y-2">
                <div
                  className={`${
                    message.role === "user" ? "bubble-user" : "bubble-bot"
                  } px-4 py-3 text-sm leading-relaxed`}
                >
                  <RichText text={message.text} />
                </div>
                {message.tools && message.tools.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {message.tools.map((tool, i) => (
                      <span
                        key={i}
                        title={JSON.stringify(tool.argumentos)}
                        className="rounded-full border border-accent/40 px-2 py-0.5 font-mono text-[10px] text-accent"
                      >
                        {tool.ferramenta}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
          {loading && (
            <div className="animate-rise flex justify-start">
              <div className="bubble-bot px-4 py-3 text-sm text-muted-foreground">
                checking the system…
              </div>
            </div>
          )}
        </div>

        {error && (
          <p className="border-t border-border px-5 py-3 text-xs text-destructive">{error}</p>
        )}

        <div className="border-t border-border p-3">
          <div className="mb-2 flex flex-wrap gap-1.5">
            {SUGGESTIONS.map((suggestion) => (
              <button
                key={suggestion}
                onClick={() => send(suggestion)}
                disabled={loading}
                className="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground transition-colors hover:border-primary hover:text-primary disabled:opacity-50"
              >
                {suggestion}
              </button>
            ))}
            <button
              onClick={newConversation}
              disabled={loading}
              className="rounded-full border border-dashed border-border px-3 py-1 text-xs text-muted-foreground transition-colors hover:border-primary hover:text-primary disabled:opacity-50"
            >
              ↺ New conversation
            </button>
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
            className="flex gap-2"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Digite sua mensagem…"
              className="flex-1 rounded-xl border border-input bg-input px-4 py-3 text-sm outline-none placeholder:text-muted-foreground focus:border-primary"
            />
            <button
              type="submit"
              disabled={loading || !input.trim()}
              className="rounded-xl bg-primary px-5 py-3 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40"
            >
              Send
            </button>
          </form>
        </div>
      </section>

      <footer className="text-xs text-muted-foreground">
        Demo interface. The agent runs in Python (Ollama gpt-oss + function calling over the store CSVs +
        policy manual) — see <span className="font-mono text-primary">README.md</span>.
      </footer>
    </main>
  );
}
