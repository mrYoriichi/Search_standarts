// Вордмарк приложения: бейдж «MAI» + слово «ассистент» на языке UI
// (cs Asistent / en Assistant / de Assistent). Размер наследуется от
// родителя (em), поэтому один компонент годится и для шапки, и для логина.
import { t } from './i18n'

export function Logo({ className = '' }: { className?: string }) {
  return (
    <span className={'inline-flex items-center gap-2 ' + className}>
      <span className="inline-flex items-center justify-center rounded-md bg-primary text-primary-foreground font-extrabold tracking-tight px-2 py-0.5 text-[0.85em]">
        MAI
      </span>
      <span className="font-bold tracking-tight">{t('logo.word')}</span>
    </span>
  )
}
