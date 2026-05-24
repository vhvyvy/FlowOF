'use client'

import { Header } from '@/components/layout/Header'
import { CatalogSection } from '@/components/catalog/CatalogSection'
import { BookOpen, Users, Clock, Tag } from 'lucide-react'

export default function CatalogPage() {
  return (
    <div className="flex flex-col min-h-screen bg-slate-950">
      <Header title="Справочники" />

      <div className="flex-1 px-6 py-6 max-w-3xl mx-auto w-full space-y-6">
        {/* Описание */}
        <div className="rounded-xl border border-slate-700/40 bg-slate-800/30 px-5 py-4">
          <p className="text-sm text-slate-300 font-medium mb-1">Настройка справочников</p>
          <p className="text-xs text-slate-500 leading-relaxed">
            Добавьте модели, чаттеров, смены и категории расходов — они используются при ручном
            вводе транзакций. Удаление — мягкое: старые записи остаются нетронутыми.
          </p>
        </div>

        {/* Секции */}
        <div className="grid grid-cols-1 gap-4">
          <div className="flex items-center gap-2 text-slate-400">
            <BookOpen className="h-4 w-4 text-indigo-400" />
            <span className="text-sm font-medium text-slate-300">Модели</span>
          </div>
          <CatalogSection
            title="Модели"
            endpoint="models"
            placeholder="Имя модели (напр. Anna)"
          />

          <div className="flex items-center gap-2 text-slate-400 pt-2">
            <Users className="h-4 w-4 text-violet-400" />
            <span className="text-sm font-medium text-slate-300">Чаттеры</span>
          </div>
          <CatalogSection
            title="Чаттеры"
            endpoint="chatters"
            placeholder="Имя чаттера"
          />

          <div className="flex items-center gap-2 text-slate-400 pt-2">
            <Clock className="h-4 w-4 text-amber-400" />
            <span className="text-sm font-medium text-slate-300">Смены</span>
          </div>
          <CatalogSection
            title="Смены"
            endpoint="shifts"
            placeholder="Название смены (напр. Ночь)"
            showOrder
          />

          <div className="flex items-center gap-2 text-slate-400 pt-2">
            <Tag className="h-4 w-4 text-emerald-400" />
            <span className="text-sm font-medium text-slate-300">Категории расходов</span>
          </div>
          <CatalogSection
            title="Категории расходов"
            endpoint="expense-categories"
            placeholder="Название категории (напр. Реклама)"
          />
        </div>
      </div>
    </div>
  )
}
