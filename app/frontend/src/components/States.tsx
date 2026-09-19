import type { ReactNode } from 'react'

export function Skeleton({ lines = 3, height = 16 }: { lines?: number; height?: number }) {
  return (
    <div className="stack" style={{ gap: 8 }}>
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="skeleton" style={{ height, width: `${100 - (i % 3) * 12}%` }} />
      ))}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>
}

export function ErrorBox({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className="error">
      <strong>{title}</strong>
      {detail && (
        <div className="small" style={{ marginTop: 4 }}>
          {detail}
        </div>
      )}
    </div>
  )
}
