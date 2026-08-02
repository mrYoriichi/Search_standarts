// App wordmark: "MAI" badge + "Assistant" (one English spelling across all
// languages — decision 2026-08-02). Size is inherited from the parent (em),
// so one component fits both the header and the login page.
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
