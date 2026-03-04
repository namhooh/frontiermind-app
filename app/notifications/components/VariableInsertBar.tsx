'use client'

import { RefObject } from 'react'

interface VariableInsertBarProps {
  variables: string[]
  targetRef: RefObject<HTMLTextAreaElement | HTMLInputElement | null>
  onInsert?: (variable: string) => void
}

export function VariableInsertBar({ variables, targetRef, onInsert }: VariableInsertBarProps) {
  if (!variables.length) return null

  function handleClick(variable: string) {
    const tag = `{{ ${variable} }}`
    const el = targetRef.current
    if (el) {
      const start = el.selectionStart ?? el.value.length
      const end = el.selectionEnd ?? start
      const before = el.value.slice(0, start)
      const after = el.value.slice(end)
      const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype, 'value'
      )?.set || Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, 'value'
      )?.set
      if (nativeInputValueSetter) {
        nativeInputValueSetter.call(el, before + tag + after)
        el.dispatchEvent(new Event('input', { bubbles: true }))
      }
      el.focus()
      const newPos = start + tag.length
      el.setSelectionRange(newPos, newPos)
    }
    onInsert?.(variable)
  }

  return (
    <div className="flex flex-wrap gap-1.5 mt-1">
      <span className="text-xs text-slate-400 self-center">Variables:</span>
      {variables.map((v) => (
        <button
          key={v}
          type="button"
          onClick={() => handleClick(v)}
          className="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-blue-50 text-blue-700 hover:bg-blue-100 transition-colors border border-blue-200"
        >
          {v}
        </button>
      ))}
    </div>
  )
}
