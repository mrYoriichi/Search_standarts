// Вордмарк приложения: бейдж «MAI» + «Assistant» (единое английское
// написание во всех языках — решение 2026-08-02). Размер наследуется от
// родителя (em), поэтому один компонент годится и для шапки, и для логина.
export function Logo({ className = '' }: { className?: string }) {
  return (
    <span className={'inline-flex items-center gap-2 ' + className}>
      <span className="inline-flex items-center justify-center rounded-md bg-primary text-primary-foreground font-extrabold tracking-tight px-2 py-0.5 text-[0.85em]">
        MAI
      </span>
      <span className="font-bold tracking-tight">Assistant</span>
    </span>
  )
}
