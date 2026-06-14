"use client";

import { useState } from "react";
import Link from "next/link";

interface Message {
  role: "user" | "agent";
  text: string;
  timestamp: Date;
}

export default function ChatDemoPage({
  params,
}: {
  params: { id: string };
}) {
  const { id } = params;
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  const sendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    // Add user message
    const userMsg: Message = {
      role: "user",
      text: input,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    try {
      const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

      // Call the agent endpoint for natural, conversational response
      const response = await fetch(
        `${apiBase}/chat/message?tenant_id=${id}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: userMsg.text,
          }),
        }
      );

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();

      // Agent response is already natural and conversational
      const agentMsg: Message = {
        role: "agent",
        text: data.reply,
        timestamp: new Date(),
      };

      setTimeout(() => {
        setMessages((prev) => [...prev, agentMsg]);
        setLoading(false);
      }, 600);
    } catch (error) {
      const errorMsg: Message = {
        role: "agent",
        text: `Error: ${error instanceof Error ? error.message : "Unknown error"}`,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMsg]);
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <Link
          href={`/tenants/${id}`}
          className="text-sm text-slate-500 hover:text-brand-600"
        >
          ← Tenant
        </Link>
        <h1 className="text-2xl font-semibold mt-4">Chat Demo (RAG Live)</h1>
        <p className="text-sm text-slate-500 mt-1">
          Prueba el agent en vivo. Pregunta sobre departamentos, barrios, precios, etc.
        </p>
      </div>

      {/* Chat container */}
      <div className="border border-slate-200 rounded-lg bg-white flex flex-col h-96">
        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {messages.length === 0 && (
            <div className="text-center text-slate-400 py-8">
              <p className="text-sm">Escribe una pregunta sobre departamentos...</p>
              <p className="text-xs mt-2">Ej: "Departamentos en Palermo"</p>
              <p className="text-xs">"¿Algo con 4 dormitorios?"</p>
            </div>
          )}
          {messages.map((msg, idx) => (
            <div
              key={idx}
              className={`flex ${
                msg.role === "user" ? "justify-end" : "justify-start"
              }`}
            >
              <div
                className={`max-w-xs px-4 py-2 rounded-lg ${
                  msg.role === "user"
                    ? "bg-brand-600 text-white rounded-br-none"
                    : "bg-slate-100 text-slate-900 rounded-bl-none"
                }`}
              >
                <p className="text-sm">{msg.text}</p>
                <p className="text-xs opacity-70 mt-1">
                  {msg.timestamp.toLocaleTimeString("es-AR", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </p>
              </div>
            </div>
          ))}
          {loading && (
            <div className="flex justify-start">
              <div className="bg-slate-100 text-slate-900 px-4 py-2 rounded-lg rounded-bl-none">
                <p className="text-sm">Agent escribiendo...</p>
              </div>
            </div>
          )}
        </div>

        {/* Input */}
        <div className="border-t border-slate-200 p-4">
          <form onSubmit={sendMessage} className="flex gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Pregunta sobre departamentos..."
              disabled={loading}
              className="flex-1 px-3 py-2 border border-slate-300 rounded text-sm disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={loading || !input.trim()}
              className="px-4 py-2 bg-brand-600 text-white rounded text-sm disabled:opacity-50 hover:bg-brand-700"
            >
              {loading ? "..." : "Enviar"}
            </button>
          </form>
        </div>
      </div>

      {/* Info box */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 text-sm">
        <p className="font-semibold text-blue-900 mb-2">Cómo funciona:</p>
        <ul className="text-blue-800 space-y-1 text-xs">
          <li>✓ Escribís tu pregunta</li>
          <li>✓ El agent busca en el RAG (100 departamentos)</li>
          <li>✓ Retorna resultados relevantes en tiempo real</li>
          <li>✓ Se guarda en conversaciones del CRM</li>
        </ul>
      </div>
    </div>
  );
}
