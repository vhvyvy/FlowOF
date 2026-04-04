'use client'

import { useState } from 'react'
import { Header } from '@/components/layout/Header'
import { Button } from '@/components/ui/button'
import { Sparkles, Loader2, Send } from 'lucide-react'
import api from '@/lib/api'
import { useMonthStore } from '@/lib/hooks/useMonth'
import { formatMonth } from '@/lib/utils'

const QUICK_PROMPTS = [
  'Сделай анализ выручки за этот месяц',
  'Кто из чаттеров показал лучший результат?',
  'Где главные точки роста?',
  'Сравни расходы с прошлым месяцем',
]

interface Message {
  role: 'user' | 'assistant'
  content: string
}

export default function AiPage() {
  const { month, year } = useMonthStore()
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)

  async function sendMessage(text: string) {
    if (!text.trim()) return
    const userMsg: Message = { role: 'user', content: text }
    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setLoading(true)

    try {
      const res = await api.post<{ answer: string }>('/api/v1/ai/analyze', {
        question: text,
        month,
        year,
      })
      setMessages((prev) => [...prev, { role: 'assistant', content: res.data.answer }])
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Ошибка при обращении к AI. Проверьте настройки OpenAI.' },
      ])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col h-full">
      <Header title="AI Аналитик" />

      <div className="flex-1 flex flex-col p-6 overflow-hidden">
        {/* Messages area */}
        <div className="flex-1 overflow-y-auto space-y-4 mb-4">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <div className="w-14 h-14 rounded-2xl bg-indigo-500/15 flex items-center justify-center mb-4">
                <Sparkles className="h-7 w-7 text-indigo-400" />
              </div>
              <h3 className="text-lg font-semibold text-slate-200 mb-2">AI Аналитик</h3>
              <p className="text-slate-500 text-sm max-w-xs">
                Задайте вопрос о данных агентства за {formatMonth(month, year)}
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-6 max-w-lg w-full">
                {QUICK_PROMPTS.map((prompt) => (
                  <button
                    key={prompt}
                    onClick={() => sendMessage(prompt)}
                    className="text-left px-4 py-3 rounded-xl bg-slate-800/50 border border-slate-700/50 text-sm text-slate-300 hover:bg-slate-700/50 hover:border-indigo-500/30 transition-colors"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`max-w-2xl rounded-2xl px-5 py-3 text-sm ${
                  msg.role === 'user'
                    ? 'bg-indigo-600 text-white'
                    : 'bg-slate-800/80 border border-slate-700/50 text-slate-200'
                }`}
              >
                <p className="whitespace-pre-wrap leading-relaxed">{msg.content}</p>
              </div>
            </div>
          ))}

          {loading && (
            <div className="flex justify-start">
              <div className="bg-slate-800/80 border border-slate-700/50 rounded-2xl px-5 py-3">
                <Loader2 className="h-4 w-4 animate-spin text-indigo-400" />
              </div>
            </div>
          )}
        </div>

        {/* Input */}
        <div className="flex gap-3">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                sendMessage(input)
              }
            }}
            placeholder="Задайте вопрос..."
            disabled={loading}
            className="flex-1 h-11 rounded-xl border border-slate-600 bg-slate-800 px-4 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50"
          />
          <Button onClick={() => sendMessage(input)} disabled={loading || !input.trim()} size="icon" className="h-11 w-11">
            <Send className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  )
}
